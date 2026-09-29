from __future__ import annotations

from enum import StrEnum


class ExecutionState(StrEnum):
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    TIMEOUT = "TIMEOUT"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    QUOTA_CONFIRMED = "QUOTA_CONFIRMED"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    PARTIAL = "PARTIAL"
    ERROR_UNKNOWN = "ERROR_UNKNOWN"
    USER_DISABLED = "USER_DISABLED"


class ParticipationState(StrEnum):
    PARTICIPANT = "PARTICIPANT"
    NONPARTICIPANT = "NONPARTICIPANT"


class AnswerState(StrEnum):
    ANSWER = "ANSWER"
    ANSWER_UNKNOWN = "ANSWER_UNKNOWN"
    REFUSAL = "REFUSAL"


class CapabilityState(StrEnum):
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


TERMINAL_EXECUTION_STATES = {
    ExecutionState.COMPLETE,
    ExecutionState.TIMEOUT,
    ExecutionState.AUTH_REQUIRED,
    ExecutionState.QUOTA_CONFIRMED,
    ExecutionState.INVALID_OUTPUT,
    ExecutionState.PARTIAL,
    ExecutionState.ERROR_UNKNOWN,
    ExecutionState.USER_DISABLED,
}

_ALLOWED_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.READY: {
        ExecutionState.RUNNING,
        ExecutionState.AUTH_REQUIRED,
        ExecutionState.ERROR_UNKNOWN,
        ExecutionState.USER_DISABLED,
    },
    ExecutionState.RUNNING: TERMINAL_EXECUTION_STATES,
}


def can_transition(current: ExecutionState, target: ExecutionState) -> bool:
    if current in TERMINAL_EXECUTION_STATES:
        return False
    return target in _ALLOWED_TRANSITIONS.get(current, set())


def require_transition(current: ExecutionState, target: ExecutionState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"invalid execution-state transition: {current} -> {target}")
