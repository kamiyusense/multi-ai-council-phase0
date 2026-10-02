"""Read-only Codex account/quota evidence interface (STATIC; nothing is queried here).

Shapes follow the codex-acp 2.1.x app-server types for ``account/read`` and
``account/rateLimits/read``. This module only (a) names the two read-only
requests and (b) turns already-received responses into a small evidence dict.
No login/logout/token refresh/billing call exists here. Any missing or
malformed field becomes UNKNOWN; nothing is inferred (a null value means
"unavailable", never "OK"). Private identifiers (email, accountId, balances)
are not copied into the evidence.
"""

from __future__ import annotations

from typing import Any

__all__ = ["READ_ONLY_METHODS", "read_only_requests", "assert_read_only", "summarize_account_evidence"]

READ_ONLY_METHODS = frozenset({"account/read", "account/rateLimits/read"})
UNKNOWN = "UNKNOWN"


def assert_read_only(method: str) -> None:
    if method not in READ_ONLY_METHODS:
        raise ValueError(f"method {method!r} is not an allowed read-only account request")


def read_only_requests(first_id: int = 1) -> list[dict[str, Any]]:
    """The only two requests this interface may ever send. refreshToken is always false."""
    return [
        {"jsonrpc": "2.0", "id": first_id, "method": "account/read", "params": {"refreshToken": False}},
        {"jsonrpc": "2.0", "id": first_id + 1, "method": "account/rateLimits/read"},
    ]


def _auth_state(account_read: Any) -> tuple[str, str]:
    if not isinstance(account_read, dict) or not isinstance(account_read.get("requiresOpenaiAuth"), bool):
        return UNKNOWN, UNKNOWN
    account = account_read.get("account")
    if account is None:
        return ("NOT_AUTHENTICATED" if account_read["requiresOpenaiAuth"] else UNKNOWN), UNKNOWN
    if not isinstance(account, dict):
        return UNKNOWN, UNKNOWN
    kind = account.get("type")
    if kind == "chatgpt":
        plan = account.get("planType")
        return "CHATGPT_ACCOUNT", plan if isinstance(plan, str) and plan else UNKNOWN
    if kind == "apiKey":
        return "API_KEY_ROUTE_VIOLATION", UNKNOWN  # Phase 0 forbids the API-key route
    return "OTHER_ROUTE_VIOLATION", UNKNOWN


def _window(w: Any) -> dict[str, Any] | str:
    if not isinstance(w, dict) or isinstance(w.get("usedPercent"), bool) or not isinstance(w.get("usedPercent"), (int, float)):
        return UNKNOWN
    return {
        "used_percent": w["usedPercent"],
        "window_minutes": w.get("windowDurationMins") if isinstance(w.get("windowDurationMins"), int) else UNKNOWN,
        "resets_at_epoch": w.get("resetsAt") if isinstance(w.get("resetsAt"), int) else UNKNOWN,
    }


def summarize_account_evidence(account_read: Any, rate_limits: Any) -> dict[str, Any]:
    auth_state, plan = _auth_state(account_read)
    evidence: dict[str, Any] = {
        "auth_state": auth_state,
        "plan_type": plan,
        "ordinary_usage_allowed": UNKNOWN,
        "primary_window": UNKNOWN,
        "secondary_window": UNKNOWN,
        "rate_limit_reached_type": UNKNOWN,
        "spend_control_reached": UNKNOWN,
        "credits_flag": UNKNOWN,
        "side_effects": 0,
    }
    if isinstance(rate_limits, dict):
        allowed = rate_limits.get("ordinaryUsageAllowed")
        evidence["ordinary_usage_allowed"] = allowed if isinstance(allowed, bool) else UNKNOWN
        snap = rate_limits.get("rateLimits")
        if isinstance(snap, dict):
            evidence["primary_window"] = _window(snap.get("primary"))
            evidence["secondary_window"] = _window(snap.get("secondary"))
            reached = snap.get("rateLimitReachedType")
            evidence["rate_limit_reached_type"] = reached if isinstance(reached, str) else (None if snap.get("rateLimitReachedType", UNKNOWN) is None else UNKNOWN)
            spend = snap.get("spendControlReached")
            evidence["spend_control_reached"] = spend if isinstance(spend, bool) else UNKNOWN
            credits = snap.get("credits")
            if isinstance(credits, dict) and isinstance(credits.get("hasCredits"), bool) and isinstance(credits.get("unlimited"), bool):
                evidence["credits_flag"] = {"has_credits": credits["hasCredits"], "unlimited": credits["unlimited"]}
    # A quota read is only trusted when the account itself was positively read.
    if auth_state != "CHATGPT_ACCOUNT":
        evidence["ordinary_usage_allowed"] = UNKNOWN
    return evidence
