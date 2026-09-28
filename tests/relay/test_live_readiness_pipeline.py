import unittest.mock
import unittest
import copy
from typing import Any
from src.providers.live_readiness_pipeline import build_live_readiness_pipeline, render_pipeline_summary_ja
from src.providers.live_readiness_inventory import build_empty_inventory
from src.providers.live_readiness_bundle import PROVIDER_ORDER


def build_synthetic_confirmed_inventory() -> dict[str, Any]:
    inventory = build_empty_inventory()
    for provider in PROVIDER_ORDER:
        for key in inventory["inventory"][provider]:
            inventory["inventory"][provider][key]["status"] = "CONFIRMED"
            inventory["inventory"][provider][key]["evidence_ref"] = f"synthetic-{provider}-{key}"
    return inventory

def get_valid_preflights():
    return {
        "openai": {
            "static_configuration_status": "PASS",
            "live_readiness": "BLOCKED",
            "reasons": ["ready"],
            "provider_id": "openai",
            "external_agent": "@agentclientprotocol/codex-acp",
            "pinned_version": "1.12.0",
            "retry_count": 0,
            "fallback_state": "disabled",
            "live_ready": False
        },
        "anthropic": {
            "static_configuration_status": "PASS",
            "live_readiness": "BLOCKED",
            "reasons": ["ready"],
            "provider_id": "anthropic",
            "external_agent": "@agentclientprotocol/claude-agent-acp",
            "pinned_version": "0.79.0",
            "retry_count": 0,
            "fallback_state": "disabled",
            "live_ready": False
        },
        "google": {
            "static_configuration_status": "PASS",
            "live_readiness": "BLOCKED",
            "reasons": ["ready"],
            "provider_id": "google",
            "external_agent": "antigravity-acp",
            "pinned_version": "1.1.1",
            "retry_count": 0,
            "fallback_state": "disabled",
            "live_ready": False
        }
    }


class TestLiveReadinessPipeline(unittest.TestCase):
    def setUp(self):
        self.empty_inventory = build_empty_inventory()
        self.synthetic_inventory = build_synthetic_confirmed_inventory()
        self.valid_preflights = get_valid_preflights()
        self.valid_input = {
            "preflights": self.valid_preflights,
            "inventory": self.synthetic_inventory["inventory"]
        }

    def test_empty_inventory_early_block(self):
        input_data = {
            "preflights": self.valid_preflights,
            "inventory": self.empty_inventory["inventory"]
        }
        result = build_live_readiness_pipeline(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(result["inventory_state"], "UNRESOLVED")
        self.assertTrue(result["unresolved_count"] > 0)
        self.assertEqual(result["provider_states"], {})
        self.assertIsNone(result["bundle_packet_sha256"])
        self.assertEqual(result["live_ready"], False)
        self.assertEqual(result["dispatch_allowed"], False)
        self.assertEqual(result["human_approval_required"], True)

    def test_synthetic_confirmed_inventory(self):
        result = build_live_readiness_pipeline(self.valid_input)
        self.assertEqual(result["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(result["inventory_state"], "PROOF_RECORDS_COMPLETE")
        self.assertEqual(result["unresolved_count"], 0)
        self.assertEqual(set(result["provider_states"].keys()), set(PROVIDER_ORDER))
        for state in result["provider_states"].values():
            self.assertEqual(state, "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(result["blocking_providers"], [])
        self.assertIsNotNone(result["bundle_packet_sha256"])
        self.assertEqual(result["live_ready"], False)
        self.assertEqual(result["dispatch_allowed"], False)
        self.assertEqual(result["human_approval_required"], True)

    def test_malformed_input(self):
        # Missing preflights
        self.assertEqual(build_live_readiness_pipeline({"inventory": self.synthetic_inventory["inventory"]})["state"], "BLOCKED_UNKNOWN")
        # Missing provider in preflights
        bad_preflights = copy.deepcopy(self.valid_preflights)
        del bad_preflights["openai"]
        self.assertEqual(build_live_readiness_pipeline({"preflights": bad_preflights, "inventory": self.synthetic_inventory["inventory"]})["state"], "BLOCKED_UNKNOWN")

    def test_equivalent_key_order_digest(self):
        input1 = {"preflights": self.valid_preflights, "inventory": self.synthetic_inventory["inventory"]}
        input2 = {"inventory": self.synthetic_inventory["inventory"], "preflights": self.valid_preflights}
        res1 = build_live_readiness_pipeline(input1)
        res2 = build_live_readiness_pipeline(input2)
        self.assertEqual(res1["pipeline_packet_sha256"], res2["pipeline_packet_sha256"])

    def test_render_pipeline_summary_ja(self):
        res = build_live_readiness_pipeline(self.valid_input)
        summary = render_pipeline_summary_ja(res)
        self.assertIn("ライブ実行: 禁止", summary)
        self.assertIn("人間承認が必要", summary)
        self.assertIn("全体状態: READY_FOR_HUMAN_APPROVAL", summary)
        self.assertIn("未解決の証明数: 0", summary)
        self.assertNotIn("synthetic-", summary)  # Ensure no evidence refs are leaked

    def test_render_sanitization(self):
        # Tamper with the states
        bad_res = copy.deepcopy(self.valid_input)
        res = build_live_readiness_pipeline(bad_res)
        res["state"] = "LIVE_READY" # Illegal state
        summary = render_pipeline_summary_ja(res)
        self.assertIn("全体状態: BLOCKED_UNKNOWN", summary)

    def test_non_serializable_input(self):
        bad_input = {
            "preflights": self.valid_preflights,
            "inventory": {"func": lambda x: x}
        }
        res = build_live_readiness_pipeline(bad_input)
        self.assertEqual(res["state"], "BLOCKED_UNKNOWN")


    @unittest.mock.patch('src.providers.live_readiness_pipeline.build_live_readiness_bundle')
    def test_bundle_builder_called_exactly_once(self, mock_bundle):
        mock_bundle.return_value = {
            "state": "READY_FOR_HUMAN_APPROVAL",
            "live_ready": False,
            "dispatch_allowed": False,
            "human_approval_required": True,
            "retry_count": 0,
            "fallback_state": "disabled",
            "provider_order": list(PROVIDER_ORDER),
            "provider_states": {p: "READY_FOR_HUMAN_APPROVAL" for p in PROVIDER_ORDER},
            "blocking_providers": [],
            "evidence": {},
            "packet_sha256": "fakehash"
        }
        build_live_readiness_pipeline(self.valid_input)
        mock_bundle.assert_called_once()

    @unittest.mock.patch('src.providers.live_readiness_pipeline.build_live_readiness_bundle')
    def test_bundle_builder_called_zero_times(self, mock_bundle):
        input_data = {
            "preflights": self.valid_preflights,
            "inventory": self.empty_inventory["inventory"]
        }
        build_live_readiness_pipeline(input_data)
        mock_bundle.assert_not_called()

    @unittest.mock.patch('src.providers.live_readiness_pipeline.build_live_readiness_bundle')
    def test_bundle_exception_fails_closed(self, mock_bundle):
        mock_bundle.side_effect = Exception("Test exception")
        result = build_live_readiness_pipeline(self.valid_input)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    @unittest.mock.patch('src.providers.live_readiness_pipeline.build_live_readiness_bundle')
    def test_malformed_bundle_unknown_state(self, mock_bundle):
        mock_bundle.return_value = {
            "state": "UNKNOWN_STATE",
            "live_ready": False,
            "dispatch_allowed": False,
            "human_approval_required": True,
            "retry_count": 0,
            "fallback_state": "disabled",
            "provider_order": list(PROVIDER_ORDER),
            "provider_states": {p: "READY_FOR_HUMAN_APPROVAL" for p in PROVIDER_ORDER},
            "blocking_providers": [],
            "evidence": {},
            "packet_sha256": "fakehash"
        }
        result = build_live_readiness_pipeline(self.valid_input)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    @unittest.mock.patch('src.providers.live_readiness_pipeline.build_live_readiness_bundle')
    def test_malformed_bundle_wrong_fixed_flags(self, mock_bundle):
        mock_bundle.return_value = {
            "state": "READY_FOR_HUMAN_APPROVAL",
            "live_ready": True, # wrong
            "dispatch_allowed": False,
            "human_approval_required": True,
            "retry_count": 0,
            "fallback_state": "disabled",
            "provider_order": list(PROVIDER_ORDER),
            "provider_states": {p: "READY_FOR_HUMAN_APPROVAL" for p in PROVIDER_ORDER},
            "blocking_providers": [],
            "evidence": {},
            "packet_sha256": "fakehash"
        }
        result = build_live_readiness_pipeline(self.valid_input)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    @unittest.mock.patch('src.providers.live_readiness_pipeline.build_live_readiness_bundle')
    def test_malformed_bundle_missing_keys(self, mock_bundle):
        mock_bundle.return_value = {
            "state": "READY_FOR_HUMAN_APPROVAL",
            "live_ready": False
        }
        result = build_live_readiness_pipeline(self.valid_input)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

if __name__ == '__main__':
    unittest.main()
