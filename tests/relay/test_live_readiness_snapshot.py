import copy
import hashlib
import json
import unittest
from typing import Any

from src.providers.live_readiness_snapshot import (
    build_live_readiness_snapshot,
    render_snapshot_summary_ja,
    _canonical_json
)
from src.providers.live_readiness_pipeline import PROVIDER_ORDER
from src.providers.live_readiness import COMMON_PROOFS, PROVIDER_PROOFS


class TestLiveReadinessSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.valid_configs = {
            "openai": {
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "custom_model_provider_configured": False,
                    "arbitrary_codex_config_present": False,
                },
                "platform": None,
                "architecture": None,
                "provider_meta": None,
            },
            "anthropic": {
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "dangerous_permission_bypass": False,
                    "hide_claude_auth": False,
                },
                "platform": None,
                "architecture": None,
                "provider_meta": {
                    "claudeCode": {
                        "options": {
                            "allowDangerouslySkipPermissions": False,
                        }
                    }
                },
            },
            "google": {
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "cloud_billing_selected": False,
                    "overages_enabled": False,
                    "adc_present": False,
                    "vertex_selected": False,
                },
                "platform": "linux",
                "architecture": "x86_64",
                "provider_meta": None,
            },
        }

        self.unknown_inventory = {
            p: {proof: None for proof in (COMMON_PROOFS | PROVIDER_PROOFS[p])}
            for p in PROVIDER_ORDER
        }

        self.confirmed_inventory = {
            p: {proof: {"status": "CONFIRMED", "evidence_ref": "evidence"} for proof in (COMMON_PROOFS | PROVIDER_PROOFS[p])}
            for p in PROVIDER_ORDER
        }

    def _assert_fail_closed(self, result: dict[str, Any]) -> None:
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["dispatch_allowed"])
        self.assertTrue(result["human_approval_required"])
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")
        self.assertEqual(result["preflight_states"], {})
        self.assertEqual(result["preflight_snapshots"], {})
        self.assertIsNone(result["preflight_packet_sha256"])
        self.assertEqual(result["provider_states"], {})
        self.assertEqual(result["blocking_providers"], list(PROVIDER_ORDER))

        base_json = _canonical_json({k: v for k, v in result.items() if k != "snapshot_packet_sha256"})
        expected_hash = hashlib.sha256(base_json.encode("utf-8")).hexdigest()
        self.assertEqual(result["snapshot_packet_sha256"], expected_hash)

    def test_valid_explicit_configs_unknown_inventory(self) -> None:
        result = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.unknown_inventory})

        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["dispatch_allowed"])
        self.assertEqual(result["retry_count"], 0)

        # Preflights passed but pipeline resolves to blocked/unknown due to UNKNOWN inventory
        self.assertEqual(result["preflight_states"]["openai"], "PASS")
        self.assertEqual(result["preflight_states"]["anthropic"], "PASS")
        self.assertEqual(result["preflight_states"]["google"], "PASS")
        self.assertEqual(result["inventory_state"], "UNRESOLVED")
        self.assertTrue(result["unresolved_count"] > 0)

        self.assertEqual(
            result["blocking_providers"],
            ["openai", "anthropic", "google"]
        )

    def test_valid_synthetic_confirmed_inventory(self) -> None:
        result = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.confirmed_inventory})

        self.assertEqual(result["state"], "READY_FOR_HUMAN_APPROVAL")
        # Fixed fields must still be false/disabled
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["dispatch_allowed"])
        self.assertEqual(result["retry_count"], 0)

        self.assertEqual(result["inventory_state"], "PROOF_RECORDS_COMPLETE")
        self.assertEqual(result["unresolved_count"], 0)
        self.assertEqual(result["blocking_providers"], [])

        for p in PROVIDER_ORDER:
            self.assertEqual(result["provider_states"][p], "READY_FOR_HUMAN_APPROVAL")

    def test_malformed_input(self) -> None:
        self._assert_fail_closed(build_live_readiness_snapshot(None))
        self._assert_fail_closed(build_live_readiness_snapshot({}))

        bad_configs = copy.deepcopy(self.valid_configs)
        del bad_configs["google"]
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_configs, 'inventory': self.unknown_inventory}))

    def test_openai_anthropic_google_structural_constraints(self) -> None:
        bad_openai = copy.deepcopy(self.valid_configs)
        del bad_openai["openai"]["auth_kind"]
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_openai, 'inventory': self.unknown_inventory}))

        bad_anthropic = copy.deepcopy(self.valid_configs)
        bad_anthropic["anthropic"]["provider_meta"] = None
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_anthropic, 'inventory': self.unknown_inventory}))

        bad_google = copy.deepcopy(self.valid_configs)
        bad_google["google"]["platform"] = 123
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_google, 'inventory': self.unknown_inventory}))

    def test_strict_route_evidence_keys(self) -> None:
        import copy
        bad_openai = copy.deepcopy(self.valid_configs)
        bad_openai["openai"]["route_evidence"]["extra"] = False
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_openai, 'inventory': self.unknown_inventory}))

        bad_anthropic = copy.deepcopy(self.valid_configs)
        del bad_anthropic["anthropic"]["route_evidence"]["api_key_present"]
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_anthropic, 'inventory': self.unknown_inventory}))

        bad_google = copy.deepcopy(self.valid_configs)
        bad_google["google"]["route_evidence"]["api_key_present"] = "False"
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_google, 'inventory': self.unknown_inventory}))

    def test_validate_provider_static_not_called_on_structural_failure(self) -> None:
        import unittest.mock
        import copy
        with unittest.mock.patch("src.providers.live_readiness_snapshot.validate_provider_static") as mock_val:
            bad_configs = copy.deepcopy(self.valid_configs)
            # anthropic is bad, but openai is first in list.
            # openai should NOT be validated if anthropic is bad structurally.
            del bad_configs["anthropic"]["route_evidence"]["api_key_present"]
            self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_configs, 'inventory': self.unknown_inventory}))
            mock_val.assert_not_called()

    def test_validate_provider_static_exception_stops_immediately(self) -> None:
        import unittest.mock
        with unittest.mock.patch("src.providers.live_readiness_snapshot.validate_provider_static") as mock_val:
            mock_val.side_effect = Exception("Boom")
            self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.unknown_inventory}))
            mock_val.assert_called_once()

    def test_malformed_preflight_outputs(self) -> None:
        import unittest.mock
        with unittest.mock.patch("src.providers.live_readiness_snapshot.validate_provider_static") as mock_val:
            # Missing key
            mock_val.return_value = {
                "static_configuration_status": "PASS",
                "live_readiness": "BLOCKED",
            }
            self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.unknown_inventory}))

    def test_malformed_pipeline_outputs(self) -> None:
        import unittest.mock
        with unittest.mock.patch("src.providers.live_readiness_snapshot.build_live_readiness_pipeline") as mock_pipe:
            # Wrong state
            mock_pipe.return_value = {
                "state": "TAMPERED_STATE",
                "live_ready": False,
                "dispatch_allowed": False,
                "human_approval_required": True,
                "retry_count": 0,
                "fallback_state": "disabled",
                "inventory_state": "BLOCKED_UNKNOWN",
                "unresolved_count": -1,
                "unresolved_by_provider": {},
                "inventory_packet_sha256": None,
                "provider_states": {},
                "blocking_providers": list(PROVIDER_ORDER),
                "bundle_packet_sha256": None,
                "pipeline_packet_sha256": None
            }
            self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.unknown_inventory}))

    def test_non_serializable_input(self) -> None:
        bad_inventory = copy.deepcopy(self.unknown_inventory)
        bad_inventory["openai"]["finite_timeout"] = lambda: None
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': bad_inventory}))

    def test_source_mutation_isolation(self) -> None:
        configs = copy.deepcopy(self.valid_configs)
        inv = copy.deepcopy(self.confirmed_inventory)

        result = build_live_readiness_snapshot({'provider_configs': configs, 'inventory': inv})

        # Mutate source
        configs["openai"]["auth_kind"] = "hacked"
        inv["anthropic"]["sdk_retry_zero"] = "hacked"

        self.assertEqual(result["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(result["preflight_snapshots"]["openai"]["provider_id"], "openai")

    def test_japanese_renderer(self) -> None:
        result = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.confirmed_inventory})
        summary = render_snapshot_summary_ja(result)

        self.assertIn("ライブ実行: 禁止", summary)
        self.assertIn("人間承認が必要", summary)
        self.assertIn("全体状態: READY_FOR_HUMAN_APPROVAL", summary)
        self.assertIn("未解決の証明数: 0", summary)
        self.assertIn("プロバイダー状態:", summary)
        self.assertIn("- openai: READY_FOR_HUMAN_APPROVAL", summary)
        self.assertIn("事前確認状態:", summary)
        self.assertIn("- openai: PASS", summary)

        # No arbitrary strings or raw objects dumped
        self.assertNotIn("{", summary)
        self.assertNotIn("}", summary)

    def test_equivalent_input_dict_key_orders_identical_snapshot_digest(self) -> None:
        configs1 = copy.deepcopy(self.valid_configs)
        configs2 = copy.deepcopy(self.valid_configs)

        # Reverse route_evidence keys order in configs2 openai
        keys = list(configs2["openai"]["route_evidence"].keys())
        configs2["openai"]["route_evidence"] = {k: configs2["openai"]["route_evidence"][k] for k in reversed(keys)}

        res1 = build_live_readiness_snapshot({'provider_configs': configs1, 'inventory': self.unknown_inventory})
        res2 = build_live_readiness_snapshot({'provider_configs': configs2, 'inventory': self.unknown_inventory})

        self.assertEqual(res1["snapshot_packet_sha256"], res2["snapshot_packet_sha256"])

    def test_changing_evidence_ref_changes_digest_but_summary_hides_it(self) -> None:
        inv1 = copy.deepcopy(self.confirmed_inventory)
        inv2 = copy.deepcopy(self.confirmed_inventory)
        inv2["openai"]["chatgpt_route_retry_zero"] = {"status": "CONFIRMED", "evidence_ref": "different"}

        res1 = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': inv1})
        res2 = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': inv2})

        self.assertNotEqual(res1["snapshot_packet_sha256"], res2["snapshot_packet_sha256"])

        sum1 = render_snapshot_summary_ja(res1)
        sum2 = render_snapshot_summary_ja(res2)

        self.assertEqual(sum1, sum2)
        self.assertNotIn("different_evidence_ref", sum1)
