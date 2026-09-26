"""Fail-closed contract for bounded Relay static batches.

The module validates durable GitHub commands for either a PREPARE_ONLY batch or
an explicitly bounded STATIC_WRITE batch. It never starts Jules, a provider,
or a live model. Actual GitHub mutation remains an external Work responsibility
after this validator passes all gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


PREPARE_ACTION = "APPLY_RELAY_STATIC_BATCH"
EXECUTE_ACTION = "EXECUTE_RELAY_STATIC_BATCH"
REQUIRED_PROFILE = "RELAY_SAFETY_BATCH_V1"

ALLOWED_PATH_SPECS = frozenset({
    "src/relay/**",
    "src/providers/**",
    "tests/relay/**",
    "docs/RELAY_STATIC_CHECKPOINT.md",
    "RELAY_JULES_HANDOFF.md",
})
REQUIRED_PROHIBITED_PATHS = frozenset({
    "main/**",
    "phase0-runs/**",
    "secrets/**",
    ".github/**",
    "settings/**",
    "workflows/**",
    "billing/**",
    "auth/**",
    "api-keys/**",
})
REQUIRED_TEST_COMMANDS = (
    "PYTHONPATH=src python -m unittest discover -s tests -t . -v",
    "python -m compileall -q src tests",
    "git diff --check",
)
REQUIRED_PATH_POLICY = (
    {"path": "src/relay/**", "allowed_ops": ("ADD", "MODIFY")},
    {"path": "src/providers/**", "allowed_ops": ("ADD", "MODIFY")},
    {"path": "tests/relay/**", "allowed_ops": ("ADD", "MODIFY")},
    {"path": "docs/RELAY_STATIC_CHECKPOINT.md", "allowed_ops": ("MODIFY",)},
    {"path": "RELAY_JULES_HANDOFF.md", "allowed_ops": ("MODIFY",)},
)
TERMINAL_STATES = {"DONE", "BLOCKED", "FAILED", "UNKNOWN", "CANCELLED"}


class GitHubContentsClient(Protocol):
    def read_pr_head(self, repository: str, pull_request: int) -> str: ...


@dataclass(frozen=True)
class RelayBatchResult:
    status: str
    reason: str
    evidence: dict[str, Any]


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("expires_at must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("expires_at must include timezone")
    return parsed


def validate_relay_command(
    command: dict[str, Any], *, current_target_head: str,
    state: dict[str, Any], terminal_receipt: dict[str, Any] | None,
    now: datetime | None = None, predecessor_exists: bool = True,
    duplicate_command: bool = False,
) -> None:
    required = {
        "schema_version", "command_id", "loop_id", "round", "correlation_id",
        "target", "action", "expected_repo", "expected_pr",
        "expected_target_head", "allowed_paths", "prohibited_paths",
        "objective", "test_commands", "requires_live_model",
        "requires_github_write", "retry", "fallback", "expires_at",
        "predecessor_receipt_id", "execution_mode", "profile",
    }
    missing = sorted(required - command.keys())
    if missing:
        raise ValueError("missing command fields: " + ", ".join(missing))

    action = command["action"]
    if command["schema_version"] != 1 or action not in {PREPARE_ACTION, EXECUTE_ACTION}:
        raise ValueError("unsupported relay command")
    if command["profile"] != REQUIRED_PROFILE:
        raise ValueError("unsupported relay batch profile")
    if command["target"] != "work" or command["retry"] != 0 or command["fallback"] != "disabled":
        raise ValueError("unsafe retry/fallback policy")
    if command["requires_live_model"] is not False:
        raise ValueError("live model execution is forbidden")

    if action == PREPARE_ACTION:
        if command["execution_mode"] != "PREPARE_ONLY" or command["requires_github_write"] is not False:
            raise ValueError("prepare action must be non-writing")
    else:
        if command["execution_mode"] != "STATIC_WRITE" or command["requires_github_write"] is not True:
            raise ValueError("execute action must explicitly request bounded static write")
        expected_tree = command.get("expected_target_tree")
        if not isinstance(expected_tree, str) or not expected_tree:
            raise ValueError("execute action requires expected target tree")
        policy = command.get("path_policy")
        if not isinstance(policy, list):
            raise ValueError("execute action requires path policy")
        normalized = tuple(
            {
                "path": item.get("path"),
                "allowed_ops": tuple(item.get("allowed_ops", [])),
            }
            for item in policy
            if isinstance(item, dict)
        )
        if normalized != REQUIRED_PATH_POLICY:
            raise ValueError("execute action path policy mismatch")

    round_number = command["round"]
    loop_id = command["loop_id"]
    if not isinstance(round_number, int) or not 1 <= round_number <= 6:
        raise ValueError("round must be 1..6")
    if not isinstance(loop_id, str) or not loop_id:
        raise ValueError("loop_id is required")
    if command["command_id"] != f"{loop_id}-{round_number:06d}":
        raise ValueError("command_id correlation mismatch")
    if command["correlation_id"] != f"{loop_id}-round-{round_number}":
        raise ValueError("correlation mismatch")
    if command["expected_target_head"] != current_target_head:
        raise ValueError("expected target head mismatch")

    if state.get("state") != "RUNNING" or state.get("stop_requested"):
        raise ValueError("state is stopped or not RUNNING")
    if state.get("loop_id") != loop_id:
        raise ValueError("state loop mismatch")
    if state.get("round") != round_number - 1 or state.get("max_rounds") != 6:
        raise ValueError("round predecessor or max6 mismatch")
    state_expiry = state.get("expires_at")
    current_time = now or datetime.now(timezone.utc)
    if state_expiry is not None and _parse_time(state_expiry) <= current_time:
        raise ValueError("state expired")
    if _parse_time(command["expires_at"]) <= current_time:
        raise ValueError("command expired")

    if terminal_receipt is not None and terminal_receipt.get("state") in TERMINAL_STATES:
        raise ValueError("terminal receipt replay")
    if duplicate_command:
        raise ValueError("duplicate command")
    if not predecessor_exists or not command["predecessor_receipt_id"]:
        raise ValueError("missing predecessor")

    allowed_paths = command["allowed_paths"]
    if not isinstance(allowed_paths, list) or not allowed_paths:
        raise ValueError("allowed_paths must be non-empty")
    if len(allowed_paths) != len(set(allowed_paths)):
        raise ValueError("duplicate allowed path")
    if not set(allowed_paths).issubset(ALLOWED_PATH_SPECS):
        raise ValueError("path outside allowed scope")

    prohibited_paths = command["prohibited_paths"]
    if not isinstance(prohibited_paths, list) or any(
        not isinstance(path, str) or not path for path in prohibited_paths
    ):
        raise ValueError("invalid prohibited_paths")
    if not REQUIRED_PROHIBITED_PATHS.issubset(set(prohibited_paths)):
        raise ValueError("prohibited scope is incomplete")

    test_commands = command["test_commands"]
    if not isinstance(test_commands, list) or tuple(test_commands) != REQUIRED_TEST_COMMANDS:
        raise ValueError("test_commands must match the fixed allowlist")
    if not isinstance(command["objective"], str) or not command["objective"].strip():
        raise ValueError("objective is required")


def prepare_relay_batch(
    command: dict[str, Any], *, client: GitHubContentsClient,
    repository: str, target_pr: int, state: dict[str, Any],
    predecessor_exists: bool = True, now: datetime | None = None,
    terminal_receipt: dict[str, Any] | None = None,
    duplicate_command: bool = False,
) -> RelayBatchResult:
    try:
        if command.get("expected_repo") != repository or command.get("expected_pr") != target_pr:
            raise ValueError("wrong target repository or PR")
        current_head = client.read_pr_head(repository, target_pr)
        validate_relay_command(
            command, current_target_head=current_head, state=state,
            terminal_receipt=terminal_receipt, predecessor_exists=predecessor_exists,
            duplicate_command=duplicate_command, now=now,
        )
    except (ValueError, TypeError, KeyError) as exc:
        return RelayBatchResult("BLOCKED", str(exc), {
            "target_pr_modified": False, "model_executed": False,
            "jules_started": False, "provider_started": False,
            "retry_count": 0, "fallback_used": False,
        })
    return RelayBatchResult("PREPARED", "static batch validated", {
        "target_head": current_head,
        "target_tree": command.get("expected_target_tree"),
        "action": command["action"],
        "execution_mode": command["execution_mode"],
        "profile": command["profile"],
        "allowed_paths": command["allowed_paths"],
        "test_commands": command["test_commands"],
        "target_pr_modified": False,
        "model_executed": False,
        "jules_started": False,
        "provider_started": False,
        "retry_count": 0,
        "fallback_used": False,
    })
