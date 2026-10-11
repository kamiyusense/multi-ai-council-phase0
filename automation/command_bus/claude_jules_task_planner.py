"""Autonomous task planner: choose the next safe development task inside the human-approved objectives.

The human approves *objectives* (what to improve, where, with which operations), not every task.  The planner
turns real evidence into the next task so the loop does not stop just because a prepared list ran out:

* **signals** are evidence of work: a failing test, a CI failure, an open issue, a TODO, a known limitation, a
  missing test.  Each has an id, an objective, the paths involved and the evidence itself;
* a **proposal** is one task for one signal.  In production Claude writes it (semantic work: what exactly to
  change, acceptance criteria, tests).  ``propose_from_signal`` is the deterministic stand-in used by tests and
  as a fallback skeleton;
* ``validate_proposal`` gates every proposal mechanically: approved objective, scope, safe operations, evidence,
  acceptance criteria and tests, no duplicate of a known task;
* ``plan_next`` picks what to do: the highest-priority open signal that is not already covered and not blocked by
  a pending Merge, or says why there is nothing.

Outcomes:

* ``PROPOSE``: a task to create;
* ``WAIT_RUNNING``: work is in flight; its PR event wakes the loop;
* ``MERGE_WAIT``: only merge-dependent work is left; the list of PRs a human could merge;
* ``NO_SAFE_TASK``: open signals exist but none is safe or valid (isolated); a human should look;
* ``SIGNALS_UNKNOWN``: the evidence could not be read; never treated as "done";
* ``GOAL_COMPLETE``: every signal of every objective is resolved (fixed on the base branch) and nothing is in
  flight.

Using up a prepared list is not completion.  Only evidence decides that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import claude_jules_production_starter as st

SIGNAL_KINDS = ("broken", "blocker", "known_bug", "failing_test", "ci_failure", "missing_test", "feature",
                "recovery", "todo", "docs")
_PRIORITY = {k: i for i, k in enumerate(SIGNAL_KINDS)}
PROPOSAL_PROFILE = "CLAUDE_TASK_PROPOSAL_V1"
PROPOSE, WAIT_RUNNING, MERGE_WAIT, NO_SAFE_TASK, SIGNALS_UNKNOWN, GOAL_COMPLETE = (
    "PROPOSE", "WAIT_RUNNING", "MERGE_WAIT", "NO_SAFE_TASK", "SIGNALS_UNKNOWN", "GOAL_COMPLETE")
# task states (derived from GitHub by the loop)
PREPARED, RUNNING, PASS_UNMERGED, MERGED, ISOLATED, CLOSED = (
    "PREPARED", "RUNNING", "PASS_UNMERGED", "MERGED", "ISOLATED", "CLOSED")
IN_FLIGHT = {PREPARED, RUNNING}


@dataclass(frozen=True)
class PlanDecision:
    outcome: str
    reason: str
    proposal: dict[str, Any] | None = None
    waiting: tuple[dict[str, Any], ...] = ()      # merge-wait / skipped candidates with their reasons
    skipped: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def validate_signal(sig: Any) -> str | None:
    if not isinstance(sig, dict):
        return "signal is not an object"
    for key in ("signal_id", "objective_id", "summary"):
        if not isinstance(sig.get(key), str) or not sig[key]:
            return f"signal {key} missing"
    if sig.get("kind") not in _PRIORITY:
        return f"signal kind {sig.get('kind')!r} unknown"
    if not isinstance(sig.get("paths"), list) or not sig["paths"]:
        return "signal needs paths"
    if not isinstance(sig.get("evidence"), list) or not sig["evidence"]:
        return "signal needs evidence"
    return None


def propose_from_signal(sig: dict[str, Any], *, objective: dict[str, Any]) -> dict[str, Any]:
    """Deterministic proposal skeleton for one signal (Claude refines it in production)."""
    ops = ["bug_fix", "test_add"] if sig["kind"] in {"broken", "blocker", "known_bug", "failing_test",
                                                     "ci_failure"} else \
        ["test_add"] if sig["kind"] == "missing_test" else ["docs_update"] if sig["kind"] == "docs" else ["code_edit"]
    ops = [o for o in ops if o in objective["allowed_operations"]] or [objective["allowed_operations"][0]]
    return {"profile": PROPOSAL_PROFILE, "objective_id": sig["objective_id"], "signal_id": sig["signal_id"],
            "title": f"[{objective['objective_id']}] {sig['summary']}", "intro": sig.get("detail") or sig["summary"],
            "allowed_paths": [{"path": p, "op": "MODIFY"} for p in sig["paths"]], "operations": ops,
            "acceptance_criteria": sig.get("acceptance_criteria") or [
                f"{sig['summary']}: fixed at the root cause", "a regression test covers it",
                "no existing test is removed, skipped or weakened"],
            "test_commands": sig.get("test_commands") or [
                "python3 -m unittest discover -s automation/command_bus/tests -t ."],
            "evidence_refs": list(sig["evidence"]), "depends_on": [],
            "safety_intent": sig.get("safety_intent"), "priority": _PRIORITY[sig["kind"]]}


def validate_proposal(proposal: Any, *, campaign: dict[str, Any], known: list[dict[str, Any]]) -> str | None:
    if not isinstance(proposal, dict) or proposal.get("profile") != PROPOSAL_PROFILE:
        return "proposal profile missing"
    objective = {o["objective_id"]: o for o in campaign.get("objectives") or []}.get(proposal.get("objective_id"))
    if objective is None:
        return "proposal is not under an approved objective"
    paths = [p.get("path") for p in proposal.get("allowed_paths") or [] if isinstance(p, dict)]
    if not paths or any(not isinstance(x, str) or not any(x.startswith(pre) for pre in objective["scope_prefixes"])
                        for x in paths):
        return "proposal paths are outside the objective scope"
    if any(p.get("op") not in {"ADD", "MODIFY"} for p in proposal["allowed_paths"]):
        return "proposal paths must be ADD or MODIFY"
    ops = proposal.get("operations")
    if not isinstance(ops, list) or not ops or not set(ops) <= set(objective["allowed_operations"]):
        return "proposal operations are not approved for the objective"
    for key in ("acceptance_criteria", "test_commands", "evidence_refs"):
        if not isinstance(proposal.get(key), list) or not proposal[key] or not all(
                isinstance(x, str) and x for x in proposal[key]):
            return f"proposal needs {key}"
    for key in ("title", "intro", "signal_id"):
        if not isinstance(proposal.get(key), str) or not proposal[key]:
            return f"proposal needs {key}"
    fp = st.task_fingerprint(proposal["objective_id"], proposal["signal_id"], paths)
    for k in known:
        if k.get("fingerprint") == fp and k.get("state") != CLOSED:
            return f"duplicate of known task {k.get('task_id')} ({k.get('state')})"
    return None


def build_task(proposal: dict[str, Any], *, campaign: dict[str, Any], base_head: str,
               now: str) -> tuple[str, str, dict[str, Any]]:
    """(title, issue body, task) for a validated proposal: one issue body with the task block and plan record."""
    paths = [p["path"] for p in proposal["allowed_paths"]]
    fp = st.task_fingerprint(proposal["objective_id"], proposal["signal_id"], paths)
    task_id = f"{campaign['campaign_id']}-{fp[:10]}"
    policy = campaign["policy"]
    task = {"profile": "CLAUDE_CLOSED_LOOP_TASK_V1", "kind": "code_change", "task_id": task_id,
            "correlation_id": f"{task_id}-{base_head[:7]}", "loop_id": campaign["loop_id"],
            "expected_target_branch": policy["base_branch"], "expected_target_head": base_head, "generation": 1,
            "max_corrective_rounds": policy["max_corrective_rounds"], "live_slot": 0, "round": 1,
            "route": campaign["policy"]["route"], "allowed_paths": proposal["allowed_paths"],
            "operations": proposal["operations"],
            "acceptance_criteria": proposal["acceptance_criteria"], "test_commands": proposal["test_commands"],
            "depends_on": proposal.get("depends_on") or [],
            "campaign": {"profile": st.STARTER_META_PROFILE, "campaign_id": campaign["campaign_id"],
                         "source": "planner", "objective_id": proposal["objective_id"],
                         "signal_id": proposal["signal_id"], "fingerprint": fp}}
    if proposal.get("safety_intent"):
        task["safety_intent"] = proposal["safety_intent"]
    plan = {"profile": st.PLAN_PROFILE, "campaign_id": campaign["campaign_id"],
            "objective_id": proposal["objective_id"], "signal_id": proposal["signal_id"], "task_id": task_id,
            "task_sha256": st.task_sha256(task), "fingerprint": fp, "evidence_refs": proposal["evidence_refs"],
            "depends_on": task["depends_on"], "created_at": now}
    intro = (f"{proposal['intro'].strip()}\n\nChange only: {', '.join(paths)}. Do not weaken, skip or delete any "
             "existing test. Run the test commands before opening the pull request, and put `Fixes #<this issue>` "
             "in the pull request body.")
    return proposal["title"], st.render_planned_issue(task, intro, plan), task


def plan_next(*, campaign: dict[str, Any], signals: list[dict[str, Any]] | None, known: list[dict[str, Any]],
              proposer=None) -> PlanDecision:
    """The next thing to do.  ``known``: every campaign task with fingerprint, signal_id, state, paths, task_id."""
    if signals is None:
        return PlanDecision(SIGNALS_UNKNOWN, "evidence of open work could not be read; nothing is declared done")
    objectives = {o["objective_id"]: o for o in campaign.get("objectives") or []}
    by_signal: dict[str, list[dict[str, Any]]] = {}
    for k in known:
        by_signal.setdefault(k.get("signal_id") or "", []).append(k)
    pending = [k for k in known if k.get("state") == PASS_UNMERGED]
    in_flight = [k for k in known if k.get("state") in IN_FLIGHT]
    skipped, waiting, candidates = [], [], []
    open_signals = 0
    for sig in signals:
        if (problem := validate_signal(sig)) is not None or sig["objective_id"] not in objectives:
            skipped.append({"signal": sig.get("signal_id") if isinstance(sig, dict) else None,
                            "reason": problem or "signal is outside the approved objectives"})
            continue
        if sig.get("resolved"):
            continue
        tasks = by_signal.get(sig["signal_id"], [])
        if any(t["state"] == MERGED for t in tasks):
            continue                                        # fixed on the base branch
        if any(t["state"] in IN_FLIGHT | {PASS_UNMERGED} for t in tasks):
            continue                                        # already covered; never planned twice
        open_signals += 1
        if any(t["state"] == ISOLATED for t in tasks):
            skipped.append({"signal": sig["signal_id"], "reason": "its task is isolated"})
            continue
        dep_tasks, dep_open = [], []
        for dep_signal in sig.get("depends_on_signals") or []:
            live = [t for t in by_signal.get(dep_signal, []) if t["state"] != CLOSED]
            if any(t["state"] == MERGED for t in live):
                continue
            if any(t["state"] == PASS_UNMERGED for t in live):
                dep_tasks += [t["task_id"] for t in live if t["state"] == PASS_UNMERGED]
            else:
                dep_open.append(dep_signal)
        if dep_tasks:
            waiting.append({"signal": sig["signal_id"], "needs_merge": dep_tasks, "reason": "depends on unmerged work"})
            continue
        if dep_open:
            skipped.append({"signal": sig["signal_id"], "reason": f"depends on unfinished {dep_open}"})
            continue
        overlap = [k["task_id"] for k in pending if set(k.get("paths") or []) & set(sig["paths"])]
        if overlap:
            waiting.append({"signal": sig["signal_id"], "needs_merge": overlap, "reason": "same files"})
            continue
        candidates.append(sig)
    candidates.sort(key=lambda s: (objectives[s["objective_id"]].get("priority", 100), _PRIORITY[s["kind"]],
                                   s["signal_id"]))
    for sig in candidates:
        objective = objectives[sig["objective_id"]]
        proposal = proposer(sig, objective) if proposer else propose_from_signal(sig, objective=objective)
        if proposal is None:
            skipped.append({"signal": sig["signal_id"], "reason": "no proposal (insufficient evidence)"})
            continue
        if (problem := validate_proposal(proposal, campaign=campaign, known=known)) is not None:
            skipped.append({"signal": sig["signal_id"], "reason": problem})
            continue
        return PlanDecision(PROPOSE, f"signal {sig['signal_id']} ({sig['kind']})", proposal, tuple(waiting),
                            tuple(skipped))
    if in_flight:
        return PlanDecision(WAIT_RUNNING, f"{len(in_flight)} task(s) in flight", None, tuple(waiting), tuple(skipped))
    if waiting:
        return PlanDecision(MERGE_WAIT, "only work that depends on unmerged PASS PRs is left", None, tuple(waiting),
                            tuple(skipped))
    if open_signals:
        return PlanDecision(NO_SAFE_TASK, f"{open_signals} open signal(s), none can be planned safely", None,
                            tuple(waiting), tuple(skipped))
    if pending:
        return PlanDecision(MERGE_WAIT, "all work is PASS; it lands when a human merges", None,
                            tuple({"needs_merge": [k["task_id"]]} for k in pending), tuple(skipped))
    return PlanDecision(GOAL_COMPLETE, "every signal of every objective is resolved on the base branch", None, (),
                        tuple(skipped))
