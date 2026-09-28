from __future__ import annotations

import copy
import unittest

from automation.command_bus.control_tower_issue_plan import (
    prepare_control_tower_issue_plan,
)
from automation.command_bus.control_tower_issue_publisher import (
    ControlTowerIssuePublisher,
)
from automation.command_bus.tests.test_control_tower_issue_plan import (
    issue,
    model,
)


class Transport:
    def __init__(
        self,
        *,
        issue_value=None,
        comments=None,
        patch_status="ACCEPTED",
        patch_exc=None,
        patch_applies=True,
        post_exc_markers=None,
        post_applies=True,
    ):
        self.issue_value = copy.deepcopy(issue_value if issue_value is not None else issue())
        self.comments = list(comments or [])
        self.patch_status = patch_status
        self.patch_exc = patch_exc
        self.patch_applies = patch_applies
        self.post_exc_markers = set(post_exc_markers or ())
        self.post_applies = post_applies
        self.read_issue_calls = 0
        self.patch_calls = 0
        self.list_comment_calls = 0
        self.post_calls = 0

    def read_issue(self, issue_number):
        self.read_issue_calls += 1
        return copy.deepcopy(self.issue_value)

    def patch_issue(self, issue_number, *, title, body):
        self.patch_calls += 1
        if self.patch_applies:
            self.issue_value["title"] = title
            self.issue_value["body"] = body
        if self.patch_exc is not None:
            raise self.patch_exc
        return self.patch_status

    def list_comment_bodies(self, issue_number):
        self.list_comment_calls += 1
        return list(self.comments)

    def post_comment(self, issue_number, *, body):
        self.post_calls += 1
        marker = body.split("<!-- ", 1)[1].split(" -->", 1)[0]
        if self.post_applies:
            self.comments.append(body)
        if marker in self.post_exc_markers:
            raise TimeoutError("ambiguous comment submit")
        return "ACCEPTED"


class ControlTowerIssuePublisherTests(unittest.TestCase):
    def plan(self, *, comments=()):
        return prepare_control_tower_issue_plan(
            model(),
            issue(),
            existing_comment_bodies=comments,
        )

    def test_verified_patch_and_notifications_are_read_back(self):
        transport = Transport()
        plan = self.plan()
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual((result.status, result.stage), ("VERIFIED", "complete"), result)
        self.assertEqual(result.issue_write, "ACCEPTED")
        self.assertEqual(transport.patch_calls, 1)
        self.assertEqual(transport.post_calls, 2)
        self.assertEqual(len(result.notifications_written), 2)
        self.assertEqual(result.notifications_replayed, ())
        self.assertEqual(transport.issue_value["title"], plan.expected_title)
        self.assertEqual(transport.issue_value["body"], plan.expected_body)

    def test_ambiguous_patch_that_applied_is_recovered_by_readback_without_resend(self):
        transport = Transport(
            patch_status="UNKNOWN",
            patch_exc=TimeoutError("ambiguous"),
            patch_applies=True,
        )
        plan = self.plan()
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual(result.status, "VERIFIED", result)
        self.assertEqual(result.issue_write, "RECOVERED")
        self.assertEqual(transport.patch_calls, 1)

    def test_ambiguous_patch_without_applied_readback_is_unknown_and_stops(self):
        transport = Transport(
            patch_exc=TimeoutError("ambiguous"),
            patch_applies=False,
        )
        plan = self.plan()
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "issue_readback"))
        self.assertEqual(transport.patch_calls, 1)
        self.assertEqual(transport.post_calls, 0)

    def test_prewrite_issue_conflict_stops_before_patch(self):
        plan = self.plan()
        changed = issue()
        changed["body"] += "\nexternal edit"
        transport = Transport(issue_value=changed)
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "pre_write_readback"))
        self.assertEqual(transport.patch_calls, 0)
        self.assertEqual(transport.post_calls, 0)

    def test_already_matching_issue_is_noop(self):
        first = self.plan()
        matching = issue(title=first.expected_title, body=first.expected_body)
        plan = prepare_control_tower_issue_plan(
            model(),
            matching,
            existing_comment_bodies=[item.body for item in first.notifications],
        )
        transport = Transport(
            issue_value=matching,
            comments=[item.body for item in first.notifications],
        )
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.issue_write, "NOOP")
        self.assertEqual(transport.patch_calls, 0)
        self.assertEqual(transport.post_calls, 0)

    def test_existing_notification_marker_is_replay_noop(self):
        plan = self.plan()
        existing = plan.notifications[0]
        transport = Transport(comments=[existing.body])
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(transport.post_calls, 1)
        self.assertEqual(result.notifications_replayed, (existing.marker,))
        self.assertEqual(len(result.notifications_written), 1)

    def test_ambiguous_comment_that_applied_is_recovered_without_resend(self):
        plan = self.plan()
        marker = plan.notifications[0].marker
        transport = Transport(post_exc_markers={marker}, post_applies=True)
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual(result.status, "VERIFIED", result)
        self.assertEqual(transport.post_calls, 2)
        self.assertEqual(len(result.notifications_written), 2)

    def test_ambiguous_comment_without_marker_readback_is_unknown_and_not_retried(self):
        plan = self.plan()
        marker = plan.notifications[0].marker
        transport = Transport(post_exc_markers={marker}, post_applies=False)
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "notification_readback"))
        self.assertEqual(transport.post_calls, 1)

    def test_same_exact_issue_plan_is_not_attempted_twice(self):
        transport = Transport()
        publisher = ControlTowerIssuePublisher(transport)
        plan = self.plan()
        first = publisher.publish(plan)
        self.assertEqual(first.status, "VERIFIED")
        patch_calls = transport.patch_calls
        post_calls = transport.post_calls

        second = publisher.publish(plan)
        self.assertEqual((second.status, second.stage), ("BLOCKED", "replay_guard"))
        self.assertEqual(transport.patch_calls, patch_calls)
        self.assertEqual(transport.post_calls, post_calls)

    def test_duplicate_marker_after_comment_write_is_unverified(self):
        plan = self.plan()

        class DuplicateTransport(Transport):
            def post_comment(self, issue_number, *, body):
                self.post_calls += 1
                self.comments.extend([body, body])
                return "ACCEPTED"

        transport = DuplicateTransport()
        result = ControlTowerIssuePublisher(transport).publish(plan)
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "notification_readback"))
        self.assertEqual(transport.post_calls, 1)

    def test_comment_readback_must_be_bounded_and_well_formed(self):
        plan = self.plan()

        class BadComments(Transport):
            def list_comment_bodies(self, issue_number):
                self.list_comment_calls += 1
                return [123]

        result = ControlTowerIssuePublisher(BadComments()).publish(plan)
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "notification_readback"))


if __name__ == "__main__":
    unittest.main()
