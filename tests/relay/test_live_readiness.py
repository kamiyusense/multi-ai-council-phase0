import ast
import copy
import unittest
from pathlib import Path

from providers.live_readiness import COMMON_PROOFS, PROVIDER_PROOFS, evaluate_live_readiness
from providers.policy import ANTIGRAVITY_POLICY, CLAUDE_POLICY, CODEX_POLICY


POLICIES = {
    "openai": CODEX_POLICY,
    "anthropic": CLAUDE_POLICY,
    "google": ANTIGRAVITY_POLICY,
}


def valid_preflight(provider_id: str) -> dict:
    policy = POLICIES[provider_id]
    return {
        "static_configuration_status": "PASS",
        "live_readiness": "BLOCKED",
        "reasons": ["static PASS is not live readiness"],
        "provider_id": provider_id,
        "external_agent": policy.external_agent,
        "pinned_version": policy.pinned_version,
        "retry_count": 0,
        "fallback_state": "disabled",
        "live_ready": False,
    }


def valid_proofs(provider_id: str) -> dict:
    keys = COMMON_PROOFS | PROVIDER_PROOFS[provider_id]
    return {
        key: {"status": "CONFIRMED", "evidence_ref": f"fixture:{provider_id}:{key}"}
        for key in keys
    }


class TestLiveReadiness(unittest.TestCase):
    def assert_blocked(self, result: dict) -> None:
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertIs(result["live_ready"], False)
        self.assertIs(result["dispatch_allowed"], False)
        self.assertIs(result["human_approval_required"], True)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")

    def assert_ready_for_human_only(self, result: dict) -> None:
        self.assertEqual(result["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertIs(result["live_ready"], False)
        self.assertIs(result["dispatch_allowed"], False)
        self.assertIs(result["human_approval_required"], True)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")

    def test_every_provider_can_reach_only_ready_for_human_approval(self):
        for provider_id in ("openai", "anthropic", "google"):
            with self.subTest(provider_id=provider_id):
                result = evaluate_live_readiness(
                    provider_id,
                    valid_preflight(provider_id),
                    valid_proofs(provider_id),
                )
                self.assert_ready_for_human_only(result)

    def test_every_missing_common_proof_blocks_every_provider(self):
        for provider_id in ("openai", "anthropic", "google"):
            for key in sorted(COMMON_PROOFS):
                with self.subTest(provider_id=provider_id, proof=key):
                    proofs = valid_proofs(provider_id)
                    del proofs[key]
                    self.assert_blocked(
                        evaluate_live_readiness(
                            provider_id,
                            valid_preflight(provider_id),
                            proofs,
                        )
                    )

    def test_every_missing_provider_specific_proof_blocks(self):
        for provider_id in ("openai", "anthropic", "google"):
            for key in sorted(PROVIDER_PROOFS[provider_id]):
                with self.subTest(provider_id=provider_id, proof=key):
                    proofs = valid_proofs(provider_id)
                    del proofs[key]
                    self.assert_blocked(
                        evaluate_live_readiness(
                            provider_id,
                            valid_preflight(provider_id),
                            proofs,
                        )
                    )

    def test_unknown_provider_and_provider_mismatch_block(self):
        self.assert_blocked(
            evaluate_live_readiness(
                "other",
                valid_preflight("openai"),
                valid_proofs("openai"),
            )
        )
        preflight = valid_preflight("anthropic")
        self.assert_blocked(
            evaluate_live_readiness(
                "openai",
                preflight,
                valid_proofs("openai"),
            )
        )

    def test_preflight_must_be_exact_and_internally_consistent(self):
        provider_id = "openai"
        mutations = {
            "status_unknown": ("static_configuration_status", "UNKNOWN"),
            "live_readiness_ready": ("live_readiness", "READY"),
            "wrong_agent": ("external_agent", "wrong-agent"),
            "wrong_version": ("pinned_version", "wrong-version"),
            "retry_nonzero": ("retry_count", 1),
            "fallback_enabled": ("fallback_state", "enabled"),
            "live_ready_true": ("live_ready", True),
            "provider_mismatch": ("provider_id", "google"),
            "reasons_wrong_type": ("reasons", "not-a-list"),
            "reasons_bad_item": ("reasons", [1]),
        }
        for name, (key, value) in mutations.items():
            with self.subTest(name=name):
                preflight = valid_preflight(provider_id)
                preflight[key] = value
                self.assert_blocked(
                    evaluate_live_readiness(
                        provider_id,
                        preflight,
                        valid_proofs(provider_id),
                    )
                )

        with self.subTest(name="missing_key"):
            preflight = valid_preflight(provider_id)
            del preflight["pinned_version"]
            self.assert_blocked(
                evaluate_live_readiness(
                    provider_id,
                    preflight,
                    valid_proofs(provider_id),
                )
            )

        with self.subTest(name="extra_key"):
            preflight = valid_preflight(provider_id)
            preflight["unexpected"] = True
            self.assert_blocked(
                evaluate_live_readiness(
                    provider_id,
                    preflight,
                    valid_proofs(provider_id),
                )
            )

    def test_malformed_proof_records_fail_closed(self):
        provider_id = "google"
        proof_key = "intended_account_route"
        cases = {
            "string_shortcut": "CONFIRMED",
            "boolean_shortcut": True,
            "unknown_status": {"status": "UNKNOWN", "evidence_ref": "fixture:x"},
            "empty_ref": {"status": "CONFIRMED", "evidence_ref": "   "},
            "non_string_ref": {"status": "CONFIRMED", "evidence_ref": 1},
            "missing_ref": {"status": "CONFIRMED"},
            "missing_status": {"evidence_ref": "fixture:x"},
            "extra_field": {
                "status": "CONFIRMED",
                "evidence_ref": "fixture:x",
                "extra": "not-allowed",
            },
        }
        for name, malformed in cases.items():
            with self.subTest(name=name):
                proofs = valid_proofs(provider_id)
                proofs[proof_key] = malformed
                self.assert_blocked(
                    evaluate_live_readiness(
                        provider_id,
                        valid_preflight(provider_id),
                        proofs,
                    )
                )

    def test_extra_unknown_proof_blocks(self):
        proofs = valid_proofs("anthropic")
        proofs["unknown_proof"] = {
            "status": "CONFIRMED",
            "evidence_ref": "fixture:unknown",
        }
        self.assert_blocked(
            evaluate_live_readiness(
                "anthropic",
                valid_preflight("anthropic"),
                proofs,
            )
        )

    def test_non_mapping_inputs_fail_closed(self):
        self.assert_blocked(evaluate_live_readiness("openai", [], {}))
        self.assert_blocked(
            evaluate_live_readiness("openai", valid_preflight("openai"), [])
        )

    def test_returned_result_does_not_alias_mutable_inputs(self):
        preflight = valid_preflight("openai")
        proofs = valid_proofs("openai")
        result = evaluate_live_readiness("openai", preflight, proofs)
        frozen_result = copy.deepcopy(result)

        preflight["static_configuration_status"] = "UNKNOWN"
        proofs["finite_timeout"]["status"] = "UNKNOWN"

        self.assertEqual(result, frozen_result)
        self.assert_ready_for_human_only(result)

    def test_new_module_has_no_ambient_io_network_or_process_surface(self):
        source_path = Path("src/providers/live_readiness.py")
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
