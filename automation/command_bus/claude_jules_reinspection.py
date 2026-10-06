"""Append-only same-head reinspection history.

The legacy inspection is never overwritten.  A same-head reinspection is
permitted only while the effective inspection is UNKNOWN/INVESTIGATE, and
each new attempt binds the previous inspection digest.  PASS/FAIL records are
terminal for this path, so this cannot be used to bypass a substantive review.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .claude_jules_dispatch import EVIDENCE_ROOT, canonical_json, sha256_of
from .claude_jules_inspection import validate_inspection_record

PROFILE = "CLAUDE_AUTO_JULES_REINSPECTION_V1"
_ROOT = f"{EVIDENCE_ROOT}/claude-auto-reinspections"
_SAFE_COMMAND = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_KEYS = {
    "schema_version", "profile", "command_id", "candidate_head", "attempt",
    "previous_inspection_sha256", "inspection", "reinspection_sha256",
}


def reinspection_path(command_id: str, candidate_head: str, attempt: int) -> str:
    if not _SAFE_COMMAND.fullmatch(command_id or "") or not _SHA40.fullmatch(candidate_head or ""):
        raise ValueError("unsafe reinspection identity")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1 or attempt > 100:
        raise ValueError("reinspection attempt must be 1..100")
    return f"{_ROOT}/{command_id}/{candidate_head}/{attempt:03d}.json"


def validate_reinspection_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _KEYS:
        raise ValueError("reinspection record keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != PROFILE:
        raise ValueError("unsupported reinspection record")
    reinspection_path(record["command_id"], record["candidate_head"], record["attempt"])
    inspection = validate_inspection_record(record["inspection"])
    if inspection["command_id"] != record["command_id"] or inspection["candidate_head"] != record["candidate_head"]:
        raise ValueError("reinspection inner inspection identity mismatch")
    previous = record["previous_inspection_sha256"]
    if not isinstance(previous, str) or not re.fullmatch(r"[0-9a-f]{64}", previous):
        raise ValueError("previous inspection digest invalid")
    unsigned = {k: v for k, v in record.items() if k != "reinspection_sha256"}
    if record["reinspection_sha256"] != sha256_of(unsigned):
        raise ValueError("reinspection digest mismatch")
    return record


class ReinspectionStore:
    def __init__(self, client: Any, *, data_branch: str):
        self.client, self.branch = client, data_branch

    def _history(self, base: dict[str, Any]) -> list[dict[str, Any]]:
        base = validate_inspection_record(base)
        prefix = f"{_ROOT}/{base['command_id']}/{base['candidate_head']}/"
        wrappers = []
        for content in self.client.list(prefix, self.branch):
            wrapper = validate_reinspection_record(json.loads(content.text))
            if content.path != reinspection_path(
                wrapper["command_id"], wrapper["candidate_head"], wrapper["attempt"]
            ):
                raise ValueError("reinspection path mismatch")
            wrappers.append(wrapper)
        wrappers.sort(key=lambda r: r["attempt"])
        previous = base["inspection_sha256"]
        for expected, wrapper in enumerate(wrappers, 1):
            if wrapper["attempt"] != expected:
                raise ValueError("reinspection attempts are not contiguous")
            if wrapper["previous_inspection_sha256"] != previous:
                raise ValueError("reinspection history chain mismatch")
            previous = wrapper["inspection"]["inspection_sha256"]
        return wrappers

    def effective(self, base: dict[str, Any]) -> dict[str, Any]:
        history = self._history(base)
        return history[-1]["inspection"] if history else validate_inspection_record(base)

    def all_versions(self, base: dict[str, Any]) -> list[dict[str, Any]]:
        return [validate_inspection_record(base), *[r["inspection"] for r in self._history(base)]]

    def persist(self, *, base: dict[str, Any], inspection: dict[str, Any]) -> str:
        base = validate_inspection_record(base)
        inspection = validate_inspection_record(inspection)
        history = self._history(base)
        previous = history[-1]["inspection"] if history else base
        if previous["verdict"] != "UNKNOWN" or previous["decision"] != "INVESTIGATE":
            return "BLOCKED"
        if (inspection["command_id"], inspection["candidate_head"], inspection["intent_sha256"]) != (
            base["command_id"], base["candidate_head"], base["intent_sha256"]
        ):
            return "BLOCKED"
        attempt = len(history) + 1
        wrapper = {
            "schema_version": 1,
            "profile": PROFILE,
            "command_id": base["command_id"],
            "candidate_head": base["candidate_head"],
            "attempt": attempt,
            "previous_inspection_sha256": previous["inspection_sha256"],
            "inspection": inspection,
        }
        wrapper["reinspection_sha256"] = sha256_of(wrapper)
        validate_reinspection_record(wrapper)
        path = reinspection_path(base["command_id"], base["candidate_head"], attempt)
        existing = self.client.get(path, self.branch)
        if existing is not None:
            try:
                return "RECOVERED" if json.loads(existing.text) == wrapper else "COLLISION"
            except json.JSONDecodeError:
                return "COLLISION"
        try:
            self.client.create(path, canonical_json(wrapper), f"Claude AUTO reinspection {attempt}", self.branch)
        except Exception:
            pass
        readback = self.client.get(path, self.branch)
        if readback is None:
            return "UNKNOWN"
        try:
            return "CREATED" if json.loads(readback.text) == wrapper else "COLLISION"
        except json.JSONDecodeError:
            return "COLLISION"

    def extend_all(self, base_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for base in base_records:
            records.extend(self.all_versions(base))
        return records
