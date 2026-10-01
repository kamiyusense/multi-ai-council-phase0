from __future__ import annotations

from dataclasses import dataclass
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
    pinned_version="2.1.0",
)

CLAUDE_POLICY = ProviderPolicy(
    provider_id="anthropic",
    external_agent="@agentclientprotocol/claude-agent-acp",
    pinned_version="0.84.0",
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
