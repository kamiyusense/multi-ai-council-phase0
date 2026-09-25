from __future__ import annotations

from dataclasses import dataclass

from .duplicate_guard import DuplicateDecision, DuplicateGuard
from .envelope import DispatchEnvelope
from .result import RelayResult, RelayState
from .transport import RelayTransport


@dataclass(slots=True)
class RelayLifecycle:
    transport: RelayTransport
    duplicate_guard: DuplicateGuard

    def dispatch_mock(self, envelope: DispatchEnvelope, *, cwd: str) -> RelayResult:
        decision = self.duplicate_guard.reserve(envelope)
        if decision is DuplicateDecision.CONFLICT:
            return RelayResult(
                provider_id=envelope.slot.provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.BLOCKED,
                error="dispatch slot conflict",
            )
        if decision is DuplicateDecision.SAME_REQUEST:
            return RelayResult(
                provider_id=envelope.slot.provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.BLOCKED,
                error="duplicate request already reserved",
            )

        provider_id = envelope.slot.provider_id
        session_id: str | None = None
        try:
            init = self.transport.initialize(provider_id)
            if init.get("live_process_started") is not False:
                return RelayResult(
                    provider_id=provider_id,
                    correlation_id=envelope.correlation_id,
                    state=RelayState.UNKNOWN,
                    error="mock transport could not prove no live process",
                )
            session_id = self.transport.open_session(provider_id, cwd=cwd)
            raw = self.transport.prompt(provider_id, session_id, envelope.payload)
            return RelayResult(
                provider_id=provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.SIMULATED,
                raw=raw,
            )
        except TimeoutError as exc:
            if session_id is not None:
                self.transport.cancel(provider_id, session_id)
            return RelayResult(
                provider_id=provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.TIMEOUT,
                error=str(exc),
            )
        except Exception as exc:
            return RelayResult(
                provider_id=provider_id,
                correlation_id=envelope.correlation_id,
                state=RelayState.UNKNOWN,
                error=str(exc),
            )
        finally:
            if session_id is not None:
                self.transport.close(provider_id, session_id)
