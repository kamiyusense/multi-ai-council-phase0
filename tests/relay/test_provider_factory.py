import unittest
from copy import deepcopy
from dataclasses import replace

from providers.base import ProviderStaticProfile
from providers.factory import create_core_adapter
from providers.codex_acp import build_codex_profile
from providers.claude_acp import build_claude_profile
from providers.antigravity_acp import build_antigravity_profile
from providers.policy import CODEX_POLICY, CLAUDE_POLICY, ANTIGRAVITY_POLICY, claude_session_meta
from relay.bridge import RelayProviderAdapterBridge
from relay.dispatcher import RelayDispatcher, DuplicateConflictGuard


class CountingBridge(RelayProviderAdapterBridge):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.preflight_count = 0

    def preflight(self, prepared_context):
        self.preflight_count += 1
        return super().preflight(prepared_context)

class TestProviderFactory(unittest.TestCase):
    @staticmethod
    def valid_raw_response():
        import json
        return json.dumps({
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "hello",
        })

    def assert_static_roundtrip(self, profile, provider_id):
        bridge = CountingBridge(mock_raw_response=self.valid_raw_response())
        adapter = create_core_adapter(profile, bridge)

        self.assertEqual(bridge.preflight_count, 0)
        self.assertEqual(bridge.dispatch_count, 0)
        self.assertEqual(bridge.collect_count, 0)
        self.assertEqual(bridge.abort_calls, [])

        dispatcher = RelayDispatcher(adapter, DuplicateConflictGuard())
        result = dispatcher.dispatch(
            provider_id,
            {
                "session_id": "s1",
                "correlation_id": f"corr-{provider_id}",
                "payload": {},
            },
        )
        self.assertEqual(result["state"], "SIMULATED")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")
        self.assertFalse(result["live_turn_executed"])
        self.assertEqual(bridge.dispatch_count, 1)
        self.assertEqual(bridge.collect_count, 1)
        self.assertEqual(bridge.preflight_count, 1)

    def test_codex_factory_success_and_roundtrip(self):
        profile = build_codex_profile(
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "custom_model_provider_configured": False,
                "arbitrary_codex_config_present": False,
            },
        )
        self.assertEqual(profile.binary_name, "codex-acp")
        self.assert_static_roundtrip(profile, "openai")

    def test_factory_rejects_unapproved_openai_binary(self):
        profile = build_codex_profile(
            "account",
            {
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "custom_model_provider_configured": False,
                "arbitrary_codex_config_present": False,
            },
        )
        wrong = replace(profile, binary_name="foreign-acp")
        with self.assertRaisesRegex(ValueError, "OpenAI profile binary_name"):
            create_core_adapter(wrong, RelayProviderAdapterBridge())

    def test_claude_factory_success(self):
        profile = build_claude_profile(
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "dangerous_permission_bypass": False,
                "hide_claude_auth": False,
            }
        )
        self.assertEqual(profile.binary_name, "claude-agent-acp")
        self.assert_static_roundtrip(profile, "anthropic")

    def test_factory_rejects_unapproved_anthropic_binary(self):
        profile = build_claude_profile(
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "dangerous_permission_bypass": False,
                "hide_claude_auth": False,
            }
        )
        wrong = replace(profile, binary_name="foreign-acp")
        with self.assertRaisesRegex(ValueError, "Anthropic profile binary_name"):
            create_core_adapter(wrong, RelayProviderAdapterBridge())

    def test_antigravity_factory_success(self):
        profile = build_antigravity_profile(
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
            architecture="x86_64",
        )
        self.assert_static_roundtrip(profile, "google")

    def test_factory_fails_unknown_provider(self):
        profile = ProviderStaticProfile(
            provider_id="unknown",
            external_agent="unknown",
            pinned_version="1.0",
            _static_preflight_config={}
        )
        bridge = RelayProviderAdapterBridge()
        with self.assertRaisesRegex(ValueError, "Unknown provider_id"):
            create_core_adapter(profile, bridge)

    def test_factory_fails_wrong_agent(self):
        profile = ProviderStaticProfile(
            provider_id="openai",
            external_agent="wrong_agent",
            pinned_version=CODEX_POLICY.pinned_version,
            _static_preflight_config={"auth_kind": "account", "route_evidence": {}}
        )
        bridge = RelayProviderAdapterBridge()
        with self.assertRaisesRegex(ValueError, "Invalid external_agent"):
            create_core_adapter(profile, bridge)

    def test_factory_fails_bad_config(self):
        profile = ProviderStaticProfile(
            provider_id="openai",
            external_agent=CODEX_POLICY.external_agent,
            pinned_version=CODEX_POLICY.pinned_version,
            _static_preflight_config={"auth_kind": "wrong", "route_evidence": {}}
        )
        bridge = RelayProviderAdapterBridge()
        with self.assertRaisesRegex(ValueError, "Provider configuration failed static validation"):
            create_core_adapter(profile, bridge)

    def test_factory_fails_claude_wrong_meta(self):
        profile = ProviderStaticProfile(
            provider_id="anthropic",
            external_agent=CLAUDE_POLICY.external_agent,
            pinned_version=CLAUDE_POLICY.pinned_version,
            _static_preflight_config={
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False, "gateway_configured": False, "external_cloud_configured": False,
                    "dangerous_permission_bypass": False, "hide_claude_auth": False
                },
                "provider_meta": claude_session_meta()
            },
            _session_meta={"wrong": "meta"}
        )
        bridge = RelayProviderAdapterBridge()
        with self.assertRaisesRegex(ValueError, "Anthropic profile must have exact claude_session_meta()"):
            create_core_adapter(profile, bridge)

    def test_factory_fails_google_wrong_binary(self):
        profile = ProviderStaticProfile(
            provider_id="google",
            external_agent=ANTIGRAVITY_POLICY.external_agent,
            pinned_version=ANTIGRAVITY_POLICY.pinned_version,
            _static_preflight_config={
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False, "gateway_configured": False, "external_cloud_configured": False,
                    "cloud_billing_selected": False, "overages_enabled": False, "adc_present": False, "vertex_selected": False
                },
                "platform": "linux", "architecture": "x86_64"
            },
            binary_name="wrong.exe"
        )
        bridge = RelayProviderAdapterBridge()
        with self.assertRaisesRegex(ValueError, "Google profile must have matching antigravity_binary_name"):
            create_core_adapter(profile, bridge)

    def test_factory_fails_openai_foreign_metadata(self):
        profile = ProviderStaticProfile(
            provider_id="openai",
            external_agent=CODEX_POLICY.external_agent,
            pinned_version=CODEX_POLICY.pinned_version,
            _static_preflight_config={
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False, "gateway_configured": False, "external_cloud_configured": False,
                    "custom_model_provider_configured": False, "arbitrary_codex_config_present": False
                }
            },
            _session_meta={"some": "meta"}
        )
        bridge = RelayProviderAdapterBridge()
        with self.assertRaisesRegex(ValueError, "OpenAI profile must not have session_meta"):
            create_core_adapter(profile, bridge)

    def test_isolation_from_caller_mutation(self):
        config = {
            "auth_kind": "account",
            "route_evidence": {
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "custom_model_provider_configured": False,
                "arbitrary_codex_config_present": False,
            }
        }
        profile = ProviderStaticProfile(
            provider_id="openai",
            external_agent=CODEX_POLICY.external_agent,
            pinned_version=CODEX_POLICY.pinned_version,
            _static_preflight_config=config
        )
        bridge = RelayProviderAdapterBridge()

        # mutate config before passing to factory
        config["auth_kind"] = "wrong"

        # Since profile freezes config, it should remain "account"
        adapter = create_core_adapter(profile, bridge)

        # retrieve from profile (after construction) and mutate
        extracted_config = profile.static_preflight_config
        extracted_config["route_evidence"]["api_key_present"] = True

        # adapter's actual config should be isolated
        prepared = adapter.prepare({"provider_id": "openai", "session_id": "s1", "correlation_id": "c1"})
        preflight_result = adapter.preflight(prepared)
        self.assertTrue(preflight_result["ok"])

if __name__ == '__main__':
    unittest.main()
