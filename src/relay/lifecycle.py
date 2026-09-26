from __future__ import annotations

from dataclasses import dataclass, field

from .duplicate_guard import DuplicateDecision, DuplicateGuard
from .envelope import DispatchEnvelope
from .result import RelayResult, RelayState
from .transport import RelayTransport


@dataclass(slots=True)
class RelayLifecycle:
    transport: RelayTransport
    duplicate_guard: DuplicateGuard
    _stop_requested: bool = field(default=False, init=False)

    def request_stop(self) -> None:
        self._stop_requested = True

    def dispatch_mock(self, envelope: DispatchEnvelope, *, cwd: str) -> RelayResult:
        if self._stop_requested:
            return RelayResult(
                provider_id=envelope.slot.provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.BLOCKED,
                error="stop requested",
                packet_sha256=envelope.packet_sha256,
            )

        decision = self.duplicate_guard.reserve(envelope)
        if decision is DuplicateDecision.CONFLICT:
            return RelayResult(
                provider_id=envelope.slot.provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.BLOCKED,
                error="dispatch slot conflict",
                packet_sha256=envelope.packet_sha256,
            )
        if decision is DuplicateDecision.SAME_REQUEST:
            return RelayResult(
                provider_id=envelope.slot.provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.BLOCKED,
                error="duplicate request already reserved",
                packet_sha256=envelope.packet_sha256,
            )

        provider_id = envelope.slot.provider_id
        session_id: str | None = None
        prompt_attempts = 0
        try:
            init = self.transport.initialize(provider_id)
            if init.get("live_process_started") is not False:
                return RelayResult(
                    provider_id=provider_id,
                    correlation_id=envelope.correlation_id,
                    state=RelayState.UNKNOWN,
                    error="mock transport could not prove no live process",
                    packet_sha256=envelope.packet_sha256,
                )
            session_id = self.transport.open_session(provider_id, cwd=cwd)
            prompt_attempts = 1
            raw = self.transport.prompt(provider_id, session_id, envelope.payload)
            return RelayResult(
                provider_id=provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.SIMULATED,
                raw=raw,
                packet_sha256=envelope.packet_sha256,
                session_id=session_id,
                prompt_attempts=prompt_attempts,
            )
        except TimeoutError as exc:
            if session_id is not None:
                self.transport.cancel(provider_id, session_id)
            return RelayResult(
                provider_id=provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.TIMEOUT,
                error=str(exc),
                packet_sha256=envelope.packet_sha256,
                session_id=session_id,
                prompt_attempts=prompt_attempts,
            )
        except Exception as exc:
            if session_id is not None:
                self.transport.cancel(provider_id, session_id)
            return RelayResult(
                provider_id=provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.UNKNOWN,
                error=str(exc),
                packet_sha256=envelope.packet_sha256,
                session_id=session_id,
                prompt_attempts=prompt_attempts,
            )
        finally:
            if session_id is not None:
                self.transport.close(provider_id, session_id)
