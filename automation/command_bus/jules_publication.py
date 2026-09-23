"""Fail-closed validation for Jules publication and PR #4 fast-forward.

This module makes no GitHub writes. It validates facts obtained from durable
GitHub readback before a caller may fast-forward the target branch.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


class PublicationState(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PublicationDecision:
    state: PublicationState
    reason: str


def validate_jules_publication(
    *,
    expected_target_head: str,
    current_target_head: str | None,
    resulting_commit: str | None,
    parent_shas: Iterable[str] | None,
    comparison_base_branch: str | None,
    expected_base_branch: str,
    changed_paths: list[dict[str, Any]] | None,
    allowed_paths: set[str],
    tests_passed: bool | None,
    compileall_passed: bool | None,
    diff_check_passed: bool | None,
    retry_count: int | None,
    fallback_used: bool | None,
    task_submitted: bool | None,
    jules_task_started: bool | None,
    model_started: bool | None,
    github_mutation_uncertainty: bool | str | None,
    main_direct_write: bool | None,
) -> PublicationDecision:
    if not expected_target_head or not resulting_commit:
        return PublicationDecision(PublicationState.UNKNOWN, "commit identity unavailable")
    if current_target_head is None:
        return PublicationDecision(PublicationState.UNKNOWN, "current target head unavailable")
    if current_target_head != expected_target_head:
        return PublicationDecision(PublicationState.BLOCKED, "STALE_TARGET: PR #4 head changed")
    if parent_shas is None:
        return PublicationDecision(PublicationState.UNKNOWN, "resulting commit parents unavailable")
    parents = list(parent_shas)
    if parents != [expected_target_head]:
        return PublicationDecision(PublicationState.BLOCKED, "resulting commit is not exactly one child of expected target head")
    if comparison_base_branch is None:
        return PublicationDecision(PublicationState.UNKNOWN, "comparison base branch unavailable")
    if comparison_base_branch != expected_base_branch:
        return PublicationDecision(PublicationState.BLOCKED, "Jules PR/comparison base mismatch")
    if changed_paths is None:
        return PublicationDecision(PublicationState.UNKNOWN, "changed paths unavailable")
    for item in changed_paths:
        if not isinstance(item, dict):
            return PublicationDecision(PublicationState.UNKNOWN, "malformed changed path record")
        path = item.get("path")
        operation = item.get("operation")
        if path not in allowed_paths:
            return PublicationDecision(PublicationState.BLOCKED, f"unexpected path: {path}")
        if operation not in {"ADD", "MODIFY"}:
            return PublicationDecision(PublicationState.BLOCKED, f"unexpected operation: {operation}")
        if item.get("symlink") is True:
            return PublicationDecision(PublicationState.BLOCKED, f"symlink change forbidden: {path}")
    if not changed_paths:
        return PublicationDecision(PublicationState.BLOCKED, "empty Jules publication")
    for name, value in (
        ("tests", tests_passed),
        ("compileall", compileall_passed),
        ("diff_check", diff_check_passed),
    ):
        if value is None:
            return PublicationDecision(PublicationState.UNKNOWN, f"{name} result unavailable")
        if value is not True:
            return PublicationDecision(PublicationState.BLOCKED, f"{name} failed")
    if retry_count is None or fallback_used is None:
        return PublicationDecision(PublicationState.UNKNOWN, "retry/fallback evidence unavailable")
    if retry_count != 0 or fallback_used is not False:
        return PublicationDecision(PublicationState.BLOCKED, "retry/fallback policy violated")
    for name, value in (
        ("task_submitted", task_submitted),
        ("jules_task_started", jules_task_started),
        ("model_started", model_started),
    ):
        if value is None:
            return PublicationDecision(PublicationState.UNKNOWN, f"{name} evidence unavailable")
        if value is not True:
            return PublicationDecision(PublicationState.BLOCKED, f"{name} not proven true")
    if github_mutation_uncertainty in {None, "UNKNOWN"}:
        return PublicationDecision(PublicationState.UNKNOWN, "GitHub mutation uncertainty unresolved")
    if github_mutation_uncertainty is True:
        return PublicationDecision(PublicationState.BLOCKED, "GitHub mutation uncertainty present")
    if main_direct_write is None:
        return PublicationDecision(PublicationState.UNKNOWN, "main direct-write evidence unavailable")
    if main_direct_write is not False:
        return PublicationDecision(PublicationState.BLOCKED, "main/default branch direct write detected")
    return PublicationDecision(PublicationState.PASS, "publication satisfies fast-forward gate")


def fast_forward_allowed(
    decision: PublicationDecision,
    *,
    current_target_head: str | None,
    expected_target_head: str,
    resulting_commit: str | None,
    ancestry_is_fast_forward: bool | None,
) -> PublicationDecision:
    if decision.state is not PublicationState.PASS:
        return decision
    if current_target_head is None or resulting_commit is None or ancestry_is_fast_forward is None:
        return PublicationDecision(PublicationState.UNKNOWN, "fast-forward facts unavailable")
    if current_target_head != expected_target_head:
        return PublicationDecision(PublicationState.BLOCKED, "STALE_TARGET before fast-forward")
    if ancestry_is_fast_forward is not True:
        return PublicationDecision(PublicationState.BLOCKED, "non-fast-forward publication")
    return PublicationDecision(PublicationState.PASS, f"safe fast-forward to {resulting_commit}")
