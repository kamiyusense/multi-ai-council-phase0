import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


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


_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


def _is_valid_sha1(val: Any) -> bool:
    return isinstance(val, str) and bool(_SHA1_RE.match(val))


def classify_blue_jules_result_event(
    event_payload: Any,
    explicit_lineage: EventLineage,
    seen_command_ids: Iterable[str]
) -> EventClassificationResult:
    """
    Decides whether one GitHub pull_request event represents a J-BLUE Jules result
    that should wake the Blue Cloud Work controller.

    This helper performs no network calls, no I/O, and no mutations.
    """
    # 14. Missing/malformed event envelope
    if not isinstance(event_payload, dict):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="malformed top-level payload")

    action = event_payload.get("action")
    if not isinstance(action, str):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="missing or malformed action")

    repo_info = event_payload.get("repository", {})
    if not isinstance(repo_info, dict):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="malformed repository")
    repo_name = repo_info.get("full_name")

    pr_info = event_payload.get("pull_request", {})
    if not isinstance(pr_info, dict):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="malformed pull_request")

    pr_number = pr_info.get("number")
    # 5. Extract and validate PR number as positive integer
    if not isinstance(pr_number, int) or pr_number <= 0:
        return EventClassificationResult(EventDecision.UNKNOWN, reason="missing or malformed PR number")

    head_info = pr_info.get("head", {})
    if not isinstance(head_info, dict):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="malformed head")

    head_sha = head_info.get("sha")
    # 5. Extract and validate current result HEAD as exact lowercase 40-hex SHA
    if not _is_valid_sha1(head_sha):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="missing or malformed head SHA")

    base_info = pr_info.get("base", {})
    if not isinstance(base_info, dict):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="malformed base")

    base_ref = base_info.get("ref")
    base_sha = base_info.get("sha")

    if not isinstance(base_ref, str) or not _is_valid_sha1(base_sha):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="missing or malformed base ref/SHA")

    # Check lineage input validation
    if not isinstance(explicit_lineage.source_command_id, str) or not explicit_lineage.source_command_id:
        return EventClassificationResult(EventDecision.UNKNOWN, reason="missing or malformed source_command_id")
    if not isinstance(explicit_lineage.work_branch, str) or not explicit_lineage.work_branch:
        return EventClassificationResult(EventDecision.UNKNOWN, reason="missing or malformed work_branch")
    if not _is_valid_sha1(explicit_lineage.expected_target_head):
        return EventClassificationResult(EventDecision.UNKNOWN, reason="missing or malformed expected_target_head")
    if not isinstance(explicit_lineage.expected_repository, str) or not explicit_lineage.expected_repository:
        return EventClassificationResult(EventDecision.UNKNOWN, reason="missing or malformed expected_repository")

    # 4. Expected repository is kamiyusense/multi-ai-council-phase0. A clearly different repository is IGNORE.
    if repo_name != explicit_lineage.expected_repository:
        return EventClassificationResult(EventDecision.IGNORE, reason="wrong repository")

    # 3. Accepted GitHub event actions are exactly opened and synchronize. Other well-formed actions are IGNORE.
    if action not in ("opened", "synchronize"):
        return EventClassificationResult(EventDecision.IGNORE, reason="unsupported action")

    # 7. A result is eligible only when the event PR base ref equals the expected isolated work_branch
    #    and the event base SHA equals expected_target_head.
    if base_ref != explicit_lineage.work_branch:
        return EventClassificationResult(EventDecision.IGNORE, reason="unrelated base branch")

    # expected work_branch match but base SHA lineage mismatch -> UNKNOWN (fail closed), not WAKE.
    if base_sha != explicit_lineage.expected_target_head:
        return EventClassificationResult(EventDecision.UNKNOWN, reason="base SHA lineage mismatch")

    # 9. Derive deterministic logical Blue command identity
    derived_command_id = f"blue-jules-result-pr{pr_number}-{head_sha}"

    # 11. Accept an explicit collection/set of already-seen logical Blue command IDs (pure input only).
    # If the derived identity already exists, return IGNORE while preserving/reporting the same deterministic identity
    if derived_command_id in seen_command_ids:
        return EventClassificationResult(EventDecision.IGNORE, command_id=derived_command_id, reason="duplicate command identity")

    return EventClassificationResult(EventDecision.WAKE, command_id=derived_command_id, reason="eligible for wake")
