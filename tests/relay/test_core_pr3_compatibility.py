import ast
import unittest
from copy import deepcopy

from src.providers.bundle import ProviderAdapterBundle
from src.providers.core_boundary import build_core_pr3_adapter_map
from src.providers.base import ProviderStaticProfile
from src.relay.bridge import RelayProviderAdapterBridge
from src.providers.policy import CODEX_POLICY, CLAUDE_POLICY, ANTIGRAVITY_POLICY, claude_session_meta, antigravity_binary_name

from tests.relay.core_pr3_contract_fixture import CorePR3ProviderAdapterProtocol, CORE_PR3_HEAD


def _create_test_bundle(mock_raw_response=None, simulate_timeout=False, simulate_error_in_collect=False):
    profiles = {
        "openai": ProviderStaticProfile(
            provider_id="openai", external_agent=CODEX_POLICY.external_agent,
            pinned_version=CODEX_POLICY.pinned_version, retry_count=0, fallback_state="disabled",
            live_ready=False, live_readiness="BLOCKED",
            _static_preflight_config={"auth_kind": "account", "route_evidence": {"api_key_present": False, "gateway_configured": False, "dangerous_permission_bypass": False, "external_cloud_configured": False, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False, "hide_claude_auth": False, "cloud_billing_selected": False, "overages_enabled": False, "adc_present": False, "vertex_selected": False}, "platform": "linux", "architecture": "x86_64"}
        ),
        "anthropic": ProviderStaticProfile(
            provider_id="anthropic", external_agent=CLAUDE_POLICY.external_agent,
            pinned_version=CLAUDE_POLICY.pinned_version, retry_count=0, fallback_state="disabled",
            live_ready=False, live_readiness="BLOCKED", _session_meta=claude_session_meta(),
            _static_preflight_config={"auth_kind": "account", "route_evidence": {"api_key_present": False, "gateway_configured": False, "dangerous_permission_bypass": False, "external_cloud_configured": False, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False, "hide_claude_auth": False, "cloud_billing_selected": False, "overages_enabled": False, "adc_present": False, "vertex_selected": False}, "platform": "linux", "architecture": "x86_64", "provider_meta": claude_session_meta()}
        ),
        "google": ProviderStaticProfile(
            provider_id="google", external_agent=ANTIGRAVITY_POLICY.external_agent,
            pinned_version=ANTIGRAVITY_POLICY.pinned_version, retry_count=0, fallback_state="disabled",
            live_ready=False, live_readiness="BLOCKED", binary_name=antigravity_binary_name("linux", "x86_64"),
            _static_preflight_config={"auth_kind": "account", "route_evidence": {"api_key_present": False, "gateway_configured": False, "dangerous_permission_bypass": False, "external_cloud_configured": False, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False, "hide_claude_auth": False, "cloud_billing_selected": False, "overages_enabled": False, "adc_present": False, "vertex_selected": False}, "platform": "linux", "architecture": "x86_64"}
        ),
    }
    bridges = {
        "openai": RelayProviderAdapterBridge(mock_raw_response=mock_raw_response, simulate_timeout=simulate_timeout, simulate_error_in_collect=simulate_error_in_collect),
        "anthropic": RelayProviderAdapterBridge(mock_raw_response=mock_raw_response, simulate_timeout=simulate_timeout, simulate_error_in_collect=simulate_error_in_collect),
        "google": RelayProviderAdapterBridge(mock_raw_response=mock_raw_response, simulate_timeout=simulate_timeout, simulate_error_in_collect=simulate_error_in_collect),
    }
    return ProviderAdapterBundle(profiles, bridges)


class TestCorePR3Compatibility(unittest.TestCase):
    def test_structural_satisfaction(self):
        bundle = _create_test_bundle()
        adapters = build_core_pr3_adapter_map(bundle)
        for provider_id, adapter in adapters.items():
            self.assertEqual(adapter.provider_id, provider_id)
            self.assertIsInstance(adapter, CorePR3ProviderAdapterProtocol)

    def test_zero_bridge_calls_on_boundary_construction(self):
        bundle = _create_test_bundle()
        adapters = build_core_pr3_adapter_map(bundle)
        for adapter in adapters.values():
            self.assertEqual(adapter.bridge.dispatch_count, 0)
            self.assertEqual(adapter.bridge.collect_count, 0)
    def test_core_like_execution_sequence(self):
        bundle = _create_test_bundle(mock_raw_response='{"answer_state":"ANSWER","conclusion_code":"DONE","safety_warning":"ABSENT","safety_reason":null,"evidence_refs":[],"marker_echoes":{"head":null,"middle":null,"tail":null},"answer_text":"Mock text","schema_version":"phase0-response-v1"}')
        adapters = build_core_pr3_adapter_map(bundle)
        for provider_id, adapter in adapters.items():
            ctx = {"case_id": "c1", "packet_sha256": "abcdef", "session_id": "s1", "correlation_id": "corr1"}
            prepared = adapter.prepare(ctx)
            preflight = adapter.preflight(prepared)
            self.assertTrue(preflight["ok"])
            self.assertFalse(preflight["live_ready"])
            self.assertEqual(preflight["live_readiness"], "BLOCKED")

            handle = adapter.dispatch(prepared)
            self.assertEqual(adapter.bridge.dispatch_count, 1)
            raw_bytes = adapter.collect(handle)
            self.assertEqual(adapter.bridge.collect_count, 1)
            self.assertIsInstance(raw_bytes, bytes)

            classification = adapter.classify(raw_bytes)
            self.assertTrue(classification["success"])
            self.assertEqual(classification["execution_state"], "COMPLETE")
    def test_simulated_timeout_and_healthy_peer(self):
        bundle = _create_test_bundle(mock_raw_response='{"answer_state":"ANSWER","conclusion_code":"DONE","safety_warning":"ABSENT","safety_reason":null,"evidence_refs":[],"marker_echoes":{"head":null,"middle":null,"tail":null},"answer_text":"Mock text","schema_version":"phase0-response-v1"}')
        bundle.adapters["openai"].bridge.simulate_timeout = True

        adapters = build_core_pr3_adapter_map(bundle)
        failing_adapter = adapters["openai"]
        healthy_adapter = adapters["anthropic"]

        ctx = {"case_id": "c1", "packet_sha256": "abcdef", "session_id": "s1", "correlation_id": "corr1"}
        prepared_f = failing_adapter.prepare(ctx)
        prepared_h = healthy_adapter.prepare(ctx)

        handle_f = failing_adapter.dispatch(prepared_f)
        with self.assertRaises(TimeoutError):
            failing_adapter.collect(handle_f)

        failing_adapter.abort(handle_f)
        self.assertEqual(len(failing_adapter.bridge.abort_calls), 1)

        handle_h = healthy_adapter.dispatch(prepared_h)
        raw_bytes_h = healthy_adapter.collect(handle_h)
        self.assertEqual(len(healthy_adapter.bridge.abort_calls), 0)
        self.assertIsInstance(raw_bytes_h, bytes)

    def test_simulated_collect_error(self):
        bundle = _create_test_bundle()
        bundle.adapters["openai"].bridge.simulate_error_in_collect = True
        adapters = build_core_pr3_adapter_map(bundle)
        ctx = {"case_id": "c1", "packet_sha256": "abcdef", "session_id": "s1", "correlation_id": "corr1"}
        adapter = adapters["openai"]
        prepared = adapter.prepare(ctx)
        handle = adapter.dispatch(prepared)
        with self.assertRaises(RuntimeError):
            adapter.collect(handle)
    def test_preflight_failure(self):
        bundle = _create_test_bundle()
        bundle.adapters["openai"].bridge.simulate_no_cli = True
        adapters = build_core_pr3_adapter_map(bundle)
        ctx = {"case_id": "c1", "packet_sha256": "abcdef", "session_id": "s1", "correlation_id": "corr1"}
        adapter = adapters["openai"]
        prepared = adapter.prepare(ctx)
        preflight = adapter.preflight(prepared)
        self.assertFalse(preflight["ok"])
        self.assertEqual(adapter.bridge.dispatch_count, 0)
        self.assertEqual(adapter.bridge.collect_count, 0)

    def test_invalid_raw_bytes_fails_closed(self):
        bundle = _create_test_bundle(mock_raw_response="not json")
        adapters = build_core_pr3_adapter_map(bundle)
        ctx = {"case_id": "c1", "packet_sha256": "abcdef", "session_id": "s1", "correlation_id": "corr1"}
        adapter = adapters["openai"]
        prepared = adapter.prepare(ctx)
        handle = adapter.dispatch(prepared)
        raw_bytes = adapter.collect(handle)
        self.assertEqual(raw_bytes, b"not json")
        classification = adapter.classify(raw_bytes)
        self.assertFalse(classification["success"])
    def test_immutability(self):
        bundle = _create_test_bundle()
        adapters = build_core_pr3_adapter_map(bundle)
        adapters["openai"] = None

        adapters2 = build_core_pr3_adapter_map(bundle)
        self.assertIsNotNone(adapters2["openai"])
        self.assertIsNotNone(bundle.adapters["openai"])

    def test_invalid_bundle(self):
        bundle = _create_test_bundle()
        # Mocking an invalid bundle by directly setting private property
        # Since bundle is immutable, we mutate a temporary dictionary to test boundary
        # A bit hacky, but demonstrates fail-closed
        adapters = build_core_pr3_adapter_map(bundle)
        with self.assertRaises(TypeError):
            build_core_pr3_adapter_map(None)

    def test_ast_static_proof(self):
        with open("src/providers/core_boundary.py", "r") as f:
            code = f.read()
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, ("os", "subprocess", "socket", "requests", "http"))
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, ("os", "subprocess", "socket", "requests", "http"))
