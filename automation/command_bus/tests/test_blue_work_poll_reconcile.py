import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from automation.command_bus.blue_jules_result_event import EventLineage
from automation.command_bus.blue_work_poll_reconcile import select_pending_blue_review
from automation.command_bus.blue_work_reconcile_prepare import (
    PREFIX, RECEIPT_PREFIX, prepare_reconciled_wake,
)
from automation.command_bus.blue_work_wake_prepare import CarrierSnapshot

FIXTURE = Path(__file__).parent / "fixtures/blue_work_reconcile/input.json"


class BluePollReconcileTests(unittest.TestCase):
    def setUp(self):
        self.inputs = json.loads(FIXTURE.read_text())
        self.now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)

    def command(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["lineage"] = EventLineage(**inputs["lineage"])
        inputs["protocol"] = CarrierSnapshot(**inputs["protocol"])
        plan = prepare_reconciled_wake(**inputs, now=self.now)
        self.assertEqual(plan.status, "PREPARED")
        return json.loads(plan.review_body.split("\n", 1)[1])

    def review(self, *, review_id=42, submitted_at="2026-10-01T11:00:00Z",
               login="github-actions[bot]", actor_type="Bot", command=None,
               state="COMMENTED"):
        command = copy.deepcopy(command or self.command())
        return {
            "id": review_id,
            "state": state,
            "submitted_at": submitted_at,
            "body": PREFIX + "\n" + json.dumps(command),
            "user": {"login": login, "type": actor_type},
        }

    def receipt(self, command=None, **changes):
        command = copy.deepcopy(command or self.command())
        payload = {
            "protocol_version": 1,
            "command_id": command["command_id"],
            "worker_generation": command["worker_generation"],
            "status": "PASS",
            "target_repository": command["target_repository"],
            "target_pr": command["target_pr"],
            "target_branch": command["target_branch"],
            "target_head_before": command["expected_target_head"],
            "target_head_after": command["expected_target_head"],
            "terminal": True,
            "verification": ["fixture only"],
        }
        payload.update(changes)
        return {"id": 77, "body": RECEIPT_PREFIX + "\n" + json.dumps(payload)}

    def select(self, *, reviews=None, comments=None, complete=True,
               active_generation=1, fixed_generation=1):
        return select_pending_blue_review(
            reviews=[] if reviews is None else reviews,
            comments=[] if comments is None else comments,
            records_complete=complete,
            active_generation=active_generation,
            fixed_generation=fixed_generation,
        )

    def test_bot_authored_review_is_selected_without_author_authority(self):
        result = self.select(reviews=[self.review()])
        self.assertEqual(result.status, "SELECTED")
        self.assertEqual(result.review_id, 42)
        self.assertEqual(result.author_login, "github-actions[bot]")
        self.assertEqual(result.author_type, "Bot")
        self.assertEqual(result.pending_count, 1)
        self.assertEqual(result.execution_mode, "PREPARE_ONLY")
        self.assertEqual(result.retry, 0)
        self.assertEqual(result.fallback, "disabled")

    def test_human_author_is_equivalent_for_selection(self):
        result = self.select(reviews=[
            self.review(login="kamiyusense", actor_type="User")
        ])
        self.assertEqual(result.status, "SELECTED")
        self.assertEqual(result.author_login, "kamiyusense")
        self.assertEqual(result.command_id, self.command()["command_id"])

    def test_terminal_receipt_makes_command_noop(self):
        command = self.command()
        result = self.select(
            reviews=[self.review(command=command)],
            comments=[self.receipt(command)],
        )
        self.assertEqual(result.status, "NO_OP")
        self.assertEqual(result.pending_count, 0)

    def test_oldest_pending_command_is_selected_deterministically(self):
        first = self.command()
        second = copy.deepcopy(first)
        second["command_id"] = "blue-chat-second-fixture"
        second["task"] = "Inspect docs only."
        second["allowed_paths"] = ["docs/example.md"]
        result = self.select(reviews=[
            self.review(review_id=90, submitted_at="2026-10-01T11:30:00Z", command=second),
            self.review(review_id=42, submitted_at="2026-10-01T11:00:00Z", command=first),
        ])
        self.assertEqual(result.status, "SELECTED")
        self.assertEqual(result.review_id, 42)
        self.assertEqual(result.pending_count, 2)

    def test_duplicate_command_identity_is_unknown(self):
        command = self.command()
        result = self.select(reviews=[
            self.review(review_id=42, command=command),
            self.review(review_id=43, submitted_at="2026-10-01T11:01:00Z", command=command),
        ])
        self.assertEqual(result.status, "UNKNOWN")

    def test_non_command_review_is_ignored(self):
        row = self.review()
        row["body"] = "[BLUE_TRIGGER_DIAGNOSTIC_HUMAN_CONTROL_V1]\nnot a command"
        result = self.select(reviews=[row])
        self.assertEqual(result.status, "NO_OP")

    def test_matching_prefix_requires_submitted_comment_review(self):
        for state in ("PENDING", "APPROVED", "CHANGES_REQUESTED", None):
            with self.subTest(state=state):
                self.assertEqual(
                    self.select(reviews=[self.review(state=state)]).status,
                    "UNKNOWN",
                )

    def test_stale_worker_noops_before_record_parsing(self):
        result = select_pending_blue_review(
            reviews=None,
            comments=None,
            records_complete=None,
            active_generation=2,
            fixed_generation=1,
        )
        self.assertEqual(result.status, "NO_OP")
        self.assertEqual(result.reason, "stale worker generation")

    def test_incomplete_or_malformed_durable_records_are_unknown(self):
        for reviews, comments, complete in (
            (None, [], True),
            ([], None, True),
            ([], [], False),
            ([None], [], True),
        ):
            with self.subTest(reviews=reviews, comments=comments, complete=complete):
                result = select_pending_blue_review(
                    reviews=reviews,
                    comments=comments,
                    records_complete=complete,
                    active_generation=1,
                    fixed_generation=1,
                )
                self.assertEqual(result.status, "UNKNOWN")

    def test_expired_command_is_still_selected_for_downstream_terminal_gate(self):
        command = self.command()
        command["expires_at"] = "2026-09-01T00:00:00Z"
        result = self.select(reviews=[self.review(command=command)])
        self.assertEqual(result.status, "SELECTED")
        self.assertEqual(result.command_id, command["command_id"])

    def test_malformed_terminal_receipt_fails_closed(self):
        command = self.command()
        result = self.select(
            reviews=[self.review(command=command)],
            comments=[self.receipt(command, terminal=False)],
        )
        self.assertEqual(result.status, "UNKNOWN")

    def test_foreign_lane_review_does_not_route_to_blue(self):
        row = self.review()
        row["body"] = "[CW_GREEN_V1]\n{}"
        self.assertEqual(self.select(reviews=[row]).status, "NO_OP")


if __name__ == "__main__":
    unittest.main()
