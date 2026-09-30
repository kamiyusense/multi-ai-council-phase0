from pathlib import Path
import unittest

WORKFLOW = Path(".github/workflows/jules-chat-semiauto.yml")

class JulesChatSemiAutoTimingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_single_submit_and_retry_zero_remain(self):
        self.assertEqual(
            self.text.count("'https://jules.googleapis.com/v1alpha/sessions'"),
            1,
        )
        self.assertIn("--retry 0", self.text)
        self.assertIn("Invoke Jules REST exactly once", self.text)

    def test_acceptance_time_comes_from_exact_session_get_readback(self):
        self.assertIn("Read back Jules session timing once", self.text)
        self.assertIn(
            "python -m automation.command_bus.jules_session_acceptance",
            self.text,
        )
        self.assertIn("--expected-session-id", self.text)
        self.assertIn(
            "https://jules.googleapis.com/v1alpha/sessions/${SESSION_ID}",
            self.text,
        )
        self.assertIn("session_create_time=", self.text)
        self.assertIn("accepted_at_jst=", self.text)
        self.assertIn(
            "JULES_SESSION_GET_CREATE_TIME_READBACK",
            self.text,
        )

    def test_acceptance_is_bound_to_isolated_work_branch(self):
        self.assertIn(
            "EXPECTED_BRANCH: ${{ steps.validate.outputs.work_branch }}",
            self.text,
        )
        self.assertIn("returned_branch=", self.text)
        self.assertIn(".sourceContext.githubRepoContext.startingBranch", self.text)
        self.assertIn(
            'if [[ "${returned_branch}" != "${EXPECTED_BRANCH}" ]]',
            self.text,
        )

    def test_summary_exposes_timing_evidence(self):
        self.assertIn(
            "SESSION_CREATE_TIME: ${{ steps.timing.outputs.session_create_time }}",
            self.text,
        )
        self.assertIn(
            "ACCEPTED_AT_JST: ${{ steps.timing.outputs.accepted_at_jst }}",
            self.text,
        )
        self.assertIn("jules_session_create_time:", self.text)
        self.assertIn("accepted_at_jst:", self.text)

    def test_no_local_clock_substitute(self):
        for value in (
            "github.event.head_commit.timestamp",
            "github.event.repository.pushed_at",
            "date -Iseconds",
            "date --iso-8601",
        ):
            self.assertNotIn(value, self.text)

if __name__ == "__main__":
    unittest.main()
