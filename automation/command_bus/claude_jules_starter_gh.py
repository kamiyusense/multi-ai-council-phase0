"""Production Starter GitHub adapter: read-only snapshot over ``gh`` + prepare-only writes.

``read_snapshot`` builds the exact snapshot ``claude_jules_production_starter.next_step`` needs, using only GET
requests through the authenticated ``gh`` CLI.  ``prepare`` turns a write step into the ``gh`` command that
would perform it and returns it as data.  **This module never sends a write**: the real label write is the LIVE
boundary and is not implemented here.

    python3 -m automation.command_bus.claude_jules_starter_gh --campaign c.json --issue 338 --predecessor 335 \\
        --route-declaration route.json --controller local-1 --out snapshot.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Callable

from . import claude_jules_production_starter as st
from .claude_closed_loop_protocol import RECEIPT_MARKER

Getter = Callable[[str], Any]


def gh_get(path: str) -> Any:
    """One paginated GET through ``gh api`` (read-only)."""
    out = subprocess.run(["gh", "api", "--method", "GET", "--paginate", "--slurp", path], check=True,
                         capture_output=True, text=True, encoding="utf-8", timeout=120).stdout
    pages = json.loads(out)
    if pages and all(isinstance(p, list) for p in pages):
        return [x for p in pages for x in p]
    return pages[0] if len(pages) == 1 else pages


def read_issue(get: Getter, repo: str, number: int) -> dict[str, Any]:
    try:
        issue = get(f"repos/{repo}/issues/{number}")
    except subprocess.CalledProcessError:
        return {"number": number, "state": "MISSING"}
    comments = get(f"repos/{repo}/issues/{number}/comments?per_page=100")
    events = get(f"repos/{repo}/issues/{number}/events?per_page=100")
    return {"number": number, "state": "OPEN" if issue["state"] == "open" else "CLOSED", "title": issue["title"],
            "body": issue.get("body") or "", "labels": [l["name"] for l in issue.get("labels") or []],
            "label_events": [{"event": e["event"], "label": (e.get("label") or {}).get("name"),
                              "actor": (e.get("actor") or {}).get("login"), "created_at": e.get("created_at")}
                             for e in events if e.get("event") in {"labeled", "unlabeled"}],
            "comments": [{"id": c["id"], "author": (c.get("user") or {}).get("login"), "body": c.get("body") or "",
                          "created_at": c["created_at"]} for c in comments]}


def _terminal(issue: dict[str, Any], correlation: str, trusted: set[str]) -> bool:
    for c in issue["comments"]:
        if c["author"] in trusted and RECEIPT_MARKER in c["body"]:
            try:
                for rec in st._block(c["body"], RECEIPT_MARKER):
                    if rec.get("correlation_id") == correlation and (
                            rec.get("verdict") == "PASS" or rec.get("decision") == "TASK_BLOCKED"):
                        return True
            except ValueError:
                return False
    return False


def read_snapshot(get: Getter, *, repo: str, campaign: dict[str, Any], issue: int, predecessor: int | None,
                  route_declaration: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    policy = campaign["policy"]
    trusted = set(policy["trusted_writers"])
    cand = read_issue(get, repo, issue)
    pred = None
    if predecessor is not None:
        pred = read_issue(get, repo, predecessor)
        pr_number = None
        for c in pred.get("comments") or []:
            if c["author"] in trusted and RECEIPT_MARKER in c["body"]:
                try:
                    for rec in st._block(c["body"], RECEIPT_MARKER):
                        if rec.get("verdict") == "PASS":
                            pr_number = rec.get("pr")
                except ValueError:
                    pass
        pred["pr_head"] = get(f"repos/{repo}/pulls/{pr_number}")["head"]["sha"] if pr_number else None
    base = get(f"repos/{repo}/git/ref/heads/{policy['base_branch']}")["object"]["sha"]
    task, _ = st._task_of(cand.get("body") or "")
    changed = []
    if task and st._SHA40.fullmatch(str(task.get("expected_target_head") or "")) \
            and task["expected_target_head"] != base:
        cmp = get(f"repos/{repo}/compare/{task['expected_target_head']}...{base}")
        changed = None if cmp.get("status") not in {"ahead", "identical"} else [f["filename"] for f in cmp["files"]]
    active = []
    for i in get(f"repos/{repo}/issues?labels={st.LABEL}&state=open&per_page=100"):
        if "pull_request" in i:
            continue
        t, _ = st._task_of(i.get("body") or "")
        if t and t.get("correlation_id") and not _terminal(read_issue(get, repo, i["number"]), t["correlation_id"],
                                                             trusted):
            active.append({"issue": i["number"], "correlation_id": t["correlation_id"]})
    return {"repository": repo, "now": now or st._fmt(datetime.now(timezone.utc)), "candidate": cand,
            "predecessor": pred, "base_head": base, "base_changed_paths": changed, "active_tasks": active,
            "quota": {"state": st.QUOTA_UNKNOWN, "evidence": "Jules subscription usage is not readable"},
            "route_observation": route_declaration, "event": {}}


def prepare(step: st.Step, repo: str) -> dict[str, Any] | None:
    """The exact write a step would perform, as data (never executed here)."""
    if step.action == st.WRITE_LABEL:
        return {"action": step.action, "command": ["gh", "api", "--method", "POST",
                                                   f"repos/{repo}/issues/{step.issue}/labels", "-f",
                                                   f"labels[]={st.LABEL}"]}
    if step.action in {st.WRITE_INTENT, st.WRITE_START_RECEIPT}:
        return {"action": step.action, "command": ["gh", "api", "--method", "POST",
                                                   f"repos/{repo}/issues/{step.issue}/comments", "-F",
                                                   "body=@<step.body>"], "body": step.body}
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--predecessor", type=int)
    ap.add_argument("--route-declaration", required=True)
    ap.add_argument("--controller", required=True)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    with open(args.campaign, encoding="utf-8") as fh:
        campaign = json.load(fh)
    with open(args.route_declaration, encoding="utf-8") as fh:
        route = json.load(fh)
    snap = read_snapshot(gh_get, repo=campaign["repository"], campaign=campaign, issue=args.issue,
                         predecessor=args.predecessor, route_declaration=route)
    step = st.next_step(snap, campaign=campaign, controller=args.controller)
    report = {"step": step.as_dict(), "prepared_write": prepare(step, campaign["repository"]), "sent": False}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({"snapshot": snap, **report}, fh, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
