from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any


def compute_intent_hash(payload: dict[str, Any], timeout_seconds: float | None = None) -> str:
    intent = {"payload": payload, "timeout_seconds": timeout_seconds}
    encoded = json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DispatchSlot:
    case_id: str
    provider_id: str
    sequence: int

    def key(self) -> str:
        if not self.case_id or not self.provider_id or self.sequence < 0:
            raise ValueError("invalid dispatch slot")
        return f"{self.case_id}:{self.provider_id}:{self.sequence}"


@dataclass(frozen=True, slots=True)
class DispatchEnvelope:
    slot: DispatchSlot
    correlation_id: str
    packet_sha256: str
    payload: dict[str, Any]
    timeout_seconds: float | None = None

    @classmethod
    def build(
        cls,
        *,
        slot: DispatchSlot,
        correlation_id: str,
        payload: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> "DispatchEnvelope":
        if not correlation_id:
            raise ValueError("correlation_id is required")
        snapshot = copy.deepcopy(payload)
        return cls(
            slot=slot,
            correlation_id=correlation_id,
            packet_sha256=compute_intent_hash(snapshot, timeout_seconds),
            payload=snapshot,
            timeout_seconds=timeout_seconds,
        )
