"""Append-only bounded recovery records for autonomous-loop evidence reads.

This module never re-sends a mutating provider/GitHub action and never alters
the inspection schema.  It records only safe evidence reacquisition attempts
that happen *before* an inspection is persisted, so a temporary test/read
failure does not become an immutable same-head UNKNOWN by accident.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .claude_jules_dispatch import EVIDENCE_ROOT, canonical_json, sha256_of

RECOVERY_PROFILE = "CLAUDE_AUTO_EVIDENCE_RECOVERY_V1"
TRANSIENT_UNKNOWN = "TRANSIENT_UNKNOWN"
RECOVERABLE_UNKNOWN = "RECOVERABLE_UNKNOWN"
TASK_BLOCKED = "TASK_BLOCKED"
HARD_UNKNOWN = "HARD_UNKNOWN"
UNCERTAINTY_CLASSES = {
    TRANSIENT_UNKNOWN, RECOVERABLE_UNKNOWN, TASK_BLOCKED, HARD_UNKNOWN,
}
_EVIDENCE_FIELDS = {"compare", "candidate_tree", "test_evidence", "test_sources", "review"}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_COMMAND = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class RecoveryResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


def recovery_path(command_id: str, candidate_head: str, attempt: int) -> str:
    if not _COMMAND.fullmatch(command_id or ""):
        raise ValueError("unsafe recovery command id")
    if not _SHA40.fullmatch(candidate_head or ""):
        raise ValueError("invalid recovery candidate head")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 20:
        raise ValueError("invalid recovery attempt")
    return (
        f"{EVIDENCE_ROOT}/claude-auto-evidence-recovery/"
        f"{command_id}/{candidate_head}/attempt-{attempt:02d}.json"
    )


_KEYS = {
    "schema_version", "profile", "command_id", "candidate_head", "attempt",
    "classification", "missing", "reason", "observed_at", "retry_limit",
    "retry_scope", "mutating_action_retried", "record_sha256",
}


def validate_recovery_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _KEYS:
        raise ValueError("recovery record keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != RECOVERY_PROFILE:
        raise ValueError("unsupported recovery record")
    if record["classification"] != TRANSIENT_UNKNOWN:
        raise ValueError("recovery record is not transient")
    recovery_path(record["command_id"], record["candidate_head"], record["attempt"])
    limit = record["retry_limit"]
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise ValueError("invalid recovery retry_limit")
    if record["attempt"] > limit:
        raise ValueError("recovery attempt exceeds retry_limit")
    missing = record["missing"]
    if (not isinstance(missing, list) or not missing
            or any(item not in _EVIDENCE_FIELDS for item in missing)
            or len(set(missing)) != len(missing)):
        raise ValueError("invalid recovery missing evidence list")
    if not isinstance(record["reason"], str) or not record["reason"].strip():
        raise ValueError("recovery reason missing")
    if not isinstance(record["observed_at"], str) or not record["observed_at"].strip():
        raise ValueError("recovery observed_at missing")
    if record["retry_scope"] != "READ_TEST_EVIDENCE_ONLY":
        raise ValueError("unsafe recovery scope")
    if record["mutating_action_retried"] is not False:
        raise ValueError("recovery retried a mutating action")
    expected = sha256_of({k: v for k, v in record.items() if k != "record_sha256"})
    if record["record_sha256"] != expected:
        raise ValueError("recovery record digest mismatch")
    return record


class EvidenceRecoveryStore:
    """Create-only evidence retry ledger; ambiguous writes are resolved by readback."""

    def __init__(self, client: Any, *, data_branch: str):
        self.client, self.branch = client, data_branch

    def list_for(self, command_id: str, candidate_head: str) -> list[dict[str, Any]]:
        # Validate identity before it becomes part of a prefix.
        recovery_path(command_id, candidate_head, 1)
        prefix = (
            f"{EVIDENCE_ROOT}/claude-auto-evidence-recovery/"
            f"{command_id}/{candidate_head}/"
        )
        records: list[dict[str, Any]] = []
        for content in self.client.list(prefix, self.branch):
            record = validate_recovery_record(json.loads(content.text))
            if content.path != recovery_path(command_id, candidate_head, record["attempt"]):
                raise ValueError("recovery record path mismatch")
            if record["command_id"] != command_id or record["candidate_head"] != candidate_head:
                raise ValueError("recovery record identity mismatch")
            records.append(record)
        records.sort(key=lambda item: item["attempt"])
        if [r["attempt"] for r in records] != list(range(1, len(records) + 1)):
            raise ValueError("recovery attempt ledger has a gap or duplicate")
        return records

    def record_failure(
        self, *, command_id: str, candidate_head: str, missing: list[str],
        reason: str, observed_at: str, max_retries: int,
    ) -> RecoveryResult:
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 1 <= max_retries <= 20:
            raise ValueError("max_retries must be 1..20")
        prior = self.list_for(command_id, candidate_head)
        if len(prior) >= max_retries:
            return RecoveryResult(
                "EXHAUSTED",
                f"transient evidence retry budget exhausted ({len(prior)}/{max_retries})",
            )
        attempt = len(prior) + 1
        clean_missing = sorted(set(missing))
        record = {
            "schema_version": 1,
            "profile": RECOVERY_PROFILE,
            "command_id": command_id,
            "candidate_head": candidate_head,
            "attempt": attempt,
            "classification": TRANSIENT_UNKNOWN,
            "missing": clean_missing,
            "reason": reason,
            "observed_at": observed_at,
            "retry_limit": max_retries,
            "retry_scope": "READ_TEST_EVIDENCE_ONLY",
            "mutating_action_retried": False,
        }
        record["record_sha256"] = sha256_of(record)
        validate_recovery_record(record)
        path = recovery_path(command_id, candidate_head, attempt)

        existing = self.client.get(path, self.branch)
        if existing is not None:
            try:
                stored = validate_recovery_record(json.loads(existing.text))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return RecoveryResult("UNKNOWN", f"existing recovery record invalid: {exc}")
            return (
                RecoveryResult("RECOVERED", "identical recovery attempt already recorded", stored)
                if stored == record
                else RecoveryResult("UNKNOWN", "recovery attempt path collision")
            )

        try:
            self.client.create(
                path, canonical_json(record),
                f"Claude AUTO transient evidence recovery {attempt}", self.branch,
            )
        except Exception:
            pass  # Never resend an ambiguous create; readback decides.

        readback = self.client.get(path, self.branch)
        if readback is None:
            return RecoveryResult("UNKNOWN", "recovery attempt write not verifiable")
        try:
            stored = validate_recovery_record(json.loads(readback.text))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return RecoveryResult("UNKNOWN", f"recovery attempt readback invalid: {exc}")
        if stored != record:
            return RecoveryResult("UNKNOWN", "recovery attempt readback mismatch")
        return RecoveryResult("CREATED", "transient evidence retry recorded", stored)
