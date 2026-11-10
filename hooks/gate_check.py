#!/usr/bin/env python3
"""Claude Code PreToolUse hook: the agent cannot approve its own work or rewrite the law.

Exit code 2 blocks the tool call and shows the reason to the model.
  * Approval is a human act: no writing approval.json, no running `recoup approve`.
  * Tax rules and gates change only with a human in the loop (RECOUP_ALLOW_RULE_EDITS=1).
  * Nothing gets filed or sent from the agent: no posting to state portals or email APIs.
"""
import json
import os
import re
import sys

PROTECTED = ("recoup/rules.py", "recoup/gates.py")
SEND_PATTERNS = re.compile(
    r"(comptroller\.texas\.gov|webfile|\.gov/.*(refund|claim)|sendgrid|mailgun|smtp|api\.postmarkapp)",
    re.I)


def deny(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    tool = event.get("tool_name", "")
    inp = event.get("tool_input", {}) or {}
    path = str(inp.get("file_path", ""))
    cmd = str(inp.get("command", ""))

    if tool in ("Write", "Edit", "MultiEdit"):
        if path.endswith("approval.json"):
            deny("Blocked: only a human approves a packet. Ask the user to run `recoup approve` themselves.")
        if any(path.endswith(p) for p in PROTECTED) and os.environ.get("RECOUP_ALLOW_RULE_EDITS") != "1":
            deny("Blocked: tax rules and gates are human-controlled. Write the proposed change and its "
                 "citation to proposals/ and ask the user to review it.")
    if tool == "Bash":
        if re.search(r"\brecoup(\.cli)?\s+approve\b|-m recoup\.cli approve", cmd):
            deny("Blocked: only a human approves a packet. Tell the user the packet is ready for review.")
        if SEND_PATTERNS.search(cmd):
            deny("Blocked: the agent prepares claims and never files or sends them.")
    sys.exit(0)


if __name__ == "__main__":
    main()
