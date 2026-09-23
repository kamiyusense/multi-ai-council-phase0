from __future__ import annotations

from datetime import datetime
from typing import Any

STATES = {"PREPARED", "RUNNING", "WAITING_FOR_EVIDENCE", "WAITING_FOR_HUMAN_AUTH", "BLOCKED", "COMPLETE", "HALTED", "FAILED", "UNKNOWN", "EXPIRED"}
TERMINAL_RECEIPTS = {"DONE", "BLOCKED", "FAILED", "UNKNOWN", "CANCELLED"}
REQUIRED_COMMAND = {"schema_version", "command_id", "loop_id", "round", "correlation_id", "target", "action", "expected_repo", "expected_pr", "expected_target_head", "retry", "fallback", "requires_live_model", "requires_github_write"}
REQUIRED_STATE = {"schema_version", "loop_id", "state", "round", "max_rounds", "expires_at", "stop_requested", "last_command_id", "last_receipt_id", "expected_target", "retry_policy"}
REQUIRED_RECEIPT = {"schema_version", "receipt_id", "command_id", "loop_id", "correlation_id", "state", "executed_once", "retry_count", "fallback_used", "evidence_refs"}

def _required(obj: dict[str, Any], fields: set[str], name: str) -> None:
    missing = sorted(fields - obj.keys())
    if missing:
        raise ValueError(f"{name} missing fields: {', '.join(missing)}")

def validate_command(obj: dict[str, Any]) -> dict[str, Any]:
    _required(obj, REQUIRED_COMMAND, "command")
    if obj["schema_version"] != 1 or not obj["command_id"] or not obj["loop_id"] or not obj["correlation_id"]:
        raise ValueError("invalid command identity")
    if not isinstance(obj["round"], int) or obj["round"] < 1:
        raise ValueError("round must be a positive integer")
    if obj["target"] != "work" or obj["retry"] != 0 or obj["fallback"] != "disabled":
        raise ValueError("unsafe command policy")
    if not isinstance(obj["expected_pr"], int) or not isinstance(obj["expected_target_head"], str):
        raise ValueError("invalid expected GitHub target")
    return obj

def validate_state(obj: dict[str, Any]) -> dict[str, Any]:
    _required(obj, REQUIRED_STATE, "state")
    if obj["schema_version"] != 1 or obj["state"] not in STATES:
        raise ValueError("invalid state")
    if not isinstance(obj["round"], int) or not isinstance(obj["max_rounds"], int) or not 1 <= obj["max_rounds"] <= 6:
        raise ValueError("max_rounds must be between 1 and 6")
    if obj["round"] < 0 or obj["round"] > obj["max_rounds"]:
        raise ValueError("invalid round")
    if obj["retry_policy"] != 0:
        raise ValueError("retry policy must be zero")
    datetime.fromisoformat(obj["expires_at"].replace("Z", "+00:00"))
    return obj

def validate_receipt(obj: dict[str, Any]) -> dict[str, Any]:
    _required(obj, REQUIRED_RECEIPT, "receipt")
    if obj["schema_version"] != 1 or obj["state"] not in TERMINAL_RECEIPTS:
        raise ValueError("invalid terminal receipt")
    if obj["executed_once"] is not True or obj["retry_count"] != 0 or obj["fallback_used"] is not False:
        raise ValueError("unsafe receipt")
    return obj
