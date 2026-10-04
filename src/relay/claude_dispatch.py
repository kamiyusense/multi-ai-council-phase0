"""Claude dispatch path (STATIC, production-intent wiring; nothing real is launched).

Order for one dispatch:
  envelope -> provider must be Claude -> Admission Gate contract for this dispatch must be PREPARED (one upstream
  generation per dispatch, retry 0, fallback disabled) -> transport with route admission + mid-turn rule ->
  existing RelayLifecycle: initialize -> identity evidence -> admission (before session/new) -> session/new ->
  admission again -> ONE prompt -> mid-turn rule (existing cancel + existing stop flag) -> terminal result.

Roles: route admission = which payment/auth route is confirmed; Admission Gate = how many upstream generations.
They are combined, never merged. Policy lives in ``providers.policy``; this module only assembles existing parts.
There is no "protection off": ``mode`` is ``enforce`` or ``monitor_only``. The official-adapter launch seam for
Claude stays closed (``AcpStdioStaticTransport`` refuses it), so this path cannot start a real Claude.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from providers.base import ProviderStaticProfile
from providers.policy import claude_route_admission, claude_route_midturn, monitor_only

from .acp_stdio_relay_transport import AcpStdioStaticTransport
from .duplicate_guard import DuplicateGuard
from .envelope import DispatchEnvelope
from .lifecycle import RelayLifecycle
from .result import RelayResult, RelayState

__all__ = ["ClaudeStaticDispatcher", "MODES"]

MODES = ("enforce", "monitor_only")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _gate_contract_problem(gate_transport: Any, dispatch_id: Any) -> str | None:
    """Why the Admission Gate contract (``prepare_transport`` output) is not usable for this dispatch, else None."""
    if not isinstance(dispatch_id, str) or not _UUID.fullmatch(dispatch_id):
        return "dispatch_id must be a lowercase UUID"
    if not isinstance(gate_transport, Mapping) or gate_transport.get("status") != "PREPARED":
        return "Admission Gate contract is not PREPARED"
    if gate_transport.get("launch") is not False or gate_transport.get("live_model") is not False \
            or gate_transport.get("external_send") is not False:
        return "Admission Gate contract allows launch / live model / external send"
    if gate_transport.get("retry") != 0 or gate_transport.get("fallback") != "disabled":
        return "Admission Gate contract must have retry=0 and fallback=disabled"
    env = gate_transport.get("env")
    if not isinstance(env, Mapping) or env.get("CLAUDE_CODE_MAX_RETRIES") != "0":
        return "Admission Gate env must set CLAUDE_CODE_MAX_RETRIES=0"
    header = env.get("ANTHROPIC_CUSTOM_HEADERS")
    if not isinstance(header, str) or header.rsplit(": ", 1)[-1] != dispatch_id:
        return "Admission Gate contract belongs to a different dispatch"
    return None


class ClaudeStaticDispatcher:
    """Assembles the Claude dispatch path from existing parts. One transport (one adapter process) per dispatch."""

    def __init__(
        self,
        profile: ProviderStaticProfile,
        agent_command: tuple[str, ...],
        *,
        mode: str = "enforce",
        duplicate_guard: DuplicateGuard | None = None,
        route_wait_seconds: float = 6.0,
    ) -> None:
        if not isinstance(profile, ProviderStaticProfile) or profile.provider_id != "anthropic":
            raise ValueError("profile must be the Claude (anthropic) profile")
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}; there is no 'off'")
        self._profile, self._command, self._wait = profile, agent_command, route_wait_seconds
        if mode == "enforce":
            self._admission, self._midturn = claude_route_admission, claude_route_midturn
        else:  # monitor_only: the real decisions are recorded, nothing is blocked or cancelled
            self._admission = monitor_only(claude_route_admission, (True, "MONITOR_ONLY"))
            self._midturn = monitor_only(claude_route_midturn, None)
        self.mode = mode
        self._guard = duplicate_guard or DuplicateGuard()
        self._lifecycle: RelayLifecycle | None = None  # kept across dispatches so the existing stop flag persists
        self.last_transport: AcpStdioStaticTransport | None = None

    @property
    def observed(self) -> tuple[list, list]:
        """Real decisions recorded in monitor_only mode: (admission, mid-turn). Empty in enforce mode."""
        if self.mode != "monitor_only":
            return [], []
        return list(self._admission.observed), list(self._midturn.observed)

    def dispatch(self, envelope: DispatchEnvelope, *, dispatch_id: str, gate_transport: Mapping[str, Any], cwd: str) -> RelayResult:
        def blocked(reason: str) -> RelayResult:
            return RelayResult(provider_id=envelope.slot.provider_id, correlation_id=envelope.correlation_id,
                               state=RelayState.BLOCKED, error=reason, packet_sha256=envelope.packet_sha256)

        if envelope.slot.provider_id != self._profile.provider_id:
            return blocked("not a Claude dispatch")
        problem = _gate_contract_problem(gate_transport, dispatch_id)
        if problem is not None:
            return blocked(problem)  # no process is started without a matching one-generation contract
        transport = AcpStdioStaticTransport(
            self._profile, self._command, route_admission=self._admission, route_midturn=self._midturn,
            route_admission_wait_seconds=self._wait,
        )
        self.last_transport = transport
        if self._lifecycle is None:
            self._lifecycle = RelayLifecycle(transport=transport, duplicate_guard=self._guard)
        else:
            self._lifecycle.transport = transport
        return self._lifecycle.dispatch_mock(envelope, cwd=cwd)
