"""Give the Claude x Jules loop work: check a signal against the ACTIVE campaign, then (optionally) file it.

A signal is one evidence-backed problem in files an approved objective covers.  The loop turns open signal
issues into Jules tasks by itself on its next wake; nobody starts Jules by hand.  See docs/claude-jules-loop/README.md.

    python -m automation.command_bus.claude_jules_signal_cli check  --file signal.json
    python -m automation.command_bus.claude_jules_signal_cli create --file signal.json     # files the issue (gh)

`check` writes nothing.  It reports every problem the planner and the starter would find, including a missing
objective (adding one is a campaign.json PR that the owner merges).  `create` runs the same check first and refuses
on any problem; it never adds a label (the loop does that).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import claude_jules_production_starter as st
from . import claude_jules_task_planner as planner
from .claude_jules_starter_gh import render_signal_issue

ACTIVE_CAMPAIGN = Path("docs/claude-jules-loop/active/campaign.json")


def check(sig: Any, campaign: dict[str, Any]) -> list[str]:
    """Every reason the loop would not plan this signal; empty when it would."""
    if (problem := planner.validate_signal(sig)) is not None:
        return [problem]
    problems = []
    objectives = {o["objective_id"]: o for o in campaign.get("objectives") or []}
    objective = objectives.get(sig["objective_id"])
    if objective is None:
        return [f"objective {sig['objective_id']!r} is not in the active campaign; add it in a campaign.json PR the "
                f"owner merges (approved: {sorted(objectives)})"]
    if not isinstance(sig.get("acceptance_criteria"), list) or not sig["acceptance_criteria"]:
        problems.append("signal needs acceptance_criteria (checkable statements the reviewer verifies)")
    if not isinstance(sig.get("test_commands"), list) or not sig["test_commands"]:
        problems.append("signal needs test_commands (the reviewer runs them on Linux)")
    proposal = planner.propose_from_signal(sig, objective=objective)
    if (problem := planner.validate_proposal(proposal, campaign=campaign, known=[])) is not None:
        problems.append(problem)
    task = dict(proposal, kind="code_change")
    if (blocked := st.classify_task(task, campaign["policy"])) is not None:
        problems.append(f"{blocked[0]}: {blocked[1]}")
    if human := st.requested_human_operations(task):
        problems.append(f"the text asks for human-only operations {sorted(human)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="claude_jules_signal_cli", description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=("check", "create"))
    ap.add_argument("--file", required=True, help="signal JSON (see docs/claude-jules-loop/README.md)")
    ap.add_argument("--campaign", default=str(ACTIVE_CAMPAIGN))
    args = ap.parse_args(argv)
    sig = json.loads(Path(args.file).read_text(encoding="utf-8"))
    campaign = json.loads(Path(args.campaign).read_text(encoding="utf-8"))
    problems = check(sig, campaign)
    if problems:
        print(json.dumps({"ok": False, "problems": problems}, ensure_ascii=False, indent=2))
        return 2
    title, body = render_signal_issue(sig)
    if args.action == "check":
        print(json.dumps({"ok": True, "title": title, "body": body}, ensure_ascii=False, indent=2))
        return 0
    done = subprocess.run(["gh", "issue", "create", "--title", title, "--body-file", "-"], input=body,
                          capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:          # outcome unknown: list the issues before trying again, never resend blindly
        print(json.dumps({"ok": False, "problems": ["gh issue create failed: " + done.stderr.strip()[:300]]}))
        return 3
    print(json.dumps({"ok": True, "issue": done.stdout.strip()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
