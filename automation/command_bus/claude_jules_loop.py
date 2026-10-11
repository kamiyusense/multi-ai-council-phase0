"""Autonomous loop controller: restore state from GitHub, start what may start, plan what is next, record why.

One ``run_tick`` is what a wake does.  In production the wake is the reviewer Routine itself: after it records a
receipt on a ``pull_request`` event it runs a tick.  A ``pull_request.closed`` (merged) event runs a tick so that
merge-dependent work resumes.  A recovery wake (schedule), if the user approves one, runs a tick so that a run that
died mid-way is picked up.  Every tick starts from GitHub alone, so a crash anywhere is recovered by the next wake.

A tick:

1. reads the campaign's issues (bounded read retry; a read that keeps failing is DEFER READ_UNKNOWN, not a stop);
2. derives every task's state (PREPARED, RUNNING, PASS_UNMERGED, MERGED, ISOLATED, CLOSED);
3. offers each PREPARED task to the Production Starter.  The first one that may start is started (intent → label
   → receipt).  The others are recorded as DEFER or ISOLATE with a reason code.  An ISOLATE affects only that
   task;
   A RUNNING task whose corrective Jules did not apply (same tree, or no commit for the ack timeout) gets that
   corrective resent once through the Jules API (``ignored_corrective``);
4. if nothing could start and capacity is free, asks the planner for the next task inside the approved
   objectives, creates its issue (one atomic write) and offers it to the Starter;
5. ends with one outcome:
   * ``CONTINUE``: a task was started or is running; its PR event is the next wake;
   * ``MERGE_WAIT``: only merge-dependent work is left; a human merges;
   * ``NO_SAFE_TASK``: there are open signals, but none of them is safe or valid; a human looks;
   * ``GOAL_COMPLETE``: every signal is resolved;
   * ``DEFER``: something temporary (quota, lease, unknown read); the next wake re-checks;
   * ``HARD_STOP_PROVIDER``: a paid route or an invalid policy; no new Jules starts, other safe work is
     unaffected;
6. writes a checkpoint (``claude-jules-loop-checkpoint v1``) on the campaign's control issue when the state
   changed or a heartbeat is due.  A DEFER keeps its ``first_seen_at`` across ticks, and when it is older than
   ``defer_escalate_minutes`` and no independent work is left it is escalated (``human_required``). So a DEFER
   never waits silently.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from . import claude_jules_production_starter as st
from . import claude_jules_task_planner as planner
from .claude_closed_loop_protocol import RECEIPT_MARKER, _block

CHECKPOINT_MARKER = "<!-- claude-jules-loop-checkpoint v1"
CHECKPOINT_PROFILE = "CLAUDE_JULES_LOOP_CHECKPOINT_V1"
CONTINUE, MERGE_WAIT, NO_SAFE_TASK, GOAL_COMPLETE, DEFER, HARD_STOP_PROVIDER = (
    "CONTINUE", "MERGE_WAIT", "NO_SAFE_TASK", "GOAL_COMPLETE", "DEFER", "HARD_STOP_PROVIDER")

RECOVERY = {
    "READ_UNKNOWN": "re-read on the next wake",
    "WRITE_READBACK_UNKNOWN": "read GitHub back on the next wake before any new start; never re-send",
    "BUDGET_EXHAUSTED": "a human raises the durable LIVE budget (declaration) and authorizes; re-checked each wake",
    "JULES_PENDING": "Jules' PR or next commit (a pull_request event) wakes the loop",
    "REVIEW_PENDING": "the recovery wake reviews any PR head without a receipt",
    "RECORD_UNREADABLE": "a human repairs the unreadable record; nothing is written over it",
    "LABEL_HISTORY_UNKNOWN": "re-read the complete issue events history; never start without it",
    "ROUTE_UNKNOWN": "re-check the route declaration on the next wake",
    "PREDECESSOR_PENDING": "the predecessor's receipt (its PR event) wakes the loop",
    "LEASE_HELD": "take over after the intent lease",
    "WRITE_UNCONFIRMED": "read back on the next wake; never re-send",
    "MERGE_WAIT": "a pull_request.closed (merged) event resumes it",
    "PATH_CONFLICT_PENDING_MERGE": "a pull_request.closed (merged) event resumes it",
    "DEPENDENCY_PENDING": "the dependency's PR event wakes the loop",
    "DEPENDENCY_UNKNOWN": "re-read on the next wake",
    "BASE_UNKNOWN": "re-read the base branch on the next wake",
    "CONCURRENCY": "the running task's PR event wakes the loop",
    "QUOTA_EXHAUSTED": "resume after the quota reset",
    "QUOTA_UNKNOWN": "re-check quota on the next wake",
    "ROUND_LIMIT": "a human may extend the campaign",
    "WRITE_PATH_UNHEALTHY": "retry with backoff after a label-never-present readback; a human checks GitHub",
    "JULES_IGNORED_CORRECTIVE": "the corrective was resent once through the Jules API; Jules' next commit wakes "
                                "the loop",
    "JULES_UNRESPONSIVE": "a human looks at the task: Jules ignored the corrective and its Jules API resend",
}


def ignored_corrective(mine: list[dict[str, Any]], *, head: str, head_tree: Callable[[], str | None], now: str,
                       ack_minutes: int) -> dict[str, Any] | None:
    """The latest corrective receipt when Jules did not apply it, else None.

    Not applied means: Jules pushed a commit with exactly the reviewed tree (the reviewer's LAYER 1 NO-OP, which
    otherwise waits forever), or nothing at all for ``ack_minutes`` after the review.  A later review of any
    kind means the corrective was answered."""
    corr = [r for r in mine if r.get("decision") == "CORRECTIVE_REQUESTED" and r.get("corrective_comment")]
    if not corr:
        return None
    latest = max(corr, key=lambda r: r.get("round") or 0)
    if any((r.get("round") or 0) > (latest.get("round") or 0) for r in mine):
        return None
    if head == latest.get("pr_head_sha"):
        try:
            overdue = st._ts(now) - st._ts(latest["reviewed_at"]) >= timedelta(minutes=ack_minutes)
        except (KeyError, TypeError, ValueError):
            return None
        return latest if overdue else None
    return latest if latest.get("pr_head_tree") and head_tree() == latest["pr_head_tree"] else None


class TransientRead(Exception):
    """A read that failed for a temporary reason (network, 5xx); bounded retry, then DEFER."""


@dataclass
class TickResult:
    outcome: str
    reason: str
    started: list[int] = field(default_factory=list)
    created: list[int] = field(default_factory=list)
    defers: list[dict[str, Any]] = field(default_factory=list)
    isolated: list[dict[str, Any]] = field(default_factory=list)
    human_actions: list[dict[str, Any]] = field(default_factory=list)
    next_wake: str = ""
    checkpoint: dict[str, Any] | None = None
    checkpoint_written: bool = False


def read_retry(read: Callable[[], Any], attempts: int) -> Any:
    last = None
    for _ in range(max(1, attempts)):
        try:
            return read()
        except TransientRead as exc:
            last = exc
    raise last  # type: ignore[misc]


def _receipts(issue: dict[str, Any], trusted: set[str]) -> list[dict[str, Any]]:
    out = []
    for c in issue.get("comments") or []:
        if c.get("author") in trusted and RECEIPT_MARKER in (c.get("body") or ""):
            try:
                out.extend(r for r in _block(c["body"], RECEIPT_MARKER) if isinstance(r, dict))
            except (ValueError, json.JSONDecodeError):
                out.append({"_unreadable": True})
    return out


def task_states(issues: list[dict[str, Any]], *, campaign: dict[str, Any],
                pr_merged: Callable[[int], bool | None]) -> list[dict[str, Any]]:
    """Every campaign task with its state, derived only from GitHub."""
    trusted = set(campaign["policy"]["trusted_writers"])
    known = []
    for issue in issues:
        task, _ = st._task_of(issue.get("body") or "")
        meta = (task or {}).get("campaign")
        if not isinstance(meta, dict) or meta.get("campaign_id") != campaign["campaign_id"]:
            continue
        mine = [r for r in _receipts(issue, trusted) if r.get("_unreadable") or
                r.get("correlation_id") == task["correlation_id"]]
        try:
            _, starts = st.starter_records(issue.get("comments") or [], trusted)
        except (ValueError, json.JSONDecodeError):
            starts = []
        started = bool(starts) or st.LABEL in (issue.get("labels") or [])
        if any(r.get("verdict") == "PASS" for r in mine):
            try:
                merged = pr_merged(issue["number"])
            except TransientRead:
                merged = False        # unknown merge state never unlocks merge-dependent work
            state = planner.MERGED if merged else planner.PASS_UNMERGED
        elif any(r.get("decision") == "TASK_BLOCKED" or r.get("verdict") == "BLOCKED" for r in mine):
            state = planner.ISOLATED
        elif started:
            state = planner.RUNNING
        elif issue.get("state") != "OPEN":
            state = planner.CLOSED
        else:
            state = planner.PREPARED
        known.append({"issue": issue["number"], "task_id": task["task_id"], "correlation_id": task["correlation_id"],
                      "fingerprint": meta.get("fingerprint"), "signal_id": meta.get("signal_id"), "state": state,
                      "paths": [p["path"] for p in task.get("allowed_paths") or []], "source": meta.get("source",
                                                                                                        "manifest")})
    return known


def _resend_corrective(port: Any, task: dict[str, Any], receipt: dict[str, Any], *, head: str, now: str,
                       ack_minutes: int) -> tuple[str, str, bool]:
    """Resend an ignored corrective once through the Jules API: one create-only request file per corrective round.

    The request id is derived from the task and round, so a lost response is read back on the next wake and never
    sent twice.  If Jules ignores the resend too, the task waits for a human (visible, never a silent stop)."""
    rnd = receipt.get("round")
    rid = f"{task['task_id']}-r{rnd}-msg"
    try:
        sent_at = port.api_message_sent_at(rid)
    except TransientRead as exc:
        return "READ_UNKNOWN", f"Jules API resend {rid}: carrier unreadable ({exc}); the next wake re-reads", False
    if sent_at is not None:
        try:
            overdue = st._ts(now) - st._ts(sent_at) >= timedelta(minutes=ack_minutes)
        except (TypeError, ValueError):
            overdue = False
        if overdue:
            return ("JULES_UNRESPONSIVE", f"Jules applied neither corrective round {rnd} nor its Jules API resend "
                    f"{rid} (sent {sent_at})", True)
        return "JULES_IGNORED_CORRECTIVE", f"corrective round {rnd} resent via the Jules API at {sent_at}", False
    try:
        status = port.api_message(rid, issue=task["issue"], receipt=receipt, head=head)
    except st.WriteOutcomeUnknown as exc:
        return "WRITE_UNCONFIRMED", f"Jules API resend {rid}: outcome unknown ({exc}); read back, never re-sent", False
    except TransientRead as exc:
        return "READ_UNKNOWN", f"Jules API resend {rid}: a read failed before sending ({exc})", False
    if status != "SENT":
        return ("JULES_IGNORED_CORRECTIVE", f"Jules did not apply corrective round {rnd}; the Jules API resend was "
                f"not sent: {status}", True)
    return "JULES_IGNORED_CORRECTIVE", f"Jules did not apply corrective round {rnd}; resent via the Jules API ({rid})", \
        False


def _previous_checkpoint(control: dict[str, Any] | None, trusted: set[str]) -> dict[str, Any] | None:
    if not control:
        return None
    for c in sorted(control.get("comments") or [], key=lambda c: c["id"], reverse=True):
        if c.get("author") in trusted and CHECKPOINT_MARKER in (c.get("body") or ""):
            try:
                rec = _block(c["body"], CHECKPOINT_MARKER)[0]
            except (ValueError, json.JSONDecodeError, IndexError):
                return None
            return {**rec, "_at": c["created_at"]}
    return None


def render_checkpoint(record: dict[str, Any]) -> str:
    return (f"Loop checkpoint: {record['outcome']} ({record['reason']}). Record only; no action needed.\n\n"
            f"{CHECKPOINT_MARKER}\n{st.canonical(record)}\n-->\n")


def run_tick(port: Any, *, campaign: dict[str, Any], controller: str, now: Callable[[], str],
             proposer=None) -> TickResult:
    """One wake of the loop.  ``port`` gives GitHub reads and the three starter writes plus ``create_issue``."""
    policy = campaign["policy"]
    trusted = set(policy["trusted_writers"])
    attempts = policy["read_retry"]["attempts"]
    try:
        issues = read_retry(port.list_campaign_issues, attempts)
        control = read_retry(port.read_control_issue, attempts)
        base = read_retry(port.base_head, attempts)
    except TransientRead as exc:
        return TickResult(DEFER, f"GitHub read failed after {attempts} attempts ({exc}); the next wake re-reads",
                          next_wake="next wake")
    known = task_states(issues, campaign=campaign, pr_merged=port.pr_merged)
    by_number = {i["number"]: i for i in issues}
    result = TickResult(CONTINUE, "")

    def snapshot(n: int) -> dict[str, Any]:
        cand = port.read_issue(n)
        task, _ = st._task_of(cand.get("body") or "")
        pred = None
        meta = (task or {}).get("campaign") or {}
        if isinstance(meta, dict) and meta.get("source", "manifest") == "manifest":
            p = meta.get("predecessor") or {}
            pred_n = p.get("issue") or port.find_issue_by_correlation(p.get("correlation_id"))
            if pred_n is not None:
                pred = port.read_issue(pred_n)
                pred["pr_head"] = port.pr_head(pred_n)
        states = {k["task_id"]: k["state"] for k in known}
        return {"repository": policy["repository"], "now": now(), "candidate": cand, "predecessor": pred,
                "base_head": base, "base_changed_paths": port.base_changed_paths(
                    (task or {}).get("expected_target_head"), base),
                "active_tasks": [{"issue": k["issue"], "correlation_id": k["correlation_id"]} for k in known
                                 if k["state"] == planner.RUNNING],
                "quota": port.quota(), "route_observation": port.route(),
                "known_tasks": known, "task_states": states,
                "pending_merge": [{"task_id": k["task_id"], "paths": k["paths"]} for k in known
                                  if k["state"] == planner.PASS_UNMERGED], "event": {}}

    wrote: list[tuple[str, int]] = []

    def add_comment(n: int, body: str) -> Any:
        wrote.append(("comment", n))
        return port.add_comment(n, body)

    def add_label(n: int, label: str) -> Any:
        wrote.append(("label", n))
        return port.add_label(n, label)

    halt_new = None       # a write whose readback failed: its state is UNKNOWN, so no new start this tick

    def offer(n: int) -> st.Step:
        nonlocal halt_new
        before = len(wrote)
        try:
            res = st.run_starter(read_snapshot=lambda: snapshot(n), add_comment=add_comment,
                                 add_label=add_label, campaign=campaign, controller=controller)
        except TransientRead as exc:
            if len(wrote) > before:
                halt_new = f"issue #{n}: a write was attempted and the readback failed ({exc})"
                return st.Step(st.DEFER, halt_new, n, code="WRITE_READBACK_UNKNOWN")
            return st.Step(st.DEFER, f"issue #{n}: GitHub read failed ({exc}); the next wake re-reads", n,
                           code="READ_UNKNOWN")
        last = res.steps[-1]
        if res.stopped == "PREPARED" and last.action == st.WRITE_LABEL:
            refused = ((getattr(port, "prepared", None) or [{}])[-1].get("refused") or [])
            if any(str(r).startswith("budget EXHAUSTED") for r in refused):
                # the durable budget is spent: a human decision, visible every wake, never a silent retry loop
                return st.Step(st.ISOLATE, "; ".join(map(str, refused)), n, code="BUDGET_EXHAUSTED",
                               human_required=True)
        if any(s.action == st.WRITE_START_RECEIPT for s in res.steps) or last.code == "STARTED":
            result.started.append(n)
        return last

    hard_stop = None
    for k in sorted((k for k in known if k["state"] == planner.PREPARED), key=lambda k: k["issue"]):
        if halt_new is not None:
            result.defers.append({"task_id": k["task_id"], "issue": k["issue"], "code": "WRITE_READBACK_UNKNOWN",
                                  "reason": "not offered: " + halt_new, "dependency": [], "retry_after": None,
                                  "human_required": False})
            continue
        last = offer(k["issue"])
        if k["issue"] in result.started:
            k["state"] = planner.RUNNING
            continue
        if last.action == st.HARD_STOP:
            hard_stop = last
            break
        if last.action == st.ISOLATE:
            k["state"] = planner.ISOLATED
            result.isolated.append({"task_id": k["task_id"], "issue": k["issue"], "code": last.code,
                                    "reason": last.reason, "human_required": last.human_required})
        elif last.action in {st.DEFER, st.NO_OP} and last.code != "STARTED":
            result.defers.append({"task_id": k["task_id"], "issue": k["issue"], "code": last.code or last.action,
                                  "reason": last.reason, "dependency": list(last.dependency),
                                  "retry_after": last.retry_after, "human_required": last.human_required})
    running = [k for k in known if k["state"] == planner.RUNNING]
    for k in running:                     # in-flight work is tracked too, so a stalled task never waits silently
        if k["issue"] in result.started:
            continue
        try:
            head = port.pr_head(k["issue"])
            issue = by_number.get(k["issue"]) or port.read_issue(k["issue"])
        except TransientRead as exc:
            result.defers.append({"task_id": k["task_id"], "issue": k["issue"], "code": "READ_UNKNOWN",
                                  "reason": f"in-flight task could not be read ({exc})", "dependency": [],
                                  "retry_after": None, "human_required": False, "in_flight": True})
            continue
        mine = [r for r in _receipts(issue, trusted) if r.get("_unreadable") or
                r.get("correlation_id") == k["correlation_id"]]
        ignored = None
        if head is not None and hasattr(port, "api_message") and not any(r.get("_unreadable") for r in mine):
            try:
                ignored = ignored_corrective(mine, head=head, head_tree=lambda: port.commit_tree(head), now=now(),
                                             ack_minutes=policy["jules_ack_timeout_minutes"])
            except TransientRead:
                ignored = None        # unknown tree: the normal path below reports it; the next wake re-checks
        if any(r.get("_unreadable") for r in mine):
            code, reason, human = "RECORD_UNREADABLE", "a receipt on the task issue is unreadable; the reviewer " \
                                                       "will not write over it", True
        elif ignored is not None:
            code, reason, human = _resend_corrective(port, k, ignored, head=head, now=now(),
                                                     ack_minutes=policy["jules_ack_timeout_minutes"])
        elif head is None:
            code, reason, human = "JULES_PENDING", "started; Jules has not opened a PR yet", False
        elif any(r.get("pr_head_sha") == head for r in mine):
            code, reason, human = "JULES_PENDING", "corrective requested; waiting for Jules' next commit", False
        else:
            code, reason, human = "REVIEW_PENDING", f"PR head {head[:7]} has no review receipt yet", False
        result.defers.append({"task_id": k["task_id"], "issue": k["issue"], "code": code, "reason": reason,
                              "dependency": [], "retry_after": None, "human_required": human, "in_flight": True})
    if hard_stop is not None:
        result.outcome, result.reason = HARD_STOP_PROVIDER, hard_stop.reason
        result.human_actions.append({"action": "resolve provider / policy boundary", "reason": hard_stop.reason})
    elif halt_new is not None:
        result.outcome, result.reason = DEFER, "no new task this tick: " + halt_new
    elif len(running) < policy["max_concurrent_tasks"] and not result.started:
        try:
            signals = read_retry(port.signals, attempts)
        except TransientRead:
            signals = None
        decision = planner.plan_next(campaign=campaign, signals=signals, known=known, proposer=proposer)
        if decision.outcome == planner.PROPOSE:
            title, body, task = planner.build_task(decision.proposal, campaign=campaign, base_head=base, now=now())
            try:
                n = port.create_issue(title, body)
            except st.PreparedOnly:
                raise
            except st.WriteOutcomeUnknown:
                n = None      # never re-sent: the next tick finds the issue by its fingerprint, or plans it again
            if n is None:
                result.defers.append({"task_id": task["task_id"], "issue": None, "code": "WRITE_UNCONFIRMED",
                                      "reason": "issue creation outcome unknown", "dependency": [],
                                      "retry_after": None, "human_required": False})
            else:
                result.created.append(n)
                known.append({"issue": n, "task_id": task["task_id"], "correlation_id": task["correlation_id"],
                              "fingerprint": task["campaign"]["fingerprint"],
                              "signal_id": task["campaign"]["signal_id"], "state": planner.PREPARED,
                              "paths": [p["path"] for p in task["allowed_paths"]], "source": "planner"})
                last = offer(n)
                if n in result.started:
                    known[-1]["state"] = planner.RUNNING
            if n is not None and n not in result.started:
                result.defers.append({"task_id": task["task_id"], "issue": n, "code": last.code or last.action,
                                      "reason": last.reason, "dependency": list(last.dependency),
                                      "retry_after": last.retry_after, "human_required": last.human_required})
        entries = st.validate_campaign(campaign)
        done = {k["task_id"]: k["state"] for k in known}
        manifest_open = [e for e in entries.values() if done.get(e["task"]["task_id"]) not in
                         {planner.PASS_UNMERGED, planner.MERGED, planner.ISOLATED}]
        if decision.outcome == planner.GOAL_COMPLETE and manifest_open:
            # a prepared manifest task whose issue does not exist yet is not "done": its predecessor's PASS
            # (reviewer, next_task.body_ref) or the human's first step creates it
            decision = planner.PlanDecision(planner.WAIT_RUNNING if running else planner.SIGNALS_UNKNOWN,
                                            f"manifest task(s) {[e['task']['task_id'] for e in manifest_open]} "
                                            "not created or not finished yet")
        elif decision.outcome == planner.GOAL_COMPLETE and any(done.get(e["task"]["task_id"]) == planner.ISOLATED
                                                               for e in entries.values()):
            decision = planner.PlanDecision(planner.NO_SAFE_TASK, "a prepared manifest task is isolated; a human "
                                            "must look at it")
        elif decision.outcome == planner.GOAL_COMPLETE and any(done.get(e["task"]["task_id"]) == planner.PASS_UNMERGED
                                                               for e in entries.values()):
            decision = planner.PlanDecision(planner.MERGE_WAIT, "manifest tasks are PASS; they land when a human "
                                            "merges")
        result.outcome, result.reason = {
            planner.PROPOSE: (CONTINUE, decision.reason), planner.WAIT_RUNNING: (CONTINUE, decision.reason),
            planner.MERGE_WAIT: (MERGE_WAIT, decision.reason), planner.NO_SAFE_TASK: (NO_SAFE_TASK, decision.reason),
            planner.SIGNALS_UNKNOWN: (DEFER, decision.reason),
            planner.GOAL_COMPLETE: (GOAL_COMPLETE, decision.reason)}[decision.outcome]
        for w in decision.waiting:
            result.human_actions.append({"action": "merge", "prs_of_tasks": w.get("needs_merge"),
                                         "unblocks": w.get("signal")})
        if decision.outcome == planner.PROPOSE and not result.started and result.defers:
            result.outcome = DEFER if not running else CONTINUE
    else:
        result.reason = f"{len(running) + len(result.started)} task(s) running"
    if result.outcome == CONTINUE and not result.started and not running and not result.created:
        result.outcome = DEFER if result.defers else result.outcome
    if result.started or running:
        result.next_wake = "pull_request event of the running task"
    elif result.outcome == MERGE_WAIT:
        result.next_wake = "pull_request.closed (merged) event"
    elif result.defers:
        result.next_wake = RECOVERY.get(result.defers[0]["code"], "next wake")
    elif result.outcome == DEFER:
        result.next_wake = "the next pull_request event, the recovery schedule, or a human Run now"
    for i in result.isolated:              # every isolated task is reported; human_required says who must act
        result.human_actions.append({"action": "review isolated task", "task_id": i["task_id"], "code": i["code"],
                                     "human_required": i["human_required"]})
    if result.outcome == NO_SAFE_TASK:
        result.human_actions.append({"action": "review open signals that cannot be planned", "reason": result.reason})

    _checkpoint(port, result, campaign=campaign, controller=controller, now=now(), control=control, known=known)
    return result


def _checkpoint(port: Any, result: TickResult, *, campaign: dict[str, Any], controller: str, now: str,
                control: dict[str, Any] | None, known: list[dict[str, Any]]) -> None:
    policy = campaign["policy"]
    prev = _previous_checkpoint(control, set(policy["trusted_writers"]))
    prev_defers = {(d["task_id"], d["code"]): d for d in (prev or {}).get("defers") or []}
    independent = result.outcome == CONTINUE
    defers = []
    for d in result.defers:
        old = prev_defers.get((d["task_id"], d["code"]))
        first = old["first_seen_at"] if old else now
        age = st._ts(now) - st._ts(first)
        if d.get("in_flight"):            # a running task that does not move: escalate even while other work runs
            escalated = age >= timedelta(minutes=policy.get("stall_escalate_minutes", 720))
        else:
            escalated = age >= timedelta(minutes=policy["defer_escalate_minutes"]) and not independent
        defers.append({"task_id": d["task_id"], "issue": d["issue"], "code": d["code"], "reason": d["reason"],
                       "state": "DEFERRED", "first_seen_at": first, "last_checked_at": now,
                       "next_check": d.get("retry_after") or RECOVERY.get(d["code"], "next wake"),
                       "recovery_action": RECOVERY.get(d["code"], "re-check on the next wake"),
                       "dependency": d["dependency"], "independent_work_remaining": independent,
                       "human_required": bool(d["human_required"] or escalated), "escalated": escalated,
                       "in_flight": bool(d.get("in_flight"))})
        if escalated:
            result.human_actions.append({"action": "look at a long DEFER", "task_id": d["task_id"],
                                         "code": d["code"], "since": first})
    tasks = {k["task_id"]: k["state"] for k in known}
    core = {"outcome": result.outcome, "tasks": tasks,
            "defers": [(d["task_id"], d["code"], d["human_required"]) for d in defers],
            "human": sorted(json.dumps(h, sort_keys=True) for h in result.human_actions)}
    digest = hashlib.sha256(st.canonical(core).encode()).hexdigest()[:16]
    record = {"profile": CHECKPOINT_PROFILE, "campaign_id": campaign["campaign_id"], "controller": controller,
              "tick_at": now, "outcome": result.outcome, "reason": result.reason, "state_digest": digest,
              "tasks": tasks, "defers": defers, "isolated": result.isolated, "human_actions": result.human_actions,
              "next_wake": result.next_wake, "started": result.started, "created": result.created}
    result.defers = defers
    result.checkpoint = record
    heartbeat_due = prev is None or st._ts(now) - st._ts(prev["_at"]) >= timedelta(minutes=policy["heartbeat_minutes"])
    if control and (prev is None or prev.get("state_digest") != digest or heartbeat_due):
        try:
            port.add_comment(control["number"], render_checkpoint(record))
            result.checkpoint_written = True
        except st.WriteOutcomeUnknown:
            result.checkpoint_written = False      # the next tick writes a fresh one if the state still differs
        except st.PreparedOnly:
            result.checkpoint_written = False      # prepare-only port: the checkpoint is reported, not sent
