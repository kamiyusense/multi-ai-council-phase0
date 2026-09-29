from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from phase0_core.fanout import FanoutGate
from phase0_core.mock_provider import MockProviderAdapter
from phase0_core.runner import CaseRunner
from phase0_core.states import ExecutionState, ParticipationState
from phase0_core.stop import StopController

FIXTURES = Path(__file__).parents[1] / "fixtures" / "core"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FullPipelineTests(unittest.TestCase):
    def adapters(self):
        raw = fixture("valid_answer_yes.json")
        return {name: MockProviderAdapter(name, raw) for name in ("openai", "anthropic", "google")}

    def run_case(self, root: Path, adapters=None, *, shareable=True):
        return CaseRunner(root, FanoutGate(), StopController()).run_mock_council(
            case_id="case-e2e",
            user_input="shareable fixture question",
            packet="fixture packet",
            adapters=adapters or self.adapters(),
            allowed_conclusion_codes={"YES", "NO", "UNKNOWN"},
            externally_shareable=shareable,
            contains_private_code=False,
            base_commit="fixture-sha",
        )

    def test_three_provider_e2e_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_case(Path(tmp))
            self.assertEqual(result["comparison"].participant_count, 3)
            self.assertEqual(result["comparison"].agreement_count, 3)
            self.assertFalse(result["comparison"].formal_consensus)
            self.assertIn("最終判断: 人間", result["report"])
            for provider in ("openai", "anthropic", "google"):
                base = result["case_root"] / "providers" / provider
                for name in ("manifest.json", "response.raw", "provider_state.json", "fs_diff.json"):
                    self.assertTrue((base / name).exists())

    def test_checkpoint_proves_no_live_retry_or_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_case(Path(tmp))
            cp = json.loads((result["case_root"] / "evidence" / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertFalse(cp["live_turn_executed"])
            self.assertEqual(cp["retry_count"], 0)
            self.assertEqual(cp["fallback_state"], "disabled")
            self.assertEqual(cp["FAIL"], [])
            self.assertEqual(cp["UNKNOWN"], [])

    def test_invalid_output_isolated_and_raw_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            adapters["google"] = MockProviderAdapter("google", fixture("invalid_missing_field.json"))
            result = self.run_case(Path(tmp), adapters)
            google = result["provider_results"]["google"]
            self.assertEqual(google.execution_state, ExecutionState.INVALID_OUTPUT)
            self.assertEqual(google.participation_state, ParticipationState.NONPARTICIPANT)
            self.assertEqual(result["comparison"].participant_count, 2)
            self.assertTrue((result["case_root"] / "providers" / "google" / "response.raw").exists())
            cp = json.loads((result["case_root"] / "evidence" / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertIn("google:INVALID_OUTPUT", cp["FAIL"])

    def test_invalid_json_is_invalid_output_with_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            adapters["google"] = MockProviderAdapter("google", fixture("invalid_json.raw"))
            result = self.run_case(Path(tmp), adapters)
            self.assertEqual(result["provider_results"]["google"].execution_state, ExecutionState.INVALID_OUTPUT)
            self.assertEqual((result["case_root"] / "providers" / "google" / "response.raw").read_bytes(), fixture("invalid_json.raw"))

    def test_error_unknown_isolated_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            bad = MockProviderAdapter("google", fail_collect=True)
            adapters["google"] = bad
            result = self.run_case(Path(tmp), adapters)
            self.assertEqual(result["provider_results"]["google"].execution_state, ExecutionState.ERROR_UNKNOWN)
            self.assertEqual(bad.dispatch_count, 1)
            self.assertEqual(bad.collect_count, 1)
            cp = json.loads((result["case_root"] / "evidence" / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertIn("google:ERROR_UNKNOWN", cp["UNKNOWN"])

    def test_timeout_is_distinct_without_retry(self):
        class TimeoutAdapter:
            provider_id = "google"
            dispatch_count = 0
            collect_count = 0
            def prepare(self, x): return dict(x)
            def preflight(self, x): return {"ok": True}
            def dispatch(self, x): self.dispatch_count += 1; return object()
            def collect(self, h): self.collect_count += 1; raise TimeoutError("fixture timeout")
            def abort(self, h): return {"aborted": True}
            def classify(self, raw): return {}

        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            timed = TimeoutAdapter()
            adapters["google"] = timed
            result = self.run_case(Path(tmp), adapters)
            self.assertEqual(result["provider_results"]["google"].execution_state, ExecutionState.TIMEOUT)
            self.assertEqual((timed.dispatch_count, timed.collect_count), (1, 1))
            cp = json.loads((result["case_root"] / "evidence" / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertIn("google:TIMEOUT", cp["FAIL"])

    def test_preflight_block_never_dispatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            blocked = MockProviderAdapter("google", preflight_ok=False)
            adapters["google"] = blocked
            result = self.run_case(Path(tmp), adapters)
            self.assertEqual(result["provider_results"]["google"].execution_state, ExecutionState.ERROR_UNKNOWN)
            self.assertEqual(blocked.dispatch_count, 0)

    def test_safety_unknown_blocks_automatic_agreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            adapters["google"] = MockProviderAdapter("google", fixture("safety_unknown.json"))
            result = self.run_case(Path(tmp), adapters)
            self.assertTrue(result["comparison"].safety_block)
            self.assertTrue(result["comparison"].human_required)

    def test_two_of_three_is_not_formal_consensus(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            adapters["google"] = MockProviderAdapter("google", fixture("valid_answer_no.json"))
            result = self.run_case(Path(tmp), adapters)
            self.assertEqual(result["comparison"].agreement_count, 2)
            self.assertFalse(result["comparison"].formal_consensus)

    def test_unknown_fanout_stops_before_snapshot_and_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            result = self.run_case(Path(tmp), adapters, shareable=None)
            self.assertIsNone(result["comparison"])
            self.assertFalse((result["case_root"] / "providers").exists())
            self.assertTrue(all(a.dispatch_count == 0 for a in adapters.values()))

    def test_unknown_response_field_is_invalid_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            adapters["google"] = MockProviderAdapter("google", fixture("invalid_unknown_field.json"))
            result = self.run_case(Path(tmp), adapters)
            self.assertEqual(result["provider_results"]["google"].execution_state, ExecutionState.INVALID_OUTPUT)

    def test_report_masks_known_secret_in_error(self):
        class SecretError:
            provider_id = "google"
            def prepare(self, x): return dict(x)
            def preflight(self, x): return {"ok": True}
            def dispatch(self, x): return object()
            def collect(self, h): raise RuntimeError("failure sk-abcdefghijklmnopqrstuvw")
            def abort(self, h): return {"aborted": True}
            def classify(self, raw): return {}

        with tempfile.TemporaryDirectory() as tmp:
            adapters = self.adapters()
            adapters["google"] = SecretError()
            result = self.run_case(Path(tmp), adapters)
            self.assertNotIn("sk-abcdefghijklmnopqrstuvw", result["report"])
            self.assertIn("[REDACTED_SECRET]", result["report"])


if __name__ == "__main__":
    unittest.main()
