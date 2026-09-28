from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "jules-chat-semiauto.yml"


class JulesChatSemiAutoTimingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_jules_create_session_post_remains_single_attempt(self):
        self.assertEqual(
            self.text.count("'https://jules.googleapis.com/v1alpha/sessions'"),
            1,
        )
        self.assertIn("--retry 0", self.text)
        self.assertIn("Invoke Jules REST exactly once", self.text)

    def test_acceptance_time_comes_from_captured_jules_response(self):
        self.assertIn(
            "python -m automation.command_bus.jules_session_acceptance",
            self.text,
        )
        self.assertIn("\"${response_file}\" \"${EXPECTED_BRANCH}\"", self.text)
        self.assertIn("session_create_time=", self.text)
        self.assertIn("accepted_at_jst=", self.text)
        self.assertIn(
            "accepted_at_source: \\`JULES_CREATE_SESSION_RESPONSE_CREATE_TIME\\`",
            self.text,
        )

    def test_workflow_does_not_use_github_or_shell_clock_as_acceptance_source(self):
        forbidden = (
            "github.event.head_commit.timestamp",
            "github.event.repository.pushed_at",
            "date -Iseconds",
            "date --iso-8601",
            "steps.locate.outputs.created_at",
            "steps.validate.outputs.created_at",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.text)

    def test_existing_target_branch_and_session_identity_checks_remain(self):
        self.assertIn(
            "returned_branch=\"$(jq -er '.sourceContext.githubRepoContext.startingBranch' \"${response_file}\")\"",
            self.text,
        )
        self.assertIn(
            "if [[ \"${returned_branch}\" != \"${EXPECTED_BRANCH}\" ]]",
            self.text,
        )
        self.assertIn(
            "if [[ ! \"${session_name}\" =~ ^sessions/[0-9]+$ ]]",
            self.text,
        )

    def test_job_summary_exposes_bounded_timing_evidence(self):
        self.assertIn(
            "SESSION_CREATE_TIME: ${{ steps.invoke.outputs.session_create_time }}",
            self.text,
        )
        self.assertIn(
            "ACCEPTED_AT_JST: ${{ steps.invoke.outputs.accepted_at_jst }}",
            self.text,
        )
        self.assertIn("jules_session_create_time:", self.text)
        self.assertIn("accepted_at_jst:", self.text)

    def test_v2_origin_correlation_is_exposed_in_summary(self):
        expected = (
            "PROFILE: ${{ steps.validate.outputs.profile }}",
            "ORIGIN_LOOP_ID: ${{ steps.validate.outputs.origin_loop_id }}",
            "ORIGIN_ROUND: ${{ steps.validate.outputs.origin_round }}",
            "ORIGIN_CORRELATION_ID: ${{ steps.validate.outputs.origin_correlation_id }}",
            "ORIGIN_GENERATION: ${{ steps.validate.outputs.origin_generation }}",
            "origin_loop_id:",
            "origin_round:",
            "origin_correlation_id:",
            "origin_generation:",
        )
        for value in expected:
            with self.subTest(value=value):
                self.assertIn(value, self.text)
    def test_live_proof_uses_dedicated_carrier_and_isolated_work_branch(self):
        self.assertIn(
            "- live/claude-jules-integrated-carrier-20260928",
            self.text,
        )
        self.assertNotIn("- feature/chat-work-command-bus", self.text)
        self.assertIn(
            "WORK_BRANCH: ${{ steps.validate.outputs.work_branch }}",
            self.text,
        )
        self.assertIn(
            "Verify exact target and isolated work branch snapshots",
            self.text,
        )
        self.assertIn('work_head="$(read_branch_head "${WORK_BRANCH}")"', self.text)
        self.assertIn(
            'if [[ "${work_head}" != "${EXPECTED_HEAD}" ]]',
            self.text,
        )
        self.assertIn(
            'if [[ "${work_tree}" != "${EXPECTED_TREE}" ]]',
            self.text,
        )
        self.assertIn(
            '--arg starting_branch "${WORK_BRANCH}"',
            self.text,
        )
        self.assertIn(
            "EXPECTED_BRANCH: ${{ steps.validate.outputs.work_branch }}",
            self.text,
        )
        self.assertIn("canonical_target_branch:", self.text)
        self.assertIn("isolated_work_branch:", self.text)

    def test_no_private_jules_url_is_added_to_summary(self):
        summary_section = self.text.split(
            "- name: Record dispatch boundary in job summary",
            1,
        )[1]
        self.assertNotIn("jules.google.com/session/", summary_section)


if __name__ == "__main__":
    unittest.main()
