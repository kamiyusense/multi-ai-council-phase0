"""Fail-closed contract for the first bounded Jules round-trip.

This module validates intent only. It never opens Jules, a browser, a model, or
an external service. The first live Jules launch is permitted only after an
append-only launch reservation has been durably written/read back by the Work
relay and all target/workspace gates pass.
"""
from __future__ import annotations

from datetime import datetime
from fnmatch import fnmatch
from typing import Any

PROFILE = "JULES_FRESH_STATIC_V1"
ACTION = "JULES_BOUNDED_STATIC_ROUNDTRIP"
LAUNCH_PROFILE = "JULES_LAUNCH_ATTEMPT_V1"
FIRST_TASK_PATH = "tests/relay/test_dispatcher.py"
FIXED_TESTS = (
    "PYTHONPATH=src python -m unittest discover -s tests -t . -v",
    "python -m compileall -q src tests",
    "git diff --check",
)


def validate_first_jules_command(command: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version", "command_id", "loop_id", "round", "correlation_id",
        "target", "action", "profile", "expected_repo", "expected_pr",
        "expected_target_head", "expected_target_tree",
        "workspace_integrity_profile", "fresh_session_required",
        "disposable_workspace_required", "reuse_existing_jules_task",
        "allowed_paths", "path_policy", "test_commands",
        "requires_live_model", "requires_github_write",
        "user_authorization", "retry", "fallback", "expires_at",
    }
    if not isinstance(command, dict) or not required <= command.keys():
        raise ValueError("incomplete first Jules command")
    if command["schema_version"] != 1:
        raise ValueError("unsupported Jules command schema")
    if command["action"] != ACTION or command["profile"] != PROFILE:
        raise ValueError("wrong Jules bounded-static profile")
    if command["target"] != "work":
        raise ValueError("Jules command target must be Work relay")
    if command["expected_repo"] != "kamiyusense/multi-ai-council-phase0":
        raise ValueError("wrong Jules target repository")
    if command["expected_pr"] != 4:
        raise ValueError("wrong Jules target PR")
    for key in (
        "command_id", "loop_id", "correlation_id",
        "expected_target_head", "expected_target_tree",
        "user_authorization",
    ):
        if not isinstance(command[key], str) or not command[key]:
            raise ValueError(f"invalid Jules command {key}")
    if command["expected_target_tree"] == "UNKNOWN":
        raise ValueError("Jules target tree must be concrete")
    if command["workspace_integrity_profile"] != "TREE_IDENTITY_V1":
        raise ValueError("Jules requires TREE_IDENTITY_V1")
    if command["fresh_session_required"] is not True:
        raise ValueError("fresh Jules session required")
    if command["disposable_workspace_required"] is not True:
        raise ValueError("disposable Jules workspace required")
    if command["reuse_existing_jules_task"] is not False:
        raise ValueError("old Jules task reuse is forbidden")
    if command["requires_live_model"] is not True:
        raise ValueError("live Jules invocation must be explicitly declared")
    if command["requires_github_write"] is not True:
        raise ValueError("first Jules round-trip must use durable GitHub write/readback")
    if command["retry"] != 0 or command["fallback"] != "disabled":
        raise ValueError("unsafe Jules retry/fallback policy")
    if command["user_authorization"] != "EXPLICIT_NEXT_BATCH_JULES_2026-09-23":
        raise ValueError("missing explicit Jules authorization identity")
    if command["allowed_paths"] != [FIRST_TASK_PATH]:
        raise ValueError("first Jules task must be exactly one test file")
    expected_policy = [{
        "path": FIRST_TASK_PATH,
        "allowed_ops": ["MODIFY"],
    }]
    if command["path_policy"] != expected_policy:
        raise ValueError("first Jules path/operation policy mismatch")
    if tuple(command["test_commands"]) != FIXED_TESTS:
        raise ValueError("first Jules fixed tests mismatch")
    if isinstance(command["round"], bool) or not isinstance(command["round"], int) or command["round"] != 1:
        raise ValueError("first Jules round must be 1")
    if command["correlation_id"] != f"{command['loop_id']}-round-1":
        raise ValueError("Jules correlation mismatch")
    expires = _time(command["expires_at"])
    if expires.utcoffset() is None:
        raise ValueError("Jules command expiry must be timezone-aware")
    return command


def make_launch_attempt(
    command: dict[str, Any], *, attempt_id: str, created_at: str
) -> dict[str, Any]:
    validate_first_jules_command(command)
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("Jules launch attempt id required")
    created = _time(created_at)
    if created.utcoffset() is None:
        raise ValueError("Jules launch timestamp must be timezone-aware")
    return {
        "schema_version": 1,
        "launch_profile": LAUNCH_PROFILE,
        "attempt_id": attempt_id,
        "command_id": command["command_id"],
        "loop_id": command["loop_id"],
        "round": command["round"],
        "correlation_id": command["correlation_id"],
        "expected_target_head": command["expected_target_head"],
        "expected_target_tree": command["expected_target_tree"],
        "state": "RESERVED",
        "fresh_session_required": True,
        "disposable_workspace_required": True,
        "workspace_integrity_profile": "TREE_IDENTITY_V1",
        "created_at": created_at,
        "retry": 0,
        "fallback": "disabled",
    }


def validate_launch_attempt(
    command: dict[str, Any], attempt: dict[str, Any]
) -> None:
    expected = make_launch_attempt(
        command,
        attempt_id=attempt.get("attempt_id"),
        created_at=attempt.get("created_at"),
    )
    if attempt != expected:
        raise ValueError("Jules launch attempt does not match command")


def validate_jules_diff(changed: list[dict[str, Any]]) -> None:
    if not isinstance(changed, list) or len(changed) != 1:
        raise ValueError("first Jules task must change exactly one file")
    item = changed[0]
    if item.get("path") != FIRST_TASK_PATH or item.get("operation") != "MODIFY":
        raise ValueError("first Jules task changed a forbidden path or operation")


def first_task_objective() -> str:
    return (
        "Add one unittest regression proving abort_signal={'aborted': True} "
        "blocks before slot reservation and before provider dispatch. "
        "Do not modify implementation code."
    )


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
