"""Campaign-scoped autonomy policy for the Claude x Jules development loop.

This layer is intentionally separate from the transport/dispatch policy.  The
transport policy remains the hard authorization envelope for repositories,
branches, lanes, and live-dispatch budget.  A campaign policy may only narrow
that envelope; it never grants transport authority by itself.

V1 keeps concurrency at one.  The schema nevertheless makes round, corrective,
retry, failure, idle and timeout limits explicit so the controller is not
architecturally tied to the historical six-round proof.
"""
from __future__ import annotations

import re
from typing import Any

CAMPAIGN_PROFILE = "CLAUDE_AUTO_CAMPAIGN_POLICY_V1"
MAX_CONFIGURED_ROUNDS = 1000
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CAMPAIGN_KEYS = {
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
    "dispatch_budget",
    "subscription_only",
}


def _bounded_int(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"campaign {name} must be {minimum}..{maximum}")
    return value


def validate_campaign_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate one finite V1 campaign policy without granting live authority."""
    if not isinstance(policy, dict) or set(policy) != _CAMPAIGN_KEYS:
        raise ValueError("campaign policy keys mismatch")
    if policy["schema_version"] != 1 or policy["profile"] != CAMPAIGN_PROFILE:
        raise ValueError("unsupported campaign policy profile")
    campaign_id = policy["campaign_id"]
    if not isinstance(campaign_id, str) or not _SAFE_ID.fullmatch(campaign_id):
        raise ValueError("campaign campaign_id is unsafe")

    _bounded_int(policy["max_rounds"], "max_rounds", minimum=1, maximum=MAX_CONFIGURED_ROUNDS)
    _bounded_int(policy["max_corrective_rounds_per_task"], "max_corrective_rounds_per_task", minimum=0, maximum=20)
    _bounded_int(policy["max_transient_retries"], "max_transient_retries", minimum=0, maximum=20)
    _bounded_int(policy["max_consecutive_failures"], "max_consecutive_failures", minimum=1, maximum=100)
    concurrency = _bounded_int(policy["max_concurrent_agents"], "max_concurrent_agents", minimum=1, maximum=32)
    if concurrency != 1:
        raise ValueError("campaign V1 supports max_concurrent_agents=1 only")

    idle = _bounded_int(policy["idle_check_interval_seconds"], "idle_check_interval_seconds", minimum=30, maximum=86400)
    task_timeout = _bounded_int(policy["task_timeout_seconds"], "task_timeout_seconds", minimum=60, maximum=604800)
    campaign_timeout = _bounded_int(policy["campaign_timeout_seconds"], "campaign_timeout_seconds", minimum=300, maximum=2592000)
    if idle >= task_timeout:
        raise ValueError("campaign idle_check_interval_seconds must be shorter than task_timeout_seconds")
    if campaign_timeout < task_timeout:
        raise ValueError("campaign campaign_timeout_seconds must be >= task_timeout_seconds")

    budget = policy["dispatch_budget"]
    if budget is not None:
        _bounded_int(budget, "dispatch_budget", minimum=1, maximum=MAX_CONFIGURED_ROUNDS)
    if policy["subscription_only"] is not True:
        raise ValueError("campaign V1 requires subscription_only=true")
    return policy


def legacy_campaign_policy(dispatch_policy: dict[str, Any], *, campaign_id: str) -> dict[str, Any]:
    """Project the historical controller policy into the new campaign schema.

    This preserves current behaviour by default: the existing max_rounds is
    retained and transient retry remains zero until the recovery layer is
    introduced in a later, separately testable change.
    """
    auth = dispatch_policy.get("live_dispatch_authorization") if isinstance(dispatch_policy, dict) else None
    budget = auth.get("max_dispatches") if isinstance(auth, dict) else None
    value = {
        "schema_version": 1,
        "profile": CAMPAIGN_PROFILE,
        "campaign_id": campaign_id,
        "max_rounds": dispatch_policy.get("max_rounds"),
        "max_corrective_rounds_per_task": 2,
        "max_transient_retries": 0,
        "max_consecutive_failures": 1,
        "max_concurrent_agents": 1,
        "idle_check_interval_seconds": 300,
        "task_timeout_seconds": 21600,
        "campaign_timeout_seconds": 86400,
        "dispatch_budget": budget,
        "subscription_only": True,
    }
    return validate_campaign_policy(value)


def validate_campaign_envelope(campaign: dict[str, Any], dispatch_policy: dict[str, Any]) -> dict[str, Any]:
    """Require campaign limits to stay inside the transport authorization envelope."""
    campaign = validate_campaign_policy(campaign)
    dispatch_max = dispatch_policy.get("max_rounds") if isinstance(dispatch_policy, dict) else None
    if isinstance(dispatch_max, bool) or not isinstance(dispatch_max, int):
        raise ValueError("dispatch policy max_rounds unavailable")
    if campaign["max_rounds"] > dispatch_max:
        raise ValueError("campaign max_rounds exceeds dispatch policy envelope")

    auth = dispatch_policy.get("live_dispatch_authorization")
    if isinstance(auth, dict) and campaign["dispatch_budget"] is not None:
        live_budget = auth.get("max_dispatches")
        if isinstance(live_budget, bool) or not isinstance(live_budget, int):
            raise ValueError("dispatch authorization max_dispatches unavailable")
        if campaign["dispatch_budget"] > live_budget:
            raise ValueError("campaign dispatch_budget exceeds live authorization envelope")
    return campaign


def narrow_dispatch_policy(campaign: dict[str, Any], dispatch_policy: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the dispatch policy narrowed to one campaign.

    This never grants a branch, lane, round, or dispatch that the transport
    policy did not already allow.  It also protects resumed half-written
    intents, which otherwise could outlive a later controller-side limit.
    """
    campaign = validate_campaign_envelope(campaign, dispatch_policy)
    narrowed = dict(dispatch_policy)
    narrowed["max_rounds"] = min(dispatch_policy["max_rounds"], campaign["max_rounds"])
    auth = dispatch_policy.get("live_dispatch_authorization")
    budget = campaign["dispatch_budget"]
    if isinstance(auth, dict) and budget is not None:
        narrowed["live_dispatch_authorization"] = dict(
            auth, max_dispatches=min(auth["max_dispatches"], budget)
        )
    return narrowed
