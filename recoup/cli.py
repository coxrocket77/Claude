"""recoup: find and draft refunds of overpaid sales and use tax.

  recoup run AP.csv --client "Acme Mfg" --out runs/acme       # full graph, resumable
  recoup run AP.csv --offline ...                              # no API key, heuristic judges
  recoup approve runs/acme --by "Jane Doe, CPA"                # the only way to clear DRAFT
  recoup status runs/acme
  recoup eval evals/labeled.csv [--offline]
  recoup tune evals/labeled.csv --iterations 3                 # improvement loop on playbook.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from . import llm
from .evals import load_labeled, score, tune
from .graph import NODES, RunContext, run


def _offline(args) -> bool:
    if args.offline:
        return True
    if not llm.have_api_key():
        print("ANTHROPIC_API_KEY not set; running offline with heuristic judges.", file=sys.stderr)
        return True
    return False


def cmd_run(args) -> int:
    clf, rev = llm.make_judges(_offline(args))
    today = date.fromisoformat(args.as_of) if args.as_of else date.today()
    ctx = RunContext(ap_csv=Path(args.ap_csv), run_dir=Path(args.out), client=args.client,
                     classifier=clf, reviewer=rev, today=today, ack_exposure=args.ack_exposure)
    findings, gate, paths = run(ctx)
    print(f"\nRefunds passing gates: ${gate.total_refund:,.2f}")
    print(f"Use tax exposure:      ${gate.total_exposure:,.2f}")
    print(f"Packet: {'BLOCKED' if gate.blocked else 'ready for human review'} -> {paths['report']}")
    return 2 if gate.blocked else 0


def cmd_approve(args) -> int:
    run_dir = Path(args.run_dir)
    if not (run_dir / "state.json").exists():
        print("No run found there.", file=sys.stderr)
        return 1
    state = json.loads((run_dir / "state.json").read_text())
    gate = state["nodes"].get("gate", {})
    if gate.get("blocked"):
        print("Refusing: the run's gate is blocked. Resolve the gate reasons and re-run first.",
              file=sys.stderr)
        return 1
    (run_dir / "approval.json").write_text(json.dumps(
        {"approved_by": args.by, "at": datetime.now().isoformat(timespec="seconds")}))
    print(f"Approved by {args.by}. Re-run `recoup run` to restamp the packet; model calls are cached.")
    return 0


def cmd_status(args) -> int:
    state = json.loads((Path(args.run_dir) / "state.json").read_text())
    for n in NODES:
        info = state["nodes"].get(n)
        print(f"{n:9} {'done ' + json.dumps({k: v for k, v in info.items() if k != 'status'}) if info else 'pending'}")
    print(f"cached judgments: {len(state['classifications'])} classify, {len(state['reviews'])} review")
    return 0


def cmd_eval(args) -> int:
    data = load_labeled(Path(args.labeled))
    clf, rev = llm.make_judges(_offline(args))
    for name, judge in (("classifier", clf), ("reviewer", rev)):
        s = score(judge, data)
        print(f"{name:10} {s.summary()}")
        if args.verbose:
            for e in s.errors:
                print(f"   {'UNSAFE ' if e['unsafe'] else ''}{e['description']!r}: "
                      f"expected {e['expected']}, got {e['predicted']}")
    return 0


def cmd_tune(args) -> int:
    if not llm.have_api_key():
        print("tune needs ANTHROPIC_API_KEY: the loop uses a model to propose playbook lessons.",
              file=sys.stderr)
        return 1
    tune(llm.make_client(), load_labeled(Path(args.labeled)), Path(args.playbook),
         llm.PROPOSER_MODEL, llm.CLASSIFIER_MODEL, iterations=args.iterations)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="recoup", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("ap_csv")
    r.add_argument("--client", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--offline", action="store_true")
    r.add_argument("--ack-exposure", action="store_true",
                   help="acknowledge use tax exposure and let the packet build anyway")
    r.add_argument("--as-of", help="evaluate the refund window as of this date (YYYY-MM-DD)")
    r.set_defaults(fn=cmd_run)

    a = sub.add_parser("approve")
    a.add_argument("run_dir")
    a.add_argument("--by", required=True)
    a.set_defaults(fn=cmd_approve)

    s = sub.add_parser("status")
    s.add_argument("run_dir")
    s.set_defaults(fn=cmd_status)

    e = sub.add_parser("eval")
    e.add_argument("labeled")
    e.add_argument("--offline", action="store_true")
    e.add_argument("-v", "--verbose", action="store_true")
    e.set_defaults(fn=cmd_eval)

    t = sub.add_parser("tune")
    t.add_argument("labeled")
    t.add_argument("--playbook", default=str(llm.DEFAULT_PLAYBOOK))
    t.add_argument("--iterations", type=int, default=3)
    t.set_defaults(fn=cmd_tune)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
