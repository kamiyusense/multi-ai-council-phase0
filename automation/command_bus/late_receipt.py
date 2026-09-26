"""Late terminal receipt reconciliation and successor issuance gates.

A mutable loop state may be closed UNKNOWN/HALTED/BLOCKED before an
event-triggered Work run publishes its durable terminal receipt.  This module
preserves that history, makes any observed terminal receipt a permanent replay
fence, and refuses replacement/successor issuance while old-run completion or
external side effects remain ambiguous.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .validator import validate_command, validate_receipt, validate_state


RECONCILABLE_PRIOR_STATES = frozenset(
    {"UNKNOWN", "HALTED", "BLOCKED", "FAILED", "EXPIRED"}
)
DURABLE_TERMINAL_STATES = frozenset(
    {
        "COMPLETE",
        "BLOCKED",
        "FAILED",
        "HALTED",
        "EXPIRED",
        "RECONCILED_LATE_RESULT",
    }
)
_EXTERNAL_ACTION_STATES = frozenset({"NONE", "OCCURRED", "UNKNOWN"})
_TRI_STATES = frozenset({True, False, "UNKNOWN"})


class SuccessorGateState(StrEnum):
    ALLOW_NEW_SUCCESSOR = "ALLOW_NEW_SUCCESSOR"
    DEFERRED = "DEFERRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class SuccessorGateDecision:
    state: SuccessorGateState
    reason: str


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed


def _match_receipt(command: dict[str, Any], receipt: dict[str, Any]) -> None:
    validate_command(command)
    validate_receipt(receipt)
    for field in ("command_id", "loop_id", "correlation_id"):
        if receipt.get(field) != command.get(field):
            raise ValueError(f"terminal receipt binding mismatch: {field}")
    if "generation" in command and "generation" in receipt:
        if receipt["generation"] != command["generation"]:
            raise ValueError("terminal receipt generation mismatch")


def receipt_replay_disposition(
    command: dict[str, Any], receipt: dict[str, Any] | None
) -> str:
    """Any durable terminal receipt permanently fences the old command."""
    validate_command(command)
    if receipt is None:
        return "NO_TERMINAL_RECEIPT"
    _match_receipt(command, receipt)
    return "NO_OP"


def durable_run_completion_state(
    command: dict[str, Any],
    state: dict[str, Any],
    receipt: dict[str, Any] | None,
) -> str:
    """Return ACTIVE, TERMINAL_DURABLE, or UNKNOWN without using elapsed time."""
    validate_command(command)
    validate_state(state)
    if state["last_command_id"] not in {None, command["command_id"]}:
        return "UNKNOWN"
    if receipt is None:
        return "ACTIVE" if state["state"] == "RUNNING" else "UNKNOWN"
    _match_receipt(command, receipt)
    if (
        state["state"] in DURABLE_TERMINAL_STATES
        and state.get("last_receipt_id") == receipt["receipt_id"]
        and state.get("stop_requested") is True
    ):
        return "TERMINAL_DURABLE"
    if state["state"] == "RUNNING":
        return "ACTIVE"
    return "UNKNOWN"


def reconcile_late_terminal_receipt(
    command: dict[str, Any],
    state: dict[str, Any],
    receipt: dict[str, Any],
    *,
    observed_at: str,
    prior_evidence_refs: list[str],
    successor_command: dict[str, Any] | None = None,
    write_ambiguity: bool | None = None,
    external_action_state: str = "UNKNOWN",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build append-only reconciliation evidence plus a safe mutable state.

    The caller persists the returned evidence at a new path.  Existing
    no-result/timeout evidence is referenced and never modified or deleted.
    """
    validate_command(command)
    validate_state(state)
    _match_receipt(command, receipt)
    _time(observed_at, "observed_at")
    if state["state"] == "RECONCILED_LATE_RESULT":
        raise ValueError("late receipt already reconciled")
    if state["state"] not in RECONCILABLE_PRIOR_STATES:
        raise ValueError("state is not eligible for late receipt reconciliation")
    if state.get("last_command_id") not in {None, command["command_id"]}:
        raise ValueError("state command binding mismatch")
    if not isinstance(prior_evidence_refs, list) or any(
        not isinstance(ref, str) or not ref for ref in prior_evidence_refs
    ):
        raise ValueError("invalid prior_evidence_refs")
    if write_ambiguity not in {True, False, None}:
        raise ValueError("invalid write_ambiguity")
    if external_action_state not in _EXTERNAL_ACTION_STATES:
        raise ValueError("invalid external_action_state")

    successor_id = None
    if successor_command is not None:
        validate_command(successor_command)
        if successor_command["command_id"] == command["command_id"]:
            raise ValueError("successor must use a fresh command_id")
        if successor_command["correlation_id"] == command["correlation_id"]:
            raise ValueError("successor must use a fresh correlation_id")
        if "generation" in command and "generation" in successor_command:
            if successor_command["generation"] <= command["generation"]:
                raise ValueError("successor generation must advance")
        successor_id = successor_command["command_id"]

    task_submitted = receipt.get("task_submitted", "UNKNOWN")
    jules_task_started = receipt.get("jules_task_started", "UNKNOWN")
    model_started = receipt.get("model_started", "UNKNOWN")
    for value, field in (
        (task_submitted, "task_submitted"),
        (jules_task_started, "jules_task_started"),
        (model_started, "model_started"),
    ):
        if value not in _TRI_STATES:
            raise ValueError(f"invalid {field}")

    prior_state = state["state"]
    reconciliation_id = f"{command['loop_id']}/late-terminal-{receipt['receipt_id'].split('/')[-1]}"
    evidence = {
        "schema_version": 1,
        "reconciliation_id": reconciliation_id,
        "command_id": command["command_id"],
        "loop_id": command["loop_id"],
        "correlation_id": command["correlation_id"],
        "generation": command.get("generation"),
        "prior_state": prior_state,
        "prior_last_receipt_id": state.get("last_receipt_id"),
        "late_receipt_id": receipt["receipt_id"],
        "late_receipt_state": receipt["state"],
        "late_terminal_receipt_observed": True,
        "successor_already_issued": successor_command is not None,
        "successor_command_id": successor_id,
        "prior_evidence_refs": list(prior_evidence_refs),
        "history_transition": (
            f"{prior_state} due prior durable observation -> "
            f"late {receipt['state']} receipt observed -> RECONCILED_LATE_RESULT"
        ),
        "replay_disposition": "PERMANENT_NO_OP",
        "run_completion_state": "TERMINAL_DURABLE",
        "write_ambiguity": write_ambiguity,
        "external_action_state": external_action_state,
        "task_submitted": task_submitted,
        "jules_task_started": jules_task_started,
        "model_started": model_started,
        "observed_at": observed_at,
    }
    validate_late_receipt_evidence(command, evidence)

    reconciled = deepcopy(state)
    reconciled["state"] = "RECONCILED_LATE_RESULT"
    reconciled["round"] = max(
        reconciled["round"],
        receipt.get("round", reconciled["round"])
        if isinstance(receipt.get("round", reconciled["round"]), int)
        else reconciled["round"],
    )
    reconciled["stop_requested"] = True
    reconciled["last_command_id"] = command["command_id"]
    reconciled["last_receipt_id"] = receipt["receipt_id"]
    reconciled["reconciled_from_state"] = prior_state
    reconciled["late_terminal_receipt_observed"] = True
    reconciled["late_receipt_state"] = receipt["state"]
    reconciled["successor_already_issued"] = successor_command is not None
    reconciled["successor_command_id"] = successor_id
    reconciled["reconciliation_observed_at"] = observed_at
    validate_state(reconciled)
    return evidence, reconciled


def validate_late_receipt_evidence(
    command: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    validate_command(command)
    required = {
        "schema_version",
        "reconciliation_id",
        "command_id",
        "loop_id",
        "correlation_id",
        "generation",
        "prior_state",
        "prior_last_receipt_id",
        "late_receipt_id",
        "late_receipt_state",
        "late_terminal_receipt_observed",
        "successor_already_issued",
        "successor_command_id",
        "prior_evidence_refs",
        "history_transition",
        "replay_disposition",
        "run_completion_state",
        "write_ambiguity",
        "external_action_state",
        "task_submitted",
        "jules_task_started",
        "model_started",
        "observed_at",
    }
    if not isinstance(evidence, dict) or not required <= evidence.keys():
        raise ValueError("incomplete late receipt reconciliation evidence")
    if evidence["schema_version"] != 1:
        raise ValueError("unsupported reconciliation schema")
    for field in ("command_id", "loop_id", "correlation_id"):
        if evidence[field] != command[field]:
            raise ValueError(f"reconciliation binding mismatch: {field}")
    if evidence["generation"] != command.get("generation"):
        raise ValueError("reconciliation generation mismatch")
    if evidence["prior_state"] not in RECONCILABLE_PRIOR_STATES:
        raise ValueError("invalid reconciliation prior_state")
    if evidence["late_receipt_state"] not in {"DONE", "BLOCKED", "FAILED", "UNKNOWN", "CANCELLED"}:
        raise ValueError("invalid late receipt state")
    if evidence["late_terminal_receipt_observed"] is not True:
        raise ValueError("late receipt observation must be true")
    if evidence["replay_disposition"] != "PERMANENT_NO_OP":
        raise ValueError("late receipt must permanently fence replay")
    if evidence["run_completion_state"] != "TERMINAL_DURABLE":
        raise ValueError("reconciliation must mark durable terminal completion")
    if evidence["write_ambiguity"] not in {True, False, None}:
        raise ValueError("invalid reconciliation write ambiguity")
    if evidence["external_action_state"] not in _EXTERNAL_ACTION_STATES:
        raise ValueError("invalid reconciliation external action state")
    for field in ("task_submitted", "jules_task_started", "model_started"):
        if evidence[field] not in _TRI_STATES:
            raise ValueError(f"invalid reconciliation {field}")
    if not isinstance(evidence["prior_evidence_refs"], list):
        raise ValueError("prior_evidence_refs must be a list")
    if evidence["successor_already_issued"] is True and not evidence["successor_command_id"]:
        raise ValueError("successor command id required")
    if evidence["successor_already_issued"] is False and evidence["successor_command_id"] is not None:
        raise ValueError("unexpected successor command id")
    _time(evidence["observed_at"], "observed_at")
    return evidence


def successor_issue_gate(
    previous_command: dict[str, Any],
    previous_state: dict[str, Any],
    terminal_receipt: dict[str, Any] | None,
    *,
    successor_command: dict[str, Any],
    write_ambiguity: bool | None,
    external_action_state: str,
    task_submitted: bool | str,
    jules_task_started: bool | str,
    model_started: bool | str,
    now: datetime | None = None,
) -> SuccessorGateDecision:
    """Fail closed before creating/dispatching a replacement logical command."""
    validate_command(previous_command)
    validate_state(previous_state)
    validate_command(successor_command)
    at = now or datetime.now(timezone.utc)
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("successor gate time must include timezone")

    if terminal_receipt is None:
        return SuccessorGateDecision(
            SuccessorGateState.DEFERRED,
            "terminal receipt absent; old event-triggered run completion remains uncertain",
        )
    _match_receipt(previous_command, terminal_receipt)

    completion = durable_run_completion_state(
        previous_command, previous_state, terminal_receipt
    )
    if completion != "TERMINAL_DURABLE":
        return SuccessorGateDecision(
            SuccessorGateState.DEFERRED,
            "terminal receipt exists but mutable state is not durably reconciled",
        )

    if write_ambiguity is not False:
        return SuccessorGateDecision(
            SuccessorGateState.DEFERRED,
            "write ambiguity is not proven false",
        )
    if external_action_state not in _EXTERNAL_ACTION_STATES:
        raise ValueError("invalid external_action_state")
    if external_action_state == "UNKNOWN":
        return SuccessorGateDecision(
            SuccessorGateState.DEFERRED,
            "external action state is UNKNOWN",
        )
    if external_action_state == "OCCURRED":
        return SuccessorGateDecision(
            SuccessorGateState.BLOCKED,
            "old logical action already produced an external side effect",
        )

    for value, field in (
        (task_submitted, "task_submitted"),
        (jules_task_started, "jules_task_started"),
        (model_started, "model_started"),
    ):
        if value not in _TRI_STATES:
            raise ValueError(f"invalid {field}")
        if value == "UNKNOWN":
            return SuccessorGateDecision(
                SuccessorGateState.DEFERRED, f"{field} is UNKNOWN"
            )
        if value is True:
            return SuccessorGateDecision(
                SuccessorGateState.BLOCKED, f"{field} is true"
            )

    if successor_command["command_id"] == previous_command["command_id"]:
        return SuccessorGateDecision(
            SuccessorGateState.BLOCKED, "successor command_id must be fresh"
        )
    if successor_command["correlation_id"] == previous_command["correlation_id"]:
        return SuccessorGateDecision(
            SuccessorGateState.BLOCKED, "successor correlation_id must be fresh"
        )
    if "generation" in previous_command and "generation" in successor_command:
        if successor_command["generation"] <= previous_command["generation"]:
            return SuccessorGateDecision(
                SuccessorGateState.BLOCKED, "successor generation must advance"
            )
    if successor_command.get("retry") != 0:
        return SuccessorGateDecision(
            SuccessorGateState.BLOCKED, "successor retry must remain zero"
        )
    expires_at = successor_command.get("expires_at")
    if expires_at is not None and _time(expires_at, "successor expires_at") <= at:
        return SuccessorGateDecision(
            SuccessorGateState.BLOCKED, "successor expiry is not in the future"
        )
    return SuccessorGateDecision(
        SuccessorGateState.ALLOW_NEW_SUCCESSOR,
        "old run is durably terminal, replay-fenced, and side effects are proven absent",
    )
