import unittest

from automation.command_bus.signal_observed_jules import map_jules_session_state_to_observed_signal
from automation.command_bus.signal_observed_github import (
    map_result_pr_head_to_observed_state,
    map_exact_head_github_run_to_observed_check
)
from automation.command_bus.signal_observed_feedback import decide_same_session_feedback
from automation.command_bus.signal_observed_feedback_request import prepare_same_session_message_request
from automation.command_bus.signal_observed_render import render_observed_signal_section

class TestSignalObservedStaticE2E(unittest.TestCase):
    """
    SF-5: Static Observed Signal E2E.
    Proves static composition of existing pure helpers.
    This does NOT prove live delivery, exactly-once, or runtime ownership.
    """

    def test_lifecycle_success_fixture(self):
        # 1. Deterministic accepted-dispatch FIXTURE only; no transport is exercised.
        mock_dispatch = {
            "status": "accepted",
            "session_id": "123456",
            "expected_target_head": "c" * 40,
        }
        mock_session_id = mock_dispatch["session_id"]
        mock_result_head = "a" * 40
        mock_workflow_head = "a" * 40
        mock_activity_name = f"sessions/{mock_session_id}/activities/act-1"
        mock_answer = "This is a fix."

        # Assert dispatch-fixture identities before mapping; not live acceptance evidence.
        self.assertEqual(mock_dispatch["status"], "accepted")
        self.assertRegex(mock_dispatch["expected_target_head"], r"^[0-9a-f]{40}$")
        self.assertEqual(mock_dispatch["session_id"], mock_session_id)
        self.assertEqual(len(mock_result_head), 40)
        self.assertTrue(mock_result_head.islower())
        self.assertTrue(mock_session_id.isascii() and mock_session_id.isdigit())

        # 2. IN_PROGRESS
        observed_in_progress = map_jules_session_state_to_observed_signal("IN_PROGRESS")
        self.assertEqual(observed_in_progress, "IN_PROGRESS")

        # 3. NEEDS_INPUT
        observed_needs_input = map_jules_session_state_to_observed_signal("AWAITING_USER_FEEDBACK")
        self.assertEqual(observed_needs_input, "NEEDS_INPUT")

        # 4. same-session answer
        decision = decide_same_session_feedback(
            observed_session_id=mock_session_id,
            expected_session_id=mock_session_id,
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="May I keep the filename within the allowlist?",
            controller_classification="SMALL_REVERSIBLE_REPO",
            already_answered=False,
        )
        self.assertEqual(decision, "CONTROLLER_REVIEW_ELIGIBLE")

        request = prepare_same_session_message_request(
            observed_session_id=mock_session_id,
            expected_session_id=mock_session_id,
            observed_activity_name=mock_activity_name,
            expected_activity_name=mock_activity_name,
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="May I keep the filename within the allowlist?",
            controller_classification="SMALL_REVERSIBLE_REPO",
            answer_text=mock_answer,
            already_answered=False,
            prior_message_request_exists=False,
        )
        self.assertEqual(request, {
            "session_id": mock_session_id,
            "expected_state": "AWAITING_USER_FEEDBACK",
            "prompt": mock_answer
        })
        self.assertNotIn("May I keep the filename within the allowlist?", str(request))

        # 5. result PR
        observed_pr_ready = map_result_pr_head_to_observed_state(mock_result_head)
        self.assertEqual(observed_pr_ready, "PR_READY")

        # 6. exact-head checks
        observed_ci_pass = map_exact_head_github_run_to_observed_check(
            mock_result_head, mock_workflow_head, "completed", "success"
        )
        self.assertEqual(observed_ci_pass, "PASS")

        # 7. review-ready observed rendering
        snapshot = {
            "jules_session_state": "COMPLETED",
            "result_pr_head": mock_result_head,
            "workflow_head_sha": mock_workflow_head,
            "workflow_status": "completed",
            "workflow_conclusion": "success"
        }
        rendered = render_observed_signal_section(snapshot)
        self.assertIn("SESSION_COMPLETE", rendered)
        self.assertIn("PR_READY", rendered)
        self.assertIn("PASS", rendered)
        self.assertIn("does NOT prove durable runtime ownership", rendered)

    def test_fail_closed_companion_cases(self):
        mock_session_id = "123456"
        other_session_id = "654321"
        mock_activity_name = f"sessions/{mock_session_id}/activities/act-1"
        other_activity_name = f"sessions/{other_session_id}/activities/act-2"
        mock_result_head = "a" * 40
        other_workflow_head = "b" * 40

        # different Session at feedback decision => UNKNOWN
        decision_wrong_session = decide_same_session_feedback(
            observed_session_id=other_session_id,
            expected_session_id=mock_session_id,
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="Hi",
            controller_classification="SMALL_REVERSIBLE_REPO"
        )
        self.assertEqual(decision_wrong_session, "UNKNOWN")

        # activity from different Session => preparation ValueError
        with self.assertRaises(ValueError):
            prepare_same_session_message_request(
                observed_session_id=other_session_id,
                expected_session_id=mock_session_id,
                observed_activity_name=other_activity_name,
                expected_activity_name=mock_activity_name,
                jules_state="AWAITING_USER_FEEDBACK",
                agent_message="Hi",
                controller_classification="SMALL_REVERSIBLE_REPO",
                answer_text="fix"
            )

        with self.assertRaises(ValueError):
            prepare_same_session_message_request(
                observed_session_id=mock_session_id,
                expected_session_id=mock_session_id,
                observed_activity_name=other_activity_name,
                expected_activity_name=mock_activity_name,
                jules_state="AWAITING_USER_FEEDBACK",
                agent_message="Hi",
                controller_classification="SMALL_REVERSIBLE_REPO",
                answer_text="fix"
            )

        # HUMAN_ONLY => HUMAN_NEEDED and preparation rejection
        decision_human_only = decide_same_session_feedback(
            observed_session_id=mock_session_id,
            expected_session_id=mock_session_id,
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="Hi",
            controller_classification="HUMAN_ONLY"
        )
        self.assertEqual(decision_human_only, "HUMAN_NEEDED")

        with self.assertRaises(ValueError):
            prepare_same_session_message_request(
                observed_session_id=mock_session_id,
                expected_session_id=mock_session_id,
                observed_activity_name=mock_activity_name,
                expected_activity_name=mock_activity_name,
                jules_state="AWAITING_USER_FEEDBACK",
                agent_message="Hi",
                controller_classification="HUMAN_ONLY",
                answer_text="fix"
            )

        # already answered / prior message request exists => NO_ACTION or preparation rejection
        decision_already_answered = decide_same_session_feedback(
            observed_session_id=mock_session_id,
            expected_session_id=mock_session_id,
            jules_state="AWAITING_USER_FEEDBACK",
            agent_message="Hi",
            controller_classification="SMALL_REVERSIBLE_REPO",
            already_answered=True
        )
        self.assertEqual(decision_already_answered, "NO_ACTION")

        with self.assertRaises(ValueError):
            prepare_same_session_message_request(
                observed_session_id=mock_session_id,
                expected_session_id=mock_session_id,
                observed_activity_name=mock_activity_name,
                expected_activity_name=mock_activity_name,
                jules_state="AWAITING_USER_FEEDBACK",
                agent_message="Hi",
                controller_classification="SMALL_REVERSIBLE_REPO",
                answer_text="fix",
                already_answered=True
            )

        with self.assertRaises(ValueError):
            prepare_same_session_message_request(
                observed_session_id=mock_session_id,
                expected_session_id=mock_session_id,
                observed_activity_name=mock_activity_name,
                expected_activity_name=mock_activity_name,
                jules_state="AWAITING_USER_FEEDBACK",
                agent_message="Hi",
                controller_classification="SMALL_REVERSIBLE_REPO",
                answer_text="fix",
                prior_message_request_exists=True
            )

        # result PR head differs from workflow head => exact-head CI UNKNOWN
        ci_mismatch = map_exact_head_github_run_to_observed_check(
            mock_result_head, other_workflow_head, "completed", "success"
        )
        self.assertEqual(ci_mismatch, "UNKNOWN")

        # malformed result SHA => UNKNOWN
        self.assertEqual(map_result_pr_head_to_observed_state("short"), "UNKNOWN")

        # unknown Jules state => UNKNOWN
        self.assertEqual(map_jules_session_state_to_observed_signal("WEIRD_STATE"), "UNKNOWN")

    def test_full_observed_lifecycle_table_with_human_attention(self):
        """Useful Signal MVP: one rendered projection per lifecycle stage (static only)."""
        head = "a" * 40
        stages = [
            # (jules state, result head, wf head, status, conclusion, session, pr, ci, attention)
            ("QUEUED", None, None, None, None, "DISPATCHED", "NO_RESULT_PR", "UNKNOWN", "NOT_NEEDED"),
            ("IN_PROGRESS", None, None, None, None, "IN_PROGRESS", "NO_RESULT_PR", "UNKNOWN", "NOT_NEEDED"),
            ("AWAITING_USER_FEEDBACK", None, None, None, None, "NEEDS_INPUT", "NO_RESULT_PR", "UNKNOWN", "NEEDED"),
            ("FAILED", None, None, None, None, "FAIL", "NO_RESULT_PR", "UNKNOWN", "NEEDED"),
            ("COMPLETED", head, head, "queued", None, "SESSION_COMPLETE", "PR_READY", "VERIFYING", "NOT_NEEDED"),
            ("COMPLETED", head, head, "completed", "success", "SESSION_COMPLETE", "PR_READY", "PASS", "NEEDED"),
            ("COMPLETED", head, head, "completed", "failure", "SESSION_COMPLETE", "PR_READY", "FAIL", "NEEDED"),
            ("COMPLETED", head, "b" * 40, "completed", "success", "SESSION_COMPLETE", "PR_READY", "UNKNOWN", "UNKNOWN"),
            ("COMPLETED", "bad", head, "completed", "success", "SESSION_COMPLETE", "UNKNOWN", "UNKNOWN", "UNKNOWN"),
        ]
        for js, rh, wh, st, co, e_s, e_p, e_c, e_a in stages:
            out = render_observed_signal_section({
                "jules_session_state": js, "result_pr_head": rh,
                "workflow_head_sha": wh, "workflow_status": st, "workflow_conclusion": co,
            })
            with self.subTest(stage=js, ci=e_c):
                self.assertIn(f"**Jules Session**: `{e_s}`", out)
                self.assertIn(f"**Result PR**: `{e_p}`", out)
                self.assertIn(f"**Exact-Head CI**: `{e_c}`", out)
                self.assertIn(f"(observed hint)**: `{e_a}`", out)
                self.assertIn("does NOT prove durable runtime ownership", out)
