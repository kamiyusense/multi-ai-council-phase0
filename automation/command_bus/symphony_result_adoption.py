"""Small result-adoption boundary for an upstream-owned Symphony worker.

This decides whether durable worker evidence may change campaign task state.
It does not schedule, start, stop, or retry a worker. A real Git ref update
must still use an expected-head compare-and-swap at the write itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AdoptionAction(str, Enum):
    ADOPT = "ADOPT"
    STALE_REPLAN = "STALE_REPLAN"
    ISOLATE_TASK = "ISOLATE_TASK"
    HOLD_AUTHORITY = "HOLD_AUTHORITY"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class AdoptionDecision:
    action: AdoptionAction
    reason: str


_ALLOWED_OPERATIONS = frozenset({"ADD", "MODIFY"})


def decide_result_adoption(
    *,
    expected_head: str | None,
    canonical_head: str | None,
    canonical_trustworthy: bool,
    task_still_valid: bool,
    mutation_operations: tuple[str, ...] = (),
) -> AdoptionDecision:
    """Check the current target and mutation class immediately before adoption.

    Unknown mutation kinds are isolated as unsafe. Internal Symphony turns and
    retries never call this function; it belongs at the result/adoption seam.
    """
    if (not isinstance(expected_head, str) or not expected_head
            or not isinstance(canonical_head, str) or not canonical_head
            or type(canonical_trustworthy) is not bool or not canonical_trustworthy):
        return AdoptionDecision(AdoptionAction.HOLD_AUTHORITY, "canonical target lineage unavailable")
    if (not isinstance(mutation_operations, tuple)
            or any(type(item) is not str or item not in _ALLOWED_OPERATIONS
                   for item in mutation_operations)):
        return AdoptionDecision(AdoptionAction.ISOLATE_TASK, "unsafe or unclassified mutation")
    if canonical_head != expected_head:
        return AdoptionDecision(AdoptionAction.STALE_REPLAN, "target HEAD changed before adoption")
    if type(task_still_valid) is not bool or not task_still_valid:
        return AdoptionDecision(AdoptionAction.ISOLATE_TASK, "task is no longer valid on canonical target")
    return AdoptionDecision(AdoptionAction.ADOPT, "result may be applied to current task")


def decide_verified_result_adoption(**inputs):
    """G6 byte/scope/identity guard; the legacy declaration-only guard above
    remains for STATIC campaign simulation and cannot authorize a Git write.
    """
    from .symphony_result_manifest import inspect_result
    return inspect_result(**inputs)
