"""Stop-resistant campaign policy and boundary classification.

This module deliberately does not authorize provider execution.  It controls
campaign continuation only; live dispatch authorization, owner fencing,
budgeting and immutable-write rules remain in the existing dispatcher.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CAMPAIGN_POLICY_PROFILE = "CLAUDE_AUTO_CAMPAIGN_POLICY_V1"

TRANSIENT_UNKNOWN = "TRANSIENT_UNKNOWN"
RECOVERABLE_UNKNOWN = "RECOVERABLE_UNKNOWN"
TASK_BLOCKED = "TASK_BLOCKED"
HARD_UNKNOWN = "HARD_UNKNOWN"

_POLICY_KEYS = {
    "schema_version",
    "profile",
    "campaign_id",
    "max_rounds",
    "max_corrective_rounds_per_task",
    "max_transient_retries",
    "max_consecutive_failures",
    "max_concurrent_agents",
    "idle_check_interval_seconds",
    "task_timeout_seconds",
    "campaign_timeout_seconds",
    "dispatch_provider_budget",
}


@dataclass(frozen=True)
class BoundaryClassification:
    kind: str
    reason: str
    retry_safe: bool
    campaign_terminal: bool = False


def _positive_int(value: Any, name: str, *, minimum: int = 1, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def validate_campaign_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate campaign continuation limits without granting any live authority."""
    if not isinstance(policy, dict) or set(policy) != _POLICY_KEYS:
        raise ValueError("campaign policy keys mismatch")
    if policy["schema_version"] != 1 or policy["profile"] != CAMPAIGN_POLICY_PROFILE:
        raise ValueError("unsupported campaign policy")
    campaign_id = policy["campaign_id"]
    if not isinstance(campaign_id, str) or not campaign_id or len(campaign_id) > 128:
        raise ValueError("campaign_id required")
    _positive_int(policy["max_rounds"], "max_rounds", maximum=1000)
    _positive_int(policy["max_corrective_rounds_per_task"], "max_corrective_rounds_per_task", maximum=50)
    _positive_int(policy["max_transient_retries"], "max_transient_retries", minimum=0, maximum=20)
    _positive_int(policy["max_consecutive_failures"], "max_consecutive_failures", maximum=100)
    if policy["max_concurrent_agents"] != 1:
        raise ValueError("max_concurrent_agents must remain 1 in campaign policy v1")
    _positive_int(policy["idle_check_interval_seconds"], "idle_check_interval_seconds", maximum=86400)
    _positive_int(policy["task_timeout_seconds"], "task_timeout_seconds", maximum=7 * 86400)
    _positive_int(policy["campaign_timeout_seconds"], "campaign_timeout_seconds", maximum=30 * 86400)
    if policy["campaign_timeout_seconds"] < policy["task_timeout_seconds"]:
        raise ValueError("campaign_timeout_seconds must be >= task_timeout_seconds")
    budget = policy["dispatch_provider_budget"]
    if budget is not None:
        _positive_int(budget, "dispatch_provider_budget", maximum=1000)
    return policy


def campaign_policy_from_legacy(policy: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    """Build the v1 campaign policy from the existing controller policy.

    This keeps old callers byte-for-byte compatible while moving continuation
    semantics behind an explicit campaign layer.
    """
    return validate_campaign_policy({
        "schema_version": 1,
        "profile": CAMPAIGN_POLICY_PROFILE,
        "campaign_id": campaign_id,
        "max_rounds": policy["max_rounds"],
        "max_corrective_rounds_per_task": 2,
        "max_transient_retries": 2,
        "max_consecutive_failures": 3,
        "max_concurrent_agents": 1,
        "idle_check_interval_seconds": 300,
        "task_timeout_seconds": 6 * 3600,
        "campaign_timeout_seconds": 12 * 3600,
        "dispatch_provider_budget": None,
    })


_AMBIGUOUS_WRITE_MARKERS = (
    "do not resend",
    "create not proven",
    "write not proven",
    "fast-forward",
    "adoption record",
    "terminal dispatch receipt",
    "collision",
)
_TRANSIENT_MARKERS = (
    "read failed",
    "readback failed",
    "transport",
    "network",
    "evidence unverifiable",
    "evidence unavailable",
    "temporar",
    "status unavailable",
    "owner chain unavailable",
)
_RECOVERABLE_MARKERS = (
    "stale_target",
    "target head changed",
    "target tree changed",
    "stale head",
    "cached evidence",
)


def classify_boundary(status: str, reason: str) -> BoundaryClassification | None:
    """Classify a non-success boundary without converting ambiguity into success.

    The classifier is conservative.  Ambiguous side-effecting writes are HARD
    and never auto-retried.  Read/evidence failures may be retried by a caller
    within an explicit bounded retry budget.  Stale snapshots are replannable.
    """
    text = (reason or "").lower()
    if any(marker in text for marker in _AMBIGUOUS_WRITE_MARKERS):
        return BoundaryClassification(HARD_UNKNOWN, reason, retry_safe=False)
    if status == "NO_RESULT_TIMEOUT":
        return BoundaryClassification(TASK_BLOCKED, reason, retry_safe=False)
    if any(marker in text for marker in _RECOVERABLE_MARKERS):
        return BoundaryClassification(RECOVERABLE_UNKNOWN, reason, retry_safe=True)
    if status == "BLOCKED":
        return BoundaryClassification(TASK_BLOCKED, reason, retry_safe=False)
    if status == "UNKNOWN":
        if any(marker in text for marker in _TRANSIENT_MARKERS):
            return BoundaryClassification(TRANSIENT_UNKNOWN, reason, retry_safe=True)
        return BoundaryClassification(HARD_UNKNOWN, reason, retry_safe=False)
    return None
