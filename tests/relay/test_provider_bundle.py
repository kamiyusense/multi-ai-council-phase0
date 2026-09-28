import unittest
from copy import deepcopy

from src.providers.base import ProviderStaticProfile
from src.providers.codex_acp import build_codex_profile
from src.providers.claude_acp import build_claude_profile
from src.providers.antigravity_acp import build_antigravity_profile
from src.providers.bundle import ProviderAdapterBundle
from src.relay.bridge import RelayProviderAdapterBridge
from src.relay.dispatcher import RelayDispatcher, DuplicateConflictGuard

class TestProviderBundle(unittest.TestCase):
    def setUp(self):
        self.valid_profiles = [
            build_codex_profile(
                auth_kind="account",
                route_evidence={
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "custom_model_provider_configured": False,
                    "arbitrary_codex_config_present": False,
                }
            ),
            build_claude_profile(
                auth_kind="account",
                route_evidence={
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "hide_claude_auth": False,
                    "dangerous_permission_bypass": False,
                }
            ),
            build_antigravity_profile(
                auth_kind="account",
                route_evidence={
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "cloud_billing_selected": False,
                    "overages_enabled": False,
                    "adc_present": False,
                    "vertex_selected": False,
                },
                platform="linux",
                architecture="x86_64"
            )
        ]
        import json
        self.valid_raw_response = json.dumps({
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "hello",
        })
        self.valid_bridges = {
            "openai": RelayProviderAdapterBridge(mock_raw_response=self.valid_raw_response),
            "anthropic": RelayProviderAdapterBridge(mock_raw_response=self.valid_raw_response),
            "google": RelayProviderAdapterBridge(mock_raw_response=self.valid_raw_response)
        }

    def test_bundle_creation_success(self):
        bundle = ProviderAdapterBundle(self.valid_profiles, self.valid_bridges)
        adapters = bundle.get_adapters_in_order()

        self.assertEqual(len(adapters), 3)
        self.assertEqual(adapters[0].provider_id, "openai")
        self.assertEqual(adapters[1].provider_id, "anthropic")
        self.assertEqual(adapters[2].provider_id, "google")

        for k in self.valid_bridges:
            self.assertEqual(self.valid_bridges[k].dispatch_count, 0)
            self.assertEqual(self.valid_bridges[k].collect_count, 0)

    def test_bundle_rejects_missing_profile(self):
        profiles = self.valid_profiles[:2]
        with self.assertRaisesRegex(ValueError, "Exactly three profiles required"):
            ProviderAdapterBundle(profiles, self.valid_bridges)

    def test_bundle_rejects_missing_bridge(self):
        bridges = {"openai": self.valid_bridges["openai"], "anthropic": self.valid_bridges["anthropic"]}
        with self.assertRaisesRegex(ValueError, "Exactly three bridges required"):
            ProviderAdapterBundle(self.valid_profiles, bridges)

    def test_bundle_rejects_duplicate_profiles(self):
        profiles = [self.valid_profiles[0], self.valid_profiles[0], self.valid_profiles[1]]
        with self.assertRaisesRegex(ValueError, "Profiles must exactly match canonical provider set"):
            ProviderAdapterBundle(profiles, self.valid_bridges)

    def test_bundle_rejects_wrong_keys_bridges(self):
        bridges = {
            "openai": self.valid_bridges["openai"],
            "anthropic": self.valid_bridges["anthropic"],
            "wrong": self.valid_bridges["google"]
        }
        with self.assertRaisesRegex(ValueError, "Bridges must exactly match canonical provider set"):
            ProviderAdapterBundle(self.valid_profiles, bridges)

    def test_adapters_preflight_and_live_ready(self):
        bundle = ProviderAdapterBundle(self.valid_profiles, self.valid_bridges)
        for adapter in bundle.get_adapters_in_order():
            prepared = adapter.prepare({
                "case_id": "test",
                "provider_id": adapter.provider_id,
                "session_id": "sess-1",
                "correlation_id": "corr-1"
            })
            preflight = adapter.preflight(prepared)
            self.assertTrue(preflight.get("ok"))
            self.assertFalse(preflight.get("live_ready"))

    def test_dispatcher_roundtrip_per_provider(self):
        bundle = ProviderAdapterBundle(self.valid_profiles, self.valid_bridges)
        adapters = bundle.get_adapters_in_order()

        for adapter in adapters:
            guard = DuplicateConflictGuard()
            dispatcher = RelayDispatcher(adapter, guard)

            result = dispatcher.dispatch(
                slot_id=f"slot-{adapter.provider_id}",
                context={
                    "case_id": "case-1",
                    "provider_id": adapter.provider_id,
                    "session_id": f"sess-{adapter.provider_id}",
                    "correlation_id": f"corr-{adapter.provider_id}",
                }
            )

            self.assertEqual(result.get("state"), "SIMULATED")
            self.assertFalse(result.get("live_ready"))
            self.assertFalse(result.get("live_turn_executed"))
            self.assertEqual(result.get("retry_count"), 0)
            self.assertEqual(result.get("fallback_state"), "disabled")

            bridge = self.valid_bridges[adapter.provider_id]
            self.assertEqual(bridge.dispatch_count, 1)
            self.assertEqual(bridge.collect_count, 1)

    def test_provider_isolation_on_failure(self):
        self.valid_bridges["openai"].simulate_failure = True
        bundle = ProviderAdapterBundle(self.valid_profiles, self.valid_bridges)
        adapters = {a.provider_id: a for a in bundle.get_adapters_in_order()}

        guard = DuplicateConflictGuard()
        dispatcher_openai = RelayDispatcher(adapters["openai"], guard)

        result_openai = dispatcher_openai.dispatch(
            slot_id="slot-openai",
            context={
                "case_id": "case-1",
                "provider_id": "openai",
                "session_id": "sess-1",
                "correlation_id": "corr-1",
            }
        )
        self.assertEqual(result_openai.get("state"), "UNKNOWN")
        self.assertEqual(self.valid_bridges["openai"].dispatch_count, 0)

        dispatcher_anthropic = RelayDispatcher(adapters["anthropic"], guard)
        result_anthropic = dispatcher_anthropic.dispatch(
            slot_id="slot-anthropic",
            context={
                "case_id": "case-2",
                "provider_id": "anthropic",
                "session_id": "sess-2",
                "correlation_id": "corr-2",
            }
        )
        self.assertEqual(result_anthropic.get("state"), "SIMULATED")
        self.assertEqual(self.valid_bridges["anthropic"].dispatch_count, 1)
        self.assertEqual(self.valid_bridges["anthropic"].collect_count, 1)


    def test_bundle_immutable_snapshot(self):
        bundle = ProviderAdapterBundle(self.valid_profiles, self.valid_bridges)
        adapters_list = bundle.get_adapters_in_order()
        adapters_list.pop()

        adapters_again = bundle.get_adapters_in_order()
        self.assertEqual(len(adapters_again), 3)
        self.assertEqual(adapters_again[2].provider_id, "google")

if __name__ == '__main__':
    unittest.main()
