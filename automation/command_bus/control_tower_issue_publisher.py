"""Transport-neutral, retry=0 Control Tower Issue publisher boundary.

No production GitHub transport is implemented here. A caller must inject a
transport. The publisher performs at most one Issue PATCH attempt and at most
one comment POST attempt per planned durable event. Ambiguous writes are resolved
by readback only; they are never blindly resent.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .control_tower_issue_plan import (
    ControlTowerIssuePlan,
    ControlTowerNotificationPlan,
    assert_issue_unchanged,
    verify_issue_applied,
)

_STATUS_ISSUE = 33


class ControlTowerIssueTransport(Protocol):
    def read_issue(self, issue_number: int) -> dict[str, Any] | None: ...
    def patch_issue(self, issue_number: int, *, title: str, body: str) -> str: ...
    def list_comment_bodies(self, issue_number: int) -> list[str] | None: ...
    def post_comment(self, issue_number: int, *, body: str) -> str: ...


@dataclass(frozen=True)
class ControlTowerPublishResult:
    status: str
    stage: str
    reason: str
    issue_write: str
    notifications_written: tuple[str, ...]
    notifications_replayed: tuple[str, ...]


class ControlTowerIssuePublisher:
    def __init__(self, transport: ControlTowerIssueTransport):
        self.transport = transport
        self._attempted_issue_plans: set[tuple[str, str, str, str]] = set()
        self._attempted_markers: set[str] = set()

    def publish(self, plan: ControlTowerIssuePlan) -> ControlTowerPublishResult:
        if not isinstance(plan, ControlTowerIssuePlan):
            return ControlTowerPublishResult(
                "BLOCKED", "validate", "ControlTowerIssuePlan is required",
                "NONE", (), (),
            )

        identity = (
            plan.base.title,
            plan.base.body,
            plan.expected_title,
            plan.expected_body,
        )
        if identity in self._attempted_issue_plans:
            return ControlTowerPublishResult(
                "BLOCKED", "replay_guard",
                "this exact Control Tower Issue plan was already attempted; retry=0",
                "NONE", (), (),
            )

        try:
            current = self.transport.read_issue(_STATUS_ISSUE)
            assert_issue_unchanged(plan.base, current)
        except Exception as exc:
            return ControlTowerPublishResult(
                "UNKNOWN", "pre_write_readback",
                f"Issue #33 conflict/readback failed: {exc}",
                "NONE", (), (),
            )

        self._attempted_issue_plans.add(identity)
        issue_write = "NOOP"

        if plan.issue_change_required:
            dispatch_state = "UNKNOWN"
            dispatch_error = None
            try:
                dispatch_state = self.transport.patch_issue(
                    _STATUS_ISSUE,
                    title=plan.expected_title,
                    body=plan.expected_body,
                )
            except Exception as exc:
                dispatch_error = exc

            try:
                applied = self.transport.read_issue(_STATUS_ISSUE)
                verify_issue_applied(plan, applied)
            except Exception as exc:
                detail = f"; patch error={dispatch_error}" if dispatch_error else ""
                return ControlTowerPublishResult(
                    "UNKNOWN", "issue_readback",
                    f"Issue PATCH result is unverified; do not retry: {exc}{detail}",
                    "UNKNOWN", (), (),
                )

            issue_write = "ACCEPTED" if dispatch_state == "ACCEPTED" else "RECOVERED"

        else:
            try:
                verify_issue_applied(plan, current)
            except Exception as exc:
                return ControlTowerPublishResult(
                    "UNKNOWN", "issue_readback",
                    f"Issue NO-OP verification failed: {exc}",
                    "NOOP", (), (),
                )

        written = []
        replayed = []
        for notification in plan.notifications:
            result = self._publish_notification(notification)
            if result == "WRITTEN":
                written.append(notification.marker)
            elif result == "REPLAY":
                replayed.append(notification.marker)
            else:
                return ControlTowerPublishResult(
                    "UNKNOWN", "notification_readback",
                    f"notification result is unverified for marker {notification.marker}; do not retry",
                    issue_write,
                    tuple(written),
                    tuple(replayed),
                )

        return ControlTowerPublishResult(
            "VERIFIED",
            "complete",
            "Issue projection and bounded notification markers verified",
            issue_write,
            tuple(written),
            tuple(replayed),
        )

    def _publish_notification(self, notification: ControlTowerNotificationPlan) -> str:
        if not isinstance(notification, ControlTowerNotificationPlan):
            return "UNKNOWN"
        marker = notification.marker
        try:
            before = self.transport.list_comment_bodies(_STATUS_ISSUE)
            _validate_comments(before)
        except Exception:
            return "UNKNOWN"

        if any(marker in body for body in before):
            return "REPLAY"

        if marker in self._attempted_markers:
            return "UNKNOWN"
        self._attempted_markers.add(marker)

        try:
            self.transport.post_comment(_STATUS_ISSUE, body=notification.body)
        except Exception:
            pass

        try:
            after = self.transport.list_comment_bodies(_STATUS_ISSUE)
            _validate_comments(after)
        except Exception:
            return "UNKNOWN"

        matches = sum(marker in body for body in after)
        if matches != 1:
            return "UNKNOWN"
        return "WRITTEN"


def _validate_comments(comments: Any) -> None:
    if not isinstance(comments, list):
        raise ValueError("Issue comment readback unavailable")
    if len(comments) > 10000:
        raise ValueError("Issue comment readback exceeds bounded maximum")
    if any(not isinstance(body, str) for body in comments):
        raise ValueError("Issue comment body readback malformed")
