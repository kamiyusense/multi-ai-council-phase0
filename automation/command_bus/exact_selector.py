"""Exact Jules Web UI repository/branch selection gate.

Pure/static contract only. Browser automation must supply candidate labels and
post-selection readback; this module never opens a browser or clicks UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

EXPECTED_REPOSITORY = "kamiyusense/multi-ai-council-phase0"
EXPECTED_BRANCH = "feature/relay-transport-7070955470193506982"


class SelectionState(StrEnum):
    EXACT = "EXACT"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExactSelection:
    state: SelectionState
    value: str | None
    reason: str


def choose_exact(candidates: Iterable[str] | None, expected: str) -> ExactSelection:
    if candidates is None:
        return ExactSelection(SelectionState.UNKNOWN, None, "candidate list unavailable")
    if not isinstance(expected, str) or not expected:
        return ExactSelection(SelectionState.UNKNOWN, None, "expected selector value invalid")
    values = list(candidates)
    if any(not isinstance(value, str) for value in values):
        return ExactSelection(SelectionState.UNKNOWN, None, "candidate list contains non-string value")
    matches = [value for value in values if value == expected]
    if len(matches) != 1:
        return ExactSelection(
            SelectionState.BLOCKED,
            None,
            f"exact candidate count is {len(matches)}, expected exactly one",
        )
    return ExactSelection(SelectionState.EXACT, matches[0], "exactly one full-string match")


def verify_selected_readback(observed: str | None, expected: str) -> ExactSelection:
    if observed is None:
        return ExactSelection(SelectionState.UNKNOWN, None, "selected value readback unavailable")
    if not isinstance(observed, str):
        return ExactSelection(SelectionState.UNKNOWN, None, "selected value readback invalid")
    if observed != expected:
        return ExactSelection(SelectionState.BLOCKED, observed, "post-selection readback mismatch")
    return ExactSelection(SelectionState.EXACT, observed, "post-selection readback exact")


def exact_repository_branch_gate(
    *,
    repository_candidates: Iterable[str] | None,
    repository_readback: str | None,
    branch_candidates: Iterable[str] | None,
    branch_readback: str | None,
) -> dict:
    repo_pick = choose_exact(repository_candidates, EXPECTED_REPOSITORY)
    if repo_pick.state is not SelectionState.EXACT:
        return {"state": repo_pick.state.value, "task_submit_allowed": False, "reason": repo_pick.reason}
    repo_verify = verify_selected_readback(repository_readback, EXPECTED_REPOSITORY)
    if repo_verify.state is not SelectionState.EXACT:
        return {"state": repo_verify.state.value, "task_submit_allowed": False, "reason": repo_verify.reason}

    branch_pick = choose_exact(branch_candidates, EXPECTED_BRANCH)
    if branch_pick.state is not SelectionState.EXACT:
        return {"state": branch_pick.state.value, "task_submit_allowed": False, "reason": branch_pick.reason}
    branch_verify = verify_selected_readback(branch_readback, EXPECTED_BRANCH)
    if branch_verify.state is not SelectionState.EXACT:
        return {"state": branch_verify.state.value, "task_submit_allowed": False, "reason": branch_verify.reason}

    return {
        "state": SelectionState.EXACT.value,
        "repository": EXPECTED_REPOSITORY,
        "branch": EXPECTED_BRANCH,
        "repository_selection_explicit": True,
        "branch_selection_explicit": True,
        "task_submit_allowed": True,
        "reason": "exact repository and branch selected and read back",
    }
