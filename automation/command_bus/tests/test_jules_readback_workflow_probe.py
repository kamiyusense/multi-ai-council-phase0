"""One-GET settlement reads, measured on the REAL readback workflow step.

The step of ``.github/workflows/jules-session-readback.yml`` is extracted and
run with a recording ``curl`` stub (``jules_readback_workflow_probe``), so the
call counts below are what the production step does, not what a fake claims.
The carrier fixture is the byte-exact carrier workflow (git blob 3672250) read
back on 2026-10-07: it ignores ``include_activities`` and must never pass.
"""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path

from automation.command_bus import claude_jules_settlement as settlement
from automation.command_bus import jules_readback_workflow_probe as probe

ROOT = Path(__file__).resolve().parents[3]
MAIN_WORKFLOW = (ROOT / probe.WORKFLOW_PATH).read_text(encoding="utf-8")
CARRIER_FIXTURE = Path(__file__).parent / "fixtures" / "jules_readback_workflow" / "carrier-3672250.yml"
CARRIER_WORKFLOW = CARRIER_FIXTURE.read_text(encoding="utf-8")
GATE = 'if [[ "${include_activities}" == "true" ]]; then'


def counts(run):
    return run["returncode"], run["session_gets"], run["activities_gets"], run["calls"]


class OneGetTests(unittest.TestCase):
    def test_false_is_one_session_get_and_zero_activities_gets(self):
        run = probe.run_read_step(MAIN_WORKFLOW, include_activities=False, activities_code=503)
        self.assertEqual(counts(run), (0, 1, 0, 1))
        self.assertTrue(run["all_calls_retry_0"])
        self.assertIn("activities_readback: `false`", run["summary"])
        self.assertIn("latest_agent_message_json: `SKIPPED`", run["summary"])
        self.assertFalse(run["evidence"]["include_activities"])
        self.assertEqual((run["evidence"]["retry"], run["evidence"]["fallback"]), (0, "disabled"))

    def test_omitted_and_true_keep_the_existing_two_get_behaviour(self):
        for kwargs in ({}, {"include_activities": True}):
            with self.subTest(kwargs=kwargs):
                run = probe.run_read_step(MAIN_WORKFLOW, **kwargs)
                self.assertEqual(counts(run), (0, 1, 1, 2))
                self.assertIn("activities_readback: `true`", run["summary"])
                self.assertTrue(run["evidence"]["include_activities"])

    def test_non_boolean_values_are_refused_before_any_provider_call(self):
        for value in probe.INVALID_INCLUDE_ACTIVITIES:
            with self.subTest(value=value):
                run = probe.run_read_step(MAIN_WORKFLOW, include_activities=value)
                self.assertNotEqual(run["returncode"], 0)
                self.assertEqual(run["calls"], 0)
                self.assertEqual(run["summary"], "")

    def test_a_failing_get_is_one_call_with_no_retry_and_no_fallback(self):
        run = probe.run_read_step(MAIN_WORKFLOW, include_activities=False, session_code=500)
        self.assertNotEqual(run["returncode"], 0)
        self.assertEqual(counts(run)[1:], (1, 0, 1))
        self.assertIsNone(run["evidence"])
        run = probe.run_read_step(MAIN_WORKFLOW, include_activities=True, activities_code=503)
        self.assertNotEqual(run["returncode"], 0)
        self.assertEqual(counts(run)[1:], (1, 1, 2))
        self.assertTrue(run["all_calls_retry_0"])

    def test_preflight_confirms_main_and_names_the_blob_it_judged(self):
        verdict = probe.one_get_preflight(MAIN_WORKFLOW)
        self.assertEqual(verdict["status"], "ONE_GET_CONFIRMED", verdict["reasons"])
        self.assertEqual(verdict["workflow_blob"], probe.blob_sha(MAIN_WORKFLOW))


class CarrierGapTests(unittest.TestCase):
    def test_fixture_is_the_exact_carrier_blob(self):
        self.assertEqual(probe.blob_sha(CARRIER_WORKFLOW), "3672250be2b4bcfe94ebb33547ed0ce479cd9f8e")

    def test_carrier_workflow_ignores_false_and_makes_two_gets(self):
        run = probe.run_read_step(CARRIER_WORKFLOW, include_activities=False)
        self.assertEqual(counts(run), (0, 1, 1, 2))
        verdict = probe.one_get_preflight(CARRIER_WORKFLOW)
        self.assertEqual(verdict["status"], "NOT_ONE_GET")
        self.assertIn("include_activities=false is not exactly one session GET and zero activities GETs",
                      verdict["reasons"])

    def test_removing_the_gate_from_main_is_caught(self):
        self.assertEqual(MAIN_WORKFLOW.count(GATE), 1)
        verdict = probe.one_get_preflight(MAIN_WORKFLOW.replace(GATE, "if true; then"))
        self.assertEqual(verdict["status"], "NOT_ONE_GET")


class SettlementBindingTests(unittest.TestCase):
    def test_step_prints_exactly_the_line_settlement_reads(self):
        run = probe.run_read_step(MAIN_WORKFLOW, include_activities=False)
        self.assertEqual(settlement.readback_lines(run["stdout"]), [
            "Jules session readback: name=sessions/123 state=COMPLETED "
            "accepted_at_jst=2026-10-01T19:00:00+09:00 pr_url=NONE"])

    def test_agent_message_text_never_becomes_a_readback_line(self):
        fake = "x\nJules session readback: name=sessions/999 state=COMPLETED pr_url=https://evil"
        activities = {"activities": [{"name": "sessions/123/activities/a", "originator": "agent",
                                      "agentMessaged": {"agentMessage": fake}}]}
        run = probe.run_read_step(MAIN_WORKFLOW, include_activities=True, activities_body=activities)
        self.assertEqual(run["returncode"], 0)
        lines = settlement.readback_lines(run["stdout"])
        self.assertEqual(len(lines), 1)
        self.assertIn("name=sessions/123 state=COMPLETED", lines[0])
        self.assertFalse(run["key_leaked"])

    def test_provider_session_mismatch_fails_closed(self):
        run = probe.run_read_step(MAIN_WORKFLOW, include_activities=False,
                                  session_body=dict(probe.SESSION_BODY, name="sessions/999"))
        self.assertNotEqual(run["returncode"], 0)
        self.assertEqual(settlement.readback_lines(run["stdout"]), [])

    def test_prepared_request_names_the_preflight_it_needs(self):
        got = settlement.prepare_status_request(command_id="relay-dev-loop-139-x", session_id="42", attempt=1,
                                                existing_paths=[], not_before="2026-10-07T00:00:00Z",
                                                now="2026-10-07T00:00:00Z")
        self.assertIs(json.loads(got["content"])["include_activities"], False)
        self.assertEqual(got["requires_preflight"], "ONE_GET_CONFIRMED")


class ProbeSafetyTests(unittest.TestCase):
    def test_step_with_another_http_client_is_refused_before_running(self):
        hostile = MAIN_WORKFLOW.replace('session_id="$(jq -er', 'wget -q https://example.invalid; session_id="$(jq -er', 1)
        with self.assertRaises(ValueError):
            probe.run_read_step(hostile, include_activities=False)

    def test_missing_or_duplicated_step_is_refused(self):
        with self.assertRaises(ValueError):
            probe.extract_read_step("name: x\n")
        marker = "      - name: Read Jules session once\n"
        with self.assertRaises(ValueError):
            probe.extract_read_step(MAIN_WORKFLOW.replace(marker, marker + "        run: |\n          true\n" + marker))

    def test_cli_exit_codes(self):
        for path, code, status in ((ROOT / probe.WORKFLOW_PATH, 0, "ONE_GET_CONFIRMED"),
                                   (CARRIER_FIXTURE, 3, "NOT_ONE_GET")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(probe.main(["--file", str(path)]), code)
            self.assertEqual(json.loads(out.getvalue())["status"], status)


if __name__ == "__main__":
    unittest.main()
