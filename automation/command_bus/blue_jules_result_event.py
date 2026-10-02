from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


from .cloud_work_lanes import lane_identity

EXPECTED_REPOSITORY = "kamiyusense/multi-ai-council-phase0"
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class EventDecision(StrEnum):
    IGNORE = "IGNORE"
    WAKE = "WAKE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EventLineage:
    source_command_id: str
    work_branch: str
    expected_target_head: str
    expected_repository: str


@dataclass(frozen=True)
class EventClassificationResult:
    decision: EventDecision
    command_id: str | None = None
    reason: str | None = None


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA1_RE.fullmatch(value) is not None


def _unknown(reason: str) -> EventClassificationResult:
    return EventClassificationResult(EventDecision.UNKNOWN, reason=reason)


def classify_jules_result_event(
    event_payload: Any,
    explicit_lineage: Any,
    seen_command_ids: Iterable[str] | None,
    *, lane: str = "blue",
) -> EventClassificationResult:
    """Classify one GitHub PR event without I/O or mutation."""

    try:
        lane_identity(lane)
    except (ValueError, TypeError):
        return _unknown("unknown lane")
    if not isinstance(event_payload, dict):
        return _unknown("malformed top-level payload")

    action = event_payload.get("action")
    if not isinstance(action, str):
        return _unknown("missing or malformed action")
    if action not in {"opened", "synchronize"}:
        return EventClassificationResult(EventDecision.IGNORE, reason="unsupported action")

    repository = event_payload.get("repository")
    if not isinstance(repository, dict):
        return _unknown("malformed repository")
    repo_name = repository.get("full_name")
    if not isinstance(repo_name, str) or not repo_name:
        return _unknown("missing or malformed repository identity")
    if repo_name != EXPECTED_REPOSITORY:
        return EventClassificationResult(EventDecision.IGNORE, reason="wrong repository")

    if not isinstance(explicit_lineage, EventLineage):
        return _unknown("missing or malformed lineage")
    if (
        not isinstance(explicit_lineage.source_command_id, str)
        or not explicit_lineage.source_command_id
    ):
        return _unknown("missing or malformed source_command_id")
    if not isinstance(explicit_lineage.work_branch, str) or not explicit_lineage.work_branch:
        return _unknown("missing or malformed work_branch")
    if not _valid_sha(explicit_lineage.expected_target_head):
        return _unknown("missing or malformed expected_target_head")
    if explicit_lineage.expected_repository != EXPECTED_REPOSITORY:
        return _unknown("lineage repository mismatch")

    pull_request = event_payload.get("pull_request")
    if not isinstance(pull_request, dict):
        return _unknown("malformed pull_request")

    base = pull_request.get("base")
    if not isinstance(base, dict):
        return _unknown("malformed base")
    base_ref = base.get("ref")
    if not isinstance(base_ref, str) or not base_ref:
        return _unknown("missing or malformed base ref")
    if base_ref != explicit_lineage.work_branch:
        return EventClassificationResult(EventDecision.IGNORE, reason="unrelated base branch")

    base_sha = base.get("sha")
    if not _valid_sha(base_sha):
        return _unknown("missing or malformed base SHA")
    if base_sha != explicit_lineage.expected_target_head:
        return _unknown("base SHA lineage mismatch")

    pr_number = pull_request.get("number")
    if (
        isinstance(pr_number, bool)
        or not isinstance(pr_number, int)
        or pr_number <= 0
    ):
        return _unknown("missing or malformed PR number")

    head = pull_request.get("head")
    if not isinstance(head, dict):
        return _unknown("malformed head")
    head_sha = head.get("sha")
    if not _valid_sha(head_sha):
        return _unknown("missing or malformed head SHA")

    if seen_command_ids is None or isinstance(seen_command_ids, (str, bytes)):
        return _unknown("missing or malformed seen command identities")
    try:
        seen = tuple(seen_command_ids)
    except TypeError:
        return _unknown("missing or malformed seen command identities")
    if any(not isinstance(item, str) for item in seen):
        return _unknown("missing or malformed seen command identities")

    command_id = f"{lane}-jules-result-pr{pr_number}-{head_sha}"
    if command_id in seen:
        return EventClassificationResult(
            EventDecision.IGNORE,
            command_id=command_id,
            reason="duplicate command identity",
        )

    return EventClassificationResult(
        EventDecision.WAKE,
        command_id=command_id,
        reason="eligible for wake",
    )


def classify_blue_jules_result_event(event_payload, explicit_lineage, seen_command_ids):
    return classify_jules_result_event(event_payload, explicit_lineage, seen_command_ids, lane="blue")
