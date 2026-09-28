import ast
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from providers.live_readiness_bundle import (
    build_live_readiness_bundle,
    render_live_readiness_summary_ja,
    PROVIDER_ORDER,
)

from .test_live_readiness import valid_preflight, valid_proofs


def valid_bundle_input():
    return {
        "openai": {
            "preflight": valid_preflight("openai"),
            "proofs": valid_proofs("openai"),
        },
        "anthropic": {
            "preflight": valid_preflight("anthropic"),
            "proofs": valid_proofs("anthropic"),
        },
        "google": {
            "preflight": valid_preflight("google"),
            "proofs": valid_proofs("google"),
        },
    }


class TestLiveReadinessBundle(unittest.TestCase):
    def assert_blocked(self, result: dict) -> None:
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertIs(result["live_ready"], False)
        self.assertIs(result["dispatch_allowed"], False)
        self.assertIs(result["human_approval_required"], True)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")
        self.assertIn("packet_sha256", result)

    def assert_ready_for_human_only(self, result: dict) -> None:
        self.assertEqual(result["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertIs(result["live_ready"], False)
        self.assertIs(result["dispatch_allowed"], False)
        self.assertIs(result["human_approval_required"], True)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")
        self.assertEqual(result["blocking_providers"], [])
        self.assertEqual(
            result["provider_states"],
            {
                "openai": "READY_FOR_HUMAN_APPROVAL",
                "anthropic": "READY_FOR_HUMAN_APPROVAL",
                "google": "READY_FOR_HUMAN_APPROVAL",
            }
        )
        self.assertIn("packet_sha256", result)

    def test_successful_bundle(self):
        result = build_live_readiness_bundle(valid_bundle_input())
        self.assert_ready_for_human_only(result)
        self.assertEqual(result["provider_order"], ["openai", "anthropic", "google"])

    def test_single_provider_blocked(self):
        for blocked_provider in PROVIDER_ORDER:
            with self.subTest(provider=blocked_provider):
                payload = valid_bundle_input()
                # Break one proof to make it block
                payload[blocked_provider]["proofs"].pop("finite_timeout", None)

                result = build_live_readiness_bundle(payload)
                self.assert_blocked(result)
                self.assertEqual(result["blocking_providers"], [blocked_provider])

                states = result["provider_states"]
                self.assertEqual(states[blocked_provider], "BLOCKED_UNKNOWN")
                for other in set(PROVIDER_ORDER) - {blocked_provider}:
                    self.assertEqual(states[other], "READY_FOR_HUMAN_APPROVAL")

    def test_two_providers_blocked(self):
        payload = valid_bundle_input()
        payload["openai"]["proofs"].pop("finite_timeout", None)
        payload["google"]["proofs"].pop("finite_timeout", None)

        result = build_live_readiness_bundle(payload)
        self.assert_blocked(result)
        self.assertEqual(result["blocking_providers"], ["openai", "google"])

    def test_malformed_inputs_fail_closed(self):
        cases = {
            "not_a_dict": [],
            "missing_provider": {"openai": {}, "anthropic": {}},
            "extra_provider": {**valid_bundle_input(), "extra": {}},
            "missing_preflight": {
                **valid_bundle_input(),
                "openai": {"proofs": {}}
            },
            "extra_key_in_entry": {
                **valid_bundle_input(),
                "openai": {
                    "preflight": valid_preflight("openai"),
                    "proofs": valid_proofs("openai"),
                    "extra": True,
                }
            },
        }

        for name, payload in cases.items():
            with self.subTest(name=name):
                result = build_live_readiness_bundle(payload)
                self.assert_blocked(result)
                self.assertEqual(result["blocking_providers"], PROVIDER_ORDER)

    @patch("providers.live_readiness_bundle.evaluate_live_readiness")
    def test_evaluate_called_exactly_once_per_provider(self, mock_evaluate):
        mock_evaluate.return_value = {
            "state": "READY_FOR_HUMAN_APPROVAL",
            "live_ready": False,
            "dispatch_allowed": False,
            "human_approval_required": True,
            "retry_count": 0,
            "fallback_state": "disabled",
        }

        build_live_readiness_bundle(valid_bundle_input())

        self.assertEqual(mock_evaluate.call_count, 3)
        calls = mock_evaluate.call_args_list
        self.assertEqual(calls[0][0][0], "openai")
        self.assertEqual(calls[1][0][0], "anthropic")
        self.assertEqual(calls[2][0][0], "google")

    @patch("providers.live_readiness_bundle.evaluate_live_readiness")
    def test_malformed_input_calls_evaluate_zero_times(self, mock_evaluate):
        build_live_readiness_bundle({"not_right": True})
        mock_evaluate.assert_not_called()

    @patch("providers.live_readiness_bundle.evaluate_live_readiness")
    def test_gate_exception_fails_closed(self, mock_evaluate):
        mock_evaluate.side_effect = ValueError("Something broke")
        result = build_live_readiness_bundle(valid_bundle_input())
        self.assert_blocked(result)
        self.assertEqual(result["blocking_providers"], PROVIDER_ORDER)

    @patch("providers.live_readiness_bundle.evaluate_live_readiness")
    def test_malformed_gate_output_fails_closed(self, mock_evaluate):
        base_valid_mock = {
            "state": "READY_FOR_HUMAN_APPROVAL",
            "live_ready": False,
            "dispatch_allowed": False,
            "human_approval_required": True,
            "retry_count": 0,
            "fallback_state": "disabled",
        }

        mutations = {
            "live_ready_true": {"live_ready": True},
            "dispatch_allowed_true": {"dispatch_allowed": True},
            "retry_nonzero": {"retry_count": 1},
            "fallback_enabled": {"fallback_state": "enabled"},
            "missing_state": {},
            "not_a_dict": None,
        }

        for name, update in mutations.items():
            with self.subTest(name=name):
                if update is None:
                    mock_evaluate.return_value = "not a dict"
                else:
                    mutated = copy.deepcopy(base_valid_mock)
                    if "missing_state" in name:
                        del mutated["state"]
                    else:
                        mutated.update(update)
                    mock_evaluate.return_value = mutated

                result = build_live_readiness_bundle(valid_bundle_input())
                self.assert_blocked(result)

    def test_deep_copy_isolation(self):
        payload = valid_bundle_input()
        result = build_live_readiness_bundle(payload)

        # Mutate input
        payload["openai"]["preflight"]["retry_count"] = 99
        # Mutate result
        result["evidence"]["anthropic"]["preflight"]["retry_count"] = 99

        # Re-evaluate pristine
        pristine_result = build_live_readiness_bundle(valid_bundle_input())

        self.assertEqual(pristine_result["evidence"]["openai"]["preflight"]["retry_count"], 0)
        self.assertEqual(pristine_result["evidence"]["anthropic"]["preflight"]["retry_count"], 0)

    def test_sha256_determinism(self):
        payload1 = valid_bundle_input()
        payload2 = valid_bundle_input()

        # Change key order, equivalent content
        payload2_reordered = {
            "google": payload2["google"],
            "openai": payload2["openai"],
            "anthropic": payload2["anthropic"],
        }

        res1 = build_live_readiness_bundle(payload1)
        res2 = build_live_readiness_bundle(payload2_reordered)

        self.assertEqual(res1["packet_sha256"], res2["packet_sha256"])

        # Change evidence ref
        payload3 = valid_bundle_input()
        payload3["openai"]["proofs"]["finite_timeout"]["evidence_ref"] = "different"
        res3 = build_live_readiness_bundle(payload3)

        self.assertNotEqual(res1["packet_sha256"], res3["packet_sha256"])

    def test_japanese_summary(self):
        payload = valid_bundle_input()
        result = build_live_readiness_bundle(payload)

        summary = render_live_readiness_summary_ja(result)

        self.assertIn("ライブ実行: 禁止", summary)
        self.assertIn("人間承認が必要", summary)
        self.assertIn("全体状態: READY_FOR_HUMAN_APPROVAL", summary)
        self.assertIn("- openai: READY_FOR_HUMAN_APPROVAL", summary)
        self.assertNotIn("fixture", summary) # evidence_ref is not present

        # Blocked case
        payload["openai"]["proofs"].pop("finite_timeout", None)
        blocked_result = build_live_readiness_bundle(payload)
        blocked_summary = render_live_readiness_summary_ja(blocked_result)

        self.assertIn("全体状態: BLOCKED_UNKNOWN", blocked_summary)
        self.assertIn("- openai: BLOCKED_UNKNOWN", blocked_summary)
        self.assertIn("- anthropic: READY_FOR_HUMAN_APPROVAL", blocked_summary)

    def test_new_module_ast_no_ambient_io(self):
        source_path = Path("src/providers/live_readiness_bundle.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        forbidden_imports = {
            "os",
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "http",
            "pathlib",
        }
        forbidden_calls = {
            "open",
            "exec",
            "eval",
            "system",
            "popen",
            "run",
            "check_call",
            "check_output",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], forbidden_imports)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], forbidden_imports)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden_calls)
                elif isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, forbidden_calls)
            elif isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "environ")


if __name__ == "__main__":
    unittest.main()
