# recoup

An agent that reads a company's accounts payable history, finds sales and use tax it overpaid, and drafts the refund packet: vendor refund letters, a state claim schedule, and a review queue for a licensed preparer.

On the sample ledger (21 lines from a fictional Texas machine shop) it finds $12,295.80 in refunds that pass every gate and $2,899.05 in likely use tax owed, and it sends five lines to a human.

## Quick start

```bash
pip install -e .
python -m recoup.cli run sample/ap_export.csv --client "Lone Star Precision Machining" \
    --out runs/demo --as-of 2026-11-09          # offline if ANTHROPIC_API_KEY is unset
cat runs/demo/packet/report.md
python -m recoup.cli approve runs/demo --by "Jane Doe, CPA"   # a human step
python -m pytest -q
```

With `ANTHROPIC_API_KEY` set, Claude does the classifying (`RECOUP_CLASSIFIER_MODEL`, default `claude-sonnet-5-5`) and reviewing (`RECOUP_REVIEWER_MODEL`, default `claude-opus-5-5`). Without it, a keyword classifier and a GL-account reviewer stand in so everything runs and tests offline.

## Architecture

```
AP export ─► ingest ─► classify ─► review ─► evaluate ─► gates ─► packet
              │          │           │          │          │         │
         alias-tolerant  Claude,    Claude as   rules as   can say   DRAFT until
         row errors      batched,   skeptical   data, no   no        a named human
                         parallel   auditor,    model                approves
                                    blind to    math
                                    classifier
           every node checkpoints to state.json + progress.md (resumable)
```

| Rung | Where it lives |
|---|---|
| Prompts | `classify.py`: closed taxonomy, XML-sectioned system prompts, forced tool output, "UNKNOWN beats a confident guess" |
| Claude Code | `CLAUDE.md`, three subagents in `.claude/agents/`, the `tx-sales-tax` skill |
| Loops | `recoup tune`: a proposer model writes playbook lessons from training errors, kept only if the held-out score improves |
| Graphs | `graph.py`: six-node pipeline with per-chunk checkpoints and an orchestrator fanning batches out to parallel workers |
| Gates | `gates.py` (evidence, independent review, materiality, net exposure) and `hooks/gate_check.py` (the agent cannot approve its own work, edit tax rules, or file anything) |
| Tools / MCP | `mcp_server.py`: three operator-shaped tools with compact responses and next-step hints |

LangGraph isn't used. A six-node linear graph with checkpoints is about 100 lines of plain Python. Switch if the graph grows branches that need replay or human interrupts mid-node.

## The exposure gate

A refund claim invites the state to audit the same period. If the review finds likely use tax owed above 25% of the refund total, the packet is blocked until someone decides how to handle it and re-runs with `--ack-exposure`. Competitors that report only refunds leave clients exposed to this.

## Status

- Verified: offline pipeline, engine rules, gates, resume, approval flow, hook, MCP tool calls, and the tune loop's keep/discard logic (22 tests, using fake model clients).
- Not yet verified: live Claude classification quality. Run `recoup eval evals/labeled.csv -v` with a key. The offline reviewer's 100% eval score is circular because the eval GL codes follow the default GL map.
- Texas only. Citations in `rules.py` need a licensed preparer's check before any packet is used.
