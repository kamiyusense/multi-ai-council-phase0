"""Run the REAL ``Read Jules session once`` step of jules-session-readback.yml.

The step is extracted from the workflow file (not copied into the test) and run
in bash with ``curl`` replaced by a local stub, so a regression in the workflow
itself fails here.  Hostile provider text (backticks, ``$(...)``, path
traversal in the activity name) must be rendered literally, never executed.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "jules-session-readback.yml"

CURL_STUB = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
out = args[args.index("--output") + 1]
url = args[-1]
spec = json.load(open(os.environ["STUB_SPEC"]))
kind = "activities" if "/activities" in url else "session"
open(out, "w").write(json.dumps(spec[kind]["body"]) if not isinstance(spec[kind]["body"], str) else spec[kind]["body"])
sys.stdout.write(str(spec[kind].get("code", 200)))
sys.exit(0 if int(spec[kind].get("code", 200)) < 400 else 22)
"""


def read_step() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("      - name: Read Jules session once")
    run = text.index("        run: |\n", start) + len("        run: |\n")
    block = []
    for line in text[run:].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        block.append(line[10:] if line.startswith("          ") else "")
    return "\n".join(block) + "\n"


SESSION = {"name": "sessions/123", "state": "COMPLETED", "createTime": "2026-10-01T10:00:00Z",
           "updateTime": "2026-10-01T10:00:05Z",
           "sourceContext": {"source": "sources/github/kamiyusense/multi-ai-council-phase0",
                             "githubRepoContext": {"startingBranch": "x"}}, "outputs": []}


def run_step(session=None, activities=None, *, session_code=200, activities_code=200, include_activities=None):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "curl"
        stub.write_text(CURL_STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        spec = tmp / "spec.json"
        spec.write_text(json.dumps({
            "session": {"body": SESSION if session is None else session, "code": session_code},
            "activities": {"body": activities if activities is not None else {}, "code": activities_code}}))
        status = tmp / "status.json"
        status_payload = {"session_id": "123"}
        if include_activities is not None:
            status_payload["include_activities"] = include_activities
        status.write_text(json.dumps(status_payload))
        summary = tmp / "summary.md"
        runner_temp = tmp / "rt"
        runner_temp.mkdir()
        script = tmp / "step.sh"
        script.write_text("set -euo pipefail\n" + read_step())
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", STUB_SPEC=str(spec),
                   STATUS_PATH=str(status), GITHUB_STEP_SUMMARY=str(summary), RUNNER_TEMP=str(runner_temp),
                   JULES_API_KEY="stub", PYTHONPATH=str(ROOT))
        result = subprocess.run(["bash", str(script)], cwd=ROOT, env=env, capture_output=True, text=True)
        text = summary.read_text() if summary.exists() else ""
        evidence_path = runner_temp / "jules-session-readback-evidence.json"
        evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else None
        return result, text, evidence


class ReadbackStepExecutionTests(unittest.TestCase):
    def test_hostile_message_text_is_rendered_literally_never_executed(self):
        with tempfile.TemporaryDirectory() as marker_dir:
            marker = Path(marker_dir) / "pwned"
            hostile = f"`touch {marker}` $(touch {marker}) ${{x}} \"; touch {marker}; \""
            activities = {"activities": [{"name": "sessions/123/activities/abc", "originator": "agent",
                                          "agentMessaged": {"agentMessage": hostile}}]}
            result, summary, _ = run_step(activities=activities)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), "provider text was executed as shell")
            self.assertNotIn("command not found", result.stderr)
            self.assertIn("latest_agent_activity_name: `sessions/123/activities/abc`", summary)
            self.assertIn("touch", summary)  # shown as data
            self.assertIn("accepted_at_jst: `2026-10-01T19:00:00+09:00`", summary)

    def test_bad_activity_names_are_reported_unknown(self):
        for name in ("sessions/123/activities/..", "sessions/123/activities/.", "sessions/123/activities/a b",
                     "sessions/999/activities/abc", "sessions/123/activities/a/../b", ""):
            with self.subTest(name=name):
                activities = {"activities": [{"name": name, "originator": "agent",
                                              "agentMessaged": {"agentMessage": "hi"}}]}
                result, summary, _ = run_step(activities=activities)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("latest_agent_activity_name: `UNKNOWN`", summary)

    def test_message_and_name_come_from_the_same_latest_agent_record(self):
        activities = {"activities": [
            {"name": "sessions/123/activities/one", "originator": "agent", "agentMessaged": {"agentMessage": "first"}},
            {"name": "sessions/123/activities/two", "originator": "user", "userMessaged": {"userMessage": "u"}},
            {"name": "sessions/123/activities/three", "originator": "agent", "agentMessaged": {"agentMessage": "last"}},
        ]}
        _, summary, _ = run_step(activities=activities)
        self.assertIn("activities/three", summary)
        self.assertIn("`\"last\"`", summary)
        self.assertNotIn("first", summary)

    def test_no_agent_message_is_none_not_a_guess(self):
        _, summary, _ = run_step(activities={"activities": []})
        self.assertIn("latest_agent_activity_name: `UNKNOWN`", summary)
        self.assertIn("latest_agent_message_json: `NONE`", summary)

    def test_failures_fail_closed_without_a_summary(self):
        cases = {
            "session http error": dict(session_code=500),
            "activities http error": dict(activities_code=503),
            "session without createTime": dict(session={"name": "sessions/123", "state": "COMPLETED"}),
            "session id mismatch": dict(session=dict(SESSION, name="sessions/999")),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                result, summary, _ = run_step(**kwargs)
                self.assertNotEqual(result.returncode, 0, label)
                self.assertNotIn("latest_agent_message_json", summary)

    def test_active_proof_can_skip_activities_get(self):
        result, summary, evidence = run_step(
            include_activities=False,
            activities_code=503,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("activities_readback: `false`", summary)
        self.assertIn("latest_agent_activity_name: `SKIPPED`", summary)
        self.assertIn("latest_agent_message_json: `SKIPPED`", summary)
        self.assertIsNotNone(evidence)
        self.assertFalse(evidence["include_activities"])

    def test_sanitized_artifact_preserves_runtime_binding_fields_only(self):
        result, _, evidence = run_step()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            evidence,
            {
                "schema_version": 1,
                "proof_kind": "JULES_SESSION_READBACK_SANITIZED",
                "session_id": "123",
                "name": "sessions/123",
                "state": "COMPLETED",
                "create_time": "2026-10-01T10:00:00Z",
                "update_time": "2026-10-01T10:00:05Z",
                "provider_source": "sources/github/kamiyusense/multi-ai-council-phase0",
                "starting_branch": "x",
                "include_activities": True,
                "retry": 0,
                "fallback": "disabled",
            },
        )
        serialized = json.dumps(evidence)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("X-Goog-Api-Key", serialized)
        self.assertNotIn("eyJ", serialized)
        self.assertNotIn("https://", serialized)

    def test_workflow_makes_only_the_two_readonly_gets(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"--retry 0", text)), 3)  # locate + session + activities
        self.assertNotIn("-X POST", text)
        self.assertNotIn("sendMessage", text)


if __name__ == "__main__":
    unittest.main()
