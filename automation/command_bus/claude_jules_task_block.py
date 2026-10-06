"""Durable task-local blocker records for the autonomous development loop.

A task block is not a campaign stop.  It records that the controller exhausted
the safe corrective path for one task family.  The roadmap may continue with
independent READY work; only when no safe independent task remains does the
campaign return HUMAN_REQUIRED.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .claude_jules_dispatch import EVIDENCE_ROOT, canonical_json, sha256_of
from .claude_jules_recovery import TASK_BLOCKED

BLOCK_PROFILE = "CLAUDE_AUTO_TASK_BLOCK_V1"
_TASK = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_COMMAND = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")

_KEYS = {
    "schema_version", "profile", "origin_loop_id", "task_id", "task_family",
    "command_id", "origin_round", "inspection_sha256", "classification",
    "reason", "blocked_at", "record_sha256",
}


@dataclass(frozen=True)
class TaskBlockResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


def task_family(task_id: str) -> str:
    if not _TASK.fullmatch(task_id or ""):
        raise ValueError("unsafe task id")
    return re.sub(r"-fix[0-9]+$", "", task_id)


def block_path(origin_loop_id: str, task_family_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", origin_loop_id or ""):
        raise ValueError("unsafe origin loop id")
    if not _TASK.fullmatch(task_family_id or "") or task_family(task_family_id) != task_family_id:
        raise ValueError("unsafe task family")
    return f"{EVIDENCE_ROOT}/claude-auto-task-blocks/{origin_loop_id}/{task_family_id}.json"


def validate_task_block(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _KEYS:
        raise ValueError("task block keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != BLOCK_PROFILE:
        raise ValueError("unsupported task block record")
    family = task_family(record["task_id"])
    if record["task_family"] != family:
        raise ValueError("task block family mismatch")
    block_path(record["origin_loop_id"], family)
    if not _COMMAND.fullmatch(record["command_id"] or ""):
        raise ValueError("unsafe task block command id")
    if isinstance(record["origin_round"], bool) or not isinstance(record["origin_round"], int) or record["origin_round"] < 1:
        raise ValueError("invalid task block round")
    if not _SHA64.fullmatch(record["inspection_sha256"] or ""):
        raise ValueError("invalid task block inspection digest")
    if record["classification"] != TASK_BLOCKED:
        raise ValueError("task block classification mismatch")
    if not isinstance(record["reason"], str) or not record["reason"].strip():
        raise ValueError("task block reason missing")
    if not isinstance(record["blocked_at"], str) or not record["blocked_at"].strip():
        raise ValueError("task block time missing")
    expected = sha256_of({k: v for k, v in record.items() if k != "record_sha256"})
    if record["record_sha256"] != expected:
        raise ValueError("task block digest mismatch")
    return record


class TaskBlockStore:
    """One immutable block per campaign/task family, resolved by readback."""

    def __init__(self, client: Any, *, data_branch: str, origin_loop_id: str):
        self.client, self.branch, self.origin_loop_id = client, data_branch, origin_loop_id

    def list_all(self) -> list[dict[str, Any]]:
        prefix = f"{EVIDENCE_ROOT}/claude-auto-task-blocks/{self.origin_loop_id}/"
        records = []
        for content in self.client.list(prefix, self.branch):
            record = validate_task_block(json.loads(content.text))
            if record["origin_loop_id"] != self.origin_loop_id:
                raise ValueError("task block origin mismatch")
            if content.path != block_path(self.origin_loop_id, record["task_family"]):
                raise ValueError("task block path mismatch")
            records.append(record)
        records.sort(key=lambda item: item["task_family"])
        if len({r["task_family"] for r in records}) != len(records):
            raise ValueError("duplicate task block family")
        return records

    def persist(self, *, intent: dict[str, Any], inspection: dict[str, Any], blocked_at: str) -> TaskBlockResult:
        request = intent["carrier_request"]
        task_id = intent["task_id"]
        family = task_family(task_id)
        if inspection.get("command_id") != request.get("command_id"):
            return TaskBlockResult("UNKNOWN", "inspection command does not bind task block")
        if inspection.get("intent_sha256") != intent.get("intent_sha256"):
            return TaskBlockResult("UNKNOWN", "inspection intent does not bind task block")
        if inspection.get("decision") != "STOP_HUMAN":
            return TaskBlockResult("BLOCKED", "only exhausted STOP_HUMAN task may be isolated")
        record = {
            "schema_version": 1,
            "profile": BLOCK_PROFILE,
            "origin_loop_id": self.origin_loop_id,
            "task_id": task_id,
            "task_family": family,
            "command_id": request["command_id"],
            "origin_round": intent["origin_round"],
            "inspection_sha256": inspection["inspection_sha256"],
            "classification": TASK_BLOCKED,
            "reason": inspection["reason"],
            "blocked_at": blocked_at,
        }
        record["record_sha256"] = sha256_of(record)
        validate_task_block(record)
        path = block_path(self.origin_loop_id, family)

        existing = self.client.get(path, self.branch)
        if existing is not None:
            try:
                stored = validate_task_block(json.loads(existing.text))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return TaskBlockResult("UNKNOWN", f"existing task block invalid: {exc}")
            if stored["origin_loop_id"] != self.origin_loop_id or stored["task_family"] != family:
                return TaskBlockResult("UNKNOWN", "task block identity mismatch")
            # A first terminal block is authoritative. Fresh controllers recover
            # it even if they are currently looking at a later superseded
            # corrective intent from the same task family.
            return TaskBlockResult("RECOVERED", "task family already isolated", stored)

        try:
            self.client.create(path, canonical_json(record), f"Claude AUTO task block {family}", self.branch)
        except Exception:
            pass  # ambiguous create: never resend, read back instead

        readback = self.client.get(path, self.branch)
        if readback is None:
            return TaskBlockResult("UNKNOWN", "task block write not verifiable")
        try:
            stored = validate_task_block(json.loads(readback.text))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return TaskBlockResult("UNKNOWN", f"task block readback invalid: {exc}")
        if stored != record:
            return TaskBlockResult("UNKNOWN", "task block readback mismatch")
        return TaskBlockResult("CREATED", "task family isolated", stored)
