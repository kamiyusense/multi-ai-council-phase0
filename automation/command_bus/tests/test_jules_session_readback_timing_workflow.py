from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "jules-session-readback.yml"


class JulesSessionReadbackTimingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_session_get_remains_single_retry_zero_readback(self):
        self.assertEqual(
            self.text.count('"https://jules.googleapis.com/v1alpha/sessions/${session_id}"'),
            1,
        )
        self.assertIn("--retry 0", self.text)
        self.assertIn("Read Jules session once", self.text)

    def test_timing_is_extracted_from_same_get_response(self):
        self.assertIn(
            "python -m automation.command_bus.jules_session_acceptance",
            self.text,
        )
        self.assertIn(
            '"${response_file}" --expected-session-id "${session_id}"',
            self.text,
        )
        self.assertIn("session_create_time=", self.text)
        self.assertIn("accepted_at_jst=", self.text)
        # The summary is rendered with printf (no backtick command substitution).
        self.assertIn("accepted_at_source: `%s`", self.text)
        self.assertIn('"JULES_SESSION_GET_CREATE_TIME_READBACK"', self.text)

    def test_readback_does_not_use_local_or_github_clock_as_acceptance_source(self):
        forbidden = (
            "github.event.head_commit.timestamp",
            "github.event.repository.pushed_at",
            "date -Iseconds",
            "date --iso-8601",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.text)

    def test_existing_status_request_and_numeric_session_gate_remain(self):
        self.assertIn("STATUS_PATH: ${{ steps.locate.outputs.path }}", self.text)
        self.assertIn("session_id=\"$(jq -er '.session_id' \"${STATUS_PATH}\")\"", self.text)
        self.assertIn(
            '[[ "${session_id}" =~ ^[0-9]+$ ]]',
            self.text,
        )

    def test_sanitized_evidence_reuses_same_session_get(self):
        self.assertIn('update_time="$(jq -r '.updateTime // ""' "${response_file}")"', self.text)
        self.assertIn('provider_source="$(jq -r '.sourceContext.source // ""' "${response_file}")"', self.text)
        self.assertIn(
            'starting_branch="$(jq -r '.sourceContext.githubRepoContext.startingBranch // ""' "${response_file}")"',
            self.text,
        )
        self.assertIn("JULES_SESSION_READBACK_SANITIZED", self.text)
        self.assertIn("jules-session-readback-evidence.json", self.text)
        self.assertEqual(
            self.text.count('"https://jules.googleapis.com/v1alpha/sessions/${session_id}"'),
            1,
        )

    def test_activities_readback_can_be_disabled_without_another_session_get(self):
        self.assertIn('include_activities="$(jq -er', self.text)
        self.assertIn('if [[ "${include_activities}" == "true" ]]; then', self.text)
        self.assertIn('latest_agent_message_json="SKIPPED"', self.text)
        self.assertIn('latest_agent_activity_name="SKIPPED"', self.text)

    def test_readback_workflow_adds_no_new_create_session_post(self):
        self.assertNotIn("-X POST", self.text)
        self.assertNotIn("--data-binary @jules_payload.json", self.text)


if __name__ == "__main__":
    unittest.main()
