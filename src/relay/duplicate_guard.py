from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .envelope import DispatchEnvelope


class DuplicateDecision(StrEnum):
    RESERVED = "RESERVED"
    SAME_REQUEST = "SAME_REQUEST"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class Reservation:
    slot_key: str
    packet_sha256: str
    first_correlation_id: str


class DuplicateGuard:
    """In-memory deterministic guard used by static/mock Relay tests.

    Same slot + same deterministic payload hash is the same request.
    Same slot + different hash is a conflict. A durable SQLite ledger may
    replace storage later without changing these semantics.
    """

    def __init__(self) -> None:
        self._reservations: dict[str, Reservation] = {}

    def reserve(self, envelope: DispatchEnvelope) -> DuplicateDecision:
        slot_key = envelope.slot.key()
        existing = self._reservations.get(slot_key)
        if existing is None:
            self._reservations[slot_key] = Reservation(
                slot_key=slot_key,
                packet_sha256=envelope.packet_sha256,
                first_correlation_id=envelope.correlation_id,
            )
            return DuplicateDecision.RESERVED
        if existing.packet_sha256 == envelope.packet_sha256:
            return DuplicateDecision.SAME_REQUEST
        return DuplicateDecision.CONFLICT
