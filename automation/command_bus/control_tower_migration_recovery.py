"""Prepare-only and retry-zero rollback boundary for Control Tower migration.

Rollback is never automatic. A caller must explicitly request it.

The rollback is allowed only when the current Issue #33 title/body still exactly
matches the Control Tower migration plan that was applied. If a human or later
refresh changed the Issue, rollback stops rather than overwriting newer work.

Notification comments are append-only evidence and are never deleted here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .control_tower_issue_plan import (
    ControlTowerIssuePlan,
    IssueSnapshot,
    normalize_issue_snapshot,
)


_STATUS_ISSUE = 33


@dataclass(frozen=True)
class ControlTowerRollbackPlan:
    expected_current: IssueSnapshot
    restore_to: IssueSnapshot

    @property
    def issue_change_required(self) -> bool:
        return self.expected_current != self.restore_to


@dataclass(frozen=True)
class ControlTowerRollbackResult:
    status: str
    stage: str
    reason: str
    issue_write: str


class ControlTowerRollbackTransport(Protocol):
    def read_issue(self, issue_number: int) -> dict[str, Any] | None: ...
    def patch_issue(self, issue_number: int, *, title: str, body: str) -> str: ...


def prepare_control_tower_rollback(
    migration_plan: ControlTowerIssuePlan,
    current_readback: dict[str, Any],
) -> ControlTowerRollbackPlan:
    """Prepare rollback only from an exact applied migration plan."""
    if not isinstance(migration_plan, ControlTowerIssuePlan):
        raise ValueError("ControlTowerIssuePlan is required")

    current = normalize_issue_snapshot(current_readback)
    expected = IssueSnapshot(
        number=_STATUS_ISSUE,
        state="open",
        title=migration_plan.expected_title,
        body=migration_plan.expected_body,
    )
    if current != expected:
        raise ValueError(
            "Issue #33 no longer exactly matches the applied Control Tower migration; "
            "refusing rollback overwrite"
        )

    base = migration_plan.base
    if base.number != _STATUS_ISSUE or base.state != "open":
        raise ValueError("migration base Issue snapshot is invalid")

    return ControlTowerRollbackPlan(
        expected_current=expected,
        restore_to=base,
    )


def verify_control_tower_rollback(
    plan: ControlTowerRollbackPlan,
    readback: dict[str, Any],
) -> None:
    if not isinstance(plan, ControlTowerRollbackPlan):
        raise ValueError("ControlTowerRollbackPlan is required")
    current = normalize_issue_snapshot(readback)
    if current != plan.restore_to:
        raise ValueError("Control Tower rollback readback mismatch")


class ControlTowerRollbackPublisher:
    """At-most-once rollback transport boundary with readback recovery."""

    def __init__(self, transport: ControlTowerRollbackTransport):
        self.transport = transport
        self._attempted: set[tuple[str, str, str, str]] = set()

    def publish(self, plan: ControlTowerRollbackPlan) -> ControlTowerRollbackResult:
        if not isinstance(plan, ControlTowerRollbackPlan):
            return ControlTowerRollbackResult(
                "BLOCKED",
                "validate",
                "ControlTowerRollbackPlan is required",
                "NONE",
            )

        identity = (
            plan.expected_current.title,
            plan.expected_current.body,
            plan.restore_to.title,
            plan.restore_to.body,
        )
        if identity in self._attempted:
            return ControlTowerRollbackResult(
                "BLOCKED",
                "replay_guard",
                "this exact rollback plan was already attempted; retry=0",
                "NONE",
            )

        try:
            current = normalize_issue_snapshot(
                self.transport.read_issue(_STATUS_ISSUE)
            )
        except Exception as exc:
            return ControlTowerRollbackResult(
                "UNKNOWN",
                "pre_write_readback",
                f"Issue #33 rollback readback failed: {exc}",
                "NONE",
            )

        if current != plan.expected_current:
            return ControlTowerRollbackResult(
                "BLOCKED",
                "pre_write_conflict",
                "Issue #33 changed after migration; refusing rollback overwrite",
                "NONE",
            )

        self._attempted.add(identity)

        if not plan.issue_change_required:
            try:
                verify_control_tower_rollback(plan, _snapshot_to_raw(current))
            except Exception as exc:
                return ControlTowerRollbackResult(
                    "UNKNOWN",
                    "rollback_readback",
                    f"rollback NO-OP verification failed: {exc}",
                    "NOOP",
                )
            return ControlTowerRollbackResult(
                "VERIFIED",
                "complete",
                "rollback was already in the requested state",
                "NOOP",
            )

        dispatch_state = "UNKNOWN"
        dispatch_error = None
        try:
            dispatch_state = self.transport.patch_issue(
                _STATUS_ISSUE,
                title=plan.restore_to.title,
                body=plan.restore_to.body,
            )
        except Exception as exc:
            dispatch_error = exc

        try:
            verify_control_tower_rollback(
                plan,
                self.transport.read_issue(_STATUS_ISSUE),
            )
        except Exception as exc:
            detail = f"; patch error={dispatch_error}" if dispatch_error else ""
            return ControlTowerRollbackResult(
                "UNKNOWN",
                "rollback_readback",
                f"rollback result is unverified; do not retry: {exc}{detail}",
                "UNKNOWN",
            )

        issue_write = (
            "ACCEPTED"
            if dispatch_state == "ACCEPTED"
            else "RECOVERED"
        )
        return ControlTowerRollbackResult(
            "VERIFIED",
            "complete",
            "rollback title/body restored and verified",
            issue_write,
        )


def _snapshot_to_raw(snapshot: IssueSnapshot) -> dict[str, Any]:
    return {
        "number": snapshot.number,
        "state": snapshot.state,
        "title": snapshot.title,
        "body": snapshot.body,
    }
