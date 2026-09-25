from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RelayState(StrEnum):
    PREPARED = "PREPARED"
    PREFLIGHT_OK = "PREFLIGHT_OK"
    SIMULATED = "SIMULATED"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RelayResult:
    provider_id: str
    correlation_id: str
    state: RelayState
    raw: bytes | None = None
    error: str | None = None
    simulated: bool = True
    packet_sha256: str = ""
    session_id: str | None = None
    prompt_attempts: int = 0
