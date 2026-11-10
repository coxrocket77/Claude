"""MCP server: lets Claude (desktop, Claude Code, or any MCP client) drive recoup.

Tools are few and shaped around the operator's job, not the internals:
scan a ledger, read what needs a human, and look at one finding in full.
Responses are compact by default and say what to do next.

  python -m recoup.mcp_server     # stdio
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import llm
from .graph import RunContext, run

server = MCPServer(
    name="recoup",
    instructions=("Finds overpaid sales and use tax in accounts payable exports and drafts "
                  "refund packets. Start with recoup_scan_ledger. Packets are drafts; never "
                  "tell the user a claim was filed."),
)


def _rows(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


@server.tool(description=(
    "Run the full recovery review on an AP export CSV. Resumable: re-running the same "
    "run_dir reuses earlier model calls. Returns totals, gate status and file paths."))
def recoup_scan_ledger(ap_csv_path: str, client_name: str, run_dir: str,
                       offline: bool = False, ack_exposure: bool = False) -> str:
    off = offline or not llm.have_api_key()
    clf, rev = llm.make_judges(off)
    logs: list[str] = []
    ctx = RunContext(Path(ap_csv_path), Path(run_dir), client_name, clf, rev,
                     today=date.today(), ack_exposure=ack_exposure, log=logs.append)
    try:
        findings, gate, paths = run(ctx)
    except SystemExit as e:
        return f"Could not read the ledger: {e}. Check the CSV has vendor, invoice, date, description, amount and tax columns."
    nxt = ("Call recoup_review_queue to see lines needing a human." if not gate.blocked
           else "The packet is blocked; explain the gate reasons to the user before anything else.")
    return json.dumps({
        "mode": "offline-heuristic" if off else "claude",
        "lines": len(findings),
        "refund_total": gate.total_refund, "exposure_total": gate.total_exposure,
        "blocked": gate.blocked, "gate_reasons": gate.reasons,
        "report": str(paths["report"]), "next": nxt}, indent=1)


@server.tool(description=(
    "List lines a human must decide, largest tax first. Use limit to page. Each item has "
    "the row number to pass to recoup_get_finding."))
def recoup_review_queue(run_dir: str, limit: int = 20, offset: int = 0) -> str:
    rows = _rows(Path(run_dir) / "packet" / "review_queue.csv")
    rows.sort(key=lambda r: -float(r["tax_charged"] or 0))
    page = rows[offset:offset + limit]
    slim = [{k: r[k] for k in ("row", "vendor", "description", "tax_charged", "category",
                                "reviewer_category", "verdict", "notes")} for r in page]
    return json.dumps({"total": len(rows), "offset": offset, "items": slim}, indent=1)


@server.tool(description="Full detail for one AP line by its CSV row number.")
def recoup_get_finding(run_dir: str, row: int) -> str:
    for r in _rows(Path(run_dir) / "packet" / "findings.csv"):
        if int(r["row"]) == row:
            return json.dumps(r, indent=1)
    return f"No finding for row {row}. Rows start at 2 because row 1 is the CSV header."


if __name__ == "__main__":
    server.run()
