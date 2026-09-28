import ast
import json
import unittest
from pathlib import Path
from types import MappingProxyType

from providers.antigravity_acp import build_antigravity_profile
from providers.bundle import ProviderAdapterBundle
from providers.claude_acp import build_claude_profile
from providers.codex_acp import build_codex_profile
from providers.core_boundary import build_core_pr3_adapter_map
from relay.bridge import RelayProviderAdapterBridge

from tests.relay.core_pr3_contract_fixture import (
    CORE_PR3_HEAD,
    CorePR3ProviderAdapterProtocol,
)


EXPECTED_CORE_PR3_HEAD = "494b7296f32dce1c173a7699e4bd2d87f70d31a9"
VALID_RESPONSE = json.dumps(
    {
        "schema_version": "phase0-response-v1",
        "answer_state": "ANSWER",
        "conclusion_code": "DONE",
        "safety_warning": "ABSENT",
        "safety_reason": None,
        "evidence_refs": [],
        "marker_echoes": {"head": None, "middle": None, "tail": None},
        "answer_text": "Mock text",
    },
    separators=(",", ":"),
)


class CountingBridge(RelayProviderAdapterBridge):
    def __init__(self, *, provider_id: str, **kwargs):
        super().__init__(**kwargs)
        self.provider_id = provider_id
        self.prepare_count = 0
        self.preflight_count = 0
        self.classify_count = 0

    def prepare(self, case_context):
        self.prepare_count += 1
        return super().prepare(case_context)

    def preflight(self, prepared_context):
        self.preflight_count += 1
        return super().preflight(prepared_context)

    def classify(self, raw_result):
        self.classify_count += 1
        return super().classify(raw_result)


def _profiles():
    return {
        "openai": build_codex_profile(
            "account",
            {
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "custom_model_provider_configured": False,
                "arbitrary_codex_config_present": False,
            },
        ),
        "anthropic": build_claude_profile(
            "account",
            {
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "dangerous_permission_bypass": False,
                "hide_claude_auth": False,
            },
        ),
        "google": build_antigravity_profile(
            "account",
            {
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "cloud_billing_selected": False,
                "overages_enabled": False,
                "adc_present": False,
                "vertex_selected": False,
            },
            "linux",
            "x86_64",
        ),
    }


def _bridges(raw_response: str = VALID_RESPONSE):
    return {
        provider_id: CountingBridge(
            provider_id=provider_id,
            mock_raw_response=raw_response,
        )
        for provider_id in ("openai", "anthropic", "google")
    }


def _bundle(raw_response: str = VALID_RESPONSE):
    source_profiles = _profiles()
    source_bridges = _bridges(raw_response)
    bundle = ProviderAdapterBundle(source_profiles, source_bridges)
    return bundle, source_profiles, source_bridges


def _case(provider_id: str):
    return {
        "case_id": "case-1",
        "packet_sha256": "abcdef",
        "provider_id": provider_id,
        "session_id": f"session-{provider_id}",
        "correlation_id": f"corr-{provider_id}",
    }


class TestCorePR3Compatibility(unittest.TestCase):
    def test_fixture_is_pinned_to_fresh_read_core_head(self):
        self.assertEqual(CORE_PR3_HEAD, EXPECTED_CORE_PR3_HEAD)

    def test_structural_satisfaction_and_exact_provider_order(self):
        bundle, _, _ = _bundle()
        adapters = build_core_pr3_adapter_map(bundle)
        self.assertEqual(tuple(adapters), ("openai", "anthropic", "google"))
        for provider_id, adapter in adapters.items():
            self.assertEqual(adapter.provider_id, provider_id)
            self.assertIsInstance(adapter, CorePR3ProviderAdapterProtocol)

    def test_boundary_construction_causes_zero_bridge_calls(self):
        bundle, _, bridges = _bundle()
        adapters = build_core_pr3_adapter_map(bundle)
        self.assertEqual(tuple(adapters), ("openai", "anthropic", "google"))
        for bridge in bridges.values():
            self.assertEqual(bridge.prepare_count, 0)
            self.assertEqual(bridge.preflight_count, 0)
            self.assertEqual(bridge.dispatch_count, 0)
            self.assertEqual(bridge.collect_count, 0)
            self.assertEqual(bridge.abort_calls, [])
            self.assertEqual(bridge.classify_count, 0)

    def test_core_like_static_sequence_preserves_exact_raw_bytes(self):
        expected = VALID_RESPONSE.encode("utf-8")
        bundle, _, bridges = _bundle()
        adapters = build_core_pr3_adapter_map(bundle)

        for provider_id, adapter in adapters.items():
            prepared = adapter.prepare(_case(provider_id))
            preflight = adapter.preflight(prepared)
            self.assertTrue(preflight["ok"])
            self.assertEqual(preflight["static_configuration_status"], "PASS")
            self.assertFalse(preflight["live_ready"])
            self.assertEqual(preflight["live_readiness"], "BLOCKED")
            self.assertEqual(preflight["retry_count"], 0)
            self.assertEqual(preflight["fallback_state"], "disabled")

            handle = adapter.dispatch(prepared)
            self.assertFalse(handle["live_process_started"])
            raw = adapter.collect(handle)
            self.assertEqual(raw, expected)

            classification = adapter.classify(raw)
            self.assertTrue(classification["success"])
            self.assertEqual(classification["execution_state"], "COMPLETE")

            bridge = bridges[provider_id]
            self.assertEqual(bridge.prepare_count, 1)
            self.assertEqual(bridge.preflight_count, 1)
            self.assertEqual(bridge.dispatch_count, 1)
            self.assertEqual(bridge.collect_count, 1)
            self.assertEqual(bridge.abort_calls, [])
            # Provider Response Contract classification belongs to RelayCoreAdapter.
            self.assertEqual(bridge.classify_count, 0)

    def test_timeout_matches_core_isolation_without_hidden_abort_or_fallback(self):
        bundle, _, bridges = _bundle()
        bridges["openai"].simulate_timeout = True
        adapters = build_core_pr3_adapter_map(bundle)

        failing = adapters["openai"]
        prepared = failing.prepare(_case("openai"))
        self.assertTrue(failing.preflight(prepared)["ok"])
        handle = failing.dispatch(prepared)
        with self.assertRaises(TimeoutError):
            failing.collect(handle)

        self.assertEqual(bridges["openai"].abort_calls, [])
        for peer in ("anthropic", "google"):
            self.assertEqual(bridges[peer].prepare_count, 0)
            self.assertEqual(bridges[peer].preflight_count, 0)
            self.assertEqual(bridges[peer].dispatch_count, 0)
            self.assertEqual(bridges[peer].collect_count, 0)
            self.assertEqual(bridges[peer].abort_calls, [])

        healthy = adapters["anthropic"]
        prepared_h = healthy.prepare(_case("anthropic"))
        self.assertTrue(healthy.preflight(prepared_h)["ok"])
        handle_h = healthy.dispatch(prepared_h)
        self.assertEqual(
            healthy.collect(handle_h),
            VALID_RESPONSE.encode("utf-8"),
        )
        self.assertEqual(bridges["google"].dispatch_count, 0)

    def test_generic_collect_error_matches_core_isolation_without_hidden_abort(self):
        bundle, _, bridges = _bundle()
        bridges["google"].simulate_error_in_collect = True
        adapters = build_core_pr3_adapter_map(bundle)

        failing = adapters["google"]
        prepared = failing.prepare(_case("google"))
        self.assertTrue(failing.preflight(prepared)["ok"])
        handle = failing.dispatch(prepared)
        with self.assertRaises(RuntimeError):
            failing.collect(handle)

        self.assertEqual(bridges["google"].abort_calls, [])
        for peer in ("openai", "anthropic"):
            self.assertEqual(bridges[peer].dispatch_count, 0)
            self.assertEqual(bridges[peer].collect_count, 0)

        healthy = adapters["openai"]
        prepared_h = healthy.prepare(_case("openai"))
        self.assertTrue(healthy.preflight(prepared_h)["ok"])
        handle_h = healthy.dispatch(prepared_h)
        self.assertEqual(
            healthy.collect(handle_h),
            VALID_RESPONSE.encode("utf-8"),
        )
        self.assertEqual(bridges["anthropic"].dispatch_count, 0)

    def test_preflight_failure_stops_before_dispatch_and_does_not_touch_peer(self):
        bundle, _, bridges = _bundle()
        bridges["openai"].simulate_no_cli = True
        adapters = build_core_pr3_adapter_map(bundle)

        failing = adapters["openai"]
        prepared = failing.prepare(_case("openai"))
        preflight = failing.preflight(prepared)
        self.assertFalse(preflight["ok"])
        self.assertFalse(preflight["live_ready"])
        self.assertEqual(bridges["openai"].dispatch_count, 0)
        self.assertEqual(bridges["openai"].collect_count, 0)
        self.assertEqual(bridges["openai"].abort_calls, [])
        for peer in ("anthropic", "google"):
            self.assertEqual(bridges[peer].prepare_count, 0)
            self.assertEqual(bridges[peer].preflight_count, 0)
            self.assertEqual(bridges[peer].dispatch_count, 0)
            self.assertEqual(bridges[peer].collect_count, 0)

    def test_invalid_raw_bytes_are_preserved_then_classification_fails_closed(self):
        bundle, _, _ = _bundle("not json")
        adapter = build_core_pr3_adapter_map(bundle)["openai"]
        prepared = adapter.prepare(_case("openai"))
        self.assertTrue(adapter.preflight(prepared)["ok"])
        handle = adapter.dispatch(prepared)
        raw = adapter.collect(handle)
        self.assertEqual(raw, b"not json")
        classification = adapter.classify(raw)
        self.assertFalse(classification["success"])
        self.assertEqual(classification["execution_state"], "UNKNOWN")

    def test_source_and_returned_mapping_mutation_cannot_mutate_bundle(self):
        bundle, source_profiles, source_bridges = _bundle()
        adapters = build_core_pr3_adapter_map(bundle)

        source_profiles.clear()
        source_bridges.clear()
        adapters["openai"] = None

        fresh = build_core_pr3_adapter_map(bundle)
        self.assertEqual(tuple(fresh), ("openai", "anthropic", "google"))
        self.assertIsNotNone(fresh["openai"])
        self.assertEqual(bundle.adapters["openai"].provider_id, "openai")

    def test_boundary_rejects_missing_extra_mismatched_and_non_adapter_maps(self):
        def corrupt(mapping):
            bundle, _, _ = _bundle()
            bundle._adapters = MappingProxyType(mapping)
            return bundle

        good_bundle, _, _ = _bundle()
        good = dict(good_bundle.adapters)

        missing = dict(good)
        missing.pop("google")
        with self.assertRaisesRegex(ValueError, "exactly match"):
            build_core_pr3_adapter_map(corrupt(missing))

        extra = dict(good)
        extra["extra"] = good["openai"]
        with self.assertRaisesRegex(ValueError, "exactly match"):
            build_core_pr3_adapter_map(corrupt(extra))

        mismatched = dict(good)
        mismatched["openai"] = good["anthropic"]
        with self.assertRaisesRegex(ValueError, "does not match map key"):
            build_core_pr3_adapter_map(corrupt(mismatched))

        non_adapter = dict(good)
        non_adapter["google"] = object()
        with self.assertRaisesRegex(TypeError, "not a RelayCoreAdapter"):
            build_core_pr3_adapter_map(corrupt(non_adapter))

        with self.assertRaises(TypeError):
            build_core_pr3_adapter_map(None)

    def test_production_boundary_has_no_ambient_io_or_network_dependencies(self):
        path = Path("src/providers/core_boundary.py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        forbidden_imports = {
            "os",
            "subprocess",
            "socket",
            "requests",
            "http",
            "urllib",
            "pathlib",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], forbidden_imports)
            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".")[0]
                self.assertNotIn(module, forbidden_imports)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"open", "exec", "eval"})


if __name__ == "__main__":
    unittest.main()
