# 使用停止中・実行禁止（規約上の理由、2026-10）
# SUSPENDED - DO NOT RUN (Antigravity terms, 2026-10). Archived from the Relay; see archive/antigravity_launch/README.md.
"""Antigravity dispatch path (STATIC; nothing real is launched).

Order for one dispatch: envelope -> provider must be Google -> route admission on the host-owned settings
snapshot (``providers.policy.antigravity_route_admission``) BEFORE any transport or process exists -> existing
``RelayLifecycle`` (initialize -> session/new -> ONE prompt -> terminal). A ``session/new`` "Authentication
required" error is an ordinary failure of the existing lifecycle (no prompt, no retry, no fallback).

Not built, on purpose (UNKNOWN in public sources): a mid-turn identity signal, so there is no mid-turn cancel
here; and no Admission Gate equivalent, so the one-generation boundary for Google is UNKNOWN. ``mode`` is
``enforce`` or ``monitor_only`` (the existing wrapper); there is no "off". The official-binary launch seam
stays closed in ``AcpStdioStaticTransport``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from providers.base import ProviderStaticProfile
from providers.policy import antigravity_route_admission, monitor_only

from .acp_stdio_relay_transport import AcpStdioStaticTransport
from .duplicate_guard import DuplicateGuard
from .envelope import DispatchEnvelope
from .lifecycle import RelayLifecycle
from .result import RelayResult, RelayState

__all__ = ["AntigravityStaticDispatcher", "MODES"]

MODES = ("enforce", "monitor_only")


class AntigravityStaticDispatcher:
    def __init__(
        self,
        profile: ProviderStaticProfile,
        agent_command: tuple[str, ...],
        *,
        mode: str = "enforce",
        duplicate_guard: DuplicateGuard | None = None,
    ) -> None:
        if not isinstance(profile, ProviderStaticProfile) or profile.provider_id != "google":
            raise ValueError("profile must be the Antigravity (google) profile")
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}; there is no 'off'")
        self._profile, self._command, self.mode = profile, agent_command, mode
        self._admission = antigravity_route_admission if mode == "enforce" else monitor_only(
            antigravity_route_admission, (True, "MONITOR_ONLY"))
        self._guard = duplicate_guard or DuplicateGuard()
        self._lifecycle: RelayLifecycle | None = None
        self.last_transport: AcpStdioStaticTransport | None = None

    @property
    def observed(self) -> list:
        return list(self._admission.observed) if self.mode == "monitor_only" else []

    def dispatch(self, envelope: DispatchEnvelope, *, settings: Mapping[str, Any] | None, cwd: str) -> RelayResult:
        def blocked(reason: str) -> RelayResult:
            return RelayResult(provider_id=envelope.slot.provider_id, correlation_id=envelope.correlation_id,
                               state=RelayState.BLOCKED, error=reason, packet_sha256=envelope.packet_sha256)

        if envelope.slot.provider_id != self._profile.provider_id:
            return blocked("not an Antigravity dispatch")
        allowed, reason = self._admission(settings)
        if not allowed:
            return blocked(f"route admission refused before any process: {reason}")
        transport = AcpStdioStaticTransport(self._profile, self._command)
        self.last_transport = transport
        if self._lifecycle is None:
            self._lifecycle = RelayLifecycle(transport=transport, duplicate_guard=self._guard)
        else:
            self._lifecycle.transport = transport
        return self._lifecycle.dispatch_mock(envelope, cwd=cwd)
