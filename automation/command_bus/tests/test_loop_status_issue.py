from __future__ import annotations

import unittest
from pathlib import Path

from automation.command_bus.loop_status_issue import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    RUNTIME_END,
    RUNTIME_START,
    managed_block,
    notification_for_state,
    project_state,
    render_issue_body,
)


def state(**changes):
    value = {
        "schema_version": 1,
        "loop_id": "loop-015",
        "state": "RUNNING",
        "round": 2,
        "max_rounds": 6,
        "expires_at": "2026-09-27T12:00:00+00:00",
        "stop_requested": False,
        "last_command_id": "cmd-015",
        "last_receipt_id": None,
        "expected_target": {
            "repo": "kamiyusense/multi-ai-council-phase0",
            "pr": 4,
            "head": "a" * 40,
        },
        "retry_policy": 0,
    }
    value.update(changes)
    return value


class LoopStatusIssueTests(unittest.TestCase):
    def test_runtime_workflow_uses_durable_transition_readbacks(self):
        workflow = Path(__file__).parents[3] / ".github/workflows/loop-status-signal.yml"
        text = workflow.read_text(encoding="utf-8")
        self.assertNotIn('--owner "NONE"', text)
        self.assertNotIn("inputs.owner", text)
        self.assertNotIn("inputs.provider_state", text)
        self.assertNotIn("inputs.event_id", text)
        self.assertIn("loop_status_transition_cli plan", text)
        self.assertIn("loop_status_transition_cli", text)
        self.assertIn("ref: main", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("--retry 0", text)
        self.assertIn("status Issue changed after transition readback", text)
        self.assertIn('.state == "open"', text)
        self.assertIn("ACQUIRE|RENEW|HANDOFF", text)

    def test_running_semiauto_projects_semiauto_without_notification(self):
        raw = state()
        projection = project_state(raw, owner="SEMI_AUTO", provider_state="Jules IN_PROGRESS")
        self.assertEqual(projection.display_state, "SEMI_AUTO")
        self.assertIsNone(notification_for_state(raw, projection))

    def test_running_auto_projects_auto(self):
        projection = project_state(state(), owner="AUTO")
        self.assertEqual(projection.display_state, "AUTO")

    def test_active_state_without_owner_fails_closed_to_blocked(self):
        raw = state(last_receipt_id="receipt-owner-missing")
        projection = project_state(raw, owner="NONE")
        self.assertEqual(projection.display_state, "BLOCKED")
        notice = notification_for_state(raw, projection)
        self.assertIsNotNone(notice)
        self.assertEqual(notice.kind, "HUMAN_NEEDED")

    def test_complete_projects_idle_and_notifies_from_receipt_identity(self):
        raw = state(state="COMPLETE", last_receipt_id="receipt-015")
        projection = project_state(raw, owner="NONE")
        self.assertEqual(projection.display_state, "IDLE")
        notice = notification_for_state(raw, projection)
        self.assertIsNotNone(notice)
        self.assertEqual(notice.kind, "TURN_COMPLETE")
        self.assertEqual(notice.event_id, "receipt-015")
        self.assertIn("loop-status-receipt:TURN_COMPLETE:receipt-015", notice.body)
        self.assertIn("@kamiyusense", notice.body)
        self.assertIn("Loop: `loop-015`", notice.body)
        self.assertIn("Round: `2/6`", notice.body)
        self.assertIn("Owner: `NONE`", notice.body)
        self.assertIn("Runtime state: `IDLE`", notice.body)

    def test_blocked_notifies_once_per_durable_event_identity(self):
        raw = state(state="BLOCKED", last_receipt_id=None, last_command_id="cmd-blocked")
        projection = project_state(raw, owner="AUTO")
        notice = notification_for_state(raw, projection)
        self.assertIsNotNone(notice)
        self.assertEqual(notice.kind, "HUMAN_NEEDED")
        self.assertEqual(notice.event_id, "cmd-blocked")

    def test_blocked_without_event_identity_does_not_create_comment(self):
        raw = state(state="BLOCKED", last_receipt_id=None, last_command_id=None)
        projection = project_state(raw, owner="AUTO")
        self.assertEqual(projection.display_state, "BLOCKED")
        self.assertIsNone(notification_for_state(raw, projection))

    def test_halted_projects_stopped_without_comment(self):
        raw = state(state="HALTED", stop_requested=True, last_receipt_id="receipt-stop")
        projection = project_state(raw, owner="AUTO")
        self.assertEqual(projection.display_state, "STOPPED")
        self.assertIsNone(notification_for_state(raw, projection))

    def test_human_auth_wait_projects_blocked(self):
        raw = state(state="WAITING_FOR_HUMAN_AUTH")
        projection = project_state(raw, owner="AUTO")
        self.assertEqual(projection.display_state, "BLOCKED")
        self.assertEqual(projection.human_action, "REVIEW REQUIRED")

    def test_provider_text_is_single_line_bounded_and_markdown_safe(self):
        projection = project_state(
            state(),
            owner="AUTO",
            provider_state="Jules\nIN_PROGRESS `unsafe` " + ("x" * 500),
        )
        self.assertNotIn("\n", projection.provider_state)
        self.assertNotIn("`", projection.provider_state)
        self.assertLessEqual(len(projection.provider_state), 200)

    def test_requested_loop_id_must_match_durable_state(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            project_state(state(), owner="AUTO", expected_loop_id="other-loop")

    def test_durable_loop_id_must_be_safe(self):
        with self.assertRaisesRegex(ValueError, "invalid durable loop_id"):
            project_state(state(loop_id="../bad"), owner="AUTO")

    def test_render_body_marks_issue_as_display_only(self):
        projection = project_state(state(), owner="SEMI_AUTO")
        body = render_issue_body(projection)
        self.assertIn("display surface only", body)
        self.assertIn("SEMI_AUTO", body)
        self.assertIn("Runtime Loop の状態", body)
        self.assertIn("Loop: `loop-015`", body)

    def test_render_body_uses_runtime_markers(self):
        projection = project_state(state(), owner="SEMI_AUTO")
        body = render_issue_body(projection)
        self.assertEqual(body.count(RUNTIME_START), 1)
        self.assertEqual(body.count(RUNTIME_END), 1)

    def test_runtime_refresh_preserves_development_block(self):
        development = managed_block(
            DEVELOPMENT_START,
            DEVELOPMENT_END,
            "## 🛠 Development progress\n\n- Relay: OPEN",
        )
        existing = managed_block(RUNTIME_START, RUNTIME_END, "# ⚫ STOPPED") + "\n\n" + development + "\n"
        projection = project_state(state(), owner="SEMI_AUTO")
        body = render_issue_body(projection, existing_body=existing)
        self.assertIn("# 🟢 Runtime: SEMI_AUTO", body)
        self.assertIn(development, body)
        self.assertEqual(body.count(DEVELOPMENT_START), 1)

    def test_legacy_runtime_migration_preserves_existing_development_block(self):
        development = managed_block(
            DEVELOPMENT_START,
            DEVELOPMENT_END,
            "## 🛠 Development progress\n\n- Relay: OPEN",
        )
        existing = "# ⚫ STOPPED\n\nlegacy runtime body\n\n" + development + "\n"
        projection = project_state(state(), owner="SEMI_AUTO")
        body = render_issue_body(projection, existing_body=existing)
        self.assertNotIn("legacy runtime body", body)
        self.assertIn(development, body)
        self.assertEqual(body.count(RUNTIME_START), 1)

    def test_partial_runtime_marker_fails_closed(self):
        projection = project_state(state(), owner="SEMI_AUTO")
        with self.assertRaisesRegex(ValueError, "markers"):
            render_issue_body(projection, existing_body=RUNTIME_START + "\npartial")

    def test_invalid_owner_is_rejected(self):
        with self.assertRaises(ValueError):
            project_state(state(), owner="CLAUDE")

    def test_invalid_notification_identity_is_rejected(self):
        raw = state(state="COMPLETE", last_receipt_id="../bad")
        projection = project_state(raw, owner="NONE")
        with self.assertRaises(ValueError):
            notification_for_state(raw, projection)

    def test_event_override_is_used_for_dedupe_marker(self):
        raw = state(state="COMPLETE", last_receipt_id="old")
        projection = project_state(raw, owner="NONE")
        notice = notification_for_state(raw, projection, event_id="receipt-new")
        self.assertIsNotNone(notice)
        self.assertEqual(notice.event_id, "receipt-new")
        self.assertIn("receipt-new", notice.marker)


if __name__ == "__main__":
    unittest.main()
