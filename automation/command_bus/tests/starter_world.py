"""In-memory GitHub + mock Jules + mock reviewer Routine for Production Starter tests (no model, no network).

``FakeGitHub`` keeps the GitHub semantics the starter depends on: comment ids grow, adding a label that is
already present creates no event, a removed label stays in the label history, and faults can be injected per
write (lost response, unapplied timeout, crash before / after the write).

``World`` wires the loop exactly as production would:

    labeled issue -> mock Jules opens a PR -> reviewer (real ``precheck`` / ``combine`` / ``build_corrective`` /
    ``render_receipt`` from claude_closed_loop_review, scripted semantic verdicts) -> PASS creates the next issue
    from the campaign manifest (``body_ref``) then the receipt -> starter wakes -> ``run_starter`` -> label ...
"""
from __future__ import annotations

import copy
import hashlib
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from typing import Any

from automation.command_bus import claude_closed_loop_review as review
from automation.command_bus import claude_jules_production_starter as st

OWNER = "kamiyusense"
JULES = "google-labs-jules[bot]"
T0 = datetime(2026, 10, 10, 0, 0, 0, tzinfo=timezone.utc)
MAIN = "a" * 40


class Crash(Exception):
    """The controller process dies here."""


def sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


class FakeGitHub:
    def __init__(self, clock):
        self.clock = clock
        self.issues: dict[int, dict[str, Any]] = {}
        self.prs: dict[int, dict[str, Any]] = {}
        self.next_number = 400
        self.next_comment = 9000
        self.events: deque = deque()
        self.faults: list[dict[str, Any]] = []
        self.write_outage = False                               # every starter / loop write times out
        self.write_log: list[tuple[str, int]] = []

    # -- fault injection
    def inject(self, op: str, mode: str, *, issue: int | None = None, when=None) -> None:
        self.faults.append({"op": op, "mode": mode, "issue": issue, "when": when})

    def _fault(self, op: str, issue: int, body: str = "") -> str | None:
        for f in self.faults:
            if f["op"] == op and f["issue"] in (None, issue) and (f["when"] is None or f["when"](issue, body)):
                self.faults.remove(f)
                return f["mode"]
        return None

    def _apply_with_fault(self, op: str, issue: int, apply, body: str = ""):
        if self.write_outage:
            raise st.WriteOutcomeUnknown(f"{op} #{issue}: GitHub write outage (not applied)")
        mode = self._fault(op, issue, body)
        if mode == "crash_before":
            raise Crash(f"crash before {op} #{issue}")
        if mode == "timeout_unapplied":
            raise st.WriteOutcomeUnknown(f"{op} #{issue} timed out (not applied)")
        apply()
        self.write_log.append((op, issue))
        if mode == "lost":
            raise st.WriteOutcomeUnknown(f"{op} #{issue} applied, response lost")
        if mode == "crash_after":
            raise Crash(f"crash after {op} #{issue}")

    # -- issues
    def create_issue(self, title: str, body: str, author: str = OWNER) -> int:
        n = self.next_number
        self.next_number += 1
        self.issues[n] = {"number": n, "state": "OPEN", "title": title, "body": body, "labels": [],
                          "label_events": [], "comments": [], "author": author}
        self.events.append({"name": "issues.opened", "issue": n})
        return n

    def comment(self, n: int, body: str, author: str = OWNER) -> int:
        target = self.issues.get(n) or self.prs.get(n)
        cid = self.next_comment
        self.next_comment += 1
        target["comments"].append({"id": cid, "author": author, "body": body, "created_at": self.clock()})
        kind = "pr_comment" if n in self.prs else "issue_comment.created"
        self.events.append({"name": kind, "issue": n, "body": body, "author": author})
        return cid

    def starter_comment(self, n: int, body: str) -> None:
        self._apply_with_fault("comment", n, lambda: self.comment(n, body), body)

    def starter_label(self, n: int, label: str) -> None:
        self._apply_with_fault("label", n, lambda: self.add_label(n, label))

    def add_label(self, n: int, label: str, actor: str = OWNER) -> None:
        issue = self.issues[n]
        if label in issue["labels"]:
            return                                   # GitHub: no event for a label already present
        issue["labels"].append(label)
        issue["label_events"].append({"event": "labeled", "label": label, "actor": actor,
                                      "created_at": self.clock()})
        self.events.append({"name": "issues.labeled", "issue": n, "label": label})

    def remove_label(self, n: int, label: str) -> None:
        issue = self.issues[n]
        issue["labels"].remove(label)
        issue["label_events"].append({"event": "unlabeled", "label": label, "actor": OWNER,
                                      "created_at": self.clock()})

    def read_issue(self, n: int) -> dict[str, Any]:
        if n not in self.issues:
            return {"number": n, "state": "MISSING"}
        issue = copy.deepcopy(self.issues[n])
        issue["label_events_complete"] = not getattr(self, "label_history_unavailable", False)
        return issue

    def open_titles(self) -> dict[str, int]:
        return {i["title"]: n for n, i in self.issues.items() if i["state"] == "OPEN"}


class World:
    """Campaigns + GitHub + mock Jules + mock reviewer + starter controllers, driven by an event queue."""

    def __init__(self, campaigns: list[dict[str, Any]], *, review_script: dict[tuple[str, int], str] | None = None,
                 duplicate_every: int = 0):
        self.now = T0
        self.gh = FakeGitHub(lambda: st._fmt(self.now))
        self.campaigns = {c["campaign_id"]: c for c in campaigns}
        self.entries = {cid: st.validate_campaign(c) for cid, c in self.campaigns.items()}
        self.review_script = review_script or {}
        self.quota: dict[str, Any] = {"state": st.QUOTA_UNKNOWN}
        self.route = {"transport": st.ROUTE, "auth_method": "account_oauth", "billing_route": "subscription"}
        self.main_head = MAIN
        self.jules_starts: Counter = Counter()
        self.jules_pr: dict[int, int] = {}
        self.controllers = 0
        self.duplicate_every = duplicate_every
        self.delivered = 0
        self.reviewer_crash_after_next_issue: set[str] = set()
        self.reviewer_crashes: set[tuple[str, str]] = set()     # (task_id, "start" | "after_receipt")
        self.log: list[str] = []
        self.starter_results: list[st.RunResult] = []

    # -- time
    def tick(self, minutes: int = 1) -> None:
        self.now += timedelta(minutes=minutes)

    # -- lookups
    def task_of(self, n: int) -> dict[str, Any] | None:
        issue = self.gh.issues.get(n)
        task, _ = st._task_of(issue["body"]) if issue else (None, None)
        return task

    def issue_by_correlation(self, corr: str) -> int | None:
        for n in sorted(self.gh.issues):
            t = self.task_of(n)
            if t and t.get("correlation_id") == corr:
                return n
        return None

    def receipts(self, n: int) -> list[dict[str, Any]]:
        return [review.parse_receipt(c["body"]) for c in self.gh.issues[n]["comments"]
                if review.RECEIPT_MARKER in c["body"]]

    def terminal(self, n: int) -> bool:
        return any(r["verdict"] == review.PASS or r["decision"] == "TASK_BLOCKED" for r in self.receipts(n))

    def active_tasks(self) -> list[dict[str, Any]]:
        out = []
        for n, issue in self.gh.issues.items():
            t = self.task_of(n)
            if t and st.LABEL in issue["labels"] and not self.terminal(n):
                out.append({"issue": n, "correlation_id": t["correlation_id"]})
        return out

    # -- starter
    def snapshot(self, n: int, predecessor: int | None, campaign_id: str) -> dict[str, Any]:
        cand = self.gh.read_issue(n)
        pred_n = predecessor
        task = self.task_of(n)
        if pred_n is None and task and isinstance(task.get("campaign"), dict):
            p = task["campaign"].get("predecessor") or {}
            pred_n = p.get("issue") or (self.issue_by_correlation(p["correlation_id"]) if p.get("correlation_id")
                                        else None)
        pred = None
        if pred_n is not None and pred_n in self.gh.issues:
            pred = self.gh.read_issue(pred_n)
            pr = self.jules_pr.get(pred_n)
            pred["pr_head"] = self.gh.prs[pr]["head"] if pr else None
        return {"repository": "kamiyusense/multi-ai-council-phase0", "now": st._fmt(self.now), "candidate": cand,
                "predecessor": pred, "base_head": self.main_head, "base_changed_paths": [],
                "active_tasks": self.active_tasks(), "quota": dict(self.quota),
                "route_observation": dict(self.route), "event": {}}

    def campaign_for(self, n: int) -> dict[str, Any] | None:
        t = self.task_of(n)
        cid = (t or {}).get("campaign", {}).get("campaign_id") if isinstance((t or {}).get("campaign"), dict) else None
        return self.campaigns.get(cid)

    def run_controller(self, n: int, predecessor: int | None = None, controller: str | None = None) -> st.RunResult | None:
        campaign = self.campaign_for(n)
        if campaign is None:
            return None
        self.controllers += 1
        ctl = controller or f"ctl-{self.controllers}"
        try:
            res = st.run_starter(read_snapshot=lambda: self.snapshot(n, predecessor, campaign["campaign_id"]),
                                 add_comment=self.gh.starter_comment, add_label=self.gh.starter_label,
                                 campaign=campaign, controller=ctl)
        except Crash as exc:
            self.log.append(f"{ctl} crashed: {exc}")
            return None
        self.starter_results.append(res)
        self.log.append(f"{ctl} #{n}: {[s.action for s in res.steps]} {res.steps[-1].reason}")
        return res

    def starter_wake(self, event: dict[str, Any]) -> None:
        for target in st.wake_targets(event, trusted=[OWNER]):
            if target["issue"] == "ALL_OPEN_CANDIDATES":
                for n in sorted(self.gh.issues):
                    if self.gh.issues[n]["state"] == "OPEN" and self.campaign_for(n):
                        self.run_controller(n)
            else:
                self.run_controller(target["issue"], target.get("predecessor"))

    # -- mock Jules
    def jules_on_label(self, n: int) -> None:
        self.jules_starts[n] += 1
        task = self.task_of(n)
        pr = self.gh.next_number
        self.gh.next_number += 1
        head = sha(f"{n}-1")
        files = [{"filename": p["path"], "status": "added" if p["op"] == "ADD" else "modified"}
                 for p in task["allowed_paths"]]
        self.gh.prs[pr] = {"number": pr, "head": head, "tree": sha(f"tree-{n}-1"), "base": "main",
                           "body": f"Change for the task.\n\nFixes #{n}", "files": files, "comments": [], "rev": 1,
                           "issue": n}
        self.jules_pr[n] = pr
        self.gh.comment(n, "Jules is on it.", author=JULES)
        self.gh.events.append({"name": "pull_request.opened", "pr": pr})

    def jules_on_corrective(self, pr: int) -> None:
        p = self.gh.prs[pr]
        p["rev"] += 1
        p["head"] = sha(f"{p['issue']}-{p['rev']}")
        p["tree"] = sha(f"tree-{p['issue']}-{p['rev']}")
        self.gh.events.append({"name": "pull_request.synchronize", "pr": pr})

    # -- mock reviewer Routine (real reviewer code, scripted semantic verdict)
    def reviewer(self, pr_n: int) -> None:
        p = self.gh.prs[pr_n]
        issue = self.gh.issues.get(p["issue"])
        pre = review.precheck(pr={"number": pr_n, "head": p["head"], "base": p["base"], "body": p["body"]},
                              issue_body=issue["body"], issue_comments=[c["body"] for c in issue["comments"]],
                              pr_comments=[c["body"] for c in p["comments"]], files=p["files"],
                              head_tree=p["tree"], open_issue_titles=self.gh.open_titles())
        if pre.status != review.PROCEED:
            self.log.append(f"reviewer PR {pr_n}: {pre.status} {pre.reason}")
            return
        task = pre.task
        if (task["task_id"], "start") in self.reviewer_crashes or self.gh.write_outage:
            self.reviewer_crashes.discard((task["task_id"], "start"))
            raise Crash(f"reviewer died before reviewing {task['task_id']}")
        verdict = self.review_script.get((task["task_id"], pre.round), review.PASS)
        crit = task["acceptance_criteria"]
        findings = []
        if verdict == review.NEEDS_CORRECTION:
            findings = [{"category": "acceptance_unmet", "severity": "major",
                         "scope_paths": [task["allowed_paths"][0]["path"]], "what_is_wrong": "criterion 1 not met",
                         "expected_behavior": crit[0], "reproduction": "read the diff",
                         "regression_test": "add a test", "pass_condition": crit[0]}]
        sem = {"profile": review.SEMANTIC_PROFILE, "verdict": verdict,
               "criteria": [{"criterion": c, "met": verdict == review.PASS or i > 0, "evidence": "mock"}
                            for i, c in enumerate(crit)],
               "findings": findings, "tests": {"result": "PASS", "commands_run": task["test_commands"],
                                               "evidence": "mock"},
               "previous_findings_resolved": [{"fingerprint": review.finding_fingerprint(f), "resolved": True,
                                               "evidence": "mock"} for f in pre.previous_findings]}
        review.validate_semantic_review(sem, task=task, previous=pre.previous_findings)
        d = review.combine(pre, sem)
        corrective = None
        next_issue = pre.existing_next_issue
        if "corrective" in d.writes:
            self.gh.comment(pr_n, review.build_corrective(d, task=task, pr_head_sha=p["head"]))
            corrective = f"https://example.invalid/pr/{pr_n}"
        if "next_issue" in d.writes:
            ref = task["next_task"]["body_ref"]          # reviewer v1.6: render-next, then create verbatim
            nxt = st.render_next(self.campaigns[ref["campaign_id"]], seq=ref["seq"],
                                 expected_sha256=ref["task_sha256"])
            next_issue = self.gh.create_issue(nxt["title"], nxt["body"])
            if task["task_id"] in self.reviewer_crash_after_next_issue:
                self.reviewer_crash_after_next_issue.discard(task["task_id"])
                self.log.append(f"reviewer crashed after creating #{next_issue}")
                return
        record = {"profile": review.RECEIPT_PROFILE, "task_id": task["task_id"], "loop_id": task["loop_id"],
                  "correlation_id": task["correlation_id"], "generation": task["generation"], "round": d.round,
                  "phase": "FINAL", "pr": pr_n, "pr_head_sha": p["head"], "pr_head_tree": p["tree"],
                  "expected_target_head": task["expected_target_head"], "observed_base_head": self.main_head,
                  "verdict": d.verdict, "decision": d.decision, "criteria": sem["criteria"],
                  "findings": list(d.findings), "escalate_root_cause": d.escalate_root_cause, "tests": sem["tests"],
                  "live_slot": task["live_slot"], "corrective_comment": corrective,
                  "next_issue": next_issue if d.verdict == review.PASS else None,
                  "wake_event": "pull_request", "reviewed_at": st._fmt(self.now)}
        self.gh.comment(p["issue"], review.render_receipt(summary=f"review {d.verdict}", record=record))
        if (task["task_id"], "after_receipt") in self.reviewer_crashes:
            self.reviewer_crashes.discard((task["task_id"], "after_receipt"))
            raise Crash(f"reviewer died right after the {d.verdict} receipt of {task['task_id']}")

    # -- event loop
    def deliver(self, event: dict[str, Any]) -> None:
        name = event["name"]
        if name in {"pull_request.opened", "pull_request.synchronize"}:
            self.reviewer(event["pr"])
        elif name == "pr_comment":
            if event["author"] == OWNER and event["body"].startswith("@jules"):
                self.jules_on_corrective(event["issue"])
        elif name == "issues.labeled":
            if event["label"] == st.LABEL:
                self.jules_on_label(event["issue"])
            self.starter_wake(event)
        else:
            self.starter_wake(event)

    def step_one(self) -> bool:
        """Deliver exactly one queued event; False when the queue is empty."""
        if not self.gh.events:
            return False
        event = self.gh.events.popleft()
        self.tick()
        self.deliver(event)
        return True

    def run(self, max_events: int = 5000, schedule_every: int = 0) -> None:
        handled = 0
        while handled < max_events:
            if not self.gh.events:
                return
            event = self.gh.events.popleft()
            self.tick()
            self.deliver(event)
            handled += 1
            self.delivered += 1
            if self.duplicate_every and self.delivered % self.duplicate_every == 0 \
                    and event["name"] != "issues.labeled":
                self.deliver(event)                   # the same webhook delivered twice
            if schedule_every and handled % schedule_every == 0:
                self.deliver({"name": "schedule"})
        raise AssertionError("event loop did not settle")

    def settle(self, rounds: int = 6, minutes: int = 20) -> None:
        """Let leases expire and run the scheduled reconciler until nothing changes."""
        for _ in range(rounds):
            self.run()
            self.tick(minutes)
            self.deliver({"name": "schedule"})
            self.run()


# ---------------------------------------------------------------- campaign builders
def code_task(task_id: str, *, path: str, base: str = MAIN, rounds: int = 2, extra: dict | None = None) -> dict:
    task = {"profile": "CLAUDE_CLOSED_LOOP_TASK_V1", "kind": "code_change", "task_id": task_id,
            "correlation_id": f"{task_id}-{base[:7]}", "expected_target_branch": "main",
            "expected_target_head": base, "generation": 1, "max_corrective_rounds": rounds, "live_slot": 0,
            "round": 1, "route": st.ROUTE, "allowed_paths": [{"path": path, "op": "MODIFY"}],
            "acceptance_criteria": [f"{task_id}: behaviour fixed", f"{task_id}: regression test added"],
            "test_commands": ["python3 -m unittest discover -s automation/command_bus/tests -t ."]}
    task.update(extra or {})
    return task


def campaign(campaign_id: str, n: int, *, policy: dict | None = None, extras: dict[int, dict] | None = None,
             external_predecessor: dict | None = None) -> dict:
    specs = [{"title": f"[{campaign_id}] task {k}", "intro": f"Task {k} of campaign {campaign_id}.",
              "task": code_task(f"{campaign_id}-t{k}", path=f"docs/{campaign_id}/t{k}.md",
                                extra=(extras or {}).get(k))} for k in range(1, n + 1)]
    return st.build_campaign(campaign_id=campaign_id, loop_id=f"loop-{campaign_id}", tasks=specs,
                             policy=policy or st.make_policy(),
                             external_predecessor=external_predecessor or
                             {"task_id": f"{campaign_id}-seed", "correlation_id": f"{campaign_id}-seed-aaaaaaa",
                              "issue": None},
                             manifest_ref={"path": f"campaigns/{campaign_id}.json",
                                           "ref": "claude/claude-jules-autoloop-data"})


def seed_predecessor(world: World, c: dict) -> tuple[int, int]:
    """A PASSed seed task whose receipt names a freshly created first campaign issue (as the reviewer would)."""
    first = world.entries[c["campaign_id"]][1]
    pred_meta = first["task"]["campaign"]["predecessor"]
    seed = code_task(pred_meta["task_id"], path=f"docs/{c['campaign_id']}/seed.md")
    seed["correlation_id"] = pred_meta["correlation_id"]
    seed["loop_id"] = c["loop_id"]
    seed_issue = world.gh.create_issue(f"[{c['campaign_id']}] seed", st.render_task_issue(seed, "Seed task."))
    world.gh.issues[seed_issue]["labels"].append(st.LABEL)
    world.gh.issues[seed_issue]["label_events"].append({"event": "labeled", "label": st.LABEL, "actor": OWNER,
                                                        "created_at": st._fmt(world.now)})
    pr = world.gh.next_number
    world.gh.next_number += 1
    world.gh.prs[pr] = {"number": pr, "head": sha("seed"), "tree": sha("seed-tree"), "base": "main",
                        "body": f"Fixes #{seed_issue}", "files": [], "comments": [], "rev": 1, "issue": seed_issue}
    world.jules_pr[seed_issue] = pr
    nxt = world.gh.create_issue(first["title"], first["body"])
    record = {"profile": review.RECEIPT_PROFILE, "task_id": seed["task_id"], "loop_id": seed["loop_id"],
              "correlation_id": seed["correlation_id"], "generation": 1, "round": 1, "phase": "FINAL", "pr": pr,
              "pr_head_sha": sha("seed"), "pr_head_tree": sha("seed-tree"), "expected_target_head": MAIN,
              "observed_base_head": MAIN, "verdict": review.PASS, "decision": "ADOPT_RECORDED",
              "criteria": [{"criterion": c_, "met": True, "evidence": "seed"} for c_ in seed["acceptance_criteria"]],
              "findings": [], "escalate_root_cause": False, "tests": {"result": "PASS"}, "live_slot": 0,
              "corrective_comment": None, "next_issue": nxt, "wake_event": "pull_request",
              "reviewed_at": st._fmt(world.now)}
    world.gh.comment(seed_issue, review.render_receipt(summary="seed PASS", record=record))
    return seed_issue, nxt


# ---------------------------------------------------------------- autonomous loop world (planner + PR-event wakes)
class LoopWorld(World):
    """The loop as production wires it: the only wakes are pull_request events (reviewer Routine, then a loop
    tick), pull_request.closed(merged) events, an optional recovery schedule, and the human's first start.
    Issue events wake nothing (Routine GitHub triggers support pull_request and release only)."""

    def __init__(self, campaign_: dict, signals: list[dict], *, review_script=None, duplicate_every: int = 0,
                 recovery_wake: bool = True, proposer=None):
        super().__init__([campaign_], review_script=review_script, duplicate_every=duplicate_every)
        from automation.command_bus import claude_jules_loop as loop
        self.loop = loop
        self.campaign = campaign_
        self.backlog = signals
        self.recovery_wake = recovery_wake
        self.proposer = proposer
        self.signal_failures = 0
        self.read_failures = 0
        self.main_history: list[tuple[str, list[str]]] = [(MAIN, [])]
        self.ticks: list[Any] = []
        self.loop_crashes = 0
        self._quota = self.__dict__.pop("quota")          # the port exposes quota() / route() as methods
        self._route = self.__dict__.pop("route")
        self.control = self.gh.create_issue("Claude x Jules loop control", "Loop checkpoints are recorded here.")
        campaign_["control_issue"] = self.control
        self.gh.events.clear()

    # -- port (what a Routine reads and writes on GitHub)
    def list_campaign_issues(self):
        if self.read_failures:
            self.read_failures -= 1
            raise self.loop.TransientRead("GitHub 502")
        return [self.gh.read_issue(n) for n in sorted(self.gh.issues) if n != self.control]

    def read_control_issue(self):
        return self.gh.read_issue(self.control)

    def base_head(self):
        return self.main_head

    def read_issue(self, n):
        return self.gh.read_issue(n)

    def find_issue_by_correlation(self, corr):
        return self.issue_by_correlation(corr) if corr else None

    def pr_head(self, n):
        pr = self.jules_pr.get(n)
        return self.gh.prs[pr]["head"] if pr else None

    def pr_merged(self, n):
        pr = self.jules_pr.get(n)
        return bool(pr and self.gh.prs[pr].get("merged"))

    def base_changed_paths(self, expected, base):
        if expected == base:
            return []
        heads = [h for h, _ in self.main_history]
        if expected not in heads:
            return None
        return sorted({p for _, paths in self.main_history[heads.index(expected) + 1:] for p in paths})

    def quota(self):
        return dict(self._quota)

    def route(self):
        return dict(self._route)

    def signals(self):
        if self.signal_failures:
            self.signal_failures -= 1
            raise self.loop.TransientRead("signal source unavailable")
        return [dict(s) for s in self.backlog]

    def create_issue(self, title, body):
        out = {}
        self.gh._apply_with_fault("create", 0, lambda: out.setdefault("n", self.gh.create_issue(title, body)), body)
        return out["n"]

    def add_comment(self, n, body):
        self.gh.starter_comment(n, body)

    def add_label(self, n, label):
        self.gh.starter_label(n, label)

    # -- wakes
    def tick_loop(self, wake: str) -> None:
        self.controllers += 1
        try:
            res = self.loop.run_tick(self, campaign=self.campaign, controller=f"routine-{self.controllers}",
                                     now=lambda: st._fmt(self.now), proposer=self.proposer)
        except Crash as exc:
            self.loop_crashes += 1
            self.log.append(f"loop tick ({wake}) crashed: {exc}")
            return
        self.ticks.append(res)
        self.log.append(f"tick {wake}: {res.outcome} started={res.started} created={res.created} {res.reason}")

    def human_merge(self, issue: int) -> None:
        pr = self.jules_pr[issue]
        p = self.gh.prs[pr]
        p["merged"] = True
        self.main_head = sha(f"main-after-{pr}")
        self.main_history.append((self.main_head, [f["filename"] for f in p["files"]]))
        self.gh.events.append({"name": "pull_request.closed", "pr": pr, "merged": True})

    def deliver(self, event):
        name = event["name"]
        if name in {"pull_request.opened", "pull_request.synchronize"}:
            try:
                self.reviewer(event["pr"])
            except Crash as exc:                 # the Routine run died: no tick in this run
                self.loop_crashes += 1
                self.log.append(f"reviewer crashed: {exc}")
                return
            self.tick_loop(name)                 # same Routine run: receipt, then a loop tick
        elif name == "pull_request.closed":
            self.tick_loop(name)
        elif name == "pr_comment":
            if event["author"] == OWNER and event["body"].startswith("@jules"):
                self.jules_on_corrective(event["issue"])
        elif name == "issues.labeled":
            if event["label"] == st.LABEL:
                self.jules_on_label(event["issue"])
        elif name in {"schedule", "start"}:
            if name == "start" or self.recovery_wake:
                if name == "schedule":       # recovery: review any PR head that has no receipt (lost PR event)
                    for pr in sorted(self.gh.prs):
                        if not self.gh.prs[pr].get("merged") and self.gh.prs[pr]["issue"] in self.gh.issues:
                            try:
                                self.reviewer(pr)
                            except Crash as exc:
                                self.loop_crashes += 1
                                self.log.append(f"reviewer crashed in recovery: {exc}")
                                return
                self.tick_loop(name)
        # issues.opened / issue_comment.created wake nothing

    def run_until_quiet(self, *, max_wakes: int = 400, merge_policy=None, schedule_minutes: int = 60) -> None:
        """Deliver events; when the queue is empty, let the human merge (merge_policy) or the schedule wake."""
        for _ in range(max_wakes):
            self.run()
            if merge_policy is not None:
                to_merge = merge_policy(self)
                for n in to_merge:
                    self.human_merge(n)
                if to_merge:
                    continue
            last = self.ticks[-1].outcome if self.ticks else None
            if last in {"GOAL_COMPLETE", "NO_SAFE_TASK", "MERGE_WAIT"} and not self.gh.events:
                if merge_policy is None or not merge_policy(self):
                    return
            self.tick(schedule_minutes)
            self.deliver({"name": "schedule"})
        raise AssertionError("loop did not settle")


def objective(oid: str, prefixes: list[str], *, ops=None, priority: int = 10) -> dict:
    return {"objective_id": oid, "title": f"objective {oid}", "scope_prefixes": prefixes,
            "allowed_operations": ops or ["bug_fix", "test_add", "test_fix", "code_edit", "docs_update",
                                          "safety_test_add", "safety_static_fix", "fixture_add", "mock_add"],
            "priority": priority, "approved_by": "user", "approved_at": "2026-10-09T00:00:00Z"}


def planner_campaign(cid: str, objectives: list[dict], *, policy: dict | None = None) -> dict:
    pol = policy or st.make_policy()
    manifest = {"profile": st.CAMPAIGN_PROFILE, "campaign_id": cid, "loop_id": f"loop-{cid}",
                "repository": pol["repository"], "policy": pol, "tasks": [], "objectives": objectives}
    st.validate_campaign(manifest)
    return manifest


def signal(sid: str, oid: str, path: str, *, kind: str = "failing_test", depends_on=None, **extra) -> dict:
    sig = {"signal_id": sid, "objective_id": oid, "kind": kind, "summary": f"fix {sid}", "paths": [path],
           "evidence": [f"log:{sid}"]}
    if depends_on:
        sig["depends_on_signals"] = depends_on
    sig.update(extra)
    return sig
