"""Fail-closed contract for bounded, prepare-only Relay static batches.

This module validates a future Work handoff.  It never edits PR #4 and never
starts Jules, a provider, or a live model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


ALLOWED_PATHS = (
    "src/relay/",
    "src/providers/",
    "tests/relay/",
    "docs/RELAY_STATIC_CHECKPOINT.md",
    "RELAY_JULES_HANDOFF.md",
)
PROHIBITED_PREFIXES = (
    ".git/", ".github/", "main/", "phase0-runs/", "secrets/",
    "settings/", "workflows/", "billing/", "auth/", "api-keys/",
)
TERMINAL_STATES = {"DONE", "BLOCKED", "FAILED", "UNKNOWN", "CANCELLED"}
BLOCKED_STATES = {"HALTED", "EXPIRED", "COMPLETE", "UNKNOWN", "FAILED"}


class GitHubContentsClient(Protocol):
    def read_pr_head(self, repository: str, pull_request: int) -> str: ...

    def write_target(self, path: str, content: str) -> None: ...


@dataclass(frozen=True)
class RelayBatchResult:
    status: str
    reason: str
    evidence: dict[str, Any]


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("expires_at must be an ISO timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _safe_path(path: Any) -> bool:
    if not isinstance(path, str) or not path or "\\" in path:
        return False
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    if path.startswith(PROHIBITED_PREFIXES):
        return False
    return path.startswith(ALLOWED_PATHS)


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
        "predecessor_receipt_id",
    }
    missing = sorted(required - command.keys())
    if missing:
        raise ValueError("missing command fields: " + ", ".join(missing))
    if command["schema_version"] != 1 or command["action"] != "APPLY_RELAY_STATIC_BATCH":
        raise ValueError("unsupported relay command")
    if command["target"] != "work" or command["retry"] != 0 or command["fallback"] != "disabled":
        raise ValueError("unsafe retry/fallback policy")
    if command["requires_live_model"] is not False:
        raise ValueError("live model execution is forbidden")
    if command["requires_github_write"] is not False:
        raise ValueError("target GitHub write is forbidden in prepare-only batch")
    if not isinstance(command["round"], int) or not 1 <= command["round"] <= 6:
        raise ValueError("round must be 1..6")
    if command["expected_target_head"] != current_target_head:
        raise ValueError("expected target head mismatch")
    if state.get("state") != "RUNNING" or state.get("stop_requested"):
        raise ValueError("state is stopped or not RUNNING")
    if state.get("round") != command["round"] - 1 or state.get("max_rounds") != 6:
        raise ValueError("round predecessor or max6 mismatch")
    if _parse_time(command["expires_at"]) <= (now or datetime.now(timezone.utc)):
        raise ValueError("command expired")
    if terminal_receipt is not None and terminal_receipt.get("state") in TERMINAL_STATES:
        raise ValueError("terminal receipt replay")
    if duplicate_command:
        raise ValueError("duplicate command")
    if not predecessor_exists or not command["predecessor_receipt_id"]:
        raise ValueError("missing predecessor")
    if not isinstance(command["allowed_paths"], list) or not command["allowed_paths"]:
        raise ValueError("allowed_paths must be non-empty")
    if any(not _safe_path(path) for path in command["allowed_paths"]):
        raise ValueError("path outside allowed scope")
    if not isinstance(command["prohibited_paths"], list) or any(
        not isinstance(path, str) or not path for path in command["prohibited_paths"]
    ):
        raise ValueError("invalid prohibited_paths")
    if any(path.startswith(PROHIBITED_PREFIXES) is False for path in command["prohibited_paths"]):
        raise ValueError("prohibited scope is incomplete")
    if not isinstance(command["test_commands"], list) or not command["test_commands"]:
        raise ValueError("test_commands must be non-empty")
    if not isinstance(command["objective"], str) or not command["objective"]:
        raise ValueError("objective is required")


def prepare_relay_batch(
    command: dict[str, Any], *, client: GitHubContentsClient,
    repository: str, target_pr: int, state: dict[str, Any],
    predecessor_exists: bool = True, now: datetime | None = None,
    terminal_receipt: dict[str, Any] | None = None,
    duplicate_command: bool = False,
) -> RelayBatchResult:
    try:
        current_head = client.read_pr_head(repository, target_pr)
        validate_relay_command(
            command, current_target_head=current_head, state=state,
            terminal_receipt=terminal_receipt, predecessor_exists=predecessor_exists,
            duplicate_command=duplicate_command, now=now,
        )
        if command["expected_repo"] != repository or command["expected_pr"] != target_pr:
            raise ValueError("wrong target repository or PR")
    except (ValueError, TypeError, KeyError) as exc:
        return RelayBatchResult("BLOCKED", str(exc), {
            "target_pr_modified": False, "model_executed": False,
            "jules_started": False, "provider_started": False,
            "retry_count": 0, "fallback_used": False,
        })
    return RelayBatchResult("PREPARED", "static batch validated", {
        "target_head": current_head, "allowed_paths": command["allowed_paths"],
        "test_commands": command["test_commands"], "target_pr_modified": False,
        "model_executed": False, "jules_started": False,
        "provider_started": False, "retry_count": 0, "fallback_used": False,
    })
