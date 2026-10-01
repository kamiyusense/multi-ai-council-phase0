"""Prepare-only Issue #33 migration boundary for Control Tower v2.

This module performs no network calls and no GitHub writes. It converts one
already-built ControlTowerModel into an exact Issue title/body plan, checks the
pre-write Issue snapshot for conflicts, and prepares only bounded terminal/user
notification comments.

The durable runtime truth remains outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .control_tower import (
    ControlTowerLane,
    ControlTowerModel,
    notification_marker,
    render_control_tower,
)

_STATUS_ISSUE = 33
_NOTIFY_KINDS = {"TURN_COMPLETE", "HUMAN_NEEDED"}


@dataclass(frozen=True)
class IssueSnapshot:
    number: int
    state: str
    title: str
    body: str


@dataclass(frozen=True)
class ControlTowerNotificationPlan:
    kind: str
    loop_id: str
    event_id: str
    marker: str
    body: str


@dataclass(frozen=True)
class ControlTowerIssuePlan:
    base: IssueSnapshot
    expected_title: str
    expected_body: str
    notifications: tuple[ControlTowerNotificationPlan, ...]

    @property
    def issue_change_required(self) -> bool:
        return (
            self.base.title != self.expected_title
            or self.base.body != self.expected_body
        )


def normalize_issue_snapshot(raw: dict[str, Any]) -> IssueSnapshot:
    if not isinstance(raw, dict):
        raise ValueError("Issue readback must be an object")
    number = raw.get("number", raw.get("issue_number"))
    state = raw.get("state")
    title = raw.get("title")
    body = raw.get("body")
    if number != _STATUS_ISSUE:
        raise ValueError("Control Tower migration is limited to Issue #33")
    if state != "open":
        raise ValueError("Issue #33 must be open")
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("Issue #33 title/body readback is unavailable")
    return IssueSnapshot(number, state, title, body)


def prepare_control_tower_issue_plan(
    model: ControlTowerModel,
    issue_readback: dict[str, Any],
    *,
    existing_comment_bodies: Iterable[str] = (),
) -> ControlTowerIssuePlan:
    if not isinstance(model, ControlTowerModel):
        raise ValueError("verified ControlTowerModel is required")
    base = normalize_issue_snapshot(issue_readback)
    rendered = render_control_tower(model, existing_body=base.body)
    notifications = _plan_notifications(model, existing_comment_bodies)
    return ControlTowerIssuePlan(
        base=base,
        expected_title=rendered.title,
        expected_body=rendered.body,
        notifications=notifications,
    )


def assert_issue_unchanged(
    base: IssueSnapshot,
    current_readback: dict[str, Any],
) -> None:
    if not isinstance(base, IssueSnapshot):
        raise ValueError("base Issue snapshot is required")
    current = normalize_issue_snapshot(current_readback)
    if current != base:
        raise ValueError("Issue #33 changed after Control Tower readback; refusing overwrite")


def verify_issue_applied(
    plan: ControlTowerIssuePlan,
    readback: dict[str, Any],
) -> None:
    if not isinstance(plan, ControlTowerIssuePlan):
        raise ValueError("Control Tower Issue plan is required")
    current = normalize_issue_snapshot(readback)
    if (
        current.title != plan.expected_title
        or current.body != plan.expected_body
    ):
        raise ValueError("Control Tower Issue title/body readback mismatch")


def _plan_notifications(
    model: ControlTowerModel,
    existing_comment_bodies: Iterable[str],
) -> tuple[ControlTowerNotificationPlan, ...]:
    comments = tuple(existing_comment_bodies)
    if any(not isinstance(body, str) for body in comments):
        raise ValueError("existing Issue comments must be strings")

    plans = []
    seen_markers = set()
    for lane in model.lanes:
        kind = lane.last_event_kind
        if kind not in _NOTIFY_KINDS:
            continue
        marker = notification_marker(lane, kind)
        if marker in seen_markers:
            raise ValueError("duplicate Control Tower notification marker")
        seen_markers.add(marker)
        if any(marker in body for body in comments):
            continue
        plans.append(_notification_plan(lane, kind, marker))
    return tuple(plans)


def _notification_plan(
    lane: ControlTowerLane,
    kind: str,
    marker: str,
) -> ControlTowerNotificationPlan:
    if kind == "TURN_COMPLETE":
        title = "✅ TURN COMPLETE"
        message = "このLoopは安全なcheckpointで完了しました。"
    elif kind == "HUMAN_NEEDED":
        title = "🔴 HUMAN NEEDED"
        message = "このLoopはユーザー判断または操作が必要です。"
    else:
        raise ValueError("unsupported Control Tower notification kind")

    body = (
        f"{title}\n\n"
        f"{message}\n\n"
        f"- Loop: {lane.display_name}\n"
        f"- loop_id: {lane.loop_id}\n"
        f"- Runtime state: {lane.display_state}\n"
        f"- Controller: {lane.controller_kind}\n"
        f"- Worker: {lane.worker_kind}\n"
        f"- Target: {lane.target_ref or '-'}\n"
        f"- Generation: {lane.generation if lane.generation is not None else '-'}\n"
        f"- Durable event: {lane.last_event_id}\n"
        f"- Human action: {lane.human_action}\n"
        f"- Safe detail: {lane.safe_detail_ref}\n\n"
        f"<!-- {marker} -->\n"
    )
    return ControlTowerNotificationPlan(
        kind=kind,
        loop_id=lane.loop_id,
        event_id=lane.last_event_id or "",
        marker=marker,
        body=body,
    )
