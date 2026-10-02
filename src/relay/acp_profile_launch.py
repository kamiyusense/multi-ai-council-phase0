"""Minimal link from a ProviderStaticProfile to the existing ACP stdio seam.

STATIC/mock only. The official adapter executable named by the profile is
resolved and validated here, but this module never launches it: the bridge
below requires an explicit fake command, so no provider/model turn can start.
A real launch is a separate, human-approved boundary (M9).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from .acp_client import acp_mock_text_to_phase0_raw, acp_mock_text_update_wire
from .bridge import RelayProviderAdapterBridge

_OFFICIAL_BINARIES = {
    "openai": ("codex-acp",),
    "anthropic": ("claude-agent-acp",),
    "google": ("agy_acp_server.exe", "agy_acp_server.par"),
}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class ACPLaunchSpec:
    provider_id: str
    executable: str
    args: tuple[str, ...]
    session_meta: dict[str, Any] | None


def resolve_acp_launch(profile: Any) -> ACPLaunchSpec:
    """Map a profile to its official adapter executable; fail closed on anything else."""
    provider_id = getattr(profile, "provider_id", None)
    allowed = _OFFICIAL_BINARIES.get(provider_id)
    if allowed is None:
        raise ValueError("unknown provider_id")
    name = getattr(profile, "binary_name", None)
    if not isinstance(name, str) or not _SAFE_NAME.match(name) or name not in allowed:
        raise ValueError("binary_name is not an official adapter executable")
    if (
        getattr(profile, "retry_count", None) != 0
        or getattr(profile, "fallback_state", None) != "disabled"
        or getattr(profile, "live_ready", None) is not False
    ):
        raise ValueError("profile violates retry/fallback/live safety defaults")
    return ACPLaunchSpec(provider_id, name, (), profile.session_meta)


class ACPProfileBridge(RelayProviderAdapterBridge):
    """Relay bridge that runs one profile-bound fake ACP process per request.

    `fake_command` is mandatory (command + args of a local test double), so the
    official adapter can never be started through this class. No retry/fallback.
    """

    def __init__(self, profile: Any, fake_command: tuple[str, ...], *, cwd: str,
                 prompt_text: str = "static ping", acp_timeout: float = 2.0):
        super().__init__()
        if not isinstance(fake_command, tuple) or not fake_command or not all(
            isinstance(a, str) and a for a in fake_command
        ):
            raise ValueError("fake_command must be a non-empty tuple of strings")
        self.spec = resolve_acp_launch(profile)
        if fake_command[0] == self.spec.executable:
            raise ValueError("official adapter must not be launched in static mode")
        self.fake_command = fake_command
        self.cwd = cwd
        self.prompt_text = prompt_text
        self.acp_timeout = acp_timeout
        self.launch_count = 0

    def collect(self, process_handle: dict[str, Any]) -> dict[str, Any]:
        self.collect_count += 1
        self.launch_count += 1
        result = asyncio.run(
            acp_mock_text_update_wire(
                self.fake_command[0], *self.fake_command[1:],
                cwd=self.cwd, prompt_text=self.prompt_text,
                timeout=self.acp_timeout, session_meta=self.spec.session_meta,
            )
        )
        raw = acp_mock_text_to_phase0_raw(result).decode("utf-8")
        return {"stdout": "acp-fake", "rawResponse": raw,
                "correlation_id": process_handle.get("correlation_id")}
