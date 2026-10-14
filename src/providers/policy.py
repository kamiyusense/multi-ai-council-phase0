from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Mapping, Sequence
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    provider_id: str
    external_agent: str
    pinned_version: str
    required_auth_kind: str = "account"
    allow_api_key: bool = False
    allow_gateway: bool = False
    allow_external_cloud: bool = False
    automatic_retry: int = 0
    fallback_enabled: bool = False
    dangerous_permission_bypass: bool = False
    live_ready: bool = False

    def validate_auth_kind(self, kind: str | None) -> bool:
        return kind == self.required_auth_kind

    def assert_static_safety(self) -> None:
        if self.automatic_retry != 0:
            raise ValueError("automatic retry must be 0")
        if self.fallback_enabled:
            raise ValueError("fallback must be disabled")
        if self.allow_api_key or self.allow_gateway or self.allow_external_cloud:
            raise ValueError("non-subscription auth route must be disabled")
        if self.dangerous_permission_bypass:
            raise ValueError("dangerous permission bypass must be disabled")
        if self.live_ready:
            raise ValueError("provider must remain live-blocked in static phase")


CODEX_POLICY = ProviderPolicy(
    provider_id="openai",
    external_agent="@agentclientprotocol/codex-acp",
    pinned_version="2.1.1",
)

CLAUDE_POLICY = ProviderPolicy(
    provider_id="anthropic",
    external_agent="@agentclientprotocol/claude-agent-acp",
    pinned_version="0.85.1",
)

ANTIGRAVITY_POLICY = ProviderPolicy(
    provider_id="google",
    external_agent="antigravity-acp",
    pinned_version="1.2.1",
)


def claude_session_meta() -> dict[str, Any]:
    return {
        "claudeCode": {
            "options": {
                "allowDangerouslySkipPermissions": False,
            }
        }
    }


def antigravity_binary_name(platform: str, architecture: str) -> str:
    supported = {
        ("windows", "x86_64"): "agy_acp_server.exe",
        ("windows", "aarch64"): "agy_acp_server.exe",
        ("linux", "x86_64"): "agy_acp_server.par",
        ("linux", "aarch64"): "agy_acp_server.par",
        ("darwin", "aarch64"): "agy_acp_server.par",
    }
    try:
        return supported[(platform.lower(), architecture.lower())]
    except KeyError as exc:
        raise ValueError("unsupported Antigravity ACP platform/architecture") from exc


def antigravity_launch_args(platform: str, architecture: str) -> tuple[str, ...]:
    """Static launch arguments the Google registry manifest lists for ``agy_acp_server`` (read-only data).

    Only linux needs ``--uid=``; validated through ``antigravity_binary_name`` so unsupported
    platforms fail closed. Nothing is launched here.
    """
    antigravity_binary_name(platform, architecture)
    return ("--uid=",) if platform.lower() == "linux" else ()


ANTIGRAVITY_ADMISSIBLE_AUTH_TYPE = "oauth-personal"


def antigravity_route_admission(settings: Mapping[str, Any] | None) -> tuple[bool, str]:
    """Phase 0 admission for the Antigravity route (STATIC; the caller passes a host-owned settings snapshot).

    ``agy_acp_server`` publishes no "who is logged in" notification (checked in public sources only), and
    ``initialize`` only lists the *available* auth methods. The selected method is ``auth.type`` in the server's
    settings (or the ``authenticate`` call). Allowed only when it is exactly the personal Google account OAuth
    type; API key, enterprise, agent-platform, missing, unknown or malformed are refused (fail closed).
    """
    auth = settings.get("auth") if isinstance(settings, Mapping) else None
    kind = auth.get("type") if isinstance(auth, Mapping) else None
    if kind is None:
        return False, "NO_AUTH_SELECTION"
    if kind != ANTIGRAVITY_ADMISSIBLE_AUTH_TYPE:
        return False, f"ROUTE_{kind if isinstance(kind, str) and kind else 'UNKNOWN'}"
    return True, "OK"


CLAUDE_ADMISSIBLE_AUTH_STATE = "CLAUDE_SUBSCRIPTION_ACCOUNT"


def claude_route_admission(auth_status_evidence: Sequence[Mapping[str, Any]]) -> tuple[bool, str]:
    """The single Phase 0 policy for the dynamic Claude route (STATIC; transports only call it).

    Input: sanitized classifications (``summarize_claude_auth_status_update``) observed from the official
    adapter *before* a prompt is sent. Allowed only if at least one was observed and every observation is the
    subscription account. Anything else - API key, gateway/3P, not authenticated, UNKNOWN, malformed, or no
    observation at all - is refused (fail closed). Returns ``(allowed, reason)``.
    """
    if not auth_status_evidence:
        return False, "NO_AUTH_STATUS_OBSERVED"
    for item in auth_status_evidence:
        state = item.get("auth_state") if isinstance(item, Mapping) else None
        if state != CLAUDE_ADMISSIBLE_AUTH_STATE:
            return False, f"ROUTE_{state if isinstance(state, str) and state else 'UNKNOWN'}"
    return True, "OK"


CLAUDE_CONFIRMED_VIOLATION_STATES = frozenset({"API_KEY_ROUTE_VIOLATION", "EXTERNAL_ROUTE_VIOLATION"})


def claude_route_midturn(auth_status_item: Mapping[str, Any]) -> str | None:
    """Mid-turn rule (same policy module): a reason only for a *confirmed* API-key / external route.

    Unknown, malformed and not-authenticated classifications return ``None`` (recorded, never acted on), so a
    mis-classification cannot kill a legitimate subscription turn.
    """
    state = auth_status_item.get("auth_state") if isinstance(auth_status_item, Mapping) else None
    return f"ROUTE_{state}" if state in CLAUDE_CONFIRMED_VIOLATION_STATES else None


def monitor_only(policy: Callable[..., Any], neutral: Any) -> Callable[..., Any]:
    """The one "monitor only" wrapper: call the real policy, record what it decided, always return ``neutral``.

    ``neutral`` is the allow value of the wrapped policy (``(True, "MONITOR_ONLY")`` for admission, ``None`` for the
    mid-turn rule). Decisions are in ``wrapper.observed`` as ``(args, real_result)``. There is no "protection off".
    """
    observed: list[tuple[Any, Any]] = []

    def wrapper(*args: Any) -> Any:
        observed.append((args, policy(*args)))
        return neutral

    wrapper.observed = observed  # type: ignore[attr-defined]
    return wrapper
