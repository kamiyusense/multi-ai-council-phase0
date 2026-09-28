"""Prepare-only Status workflow dispatch planning.

The adapter never calls GitHub Actions. It converts a verified
StatusRefreshPlan into the only two caller inputs accepted by the deployed
loop-status-signal workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runtime_transition_coordinator import StatusRefreshPlan

_WORKFLOW = ".github/workflows/loop-status-signal.yml"


@dataclass(frozen=True)
class PreparedStatusWorkflowCall:
    workflow: str
    code_ref: str
    inputs: dict[str, str]
    event_id: str
    generation: int
    display_state: str
    transition_status: str


def prepare_status_workflow_call(plan: StatusRefreshPlan) -> PreparedStatusWorkflowCall:
    if not isinstance(plan, StatusRefreshPlan):
        raise ValueError("invalid StatusRefreshPlan")
    if not isinstance(plan.loop_id, str) or not plan.loop_id:
        raise ValueError("loop_id is required")
    if not isinstance(plan.state_ref, str) or not plan.state_ref or "\n" in plan.state_ref or "\r" in plan.state_ref:
        raise ValueError("unsafe state_ref")
    if plan.state_ref in {"main", "master"}:
        raise ValueError("runtime data ref must be non-default")
    if not isinstance(plan.event_id, str) or not plan.event_id:
        raise ValueError("event_id is required")
    if isinstance(plan.generation, bool) or not isinstance(plan.generation, int) or plan.generation < 1:
        raise ValueError("invalid generation")
    if plan.display_state not in {"SEMI_AUTO", "AUTO", "IDLE", "BLOCKED", "STOPPED"}:
        raise ValueError("invalid display_state")
    if plan.transition_status not in {"VALID", "TERMINAL", "BLOCKED"}:
        raise ValueError("invalid transition_status")
    return PreparedStatusWorkflowCall(
        workflow=_WORKFLOW,
        code_ref="main",
        inputs={"loop_id": plan.loop_id, "state_ref": plan.state_ref},
        event_id=plan.event_id,
        generation=plan.generation,
        display_state=plan.display_state,
        transition_status=plan.transition_status,
    )


class PrepareOnlyStatusBoundary:
    """Stores one deterministic plan; it does not dispatch or retry."""

    def __init__(self):
        self.prepared: list[PreparedStatusWorkflowCall] = []

    def prepare(self, plan: StatusRefreshPlan) -> None:
        prepared = prepare_status_workflow_call(plan)
        if self.prepared and self.prepared[-1] == prepared:
            return
        self.prepared.append(prepared)
