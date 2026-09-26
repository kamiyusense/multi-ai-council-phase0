from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any


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

    @classmethod
    def build(
        cls,
        *,
        slot: DispatchSlot,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> "DispatchEnvelope":
        if not correlation_id:
            raise ValueError("correlation_id is required")
        snapshot = copy.deepcopy(payload)
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return cls(
            slot=slot,
            correlation_id=correlation_id,
            packet_sha256=hashlib.sha256(encoded).hexdigest(),
            payload=snapshot,
        )
