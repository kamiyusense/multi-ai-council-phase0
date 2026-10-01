import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .blue_jules_result_event import EventClassificationResult, EventDecision


_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class CarrierSnapshot:
    protocol_version: Any
    lane: Any
    command_prefix: Any
    worker_generation: Any


@dataclass(frozen=True)
class TargetSnapshot:
    target_repository: Any
    target_pr: Any
    target_branch: Any
    expected_target_head: Any
    current_target_head: Any


@dataclass(frozen=True)
class PrepareResult:
    status: str
    command_id: str | None = None
    review_body: str | None = None


def _unknown() -> PrepareResult:
    return PrepareResult("UNKNOWN")


def _no_op(command_id: str | None = None) -> PrepareResult:
    return PrepareResult("NO_OP", command_id=command_id)


def _stale(command_id: str | None = None) -> PrepareResult:
    return PrepareResult("STALE", command_id=command_id)


def prepare_blue_work_wake(
    classification: EventClassificationResult,
    carrier: CarrierSnapshot,
    target: TargetSnapshot,
    existing_command_ids: Iterable[str],
    expires_at: Any,
    now: datetime,
) -> PrepareResult:
    if not isinstance(classification, EventClassificationResult):
        return _unknown()

    if classification.decision == EventDecision.UNKNOWN:
        return _unknown()

    if classification.decision == EventDecision.IGNORE:
        return _no_op(classification.command_id)

    # Carrier validation
    if not isinstance(carrier, CarrierSnapshot):
        return _unknown()
    if carrier.protocol_version != 1:
        return _unknown()
    if carrier.lane != "blue":
        return _unknown()
    if carrier.command_prefix != "[CW_BLUE_V1]":
        return _unknown()
    if (
        isinstance(carrier.worker_generation, bool)
        or not isinstance(carrier.worker_generation, int)
        or carrier.worker_generation <= 0
    ):
        return _unknown()

    # Target validation
    if not isinstance(target, TargetSnapshot):
        return _unknown()
    if target.target_repository != "kamiyusense/multi-ai-council-phase0":
        return _unknown()
    if (
        isinstance(target.target_pr, bool)
        or not isinstance(target.target_pr, int)
        or target.target_pr <= 0
    ):
        return _unknown()
    if not isinstance(target.target_branch, str) or not target.target_branch:
        return _unknown()
    if target.target_branch in {"main", "master"}:
        return _unknown()
    if not isinstance(target.expected_target_head, str) or not _SHA1_RE.fullmatch(target.expected_target_head):
        return _unknown()
    if not isinstance(target.current_target_head, str) or not _SHA1_RE.fullmatch(target.current_target_head):
        return _unknown()

    # Identity validation
    if not isinstance(classification.command_id, str):
        return _unknown()
    expected_command_id = f"blue-jules-result-pr{target.target_pr}-{target.expected_target_head}"
    if classification.command_id != expected_command_id:
        return _unknown()

    # Validate existing command IDs
    if not isinstance(existing_command_ids, (list, tuple, set)):
        return _unknown()
    try:
        existing = tuple(existing_command_ids)
    except Exception:
        return _unknown()
    if any(not isinstance(item, str) for item in existing):
        return _unknown()

    if classification.command_id in existing:
        return _no_op(command_id=classification.command_id)

    if target.current_target_head != target.expected_target_head:
        return _stale(command_id=classification.command_id)

    # Expiry validation
    if not isinstance(expires_at, str) or not expires_at:
        return _unknown()
    try:
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return _unknown()
    if expires_dt.tzinfo is None or expires_dt.utcoffset() is None:
        return _unknown()

    if not isinstance(now, datetime):
        return _unknown()
    if now.tzinfo is None or now.utcoffset() is None:
        return _unknown()

    # Normalize to UTC for strict comparison
    expires_dt_utc = expires_dt.astimezone(timezone.utc)
    now_utc = now.astimezone(timezone.utc)

    if expires_dt_utc <= now_utc:
        return _unknown()

    payload = {
        "protocol_version": 1,
        "command_id": classification.command_id,
        "worker_generation": carrier.worker_generation,
        "target_repository": target.target_repository,
        "target_pr": target.target_pr,
        "target_branch": target.target_branch,
        "expected_target_head": target.expected_target_head,
        "expires_at": expires_at,
        "task": "fresh-read GitHub; verify exact J-BLUE claim/command/session/result lineage and current result head; independently inspect paths/semantics/negative tests/test evidence; return PASS/FAIL/BLOCKED/UNKNOWN plus one bounded next-task proposal; perform no target write and do not dispatch Jules.",
        "allowed_paths": [],
        "verification": [
            "fresh result PR/branch/head readback",
            "durable J-BLUE lineage verification",
            "independent diff/test evidence inspection",
            "confirmation no target write/Jules dispatch/live provider execution occurred",
        ],
        "live_provider_or_model_allowed": False,
        "retry": 0,
        "fallback": "disabled",
    }

    # Strict JSON formatting: deterministic object with exact keys
    # `json.dumps` with sort_keys=False because keys order matters? Let's use standard dumps.
    # Actually, the instructions say "one deterministic valid JSON object with exactly these keys:".
    # And "Identical inputs -> byte-identical body."
    # Let's ensure deterministic output.
    body_json = json.dumps(payload, indent=2)

    review_body = f"{carrier.command_prefix}\n{body_json}"

    return PrepareResult(
        "PREPARED",
        command_id=classification.command_id,
        review_body=review_body,
    )
