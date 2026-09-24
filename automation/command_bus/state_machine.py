from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from .validator import validate_state

class LoopState(StrEnum):
    PREPARED = "PREPARED"
    RUNNING = "RUNNING"
    WAITING_FOR_EVIDENCE = "WAITING_FOR_EVIDENCE"
    WAITING_FOR_HUMAN_AUTH = "WAITING_FOR_HUMAN_AUTH"
    HUMAN_COMPLETED_UNVERIFIED = "HUMAN_COMPLETED_UNVERIFIED"
    VERIFYING_POST_AUTH = "VERIFYING_POST_AUTH"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"
    HALTED = "HALTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"

@dataclass
class StateMachine:
    state: dict

    def __post_init__(self) -> None:
        validate_state(self.state)

    def blocked_reason(self, now: datetime | None = None) -> str | None:
        now = now or datetime.now(timezone.utc)
        if self.state["round"] >= self.state["max_rounds"]:
            return "max_rounds reached"
        if now >= datetime.fromisoformat(self.state["expires_at"].replace("Z", "+00:00")):
            return "expired"
        if self.state["stop_requested"]:
            return "stop requested"
        if self.state["state"] != LoopState.RUNNING:
            return f"state is {self.state['state']}"
        return None

    def request_stop(self) -> None:
        self.state["stop_requested"] = True
        self.state["state"] = LoopState.HALTED

    def mark_expired(self, now: datetime | None = None) -> bool:
        if datetime.fromisoformat(self.state["expires_at"].replace("Z", "+00:00")) <= (now or datetime.now(timezone.utc)):
            self.state["state"] = LoopState.EXPIRED
            return True
        return False
