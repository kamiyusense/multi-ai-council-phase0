import ast
import json
import unittest
from pathlib import Path

from providers.antigravity_acp import build_antigravity_profile
from providers.base import ProviderStaticProfile
from providers.bundle import ProviderAdapterBundle
from providers.claude_acp import build_claude_profile
from providers.codex_acp import build_codex_profile
from relay.bridge import RelayProviderAdapterBridge
from relay.dispatcher import DuplicateConflictGuard, RelayDispatcher


class CountingBridge(RelayProviderAdapterBridge):
    def __init__(self, *, provider_id=None, **kwargs):
        super().__init__(**kwargs)
        self.provider_id = provider_id
        self.preflight_count = 0
        self.classify_count = 0

    def preflight(self, prepared_context):
        self.preflight_count += 1
        return super().preflight(prepared_context)

    def classify(self, raw_result):
        self.classify_count += 1
        return super().classify(raw_result)


class DuckBridge:
    def __init__(self, inner, provider_id=None):
        self.inner = inner
        self.provider_id = provider_id

    def prepare(self, value):
        return self.inner.prepare(value)

    def preflight(self, value):
        return self.inner.preflight(value)

    def dispatch(self, value):
        return self.inner.dispatch(value)

    def collect(self, value):
        return self.inner.collect(value)

    def abort(self, value):
        return self.inner.abort(value)

    def classify(self, value):
        return self.inner.classify(value)


def raw_response():
    return json.dumps(
        {
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "hello",
        }
    )


def profiles():
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


def bridges():
    response = raw_response()
    return {
        provider_id: CountingBridge(
            provider_id=provider_id,
            mock_raw_response=response,
        )
        for provider_id in ("openai", "anthropic", "google")
    }


class TestProviderAdapterBundle(unittest.TestCase):
    def test_bundle_construction_is_side_effect_free_and_deterministic(self):
        source_profiles = profiles()
        source_bridges = bridges()
        bundle = ProviderAdapterBundle(source_profiles, source_bridges)

        self.assertEqual(
            tuple(adapter.provider_id for adapter in bundle.get_adapters_in_order()),
            ("openai", "anthropic", "google"),
        )
        self.assertEqual(tuple(bundle.adapters), ("openai", "anthropic", "google"))

        for bridge in source_bridges.values():
            self.assertEqual(bridge.preflight_count, 0)
            self.assertEqual(bridge.dispatch_count, 0)
            self.assertEqual(bridge.collect_count, 0)
            self.assertEqual(bridge.classify_count, 0)
            self.assertEqual(bridge.abort_calls, [])

    def test_accepts_bridge_compatible_duck_type(self):
        source_profiles = profiles()
        source_bridges = bridges()
        source_bridges["openai"] = DuckBridge(
            source_bridges["openai"], provider_id="openai"
        )
        bundle = ProviderAdapterBundle(source_profiles, source_bridges)
        self.assertEqual(bundle.get_adapters_in_order()[0].provider_id, "openai")

    def test_all_three_static_preflights_pass_but_live_stays_blocked(self):
        bundle = ProviderAdapterBundle(profiles(), bridges())
        for adapter in bundle.get_adapters_in_order():
            prepared = adapter.prepare(
                {
                    "case_id": "case",
                    "provider_id": adapter.provider_id,
                    "session_id": f"sess-{adapter.provider_id}",
                    "correlation_id": f"corr-{adapter.provider_id}",
                }
            )
            result = adapter.preflight(prepared)
            self.assertTrue(result["ok"])
            self.assertEqual(result["static_configuration_status"], "PASS")
            self.assertFalse(result["live_ready"])
            self.assertEqual(result["live_readiness"], "BLOCKED")

    def test_exact_mock_round_trip_once_per_provider(self):
        source_bridges = bridges()
        bundle = ProviderAdapterBundle(profiles(), source_bridges)

        for adapter in bundle.get_adapters_in_order():
            dispatcher = RelayDispatcher(adapter, DuplicateConflictGuard())
            result = dispatcher.dispatch(
                f"slot-{adapter.provider_id}",
                {
                    "case_id": "case",
                    "provider_id": adapter.provider_id,
                    "session_id": f"sess-{adapter.provider_id}",
                    "correlation_id": f"corr-{adapter.provider_id}",
                    "payload": {},
                },
            )
            self.assertEqual(result["state"], "SIMULATED")
            self.assertEqual(result["retry_count"], 0)
            self.assertEqual(result["fallback_state"], "disabled")
            self.assertFalse(result["live_ready"])
            self.assertFalse(result["live_turn_executed"])
            self.assertEqual(
                result["raw_evidence"],
                raw_response().encode("utf-8"),
            )
            self.assertTrue(result["provider_state"]["success"])

        for bridge in source_bridges.values():
            self.assertEqual(bridge.dispatch_count, 1)
            self.assertEqual(bridge.collect_count, 1)
            # RelayCoreAdapter owns Provider Response Contract classification;
            # the transport bridge must not classify the raw bytes again.
            self.assertEqual(bridge.classify_count, 0)

    def test_timeout_does_not_touch_or_fallback_to_other_provider(self):
        source_bridges = bridges()
        source_bridges["openai"].simulate_timeout = True
        bundle = ProviderAdapterBundle(profiles(), source_bridges)
        adapters = bundle.adapters

        result = RelayDispatcher(
            adapters["openai"], DuplicateConflictGuard()
        ).dispatch(
            "slot-openai",
            {
                "provider_id": "openai",
                "session_id": "sess-openai",
                "correlation_id": "corr-openai",
                "payload": {},
            },
        )
        self.assertEqual(result["state"], "TIMEOUT")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")
        self.assertEqual(source_bridges["openai"].dispatch_count, 1)
        self.assertEqual(source_bridges["openai"].collect_count, 1)
        self.assertEqual(len(source_bridges["openai"].abort_calls), 1)
        for other in ("anthropic", "google"):
            self.assertEqual(source_bridges[other].dispatch_count, 0)
            self.assertEqual(source_bridges[other].collect_count, 0)
            self.assertEqual(source_bridges[other].abort_calls, [])

    def test_error_does_not_touch_or_fallback_to_other_provider(self):
        source_bridges = bridges()
        source_bridges["anthropic"].simulate_error_in_collect = True
        bundle = ProviderAdapterBundle(profiles(), source_bridges)
        adapters = bundle.adapters

        result = RelayDispatcher(
            adapters["anthropic"], DuplicateConflictGuard()
        ).dispatch(
            "slot-anthropic",
            {
                "provider_id": "anthropic",
                "session_id": "sess-anthropic",
                "correlation_id": "corr-anthropic",
                "payload": {},
            },
        )
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")
        self.assertEqual(source_bridges["anthropic"].dispatch_count, 1)
        self.assertEqual(source_bridges["anthropic"].collect_count, 1)
        self.assertEqual(len(source_bridges["anthropic"].abort_calls), 1)
        for other in ("openai", "google"):
            self.assertEqual(source_bridges[other].dispatch_count, 0)
            self.assertEqual(source_bridges[other].collect_count, 0)
            self.assertEqual(source_bridges[other].abort_calls, [])

    def test_rejects_missing_extra_and_mismatched_profiles(self):
        good_profiles = profiles()
        good_bridges = bridges()

        missing = dict(good_profiles)
        missing.pop("google")
        with self.assertRaisesRegex(ValueError, "Profiles must exactly match"):
            ProviderAdapterBundle(missing, good_bridges)

        extra = dict(good_profiles)
        extra["extra"] = good_profiles["openai"]
        with self.assertRaisesRegex(ValueError, "Profiles must exactly match"):
            ProviderAdapterBundle(extra, good_bridges)

        mismatched = dict(good_profiles)
        mismatched["anthropic"] = good_profiles["openai"]
        with self.assertRaisesRegex(ValueError, "profile key/provider_id mismatch"):
            ProviderAdapterBundle(mismatched, good_bridges)

    def test_rejects_missing_extra_and_mismatched_bridges(self):
        good_profiles = profiles()
        good_bridges = bridges()

        missing = dict(good_bridges)
        missing.pop("google")
        with self.assertRaisesRegex(ValueError, "Bridges must exactly match"):
            ProviderAdapterBundle(good_profiles, missing)

        extra = dict(good_bridges)
        extra["extra"] = CountingBridge(provider_id="extra")
        with self.assertRaisesRegex(ValueError, "Bridges must exactly match"):
            ProviderAdapterBundle(good_profiles, extra)

        mismatched = dict(good_bridges)
        mismatched["google"] = CountingBridge(provider_id="openai")
        with self.assertRaisesRegex(ValueError, "bridge key/provider_id mismatch"):
            ProviderAdapterBundle(good_profiles, mismatched)

    def test_rejects_non_profile_and_non_compatible_bridge(self):
        bad_profiles = profiles()
        bad_profiles["google"] = object()
        with self.assertRaisesRegex(TypeError, "ProviderStaticProfile"):
            ProviderAdapterBundle(bad_profiles, bridges())

        bad_bridges = bridges()
        bad_bridges["google"] = object()
        with self.assertRaisesRegex(TypeError, "bridge must provide callable"):
            ProviderAdapterBundle(profiles(), bad_bridges)

    def test_source_mapping_mutation_and_returned_snapshots_cannot_mutate_bundle(self):
        source_profiles = profiles()
        source_bridges = bridges()
        bundle = ProviderAdapterBundle(source_profiles, source_bridges)

        source_profiles.clear()
        source_bridges.clear()
        self.assertEqual(
            tuple(adapter.provider_id for adapter in bundle.get_adapters_in_order()),
            ("openai", "anthropic", "google"),
        )

        returned = bundle.get_adapters_in_order()
        self.assertIsInstance(returned, tuple)
        with self.assertRaises(TypeError):
            bundle.adapters["openai"] = returned[0]

    def test_new_module_has_no_os_subprocess_or_network_side_effect_imports(self):
        path = Path("src/providers/bundle.py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, ("os", "subprocess", "socket"))
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, ("os", "subprocess", "socket"))


if __name__ == "__main__":
    unittest.main()
