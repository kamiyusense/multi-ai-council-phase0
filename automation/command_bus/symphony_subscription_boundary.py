"""STATIC new-worker route decision for subscription-only Symphony campaigns.

The caller supplies the sanitized result of the existing read-only Codex
account parser. This is checked only when admitting a *new* upstream worker;
Symphony keeps ownership of same-session turns, retry, and stall recovery.
No account request or model dispatch occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Mapping


_METERED_ENV_KEYS = frozenset({
    "OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY",
    "OPENAI_BASE_URL", "OPENAI_API_BASE",
})

# OS/locale/config-directory selectors only. Unknown authority aliases, signing
# keys, proxies, token variables and observer paths never enter model workers.
_WORKER_ENV_KEYS = frozenset({
    "PATH", "HOME", "CODEX_HOME", "USER", "LOGNAME", "USERNAME", "USERPROFILE",
    "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "WINDIR",
    "COMSPEC", "PATHEXT", "TMP", "TEMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
    "TZ", "TERM", "COLORTERM", "NO_COLOR",
})


def subscription_worker_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Make a worker environment without ambient metered API selectors.

    This is a process-launch boundary, not an account or quota probe. The
    original mapping is never changed, and no credential values are inspected.
    """
    return {key: value for key, value in source.items()
            if type(key) is str and key.upper() in _WORKER_ENV_KEYS and type(value) is str}


def metered_worker_environment_present(keys: Collection[str]) -> bool:
    """Selector names only; no authentication assumption or credential values."""
    if not isinstance(keys, (set, frozenset, tuple, list)) or any(type(k) is not str for k in keys):
        return True
    return bool(_METERED_ENV_KEYS.intersection(k.upper() for k in keys))


@dataclass(frozen=True)
class SubscriptionRouteDecision:
    new_worker_route_compatible: bool
    reason: str
    dispatch_authorized: bool = False


def assess_new_worker_route(
    account_evidence: Mapping[str, object],
    *,
    worker_environment_keys: Collection[str],
    metered_fallback_configured: bool = False,
    paid_provider_fallback_configured: bool = False,
    paid_credit_fallback_configured: bool = False,
) -> SubscriptionRouteDecision:
    """Check structural paid routes and account type without quota preflight loops.

    ``new_worker_route_compatible`` describes only the cost boundary; it never
    authorizes LIVE or bypasses the separate campaign/attempt admission gate.
    An unreadable quota number alone is compatible with subscription work.
    """
    if any(type(flag) is not bool or flag for flag in (
        metered_fallback_configured, paid_provider_fallback_configured,
        paid_credit_fallback_configured,
    )):
        return SubscriptionRouteDecision(False, "paid fallback configured")
    if (not isinstance(worker_environment_keys, (set, frozenset, tuple, list))
            or any(type(key) is not str for key in worker_environment_keys)):
        return SubscriptionRouteDecision(False, "worker environment keys unverified")
    if metered_worker_environment_present(worker_environment_keys):
        return SubscriptionRouteDecision(False, "metered API route present in worker environment")
    if not isinstance(account_evidence, Mapping):
        return SubscriptionRouteDecision(False, "Codex account route unverified")
    if account_evidence.get("auth_state") != "CHATGPT_ACCOUNT":
        return SubscriptionRouteDecision(False, "Codex account is not verified ChatGPT subscription route")
    if account_evidence.get("ordinary_usage_allowed") is False:
        return SubscriptionRouteDecision(False, "Codex reported ordinary usage unavailable")
    return SubscriptionRouteDecision(True, "ChatGPT route; no paid fallback; quota unreadable is permitted")
