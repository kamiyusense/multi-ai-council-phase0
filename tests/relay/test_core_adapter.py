import json
import unittest
from copy import deepcopy

from relay.bridge import RelayProviderAdapterBridge
from relay.core_adapter import RelayCoreAdapter


class TestCoreAdapter(unittest.TestCase):
    def test_provider_id_exposure(self):
        bridge = RelayProviderAdapterBridge()
        adapter = RelayCoreAdapter("my-provider-id", bridge)
        self.assertEqual(adapter.provider_id, "my-provider-id")

    def test_deterministic_bytes_output(self):
        bridge = RelayProviderAdapterBridge()
        adapter = RelayCoreAdapter("prov", bridge)

        handle = {"correlation_id": "c123"}
        result_bytes = adapter.collect(handle)

        self.assertIsInstance(result_bytes, bytes)
        decoded = json.loads(result_bytes.decode("utf-8"))
        self.assertEqual(decoded["correlation_id"], "c123")
        self.assertEqual(decoded["rawResponse"], '{"answer_state":"ANSWER"}')
        self.assertEqual(decoded["stdout"], "mock")

    def test_malformed_missing_raw_fails_closed(self):
        bridge = RelayProviderAdapterBridge(simulate_unknown=True)
        adapter = RelayCoreAdapter("prov", bridge)
        handle = {"correlation_id": "c123"}

        with self.assertRaises(RuntimeError) as cm:
            adapter.collect(handle)

        self.assertIn("Missing or non-string rawResponse in collect", str(cm.exception))

    def test_abort_delegation(self):
        bridge = RelayProviderAdapterBridge()
        adapter = RelayCoreAdapter("prov", bridge)

        handle = {"provider_id": "prov", "session_id": "sess1"}
        res = adapter.abort(handle)

        self.assertTrue(res["aborted"])
        self.assertIn(("prov", "sess1"), bridge.abort_calls)

    def test_no_mutation_of_caller_payload(self):
        bridge = RelayProviderAdapterBridge()
        adapter = RelayCoreAdapter("prov", bridge)

        original_payload = {"foo": "bar"}
        case_context = {
            "provider_id": "prov",
            "session_id": "sess1",
            "correlation_id": "c123",
            "payload": original_payload,
            "timeout_seconds": 10
        }
        case_context_copy = deepcopy(case_context)

        prepared = adapter.prepare(case_context)

        # Verify bridge prepared things correctly
        self.assertEqual(prepared["payload"], {"foo": "bar"})

        # Verify original was not mutated
        self.assertEqual(case_context, case_context_copy)

        # Verify payload inside prepared is a copy
        original_payload["foo"] = "baz"
        self.assertEqual(prepared["payload"], {"foo": "bar"})

    def test_classify_preserves_static_values(self):
        bridge = RelayProviderAdapterBridge()
        adapter = RelayCoreAdapter("prov", bridge)

        handle = {"correlation_id": "c123"}
        result_bytes = adapter.collect(handle)

        classified = adapter.classify(result_bytes)

        self.assertTrue(classified["simulated"])
        self.assertFalse(classified["live_ready"])
        self.assertFalse(classified["live_turn_executed"])
        self.assertEqual(classified["retry_count"], 0)
        self.assertEqual(classified["fallback_state"], "disabled")
        self.assertTrue(classified["success"])
        self.assertEqual(classified["execution_state"], "COMPLETE")