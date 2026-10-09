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
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"snapshot": snap, **report}, fh, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0




# ---------------------------------------------------------------- loop tick over real GitHub reads (prepare-only)
class GhLoopPort:
    """The loop's port over ``gh`` GETs.  Every write raises ``PreparedOnly`` after recording what it would send."""

    def __init__(self, get: Getter, *, repo: str, campaign: dict[str, Any], route_declaration: dict[str, Any],
                 signals: list[dict[str, Any]] | None):
        self.get, self.repo, self.campaign = get, repo, campaign
        self.route_declaration, self.signal_list = route_declaration, signals
        self.prepared: list[dict[str, Any]] = []
        self._issues: dict[int, dict[str, Any]] = {}

    def _search(self, query: str) -> list[dict[str, Any]]:
        res = self.get(f"search/issues?q={query}&per_page=100")
        items = res.get("items", []) if isinstance(res, dict) else [x for p in res for x in p.get("items", [])]
        return items

    def list_campaign_issues(self):
        cid = self.campaign["campaign_id"]
        found = {i["number"] for i in self._search(f"repo:{self.repo}+is:issue+%22{cid}%22+in:body")}
        return [self.read_issue(n) for n in sorted(found)]

    def read_control_issue(self):
        n = self.campaign.get("control_issue")
        return self.read_issue(n) if n else None

    def base_head(self):
        return self.get(f"repos/{self.repo}/git/ref/heads/{self.campaign['policy']['base_branch']}")["object"]["sha"]

    def read_issue(self, n):
        if n not in self._issues:
            issue = read_issue(self.get, self.repo, n)
            if issue.get("state") != "MISSING":
                issue["author"] = (self.get(f"repos/{self.repo}/issues/{n}").get("user") or {}).get("login")
            self._issues[n] = issue
        return dict(self._issues[n])

    def find_issue_by_correlation(self, corr):
        if not corr:
            return None
        items = self._search(f"repo:{self.repo}+is:issue+%22{corr}%22+in:body")
        return items[0]["number"] if items else None

    def _linked_pr(self, n):
        items = self._search(f"repo:{self.repo}+is:pr+%22Fixes+%23{n}%22+in:body")
        return items[0]["number"] if items else None

    def pr_head(self, n):
        pr = self._linked_pr(n)
        return self.get(f"repos/{self.repo}/pulls/{pr}")["head"]["sha"] if pr else None

    def pr_merged(self, n):
        pr = self._linked_pr(n)
        return bool(pr and self.get(f"repos/{self.repo}/pulls/{pr}").get("merged"))

    def base_changed_paths(self, expected, base):
        if not expected or expected == base:
            return []
        cmp = self.get(f"repos/{self.repo}/compare/{expected}...{base}")
        return None if cmp.get("status") not in {"ahead", "identical"} else [f["filename"] for f in cmp["files"]]

    def quota(self):
        return {"state": st.QUOTA_UNKNOWN, "evidence": "Jules subscription usage is not readable"}

    def route(self):
        return dict(self.route_declaration)

    def signals(self):
        return self.signal_list

    def _prepare(self, kind: str, **data: Any):
        self.prepared.append({"write": kind, **data})
        raise st.PreparedOnly(kind)

    def create_issue(self, title, body):
        self._prepare("create_issue", title=title, body=body)

    def add_comment(self, n, body):
        self._prepare("comment", issue=n, body=body)

    def add_label(self, n, label):
        self._prepare("add_label", issue=n, label=label)


def main_tick(argv: list[str]) -> int:
    from . import claude_jules_loop as loop
    ap = argparse.ArgumentParser(prog="claude_jules_starter_gh tick",
                                 description="one loop tick over real GitHub reads; writes are prepared, never sent")
    ap.add_argument("--campaign", required=True)
    ap.add_argument("--route-declaration", required=True)
    ap.add_argument("--signals")
    ap.add_argument("--controller", required=True)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    with open(args.campaign, encoding="utf-8") as fh:
        campaign = json.load(fh)
    with open(args.route_declaration, encoding="utf-8") as fh:
        route = json.load(fh)
    signals = []
    if args.signals:
        with open(args.signals, encoding="utf-8") as fh:
            signals = json.load(fh)
    port = GhLoopPort(gh_get, repo=campaign["repository"], campaign=campaign, route_declaration=route,
                      signals=signals)
    try:
        res = loop.run_tick(port, campaign=campaign, controller=args.controller,
                            now=lambda: st._fmt(datetime.now(timezone.utc)))
        report = {"outcome": res.outcome, "reason": res.reason, "started": res.started, "created": res.created,
                  "defers": res.defers, "isolated": res.isolated, "human_actions": res.human_actions,
                  "next_wake": res.next_wake}
    except st.PreparedOnly:
        report = {"outcome": "PREPARED", "reason": "the tick reached a write"}
    report.update({"prepared_writes": port.prepared, "sent": False})
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main_tick(sys.argv[2:]) if sys.argv[1:2] == ["tick"] else main())
