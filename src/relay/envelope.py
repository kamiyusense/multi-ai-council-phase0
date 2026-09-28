from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any


def validate_timeout(timeout_seconds: Any) -> None:
    if timeout_seconds is not None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
            raise ValueError("Invalid timeout_seconds")


def validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dictionary")
    blocked = {"model", "modelProvider", "serviceTier", "reasoning", "effort", "thinking",
               "approvalPolicy", "approvalsReviewer", "sandbox", "sandboxPolicy", "cwd",
               "config", "base", "developer", "general instructions", "plugin disabling",
               "billing", "auth route", "timeout_seconds"}
    if blocked.intersection(payload):
        raise ValueError("Request override fields rejected.")


def compute_intent_hash(payload: dict[str, Any], timeout_seconds: int | None = None) -> str:
    validate_timeout(timeout_seconds)
    intent = {"payload": payload, "timeout_seconds": timeout_seconds}
    encoded = json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DispatchSlot:
    case_id: str
    provider_id: str
    sequence: int

    def key(self) -> str:
        if not isinstance(self.case_id, str) or not self.case_id:
            raise ValueError("invalid dispatch slot")
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("invalid dispatch slot")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 0:
            raise ValueError("invalid dispatch slot")
        return f"{self.case_id}:{self.provider_id}:{self.sequence}"


@dataclass(frozen=True, slots=True)
class DispatchEnvelope:
    slot: DispatchSlot
    correlation_id: str
    packet_sha256: str
    payload: dict[str, Any]
    timeout_seconds: int | None = None

    @classmethod
    def build(
        cls,
        *,
        slot: DispatchSlot,
        correlation_id: str,
        payload: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> "DispatchEnvelope":
        slot.key()
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValueError("correlation_id is required")
        validate_timeout(timeout_seconds)
        validate_payload(payload)
        snapshot = copy.deepcopy(payload)
        return cls(
            slot=slot,
            correlation_id=correlation_id,
            packet_sha256=compute_intent_hash(snapshot, timeout_seconds),
            payload=snapshot,
            timeout_seconds=timeout_seconds,
        )
