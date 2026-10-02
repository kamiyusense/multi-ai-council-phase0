"""STATIC-only RelayTransport that hosts one ACP stdio child per request.

Thin seam: ``RelayLifecycle`` (sync RelayTransport) -> existing
``acp_mock_text_update_wire`` (initialize -> session/new -> session/prompt over
``spawn_stdio_transport``) -> existing ``acp_mock_text_to_phase0_raw`` mapper.

It launches only a caller-injected command (a fake/local test agent). The
official live adapter binaries named by the provider profiles are refused, so
this class can never start a real provider/model turn. No retry, no relaunch,
no fallback: one request -> one child -> one prompt.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from providers.base import ProviderStaticProfile

from .acp_client import acp_mock_text_to_phase0_raw, acp_mock_text_update_wire

__all__ = ["AcpStdioStaticTransport", "LIVE_ADAPTER_MARKERS"]

# Official adapter identities that must never be launched from the STATIC seam.
LIVE_ADAPTER_MARKERS = (
    "codex-acp",
    "claude-agent-acp",
    "agy_acp_server",
    "antigravity-acp",
    "@agentclientprotocol/",
)

_DEFAULT_TIMEOUT_SECONDS = 5


def _refuse_live_command(command: tuple[str, ...], profile: ProviderStaticProfile) -> None:
    markers = LIVE_ADAPTER_MARKERS + ((profile.binary_name,) if profile.binary_name else ())
    for part in command:
        if not isinstance(part, str) or not part:
            raise ValueError("command parts must be non-empty strings")
        lowered = (part.lower(), os.path.basename(part.replace("\\", "/")).lower())
        if any(marker.lower() in text for marker in markers for text in lowered):
            raise ValueError("official live adapter launch is blocked in STATIC mode")


class AcpStdioStaticTransport:
    """RelayTransport-compatible; spawns the injected fake agent at prompt time."""

    def __init__(self, profile: ProviderStaticProfile, command: tuple[str, ...]) -> None:
        if not isinstance(profile, ProviderStaticProfile):
            raise TypeError("profile must be a ProviderStaticProfile")
        if profile.live_ready is not False or profile.retry_count != 0 or profile.fallback_state != "disabled":
            raise ValueError("profile must be static: live_ready=False, retry=0, fallback=disabled")
        if not isinstance(command, tuple) or not command:
            raise ValueError("command must be a non-empty tuple")
        _refuse_live_command(command, profile)
        self.profile = profile
        self.command = command
        self.spawn_count = 0
        self._session_count = 0
        self._sessions: dict[str, dict[str, Any]] = {}

    def _session(self, provider_id: str, session_id: str) -> dict[str, Any]:
        if provider_id != self.profile.provider_id:
            raise ValueError("Wrong provider")
        if session_id not in self._sessions:
            raise ValueError("Unknown session")
        return self._sessions[session_id]

    def initialize(self, provider_id: str) -> dict[str, Any]:
        if provider_id != self.profile.provider_id:
            raise ValueError("provider_id does not match profile")
        # No process is started here; the fake child starts once, at prompt().
        return {
            "protocol_version": 1,
            "provider_id": provider_id,
            "mode": "acp_stdio_static",
            "live_process_started": False,
        }

    def open_session(self, provider_id: str, *, cwd: str) -> str:
        if provider_id != self.profile.provider_id:
            raise ValueError("provider_id does not match profile")
        self._session_count += 1
        session_id = f"acp-stdio-static:{provider_id}:{self._session_count}"
        self._sessions[session_id] = {"cwd": cwd, "state": "open", "prompted": False}
        return session_id

    def prompt(
        self,
        provider_id: str,
        session_id: str,
        payload: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> bytes:
        session = self._session(provider_id, session_id)
        if session["state"] != "open":
            raise ValueError("Session is not open")
        if session["prompted"]:
            raise ValueError("Session already prompted")
        session["prompted"] = True

        text = payload.get("prompt") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("payload['prompt'] must be a non-empty string")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("sync transport cannot run inside an event loop")

        self.spawn_count += 1
        result = asyncio.run(
            acp_mock_text_update_wire(
                *self.command,
                cwd=session["cwd"],
                prompt_text=text,
                timeout=float(timeout_seconds or _DEFAULT_TIMEOUT_SECONDS),
            )
        )
        # Non end_turn / empty text raises -> lifecycle reports UNKNOWN, never success.
        return acp_mock_text_to_phase0_raw(result)

    def cancel(self, provider_id: str, session_id: str) -> None:
        session = self._session(provider_id, session_id)
        if session["state"] in ("cancelled", "closed"):
            raise ValueError("Session already closed/cancelled")
        # The child is already torn down by the stdio context manager.
        session["state"] = "cancelled"

    def close(self, provider_id: str, session_id: str) -> None:
        session = self._session(provider_id, session_id)
        if session["state"] == "closed":
            raise ValueError("Session already closed")
        session["state"] = "closed"
