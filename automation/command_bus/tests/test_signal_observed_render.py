import unittest

from automation.command_bus.loop_status_issue import (
    RUNTIME_START,
    RUNTIME_END,
    DEVELOPMENT_START,
    DEVELOPMENT_END,
)
from automation.command_bus.signal_observed_render import (
    render_observed_signal_section,
    render_observed_signal_body,
    OBSERVED_START,
    OBSERVED_END,
)


class TestSignalObservedRender(unittest.TestCase):
    def setUp(self):
        self.valid_sha = "a" * 40
        self.another_sha = "b" * 40

    def test_non_dict_snapshot_raises_value_error(self):
        with self.assertRaises(ValueError):
            render_observed_signal_section(["not a dict"])
        with self.assertRaises(ValueError):
            render_observed_signal_section("not a dict")

    def test_in_progress_no_result_head_renders_correctly(self):
        snapshot = {
            "jules_session_state": "PLANNING",
            "result_pr_head": None,
            "workflow_head_sha": self.valid_sha,
            "workflow_status": "completed",
            "workflow_conclusion": "success"
        }
        output = render_observed_signal_section(snapshot)
        self.assertIn("- **Jules Session**: `IN_PROGRESS`", output)
        self.assertIn("- **Result PR**: `NO_RESULT_PR`", output)
        self.assertIn("- **Exact-Head CI**: `UNKNOWN`", output)
        self.assertIn("does NOT prove durable runtime ownership", output)

    def test_completed_valid_pr_and_ci_success_renders_correctly(self):
        snapshot = {
            "jules_session_state": "COMPLETED",
            "result_pr_head": self.valid_sha,
            "workflow_head_sha": self.valid_sha,
            "workflow_status": "completed",
            "workflow_conclusion": "success"
        }
        output = render_observed_signal_section(snapshot)
        self.assertIn("- **Jules Session**: `SESSION_COMPLETE`", output)
        self.assertIn("- **Result PR**: `PR_READY`", output)
        self.assertIn("- **Exact-Head CI**: `PASS`", output)

    def test_stale_workflow_sha_maps_to_unknown(self):
        snapshot = {
            "jules_session_state": "COMPLETED",
            "result_pr_head": self.valid_sha,
            "workflow_head_sha": self.another_sha,
            "workflow_status": "completed",
            "workflow_conclusion": "success"
        }
        output = render_observed_signal_section(snapshot)
        self.assertIn("- **Exact-Head CI**: `UNKNOWN`", output)

    def test_malformed_result_sha_maps_to_unknown(self):
        snapshot = {
            "jules_session_state": "COMPLETED",
            "result_pr_head": "malformed",
            "workflow_head_sha": "malformed",
            "workflow_status": "completed",
            "workflow_conclusion": "success"
        }
        output = render_observed_signal_section(snapshot)
        self.assertIn("- **Result PR**: `UNKNOWN`", output)
        self.assertIn("- **Exact-Head CI**: `UNKNOWN`", output)

    def test_unknown_jules_state_maps_to_unknown(self):
        snapshot = {
            "jules_session_state": "MAGIC_STATE_DOES_NOT_EXIST",
            "result_pr_head": None,
        }
        output = render_observed_signal_section(snapshot)
        self.assertIn("- **Jules Session**: `UNKNOWN`", output)

    def test_append_replace_is_idempotent_and_preserves_other_blocks(self):
        snapshot = {
            "jules_session_state": "QUEUED",
            "result_pr_head": self.valid_sha,
            "workflow_head_sha": self.valid_sha,
            "workflow_status": "in_progress",
            "workflow_conclusion": None
        }

        # Initial issue body with a runtime block
        runtime_block = f"{RUNTIME_START}\n# 🟡 Runtime: IDLE\n{RUNTIME_END}"
        dev_block = f"{DEVELOPMENT_START}\nDevelopment content\n{DEVELOPMENT_END}"
        initial_body = f"{runtime_block}\n\n{dev_block}\n"

        # First application
        updated_body = render_observed_signal_body(initial_body, snapshot)
        self.assertIn(runtime_block, updated_body)
        self.assertIn(dev_block, updated_body)
        self.assertEqual(updated_body.count(OBSERVED_START), 1)
        self.assertIn("DISPATCHED", updated_body)

        # Second application (idempotency)
        second_update = render_observed_signal_body(updated_body, snapshot)
        self.assertEqual(second_update.count(OBSERVED_START), 1)
        self.assertEqual(updated_body, second_update)

        # Test replace with different state
        snapshot2 = dict(snapshot)
        snapshot2["jules_session_state"] = "FAILED"
        third_update = render_observed_signal_body(second_update, snapshot2)
        self.assertEqual(third_update.count(OBSERVED_START), 1)
        self.assertIn("FAIL", third_update)
        self.assertNotIn("DISPATCHED", third_update)
        self.assertIn(runtime_block, third_update)
        self.assertIn(dev_block, third_update)


class TestObservedHumanAttention(unittest.TestCase):
    """Observed hint only; never an approval or authority decision."""

    def setUp(self):
        self.sha = "a" * 40

    def _attn(self, jules, head="__sha__", wf_head="__sha__", status="completed", conclusion="success"):
        head = self.sha if head == "__sha__" else head
        wf_head = self.sha if wf_head == "__sha__" else wf_head
        out = render_observed_signal_section({
            "jules_session_state": jules, "result_pr_head": head,
            "workflow_head_sha": wf_head, "workflow_status": status,
            "workflow_conclusion": conclusion,
        })
        for line in out.splitlines():
            if "Human attention" in line:
                return line.split("`")[1]
        self.fail("attention line missing")

    def test_waiting_states_need_no_human(self):
        self.assertEqual(self._attn("QUEUED", head=None), "NOT_NEEDED")
        self.assertEqual(self._attn("IN_PROGRESS", head=None), "NOT_NEEDED")
        self.assertEqual(self._attn("COMPLETED", status="in_progress", conclusion=None), "NOT_NEEDED")

    def test_input_failure_and_review_need_human(self):
        self.assertEqual(self._attn("AWAITING_USER_FEEDBACK", head=None), "NEEDED")
        self.assertEqual(self._attn("FAILED", head=None), "NEEDED")
        self.assertEqual(self._attn("COMPLETED"), "NEEDED")
        self.assertEqual(self._attn("COMPLETED", conclusion="failure"), "NEEDED")
        self.assertEqual(self._attn("COMPLETED", head=None), "NEEDED")

    def test_malformed_stale_or_unknown_is_unknown(self):
        self.assertEqual(self._attn("PAUSED", head=None), "UNKNOWN")
        self.assertEqual(self._attn("COMPLETED", head="xyz"), "UNKNOWN")
        self.assertEqual(self._attn("COMPLETED", wf_head="b" * 40), "UNKNOWN")
        self.assertEqual(self._attn(None, head=None), "UNKNOWN")

    def test_explicit_attention_signal_is_not_suppressed_by_unrelated_unknown(self):
        self.assertEqual(self._attn("AWAITING_USER_FEEDBACK", head="xyz"), "NEEDED")
        self.assertEqual(self._attn("FAILED", head="xyz"), "NEEDED")
        self.assertEqual(
            self._attn(None, head=self.sha, wf_head=self.sha, status="completed", conclusion="failure"),
            "NEEDED",
        )
