"""Append-only durable launch reservation for the first Jules round-trip.

A fresh reservation may authorize one launch in the same Work run. Any
reservation recovered by a later Work run is evidence that a launch may have
already happened and therefore never authorizes a second launch.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .jules_static import make_launch_attempt, validate_launch_attempt

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class JulesLaunchContent:
    path: str
    text: str
    sha: str


class JulesLaunchContentsClient(Protocol):
    def get(self, path: str, ref: str) -> JulesLaunchContent | None: ...
    def create(
        self, path: str, text: str, message: str, branch: str
    ) -> JulesLaunchContent: ...


def launch_attempt_path(loop_id: str, command_id: str) -> str:
    _safe(loop_id, "loop_id")
    _safe(command_id, "command_id")
    return f"jules_launch_attempts/{loop_id}/{command_id}.json"


class DurableJulesLaunchBackend:
    def __init__(
        self,
        client: JulesLaunchContentsClient,
        *,
        branch: str,
        ref: str | None = None,
    ) -> None:
        self.client = client
        self.branch = branch
        self.ref = ref or branch

    def reserve(
        self,
        command: dict[str, Any],
        *,
        attempt_id: str,
        created_at: str,
    ) -> dict[str, Any]:
        record = make_launch_attempt(
            command, attempt_id=attempt_id, created_at=created_at
        )
        path = launch_attempt_path(command["loop_id"], command["command_id"])
        existing = self.client.get(path, self.branch)
        if existing is not None:
            recovered = self._decode(command, existing)
            return {
                "status": "BLOCKED",
                "reason": "durable Jules launch reservation already exists",
                "fresh_reservation": False,
                "attempt_record": recovered,
                "retry_count": 0,
                "fallback_used": False,
            }

        self.client.create(
            path,
            _canonical(record),
            f"reserve Jules launch {attempt_id}",
            self.branch,
        )
        verified = self.client.get(path, self.branch)
        if verified is None:
            return {
                "status": "UNKNOWN",
                "reason": "Jules launch reservation write readback unavailable",
                "fresh_reservation": False,
                "retry_count": 0,
                "fallback_used": False,
            }
        readback = self._decode(command, verified)
        if readback != record:
            return {
                "status": "UNKNOWN",
                "reason": "Jules launch reservation write readback mismatch",
                "fresh_reservation": False,
                "retry_count": 0,
                "fallback_used": False,
            }
        return {
            "status": "RESERVED",
            "reason": "Jules launch reservation written and verified",
            "fresh_reservation": True,
            "attempt_record": readback,
            "attempt_path": path,
            "retry_count": 0,
            "fallback_used": False,
        }

    def recover(self, command: dict[str, Any]) -> dict[str, Any]:
        path = launch_attempt_path(command["loop_id"], command["command_id"])
        content = self.client.get(path, self.ref)
        if content is None:
            return {
                "status": "UNKNOWN",
                "reason": "Jules launch reservation missing",
                "fresh_reservation": False,
                "retry_count": 0,
                "fallback_used": False,
            }
        try:
            record = self._decode(command, content)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return {
                "status": "UNKNOWN",
                "reason": str(exc),
                "fresh_reservation": False,
                "retry_count": 0,
                "fallback_used": False,
            }
        return {
            "status": "READ",
            "reason": "Jules launch reservation recovered; relaunch forbidden",
            "fresh_reservation": False,
            "attempt_record": record,
            "retry_count": 0,
            "fallback_used": False,
        }

    def _decode(
        self, command: dict[str, Any], content: JulesLaunchContent
    ) -> dict[str, Any]:
        expected_path = launch_attempt_path(
            command["loop_id"], command["command_id"]
        )
        if content.path != expected_path:
            raise ValueError("Jules launch reservation path identity mismatch")
        record = json.loads(content.text)
        if not isinstance(record, dict):
            raise ValueError("Jules launch reservation is not an object")
        validate_launch_attempt(command, record)
        return record


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _safe(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or not _COMPONENT.fullmatch(value)
    ):
        raise ValueError(f"unsafe Jules launch {field}")
