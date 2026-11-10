"""The run graph and its harness.

ingest -> classify -> review -> evaluate -> gate -> packet

Each node checkpoints to <run_dir>/state.json and appends to progress.md, so a run
over 50,000 AP lines can stop (rate limit, crash, laptop lid) and resume without
paying for the same model calls twice. This follows the long-running harness
pattern: durable state on disk, a human-readable progress log, one node at a time.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .classify import Classifier
from .engine import evaluate
from .gates import GateReport, line_gates, run_gate
from .ingest import load_ap_csv
from .models import APLine, Category, Classification, Finding
from .packet import write_packet

NODES = ["ingest", "classify", "review", "evaluate", "gate", "packet"]


@dataclass
class RunContext:
    ap_csv: Path
    run_dir: Path
    client: str
    classifier: Classifier
    reviewer: Classifier
    today: date = field(default_factory=date.today)
    ack_exposure: bool = False
    log: Callable[[str], None] = print


class Harness:
    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = run_dir / "state.json"
        self.progress = run_dir / "progress.md"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            "created": datetime.now().isoformat(timespec="seconds"),
            "nodes": {}, "classifications": {}, "reviews": {}}

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1))
        tmp.replace(self.state_path)  # atomic: a crash never leaves half a state file

    def note(self, msg: str) -> None:
        with open(self.progress, "a") as fh:
            fh.write(f"- {datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")

    def done(self, node: str, **info) -> None:
        self.state["nodes"][node] = {"status": "done", **info}
        self.save()
        self.note(f"{node}: done {json.dumps(info) if info else ''}")

    def cached(self, bucket: str) -> dict[str, Classification]:
        return {k: Classification(Category(v["category"]), v["confidence"], v["rationale"], v["source"])
                for k, v in self.state[bucket].items()}

    def store(self, bucket: str, items: dict[str, Classification]) -> None:
        for k, c in items.items():
            self.state[bucket][k] = {"category": c.category.value, "confidence": c.confidence,
                                     "rationale": c.rationale, "source": c.source}
        self.save()


def _judge(h: Harness, bucket: str, judge: Classifier, lines: list[APLine],
           chunk: int, log) -> dict[str, Classification]:
    have = h.cached(bucket)
    todo = [ln for ln in lines if ln.key not in have]
    if len(todo) < len(lines):
        log(f"  {bucket}: resuming, {len(lines) - len(todo)} cached, {len(todo)} to do")
    for i in range(0, len(todo), chunk):
        part = todo[i:i + chunk]
        res = judge.classify(part)
        h.store(bucket, res)  # checkpoint after every chunk
        have.update(res)
    return have


def run(ctx: RunContext, chunk: int = 200) -> tuple[list[Finding], GateReport, dict]:
    h = Harness(ctx.run_dir)
    log = ctx.log
    t0 = time.time()

    log("[1/6] ingest")
    ing = load_ap_csv(ctx.ap_csv)
    for e in ing.errors:
        h.note(f"ingest error: {e}")
    if not ing.lines:
        raise SystemExit("No usable lines. " + "; ".join(ing.errors[:5]))
    h.done("ingest", lines=len(ing.lines), errors=len(ing.errors))
    log(f"  {len(ing.lines)} lines, {len(ing.errors)} rejected")

    lines = ing.lines

    log("[2/6] classify")
    cls = _judge(h, "classifications", ctx.classifier, lines, chunk, log)
    h.done("classify", judge=getattr(ctx.classifier, "name", type(ctx.classifier).__name__))

    log("[3/6] independent review")
    rev = _judge(h, "reviews", ctx.reviewer, lines, chunk, log)
    h.done("review", judge=getattr(ctx.reviewer, "name", type(ctx.reviewer).__name__))

    log("[4/6] evaluate")
    findings = evaluate(lines, cls, rev, ctx.today)
    h.done("evaluate")

    log("[5/6] gates")
    line_gates(findings)
    gate = run_gate(findings, ack_exposure=ctx.ack_exposure)
    h.done("gate", blocked=gate.blocked, refund=gate.total_refund, exposure=gate.total_exposure)
    for r in gate.reasons:
        log(f"  GATE: {r}")

    log("[6/6] packet")
    approval = ctx.run_dir / "approval.json"
    approved_by = json.loads(approval.read_text())["approved_by"] if approval.exists() else None
    paths = write_packet(ctx.run_dir / "packet", findings, gate, ctx.client, ctx.today, approved_by)
    h.done("packet", files=len(paths), seconds=round(time.time() - t0, 1))
    return findings, gate, paths
