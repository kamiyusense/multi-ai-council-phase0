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
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Callable

from . import claude_jules_production_starter as st
from .claude_closed_loop_protocol import RECEIPT_MARKER
from .claude_jules_loop import TransientRead

Getter = Callable[[str], Any]


class NotFound(Exception):
    """GitHub answered 404 for the path."""


class ReadFailed(TransientRead):
    """A GET that failed for any other reason (auth, permission, 5xx, timeout): never read as "absent"."""


MAX_PAGES = 50
_STATUS = re.compile(r"HTTP/\S+\s+(\d{3})")
_NEXT_PAGE = re.compile(r'<[^>]*[?&]page=(\d+)[^>]*>;\s*rel="next"')


def _with_page(path: str, page: int) -> str:
    base, _, query = path.partition("?")
    params = [q for q in query.split("&") if q and not q.startswith("page=")]
    return f"{base}?{'&'.join(params + [f'page={page}'])}"


def gh_get(path: str) -> Any:
    """One GET through ``gh api``, following every page, read-only.

    Pages are followed by the page number in GitHub's ``Link`` header, but every request keeps the caller's
    ``repos/{owner}/{repo}/...`` path: the ``Link`` URLs use ``repositories/{id}/...``, which the cloud proxy refuses
    (HTTP 403), so ``gh api --paginate`` fails after page 1 in a cloud run.
    A 404 raises ``NotFound``; every other failure raises ``ReadFailed``, so a permission or network problem can
    never look like "no label history" or "issue missing".
    """
    pages: list[Any] = []
    page = 1
    for _ in range(MAX_PAGES):
        url = _with_page(path, page) if page > 1 else path
        try:
            proc = subprocess.run(["gh", "api", "--method", "GET", "--include", url],
                                  capture_output=True, text=True, encoding="utf-8", timeout=120)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ReadFailed(f"GET {url}: {exc}") from exc
        if proc.returncode != 0:
            if "HTTP 404" in (proc.stderr or ""):
                raise NotFound(path)
            raise ReadFailed(f"GET {url}: exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}")
        head, _, body = (proc.stdout or "").replace("\r\n", "\n").partition("\n\n")
        status = _STATUS.match(head)
        if not status or status.group(1) != "200":
            raise ReadFailed(f"GET {url}: status {status.group(1) if status else 'unreadable'}")
        try:
            pages.append(json.loads(body))
        except json.JSONDecodeError as exc:
            raise ReadFailed(f"GET {url}: unreadable JSON") from exc
        nxt = _NEXT_PAGE.search(head)
        if not nxt:
            if all(isinstance(p, list) for p in pages):
                return [x for p in pages for x in p]
            return pages[0] if len(pages) == 1 else pages
        if int(nxt.group(1)) <= page:
            raise ReadFailed(f"GET {path}: next page {nxt.group(1)} does not advance past {page}")
        page = int(nxt.group(1))
    raise ReadFailed(f"GET {path}: more than {MAX_PAGES} pages")


def read_issue(get: Getter, repo: str, number: int) -> dict[str, Any]:
    """Issue, every comment and the complete label history (all pages).  Only a 404 means MISSING."""
    try:
        issue = get(f"repos/{repo}/issues/{number}")
    except NotFound:
        return {"number": number, "state": "MISSING"}
    comments = get(f"repos/{repo}/issues/{number}/comments?per_page=100")
    events = get(f"repos/{repo}/issues/{number}/events?per_page=100")
    if not isinstance(comments, list) or not isinstance(events, list):
        raise ReadFailed(f"issue #{number}: comments or events are not lists")
    return {"number": number, "state": "OPEN" if issue["state"] == "open" else "CLOSED", "title": issue["title"],
            "body": issue.get("body") or "", "labels": [l["name"] for l in issue.get("labels") or []],
            "author": (issue.get("user") or {}).get("login"),
            "label_events": [{"event": e["event"], "label": (e.get("label") or {}).get("name"),
                              "actor": (e.get("actor") or {}).get("login"), "created_at": e.get("created_at")}
                             for e in events if e.get("event") in {"labeled", "unlabeled"}],
            "label_events_complete": True,       # every page of the issue events API was read
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
        self._issue_list: list[dict[str, Any]] | None = None
        self._pull_list: list[dict[str, Any]] | None = None

    # Repository-scoped listings, not ``search/issues``: a cloud session's proxy only serves
    # ``repos/{owner}/{repo}/...`` paths and answers HTTP 403 for search.  Each listing is read once per tick.
    def _all_issues(self) -> list[dict[str, Any]]:
        if self._issue_list is None:
            items = self.get(f"repos/{self.repo}/issues?state=all&per_page=100")
            self._issue_list = [i for i in items if "pull_request" not in i]
        return self._issue_list

    def _all_pulls(self) -> list[dict[str, Any]]:
        if self._pull_list is None:
            self._pull_list = self.get(f"repos/{self.repo}/pulls?state=all&per_page=100")
        return self._pull_list

    def _issues_with(self, needle: str) -> list[int]:
        return sorted(i["number"] for i in self._all_issues() if needle in (i.get("body") or ""))

    def list_campaign_issues(self):
        return [self.read_issue(n) for n in self._issues_with(self.campaign["campaign_id"])]

    def read_control_issue(self):
        n = self.campaign.get("control_issue")
        return self.read_issue(n) if n else None

    def base_head(self):
        return self.get(f"repos/{self.repo}/git/ref/heads/{self.campaign['policy']['base_branch']}")["object"]["sha"]

    def read_issue(self, n):
        if n not in self._issues:
            self._issues[n] = read_issue(self.get, self.repo, n)
        return dict(self._issues[n])

    def find_issue_by_correlation(self, corr):
        if not corr:
            return None
        found = self._issues_with(corr)
        return found[0] if found else None

    def _linked_pr(self, n):
        """The newest PR whose body says Fixes/Closes/Resolves #n (the reviewer's LAYER 1 rule)."""
        link = re.compile(rf"\b(?:fixes|closes|resolves)\s+#{n}\b", re.IGNORECASE)
        found = [p["number"] for p in self._all_pulls() if link.search(p.get("body") or "")]
        return max(found) if found else None

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
    ap.add_argument("--live-authorization", help="CLAUDE_JULES_LIVE_AUTHORIZATION_V1 file; without it nothing is sent")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    with open(args.campaign, encoding="utf-8") as fh:
        campaign = json.load(fh)
    with open(args.route_declaration, encoding="utf-8") as fh:
        route = json.load(fh)
    authorization = None
    if args.live_authorization:
        with open(args.live_authorization, encoding="utf-8") as fh:
            authorization = json.load(fh)
    signals = []
    if args.signals:
        with open(args.signals, encoding="utf-8") as fh:
            signals = json.load(fh)
    if authorization is None:
        port = GhLoopPort(gh_get, repo=campaign["repository"], campaign=campaign, route_declaration=route,
                          signals=signals)
    else:
        from .claude_jules_starter_live import GhLiveWritePort
        port = GhLiveWritePort(gh_get, repo=campaign["repository"], campaign=campaign, route_declaration=route,
                               signals=signals, authorization=authorization)
    try:
        res = loop.run_tick(port, campaign=campaign, controller=args.controller,
                            now=lambda: st._fmt(datetime.now(timezone.utc)))
        report = {"outcome": res.outcome, "reason": res.reason, "started": res.started, "created": res.created,
                  "defers": res.defers, "isolated": res.isolated, "human_actions": res.human_actions,
                  "next_wake": res.next_wake}
    except st.PreparedOnly:
        report = {"outcome": "PREPARED", "reason": "the tick reached a write"}
    report.update({"prepared_writes": port.prepared, "sent": list(getattr(port, "sent", [])),
                   "live": bool(getattr(port, "live", False)),
                   "authorization_problems": list(getattr(port, "problems", []))})
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main_tick(sys.argv[2:]) if sys.argv[1:2] == ["tick"] else main())
