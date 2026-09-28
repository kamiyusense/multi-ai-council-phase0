from __future__ import annotations

import copy
import unittest

from automation.command_bus.control_tower_issue_plan import (
    prepare_control_tower_issue_plan,
)
from automation.command_bus.control_tower_migration_recovery import (
    ControlTowerRollbackPublisher,
    prepare_control_tower_rollback,
)
from automation.command_bus.tests.test_control_tower_issue_plan import (
    issue,
    model,
)


class Transport:
    def __init__(
        self,
        issue_value,
        *,
        patch_status="ACCEPTED",
        patch_exc=None,
        patch_applies=True,
        comments=None,
    ):
        self.issue_value = copy.deepcopy(issue_value)
        self.patch_status = patch_status
        self.patch_exc = patch_exc
        self.patch_applies = patch_applies
        self.comments = list(comments or [])
        self.read_calls = 0
        self.patch_calls = 0
        self.comment_calls = 0

    def read_issue(self, issue_number):
        self.read_calls += 1
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
        self.comment_calls += 1
        return list(self.comments)

    def post_comment(self, issue_number, *, body):
        self.comment_calls += 1
        self.comments.append(body)
        return "ACCEPTED"


def migration_plan():
    return prepare_control_tower_issue_plan(
        model(),
        issue(),
    )


def applied_issue(plan=None):
    plan = plan or migration_plan()
    return {
        "number": 33,
        "state": "open",
        "title": plan.expected_title,
        "body": plan.expected_body,
    }


class ControlTowerMigrationRecoveryTests(unittest.TestCase):
    def test_prepare_rollback_requires_exact_applied_migration(self):
        plan = migration_plan()
        rollback = prepare_control_tower_rollback(
            plan,
            applied_issue(plan),
        )
        self.assertEqual(rollback.expected_current.title, plan.expected_title)
        self.assertEqual(rollback.expected_current.body, plan.expected_body)
        self.assertEqual(rollback.restore_to, plan.base)
        self.assertTrue(rollback.issue_change_required)

    def test_human_or_later_issue_edit_blocks_prepare(self):
        plan = migration_plan()
        changed = applied_issue(plan)
        changed["body"] += "\nmanual edit"
        with self.assertRaisesRegex(ValueError, "refusing rollback overwrite"):
            prepare_control_tower_rollback(plan, changed)

        changed = applied_issue(plan)
        changed["title"] = "newer Control Tower title"
        with self.assertRaisesRegex(ValueError, "refusing rollback overwrite"):
            prepare_control_tower_rollback(plan, changed)

    def test_closed_issue_blocks_prepare(self):
        plan = migration_plan()
        changed = applied_issue(plan)
        changed["state"] = "closed"
        with self.assertRaisesRegex(ValueError, "must be open"):
            prepare_control_tower_rollback(plan, changed)

    def test_verified_rollback_restores_exact_original_title_and_body(self):
        plan = migration_plan()
        rollback = prepare_control_tower_rollback(plan, applied_issue(plan))
        transport = Transport(applied_issue(plan))
        result = ControlTowerRollbackPublisher(transport).publish(rollback)
        self.assertEqual((result.status, result.stage), ("VERIFIED", "complete"), result)
        self.assertEqual(result.issue_write, "ACCEPTED")
        self.assertEqual(transport.patch_calls, 1)
        self.assertEqual(transport.issue_value["title"], plan.base.title)
        self.assertEqual(transport.issue_value["body"], plan.base.body)

    def test_rollback_restores_development_block_exactly(self):
        plan = migration_plan()
        original_body = plan.base.body
        self.assertIn("Relay: OPEN", original_body)

        rollback = prepare_control_tower_rollback(plan, applied_issue(plan))
        transport = Transport(applied_issue(plan))
        result = ControlTowerRollbackPublisher(transport).publish(rollback)

        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(transport.issue_value["body"], original_body)
        self.assertIn("Relay: OPEN", transport.issue_value["body"])

    def test_pre_write_conflict_blocks_without_patch(self):
        plan = migration_plan()
        rollback = prepare_control_tower_rollback(plan, applied_issue(plan))
        current = applied_issue(plan)
        current["body"] += "\nnewer refresh"
        transport = Transport(current)

        result = ControlTowerRollbackPublisher(transport).publish(rollback)
        self.assertEqual((result.status, result.stage), ("BLOCKED", "pre_write_conflict"))
        self.assertEqual(transport.patch_calls, 0)

    def test_ambiguous_patch_that_applied_is_recovered_without_resend(self):
        plan = migration_plan()
        rollback = prepare_control_tower_rollback(plan, applied_issue(plan))
        transport = Transport(
            applied_issue(plan),
            patch_status="UNKNOWN",
            patch_exc=TimeoutError("ambiguous"),
            patch_applies=True,
        )
        result = ControlTowerRollbackPublisher(transport).publish(rollback)
        self.assertEqual(result.status, "VERIFIED", result)
        self.assertEqual(result.issue_write, "RECOVERED")
        self.assertEqual(transport.patch_calls, 1)

    def test_ambiguous_patch_without_applied_readback_is_unknown_and_not_retried(self):
        plan = migration_plan()
        rollback = prepare_control_tower_rollback(plan, applied_issue(plan))
        transport = Transport(
            applied_issue(plan),
            patch_exc=TimeoutError("ambiguous"),
            patch_applies=False,
        )
        publisher = ControlTowerRollbackPublisher(transport)

        first = publisher.publish(rollback)
        self.assertEqual((first.status, first.stage), ("UNKNOWN", "rollback_readback"))
        self.assertEqual(transport.patch_calls, 1)

        second = publisher.publish(rollback)
        self.assertEqual((second.status, second.stage), ("BLOCKED", "replay_guard"))
        self.assertEqual(transport.patch_calls, 1)

    def test_same_exact_rollback_plan_is_not_attempted_twice(self):
        plan = migration_plan()
        rollback = prepare_control_tower_rollback(plan, applied_issue(plan))
        transport = Transport(applied_issue(plan))
        publisher = ControlTowerRollbackPublisher(transport)

        first = publisher.publish(rollback)
        self.assertEqual(first.status, "VERIFIED")
        self.assertEqual(transport.patch_calls, 1)

        second = publisher.publish(rollback)
        self.assertEqual((second.status, second.stage), ("BLOCKED", "replay_guard"))
        self.assertEqual(transport.patch_calls, 1)

    def test_rollback_does_not_delete_or_post_notification_comments(self):
        plan = migration_plan()
        rollback = prepare_control_tower_rollback(plan, applied_issue(plan))
        comments = [
            "✅ TURN COMPLETE\n<!-- phase0-control-tower-notify:v1:TURN_COMPLETE:loop-x:event-x -->"
        ]
        transport = Transport(applied_issue(plan), comments=comments)

        result = ControlTowerRollbackPublisher(transport).publish(rollback)
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(transport.comment_calls, 0)
        self.assertEqual(transport.comments, comments)

    def test_noop_rollback_is_verified_without_patch(self):
        plan = migration_plan()
        noop_plan = copy.deepcopy(plan)
        # Build a migration plan whose expected output already equals its base.
        from automation.command_bus.control_tower_issue_plan import ControlTowerIssuePlan
        noop_plan = ControlTowerIssuePlan(
            base=plan.base,
            expected_title=plan.base.title,
            expected_body=plan.base.body,
            notifications=(),
        )
        current = {
            "number": 33,
            "state": "open",
            "title": plan.base.title,
            "body": plan.base.body,
        }
        rollback = prepare_control_tower_rollback(noop_plan, current)
        self.assertFalse(rollback.issue_change_required)

        transport = Transport(current)
        result = ControlTowerRollbackPublisher(transport).publish(rollback)
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.issue_write, "NOOP")
        self.assertEqual(transport.patch_calls, 0)


if __name__ == "__main__":
    unittest.main()
