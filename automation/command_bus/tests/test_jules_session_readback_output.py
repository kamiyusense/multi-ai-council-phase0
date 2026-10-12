import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/jules-session-readback.yml")

class TestJulesSessionReadbackOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_properties_preserved(self):
        # Triggers and permissions
        self.assertIn("feature/chat-work-command-bus", self.text)
        self.assertIn("automation/command_bus/jules_api_status_requests/*.json", self.text)
        self.assertIn("permissions:\n  contents: read", self.text)

        # GET endpoints
        self.assertIn("https://jules.googleapis.com/v1alpha/sessions/${session_id}", self.text)
        self.assertIn("https://jules.googleapis.com/v1alpha/sessions/${session_id}/activities", self.text)

        # Retry 0
        self.assertEqual(self.text.count("--retry 0"), 3)

        # No POST or added API calls
        self.assertNotIn("POST", self.text)
        self.assertNotIn("sendMessage", self.text)

        # Bounded proof mode and sanitized artifact are explicit.
        self.assertIn("include_activities", self.text)
        self.assertIn("JULES_SESSION_READBACK_SANITIZED", self.text)
        self.assertIn("jules-session-readback-evidence.json", self.text)
        self.assertIn(
            "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            self.text,
        )
        self.assertIn("persist-credentials: false", self.text)

    def test_single_record_extraction_pattern(self):
        # Assert extraction uses last // empty on full activity
        self.assertIn("latest_agent_activity=\"$(jq -c '[.activities[]? | select(.originator == \"agent\" and .agentMessaged.agentMessage != null)] | last // empty' \"${activities_file}\")\"", self.text)
        # Assert extraction of message and name from the same record
        self.assertIn("latest_agent_message_json=\"$(jq -c '.agentMessaged.agentMessage' <<<\"${latest_agent_activity}\")\"", self.text)
        self.assertIn("latest_agent_activity_name=\"$(jq -r '.name // \"UNKNOWN\"' <<<\"${latest_agent_activity}\")\"", self.text)

    def test_fail_closed_activity_name_checking(self):
        # Assert regex and boundary check for activity id
        self.assertIn("if [[ ! \"${activity_id}\" =~ ^[A-Za-z0-9._-]+$ ]] || [[ \"${activity_id}\" == \".\" ]] || [[ \"${activity_id}\" == \"..\" ]]; then", self.text)
        self.assertIn("latest_agent_activity_name=\"UNKNOWN\"", self.text)

    def test_static_printf_format_strings(self):
        # Assert printf usage and lack of eval/backticks in summary
        self.assertIn("printf '## Jules session readback\\n'", self.text)
        self.assertIn("printf -- '- session_id: `%s`\\n' \"${session_id}\"", self.text)
        self.assertIn("printf -- '- state: `%s`\\n' \"${state}\"", self.text)
        self.assertIn("printf -- '- pull_request: `%s`\\n' \"${pr_url:-NONE}\"", self.text)
        self.assertIn("printf -- '- activities_readback: `%s`\\n' \"${include_activities}\"", self.text)
        self.assertIn("printf -- '- latest_agent_activity_name: `%s`\\n' \"${latest_agent_activity_name}\"", self.text)
        self.assertIn("printf -- '- latest_agent_message_json: `%s`\\n' \"${latest_agent_message_json}\"", self.text)
        self.assertNotIn("echo \"- session_id: `${session_id}`\"", self.text)
        self.assertNotIn("eval", self.text)

    @unittest.skipUnless(
        Path("/bin/bash").exists() and shutil.which("jq") is not None,
        "/bin/bash or jq is unavailable",
    )
    def test_isolated_bash_execution_safety(self):
        script = """
set -euo pipefail

session_id="123"
state="COMPLETED"
pr_url=""
activities_file="mock_activities.json"

cat << 'EOF' > "${activities_file}"
{
  "activities": [
    {
      "name": "sessions/123/activities/abc",
      "originator": "agent",
      "agentMessaged": {
        "agentMessage": {"text": "`command`"}
      }
    }
  ]
}
EOF

latest_agent_activity="$(jq -c '[.activities[]? | select(.originator == "agent" and .agentMessaged.agentMessage != null)] | last // empty' "${activities_file}")"

if [[ -z "${latest_agent_activity}" ]]; then
  latest_agent_message_json="NONE"
  latest_agent_activity_name="UNKNOWN"
else
  latest_agent_message_json="$(jq -c '.agentMessaged.agentMessage' <<<"${latest_agent_activity}")"
  latest_agent_activity_name="$(jq -r '.name // "UNKNOWN"' <<<"${latest_agent_activity}")"

  prefix="sessions/${session_id}/activities/"
  if [[ "${latest_agent_activity_name}" == "${prefix}"* ]]; then
    activity_id="${latest_agent_activity_name#${prefix}}"
    if [[ ! "${activity_id}" =~ ^[A-Za-z0-9._-]+$ ]] || [[ "${activity_id}" == "." ]] || [[ "${activity_id}" == ".." ]]; then
      latest_agent_activity_name="UNKNOWN"
    fi
  else
    latest_agent_activity_name="UNKNOWN"
  fi
fi

GITHUB_STEP_SUMMARY="mock_summary.md"
{
  printf '## Jules session readback\\n'
  printf -- '- session_id: `%s`\\n' "${session_id}"
  printf -- '- state: `%s`\\n' "${state}"
  printf -- '- pull_request: `%s`\\n' "${pr_url:-NONE}"
  printf -- '- latest_agent_activity_name: `%s`\\n' "${latest_agent_activity_name}"
  printf -- '- latest_agent_message_json: `%s`\\n' "${latest_agent_message_json}"
} >> "${GITHUB_STEP_SUMMARY}"

cat "${GITHUB_STEP_SUMMARY}"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "test_script.sh"
            script_path.write_text(script)

            result = subprocess.run(
                ["/bin/bash", str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                check=True
            )

            self.assertIn("- session_id: `123`", result.stdout)
            self.assertIn("- latest_agent_activity_name: `sessions/123/activities/abc`", result.stdout)
            self.assertIn("- latest_agent_message_json: `{\"text\":\"`command`\"}`", result.stdout)
            self.assertNotIn("command not found", result.stderr)
            self.assertEqual(result.stderr, "")

    @unittest.skipUnless(
        Path("/bin/bash").exists() and shutil.which("jq") is not None,
        "/bin/bash or jq is unavailable",
    )
    def test_isolated_bash_execution_safety_no_activities(self):
        script = """
set -euo pipefail

session_id="123"
state="COMPLETED"
pr_url=""
activities_file="mock_activities.json"

cat << 'EOF' > "${activities_file}"
{}
EOF

latest_agent_activity="$(jq -c '[.activities[]? | select(.originator == "agent" and .agentMessaged.agentMessage != null)] | last // empty' "${activities_file}")"

if [[ -z "${latest_agent_activity}" ]]; then
  latest_agent_message_json="NONE"
  latest_agent_activity_name="UNKNOWN"
else
  latest_agent_message_json="$(jq -c '.agentMessaged.agentMessage' <<<"${latest_agent_activity}")"
  latest_agent_activity_name="$(jq -r '.name // "UNKNOWN"' <<<"${latest_agent_activity}")"

  prefix="sessions/${session_id}/activities/"
  if [[ "${latest_agent_activity_name}" == "${prefix}"* ]]; then
    activity_id="${latest_agent_activity_name#${prefix}}"
    if [[ ! "${activity_id}" =~ ^[A-Za-z0-9._-]+$ ]] || [[ "${activity_id}" == "." ]] || [[ "${activity_id}" == ".." ]]; then
      latest_agent_activity_name="UNKNOWN"
    fi
  else
    latest_agent_activity_name="UNKNOWN"
  fi
fi

GITHUB_STEP_SUMMARY="mock_summary.md"
{
  printf '## Jules session readback\\n'
  printf -- '- session_id: `%s`\\n' "${session_id}"
  printf -- '- state: `%s`\\n' "${state}"
  printf -- '- pull_request: `%s`\\n' "${pr_url:-NONE}"
  printf -- '- latest_agent_activity_name: `%s`\\n' "${latest_agent_activity_name}"
  printf -- '- latest_agent_message_json: `%s`\\n' "${latest_agent_message_json}"
} >> "${GITHUB_STEP_SUMMARY}"

cat "${GITHUB_STEP_SUMMARY}"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "test_script.sh"
            script_path.write_text(script)

            result = subprocess.run(
                ["/bin/bash", str(script_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                check=True
            )

            self.assertIn("- latest_agent_activity_name: `UNKNOWN`", result.stdout)
            self.assertIn("- latest_agent_message_json: `NONE`", result.stdout)

if __name__ == "__main__":
    unittest.main()
