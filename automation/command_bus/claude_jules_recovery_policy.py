"""Reasoned, bounded recovery policy for long Claude AUTO campaigns (explicit opt-in, v1).

The legacy engine reads ``max_transient_retries`` and retries a read boundary at
once.  That stays the default.  A campaign that passes an explicit recovery
policy to ``ClaudeJulesAutoLoop`` instead gets the decision table below: every
retry has a typed cause, a finite attempt cap, a backoff, a deadline, a named
condition that must have changed since the previous attempt, a provider-budget
effect and an exhaustion action.  Each decision is written as a create-only
``RECOVERY_DECISION`` campaign event *before* the retry happens, so a restart
counts the same attempts and backoff from GitHub, never from memory.

Nothing here grants authority.  A retry that would need a provider call still
goes through the dispatcher's authorization, owner fence and budget, and a cause
of AUTHORITY / BUDGET / INTEGRITY / AMBIGUOUS_WRITE is never retried blindly.

Why these numbers (all are caps, not targets):

* TRANSIENT_READ 3 attempts, backoff 0 s / 120 s / 600 s, deadline 1 h: GitHub
  API and log blobs usually recover within minutes; three spaced reads cover a
  short outage without turning a real outage into polling.  No provider cost.
* TEST_ENVIRONMENT 2 attempts: one re-run after a recorded environment change
  (interpreter, dependency) and one more if that change was itself wrong.  A
  re-run with an unchanged environment is refused as no progress.
* SEMANTIC_FAILURE uses the campaign's ``max_corrective_rounds_per_task``; a
  corrective that reproduces the same finding fingerprint first shrinks scope,
  then isolates the task.  Each corrective costs one provider dispatch.
* STALE_TARGET 3 replans per task: the canonical head moved under the task;
  each replan needs a different head.  A target that keeps moving more than
  three times is a coordination problem, so the task is isolated.
* PROVIDER_FAILURE 1 new distinct attempt, only for a verified SETTLED
  ``FAILED`` provider with a fixable cause; costs one dispatch.
* AMBIGUOUS_WRITE 1 new attempt, only after a readback proved the earlier write
  absent; otherwise the boundary stays and nothing is resent.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

RECOVERY_POLICY_PROFILE = "CLAUDE_AUTO_RECOVERY_POLICY_V1"

TRANSIENT_READ = "TRANSIENT_READ"
TEST_ENVIRONMENT = "TEST_ENVIRONMENT"
SEMANTIC_FAILURE = "SEMANTIC_FAILURE"
STALE_TARGET = "STALE_TARGET"
AMBIGUOUS_WRITE = "AMBIGUOUS_WRITE"
PROVIDER_FAILURE = "PROVIDER_FAILURE"
TASK_BLOCKER = "TASK_BLOCKER"
AUTHORITY = "AUTHORITY"
BUDGET = "BUDGET"
INTEGRITY = "INTEGRITY"
CAUSES = (TRANSIENT_READ, TEST_ENVIRONMENT, SEMANTIC_FAILURE, STALE_TARGET, AMBIGUOUS_WRITE,
          PROVIDER_FAILURE, TASK_BLOCKER, AUTHORITY, BUDGET, INTEGRITY)

# decisions
RETRY = "RETRY"                    # perform the bounded retry now (and record it first)
WAIT_UNTIL = "WAIT_UNTIL"          # retry allowed later; nothing to do before not_before
RECONCILE_FIRST = "RECONCILE_FIRST"  # read back the ambiguous write; never resend yet
REDUCE_SCOPE = "REDUCE_SCOPE"      # same failure again: retry only with a smaller task
ISOLATE_TASK = "ISOLATE_TASK"      # record TASK_BLOCKED, continue independent READY tasks
STOP_CAMPAIGN = "STOP_CAMPAIGN"    # authority/budget/integrity boundary: never retried


@dataclass(frozen=True)
class CauseRule:
    retryable: bool
    operations: tuple[str, ...]
    max_attempts: int
    backoff_seconds: tuple[int, ...]
    deadline_seconds: int
    must_change: str               # condition key that must differ between attempts ("" = time only)
    provider_budget_per_attempt: int
    on_exhaustion: str


DEFAULT_RULES: dict[str, CauseRule] = {
    TRANSIENT_READ: CauseRule(True, ("github-read", "actions-log-read", "status-readback", "evidence-read"),
                              3, (0, 120, 600), 3600, "", 0, ISOLATE_TASK),
    TEST_ENVIRONMENT: CauseRule(True, ("claude-test-run",), 2, (0, 0), 6 * 3600, "environment_digest", 0,
                                ISOLATE_TASK),
    SEMANTIC_FAILURE: CauseRule(True, ("jules-corrective",), 2, (0, 0), 24 * 3600, "findings_fingerprint", 1,
                                ISOLATE_TASK),
    STALE_TARGET: CauseRule(True, ("replan",), 3, (0, 0, 0), 24 * 3600, "canonical_head", 1, ISOLATE_TASK),
    PROVIDER_FAILURE: CauseRule(True, ("jules-new-attempt",), 1, (0,), 24 * 3600, "attempt_plan_digest", 1,
                                ISOLATE_TASK),
    AMBIGUOUS_WRITE: CauseRule(True, ("create-after-proven-absent",), 1, (0,), 3600, "absence_proof", 0,
                               STOP_CAMPAIGN),
    TASK_BLOCKER: CauseRule(False, (), 0, (), 0, "", 0, ISOLATE_TASK),
    AUTHORITY: CauseRule(False, (), 0, (), 0, "", 0, STOP_CAMPAIGN),
    BUDGET: CauseRule(False, (), 0, (), 0, "", 0, STOP_CAMPAIGN),
    INTEGRITY: CauseRule(False, (), 0, (), 0, "", 0, STOP_CAMPAIGN),
}


def recovery_policy(*, semantic_max_attempts: int = 2, rules: dict[str, CauseRule] | None = None) -> dict[str, Any]:
    """Explicit opt-in policy object.  Caps can be lowered, never raised past the hard limits."""
    table = dict(rules or DEFAULT_RULES)
    if type(semantic_max_attempts) is not int or not 1 <= semantic_max_attempts <= 10:
        raise ValueError("semantic_max_attempts must be 1..10")
    sem = table[SEMANTIC_FAILURE]
    table[SEMANTIC_FAILURE] = CauseRule(sem.retryable, sem.operations, semantic_max_attempts,
                                        tuple([0] * semantic_max_attempts), sem.deadline_seconds, sem.must_change,
                                        sem.provider_budget_per_attempt, sem.on_exhaustion)
    return validate_recovery_policy({"profile": RECOVERY_POLICY_PROFILE, "rules": table})


def validate_recovery_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict) or policy.get("profile") != RECOVERY_POLICY_PROFILE:
        raise ValueError("unsupported recovery policy")
    rules = policy.get("rules")
    if not isinstance(rules, dict) or set(rules) != set(CAUSES):
        raise ValueError("recovery policy must define every cause")
    for cause, rule in rules.items():
        if not isinstance(rule, CauseRule):
            raise ValueError(f"rule for {cause} malformed")
        if cause in {AUTHORITY, BUDGET, INTEGRITY, TASK_BLOCKER} and rule.retryable:
            raise ValueError(f"{cause} can never be retryable")
        if rule.retryable:
            if not 1 <= rule.max_attempts <= 10 or len(rule.backoff_seconds) != rule.max_attempts:
                raise ValueError(f"{cause} needs 1..10 attempts and one backoff per attempt")
            if any(type(b) is not int or not 0 <= b <= 86400 for b in rule.backoff_seconds):
                raise ValueError(f"{cause} backoff out of range")
            if not 1 <= rule.deadline_seconds <= 7 * 86400:
                raise ValueError(f"{cause} needs a finite deadline")
        if cause == AMBIGUOUS_WRITE and (rule.must_change != "absence_proof" or rule.max_attempts > 1):
            raise ValueError("ambiguous writes retry at most once and only after proven absence")
        if rule.on_exhaustion not in {ISOLATE_TASK, STOP_CAMPAIGN}:
            raise ValueError(f"{cause} exhaustion must isolate or stop")
    return policy


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed


_VOLATILE = re.compile(r"\b[0-9a-f]{7,64}\b|\b\d+\b")


def failure_fingerprint(cause: str, operation: str, reason: str) -> str:
    """Stable identity of *what* failed: volatile numbers/hashes are removed so a repeat is recognised."""
    normal = _VOLATILE.sub("#", (reason or "").lower()).strip()
    return hashlib.sha256(json.dumps([cause, operation, normal]).encode()).hexdigest()


def condition_digest(conditions: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(conditions, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class RecoveryDecision:
    decision: str
    cause: str
    attempt: int
    reason: str
    not_before: str | None = None
    deadline: str | None = None
    provider_budget_effect: int = 0
    details: dict[str, Any] = field(default_factory=dict)


def classify_cause(boundary_kind: str, reason: str) -> str:
    """Map the engine's typed boundary onto a recovery cause (conservative)."""
    text = (reason or "").lower()
    if boundary_kind == "TRANSIENT_UNKNOWN":
        return TRANSIENT_READ
    if boundary_kind == "RECOVERABLE_UNKNOWN":
        return STALE_TARGET
    if boundary_kind == "TASK_BLOCKED":
        return TASK_BLOCKER
    if any(m in text for m in ("not granted", "owned by", "not owned", "authorization", "owner chain")):
        return AUTHORITY
    if "budget" in text:
        return BUDGET
    if any(m in text for m in ("do not resend", "not proven", "collision")):
        return AMBIGUOUS_WRITE
    return INTEGRITY


def decide(policy: dict[str, Any], *, cause: str, operation: str, reason: str, conditions: dict[str, Any],
           history: Iterable[dict[str, Any]], now: str, first_failure_at: str | None = None) -> RecoveryDecision:
    """Pure decision for one failure scope.

    ``history`` holds the earlier ``RECOVERY_DECISION`` payloads of the same
    scope (restored from GitHub).  ``conditions`` names what is true now (for
    example the canonical head or an environment digest).  The returned
    decision is what the caller must persist before acting on it.
    """
    rule: CauseRule = validate_recovery_policy(policy)["rules"][cause]
    previous = sorted(history, key=lambda h: h["attempt"])
    if [h["attempt"] for h in previous] != list(range(1, len(previous) + 1)):
        return RecoveryDecision(STOP_CAMPAIGN, INTEGRITY, 0, "recovery history non-contiguous; do not resend")
    attempt = len(previous) + 1
    fingerprint = failure_fingerprint(cause, operation, reason)
    cond = condition_digest(conditions)
    if not rule.retryable:
        return RecoveryDecision(rule.on_exhaustion, cause, attempt, f"{cause} is never retried: {reason}")
    if operation not in rule.operations:
        return RecoveryDecision(STOP_CAMPAIGN, cause, attempt, f"operation {operation} is not retryable for {cause}")
    if cause == AMBIGUOUS_WRITE and conditions.get("absence_proof") is not True:
        return RecoveryDecision(RECONCILE_FIRST, cause, attempt,
                                "write outcome not proven either way; read back before any new attempt")
    origin = _time(first_failure_at or (previous[0]["recorded_at"] if previous else now))
    deadline = origin + timedelta(seconds=rule.deadline_seconds)
    common = {"failure_fingerprint": fingerprint, "condition_digest": cond}
    if _time(now) > deadline:
        return RecoveryDecision(rule.on_exhaustion, cause, attempt, f"{cause} recovery deadline passed",
                                deadline=deadline.isoformat(), details=common)
    if attempt > rule.max_attempts:
        return RecoveryDecision(rule.on_exhaustion, cause, attempt,
                                f"{cause} retry budget exhausted after {rule.max_attempts} attempt(s)",
                                deadline=deadline.isoformat(), details=common)
    if previous and rule.must_change:
        last = previous[-1]
        if last["failure_fingerprint"] == fingerprint and last["condition_digest"] == cond:
            if cause == SEMANTIC_FAILURE and not last.get("reduced_scope"):
                return RecoveryDecision(REDUCE_SCOPE, cause, attempt,
                                        "same finding after a corrective: retry only with reduced scope",
                                        deadline=deadline.isoformat(),
                                        provider_budget_effect=rule.provider_budget_per_attempt,
                                        details=dict(common, reduced_scope=True))
            return RecoveryDecision(rule.on_exhaustion, cause, attempt,
                                    f"no progress: {cause} repeated with unchanged {rule.must_change}",
                                    deadline=deadline.isoformat(), details=common)
        if rule.must_change in conditions and last.get("conditions", {}).get(rule.must_change) == conditions[rule.must_change] \
                and cause != SEMANTIC_FAILURE:
            return RecoveryDecision(rule.on_exhaustion, cause, attempt,
                                    f"no progress: {rule.must_change} unchanged since attempt {last['attempt']}",
                                    deadline=deadline.isoformat(), details=common)
    if previous:
        not_before = _time(previous[-1]["recorded_at"]) + timedelta(seconds=rule.backoff_seconds[attempt - 1])
        if _time(now) < not_before:
            return RecoveryDecision(WAIT_UNTIL, cause, attempt, f"{cause} backoff until {not_before.isoformat()}",
                                    not_before=not_before.isoformat(), deadline=deadline.isoformat(), details=common)
    return RecoveryDecision(RETRY, cause, attempt, f"{cause} attempt {attempt}/{rule.max_attempts}: {reason}",
                            deadline=deadline.isoformat(), provider_budget_effect=rule.provider_budget_per_attempt,
                            details=common)


def decision_payload(decision: RecoveryDecision, *, scope: str, operation: str, reason: str, evidence_ref: str,
                     why_meaningful: str, conditions: dict[str, Any], recorded_at: str) -> dict[str, Any]:
    """The durable RECOVERY_DECISION payload (see ``claude_jules_campaign_state``)."""
    return {
        "scope": scope, "attempt": decision.attempt, "cause": decision.cause, "operation": operation,
        "reason": reason, "evidence_ref": evidence_ref, "why_meaningful": why_meaningful,
        "conditions": conditions, "condition_digest": condition_digest(conditions),
        "failure_fingerprint": failure_fingerprint(decision.cause, operation, reason),
        "decision": decision.decision, "not_before": decision.not_before, "deadline": decision.deadline,
        "provider_budget_effect": decision.provider_budget_effect,
        "reduced_scope": bool(decision.details.get("reduced_scope")), "recorded_at": recorded_at,
        "policy_profile": RECOVERY_POLICY_PROFILE,
    }
