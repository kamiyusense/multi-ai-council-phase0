"""Create-only initializer for the first durable runtime state.

This boundary performs no provider/model action. It may only create the exact
PREPARED state for a previously absent durable loop on a non-default data branch.
An existing identical state is recovered by readback; any different existing
state blocks initialization. Ambiguous create results are resolved by one
readback and are never resent.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .github_backend import GitHubContentsClient
from .validator import validate_state

_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class RuntimeStateInitResult:
    status: str
    reason: str
    state: dict[str, Any] | None = None


def runtime_state_path(loop_id: str) -> str:
    if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
        raise ValueError("unsafe durable loop_id")
    return f"automation/command_bus/state/{loop_id}.json"


def build_initial_prepared_state(
    *,
    loop_id: str,
    expected_repo: str,
    expected_pr: int,
    expected_target_head: str,
    expires_at: str,
) -> dict[str, Any]:
    path = runtime_state_path(loop_id)
    del path
    if not isinstance(expected_repo, str) or "/" not in expected_repo:
        raise ValueError("invalid expected repository")
    if isinstance(expected_pr, bool) or not isinstance(expected_pr, int) or expected_pr < 1:
        raise ValueError("expected_pr must be a positive integer")
    if not isinstance(expected_target_head, str) or not _SHA.fullmatch(expected_target_head):
        raise ValueError("expected_target_head must be a full lowercase SHA")
    state = {
        "schema_version": 1,
        "loop_id": loop_id,
        "state": "PREPARED",
        "round": 0,
        "max_rounds": 1,
        "expires_at": expires_at,
        "stop_requested": False,
        "last_command_id": None,
        "last_receipt_id": None,
        "expected_target": {
            "repo": expected_repo,
            "pr": expected_pr,
            "head": expected_target_head,
        },
        "retry_policy": 0,
    }
    validate_state(state)
    return state


class RuntimeStateInitializer:
    def __init__(self, client: GitHubContentsClient, *, branch: str):
        if not isinstance(branch, str) or not branch or branch in {"main", "master"}:
            raise ValueError("runtime state initializer requires a non-default data branch")
        self.client = client
        self.branch = branch

    def create(self, state: dict[str, Any]) -> RuntimeStateInitResult:
        try:
            validate_state(state)
            if state.get("state") != "PREPARED":
                return RuntimeStateInitResult(
                    "BLOCKED",
                    "initial runtime state must be PREPARED",
                )
            if state.get("round") != 0:
                return RuntimeStateInitResult(
                    "BLOCKED",
                    "initial runtime state round must be zero",
                )
            loop_id = state.get("loop_id")
            path = runtime_state_path(loop_id)
            canonical = _canonical(state)

            existing = self.client.get(path, self.branch)
            if existing is not None:
                record = _decode(existing.text)
                validate_state(record)
                if _canonical(record) == canonical:
                    return RuntimeStateInitResult(
                        "RECOVERED",
                        "identical PREPARED runtime state already exists",
                        record,
                    )
                return RuntimeStateInitResult(
                    "BLOCKED",
                    "durable runtime state already exists with different content",
                    record,
                )

            try:
                self.client.create(
                    path,
                    canonical,
                    f"initialize durable runtime state {loop_id}",
                    self.branch,
                )
            except Exception:
                pass

            readback = self.client.get(path, self.branch)
            if readback is None:
                return RuntimeStateInitResult(
                    "UNKNOWN",
                    "runtime state create result is unverified; do not retry",
                )
            record = _decode(readback.text)
            validate_state(record)
            if _canonical(record) != canonical:
                return RuntimeStateInitResult(
                    "UNKNOWN",
                    "runtime state create readback mismatch; do not retry",
                    record,
                )
            return RuntimeStateInitResult(
                "ACCEPTED",
                "PREPARED runtime state created and verified",
                record,
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return RuntimeStateInitResult("UNKNOWN", str(exc))


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _decode(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("runtime state readback is not a JSON object")
    return value
