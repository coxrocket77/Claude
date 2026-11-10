"""Write the claim packet. Everything is a draft until a named human approves it."""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from .gates import GateReport
from .models import Finding, Verdict

NOTICE = ("DRAFT prepared by an automated agent. A licensed tax professional must verify "
          "every line, citation and form number before anything is sent or filed.")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "vendor"


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_packet(out: Path, findings: list[Finding], gate: GateReport, client: str,
                 today: date, approved_by: str | None = None) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    status = f"APPROVED by {approved_by}" if approved_by else "DRAFT, NOT APPROVED"

    paths["findings"] = out / "findings.csv"
    _write_csv(paths["findings"], [f.to_row() for f in findings])
    paths["review_queue"] = out / "review_queue.csv"
    _write_csv(paths["review_queue"], [f.to_row() for f in findings
                                        if f.verdict == Verdict.NEEDS_REVIEW
                                        or (f.verdict == Verdict.OVERPAID and f.gate_failures)])
    paths["exposure"] = out / "exposure.csv"
    _write_csv(paths["exposure"], [f.to_row() for f in findings if f.verdict == Verdict.UNDERPAID])

    claimable = [f for f in findings if f.claimable]
    if not gate.blocked:
        letters = out / "vendor_letters"
        letters.mkdir(exist_ok=True)
        by_vendor: dict[str, list[Finding]] = defaultdict(list)
        for f in claimable:
            if f.line.tax_charged > 0:
                by_vendor[f.line.vendor].append(f)
        for vendor, items in sorted(by_vendor.items()):
            total = sum(i.refund_amount for i in items)
            rows = "\n".join(
                f"| {i.line.invoice_no} | {i.line.invoice_date} | {i.line.description} | "
                f"${i.line.amount:,.2f} | ${i.line.tax_charged:,.2f} | ${i.refund_amount:,.2f} | {i.rule_cite} |"
                for i in sorted(items, key=lambda x: x.line.invoice_date))
            p = letters / f"{_slug(vendor)}.md"
            p.write_text(f"""> {NOTICE}
> Status: {status}

**To:** {vendor}, Accounts Receivable
**From:** {client}
**Date:** {today:%B %d, %Y}
**Re:** Request for refund of sales tax collected in error, ${total:,.2f}

We reviewed our purchase records and found sales tax billed on the purchases below that we believe were not taxable, or were taxed above the correct amount. We ask that you refund ${total:,.2f}. If you would rather not process the refund yourself, please sign an assignment of your right to the refund so we can claim it directly from the state.

| Invoice | Date | Description | Amount | Tax billed | Refund requested | Basis |
|---|---|---|---|---|---|---|
{rows}

We can provide exemption certificates and supporting documentation on request.
""")
            paths[f"letter:{vendor}"] = p

        paths["state_schedule"] = out / "state_claim_schedule.csv"
        _write_csv(paths["state_schedule"], [{
            "vendor": f.line.vendor, "invoice_no": f.line.invoice_no,
            "invoice_date": f.line.invoice_date.isoformat(), "description": f.line.description,
            "taxable_amount_claimed": round(f.line.amount, 2),
            "tax_paid": round(f.line.tax_charged + f.line.use_tax_accrued, 2),
            "refund_claimed": round(f.refund_amount, 2), "basis": f.rule_cite,
            "route": f.refund_route} for f in claimable])

    counts = defaultdict(int)
    for f in findings:
        counts[f.verdict.value] += 1
    top = sorted(claimable, key=lambda f: -f.refund_amount)[:10]
    top_rows = "\n".join(f"| {f.line.vendor} | {f.line.invoice_no} | {f.line.description} | "
                         f"${f.refund_amount:,.2f} | {f.rule_id} |" for f in top)
    by_rule: dict[str, float] = defaultdict(float)
    for f in claimable:
        by_rule[f.rule_id] += f.refund_amount
    rule_rows = "\n".join(f"| {k} | ${v:,.2f} |" for k, v in sorted(by_rule.items(), key=lambda x: -x[1]))
    gate_text = ("BLOCKED\n\n" + "\n".join(f"- {r}" for r in gate.reasons)) if gate.blocked else "PASSED"

    paths["report"] = out / "report.md"
    paths["report"].write_text(f"""# Sales and use tax recovery review: {client}

> {NOTICE}
> Status: {status}

Run date: {today}. Lines reviewed: {len(findings)}.

## Position

| | |
|---|---|
| Refunds that passed every gate | ${gate.total_refund:,.2f} |
| Likely use tax owed (exposure) | ${gate.total_exposure:,.2f} |
| Net | ${gate.net:,.2f} |

Packet gate: {gate_text}

## Line outcomes

{chr(10).join(f"- {k}: {v}" for k, v in sorted(counts.items()))}

## Refunds by rule

| Rule | Refund |
|---|---|
{rule_rows or "| (none) | |"}

## Largest refund lines

| Vendor | Invoice | Description | Refund | Rule |
|---|---|---|---|---|
{top_rows or "| (none) | | | | |"}

## Human review queue

{len([f for f in findings if f.verdict == Verdict.NEEDS_REVIEW])} lines need a person to decide (see review_queue.csv). Most are utility bills that need a predominant-use study, repair parts that need a useful-life check, and lines where the two judges disagreed.
""")
    return paths
