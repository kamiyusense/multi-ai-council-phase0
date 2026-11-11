from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from phase0_core.comparison import MatchState, compare_responses
from phase0_core.evidence import capture_then_parse, diff_snapshots, mask_known_secrets, snapshot_tree
from phase0_core.fanout import FanoutDecision, FanoutGate
from phase0_core.mock_provider import MockProviderAdapter
from phase0_core.models import MarkerEchoes, ProviderManifest, ProviderResponse
from phase0_core.reporting import render_japanese_summary
from phase0_core.runner import CaseRunner, ExecutionMode
from phase0_core.states import AnswerState, CapabilityState, ExecutionState, can_transition
from phase0_core.stop import StopController
from phase0_core.validators import (
    parse_provider_response,
    validate_post_execution_model,
    validate_provider_manifest,
    validate_timeout,
)
from phase0_core.workspace import ensure_within, validate_snapshot_tree


class ManifestTests(unittest.TestCase):
    def test_safe_defaults(self):
        manifest = ProviderManifest(provider="openai", cli_name="codex")
        self.assertEqual(manifest.retry_count, 0)
        self.assertEqual(manifest.fallback_state, "disabled")
        self.assertEqual(manifest.capability_state, CapabilityState.UNKNOWN)
        self.assertFalse(manifest.permission_profile.git_write)

    def test_live_gate_fails_closed(self):
        manifest = ProviderManifest(provider="openai", cli_name="codex")
        result = validate_provider_manifest(manifest, live_gate=True)
        self.assertFalse(result.valid)
        self.assertTrue(any("timeout" in x for x in result.errors))
        self.assertTrue(any("subscription" in x for x in result.errors))
        self.assertFalse(any("executed model verification" in x for x in result.errors))

    def test_post_execution_model_verification(self):
        manifest = ProviderManifest(
            provider="openai",
            cli_name="codex",
            requested_model="m1",
            configured_model="m1",
            executed_model="m1",
            executed_model_verified=True,
            executed_model_verification_source="provider-process-evidence",
        )
        self.assertTrue(validate_post_execution_model(manifest).valid)
        manifest.executed_model = "m2"
        result = validate_post_execution_model(manifest)
        self.assertFalse(result.valid)
        self.assertTrue(any("mismatch" in x for x in result.errors))

    def test_timeout_contract(self):
        for invalid in (None, 0, -1, True, 1.5, "60"):
            self.assertFalse(validate_timeout(invalid).valid, invalid)
        self.assertTrue(validate_timeout(60).valid)


class StateTests(unittest.TestCase):
    def test_terminal_state_does_not_restart(self):
        self.assertTrue(can_transition(ExecutionState.READY, ExecutionState.RUNNING))
        self.assertFalse(can_transition(ExecutionState.TIMEOUT, ExecutionState.RUNNING))


class FanoutTests(unittest.TestCase):
    def test_unknown_is_not_pass(self):
        gate = FanoutGate()
        result = gate.evaluate("ordinary question", externally_shareable=None, contains_private_code=False)
        self.assertEqual(result.decision, FanoutDecision.UNKNOWN)

    def test_secret_blocks(self):
        gate = FanoutGate()
        result = gate.evaluate("token sk-abcdefghijklmnopqrstuvw", externally_shareable=True, contains_private_code=False)
        self.assertEqual(result.decision, FanoutDecision.BLOCK)

    def test_confirmed_safe_passes(self):
        gate = FanoutGate()
        result = gate.evaluate("ordinary question", externally_shareable=True, contains_private_code=False)
        self.assertEqual(result.decision, FanoutDecision.PASS)


class ResponseTests(unittest.TestCase):
    def payload(self):
        return {
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "YES",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": ["sha256:abc"],
            "marker_echoes": {"head": "h", "middle": "m", "tail": "t"},
            "answer_text": "answer",
        }

    def test_parse_valid(self):
        response = parse_provider_response(self.payload(), allowed_conclusion_codes={"YES", "NO"})
        self.assertEqual(response.conclusion_code, "YES")

    def test_missing_required_invalid(self):
        payload = self.payload()
        del payload["safety_warning"]
        with self.assertRaises(ValueError):
            parse_provider_response(payload, allowed_conclusion_codes={"YES", "NO"})

    def test_unknown_safety_is_preserved(self):
        payload = self.payload()
        payload["safety_warning"] = "UNKNOWN"
        response = parse_provider_response(payload, allowed_conclusion_codes={"YES"})
        self.assertEqual(response.safety_warning, "UNKNOWN")


class EvidenceTests(unittest.TestCase):
    def test_raw_saved_before_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "response.raw"
            seen = []

            def parser(data: bytes):
                seen.append(path.exists())
                return json.loads(data)

            parsed = capture_then_parse(path, b'{"ok": true}', parser)
            self.assertEqual(parsed, {"ok": True})
            self.assertEqual(seen, [True])

    def test_fs_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("one", encoding="utf-8")
            before = snapshot_tree(root)
            (root / "a.txt").write_text("two", encoding="utf-8")
            (root / "b.txt").write_text("new", encoding="utf-8")
            after = snapshot_tree(root)
            diff = diff_snapshots(before, after)
            self.assertEqual([x.path for x in diff.modified], ["a.txt"])
            self.assertEqual([x.path for x in diff.created], ["b.txt"])

    def test_mask_known_secret(self):
        text = "sk-abcdefghijklmnopqrstuvw"
        self.assertNotIn("sk-", mask_known_secrets(text))


class WorkspaceTests(unittest.TestCase):
    def test_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            root.mkdir()
            with self.assertRaises(ValueError):
                ensure_within(root, root / ".." / "escape")

    def test_forbidden_snapshot_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("x", encoding="utf-8")
            self.assertTrue(validate_snapshot_tree(root))


class ComparisonTests(unittest.TestCase):
    def response(self, code="YES", evidence=("e1",), safety="ABSENT"):
        return ProviderResponse(
            answer_state=AnswerState.ANSWER,
            conclusion_code=code,
            safety_warning=safety,
            safety_reason=None,
            evidence_refs=evidence,
            marker_echoes=MarkerEchoes("h", "m", "t"),
            answer_text="text",
        )

    def test_exact_three_way(self):
        result = compare_responses({"a": self.response(), "b": self.response(), "c": self.response()})
        self.assertEqual(result.conclusion_match_state, MatchState.EXACT)
        self.assertEqual(result.evidence_match_state, MatchState.EXACT)
        self.assertEqual(result.agreement_count, 3)
        self.assertFalse(result.formal_consensus)
        self.assertTrue(result.human_required)

    def test_two_of_three_not_formal_consensus(self):
        result = compare_responses({"a": self.response(), "b": self.response(), "c": self.response(code="NO")})
        self.assertEqual(result.agreement_count, 2)
        self.assertEqual(result.conclusion_match_state, MatchState.DIFFERENT)
        self.assertFalse(result.formal_consensus)

    def test_safety_unknown_blocks(self):
        result = compare_responses({"a": self.response(safety="UNKNOWN")})
        self.assertTrue(result.safety_block)
        self.assertTrue(result.human_required)

    def test_japanese_report_keeps_human_final(self):
        responses = {"openai": self.response()}
        report = render_japanese_summary(responses, compare_responses(responses))
        self.assertIn("最終判断: 人間", report)
        self.assertIn("自動昇格しない", report)


class RunnerTests(unittest.TestCase):
    def test_snapshot_not_created_before_gate_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = CaseRunner(Path(tmp), FanoutGate(), StopController())
            result = runner.prepare_case(
                case_id="case-1",
                user_input="ordinary",
                packet="packet",
                providers=("openai", "anthropic"),
                externally_shareable=None,
                contains_private_code=False,
            )
            self.assertFalse(result["prepared"])
            self.assertFalse((Path(tmp) / "case-1" / "providers").exists())

    def test_snapshot_created_only_after_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = CaseRunner(Path(tmp), FanoutGate(), StopController())
            result = runner.prepare_case(
                case_id="case-2",
                user_input="ordinary",
                packet="packet",
                providers=("openai", "anthropic"),
                externally_shareable=True,
                contains_private_code=False,
            )
            self.assertTrue(result["prepared"])
            self.assertTrue((Path(tmp) / "case-2" / "providers" / "openai" / "snapshot").is_dir())

    def test_live_mode_hard_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = CaseRunner(Path(tmp), FanoutGate(), StopController())
            adapter = MockProviderAdapter("openai", b'{"ok":true}')
            with self.assertRaises(RuntimeError):
                runner.execute_with_adapter(
                    adapter=adapter,
                    case_context={},
                    raw_path=Path(tmp) / "raw",
                    mode=ExecutionMode.LIVE,
                )
            self.assertEqual(adapter.dispatch_count, 0)
            self.assertEqual(adapter.live_execution_count, 0)

    def test_mock_execution_and_raw_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = CaseRunner(Path(tmp), FanoutGate(), StopController())
            adapter = MockProviderAdapter("openai", b'{"ok":true}')
            raw_path = Path(tmp) / "response.raw"
            result = runner.execute_with_adapter(
                adapter=adapter,
                case_context={"x": 1},
                raw_path=raw_path,
                mode=ExecutionMode.MOCK,
            )
            self.assertEqual(result["state"], "SIMULATED")
            self.assertTrue(raw_path.exists())
            self.assertEqual(adapter.dispatch_count, 1)
            self.assertEqual(adapter.live_execution_count, 0)

    def test_stop_prevents_new_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop = StopController()
            stop.request_stop("test")
            runner = CaseRunner(Path(tmp), FanoutGate(), stop)
            adapter = MockProviderAdapter("openai")
            with self.assertRaises(RuntimeError):
                runner.execute_with_adapter(
                    adapter=adapter,
                    case_context={},
                    raw_path=Path(tmp) / "raw",
                    mode=ExecutionMode.MOCK,
                )
            self.assertEqual(adapter.dispatch_count, 0)


if __name__ == "__main__":
    unittest.main()
