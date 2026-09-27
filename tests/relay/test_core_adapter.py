import json
import unittest
from src.relay.bridge import RelayProviderAdapterBridge
from src.relay.core_adapter import RelayCoreAdapter

class MockPhase0Bridge(RelayProviderAdapterBridge):
    def collect(self, process_handle):
        return {
            "stdout": "ignored",
            "rawResponse": '{"answer_state": "ANSWER"}',
            "correlation_id": "test"
        }

class TestRelayCoreAdapter(unittest.TestCase):
    def test_provider_id_validation(self):
        with self.assertRaises(ValueError):
            RelayCoreAdapter("", RelayProviderAdapterBridge())
        with self.assertRaises(ValueError):
            RelayCoreAdapter(None, RelayProviderAdapterBridge())

    def test_prepare_omitted_provider_id_injected(self):
        adapter = RelayCoreAdapter("test_provider", RelayProviderAdapterBridge())
        ctx = {"session_id": "s1", "correlation_id": "c1"}
        prepared = adapter.prepare(ctx)
        self.assertEqual(prepared["provider_id"], "test_provider")
        self.assertNotIn("provider_id", ctx)  # payload unmodified

    def test_prepare_conflict_rejected(self):
        adapter = RelayCoreAdapter("test_provider", RelayProviderAdapterBridge())
        ctx = {"provider_id": "other_provider", "session_id": "s1", "correlation_id": "c1"}
        with self.assertRaises(ValueError):
            adapter.prepare(ctx)

    def test_collect_returns_exact_raw_bytes(self):
        adapter = RelayCoreAdapter("test_provider", MockPhase0Bridge())
        res = adapter.collect({})
        self.assertEqual(res, b'{"answer_state": "ANSWER"}')

    def test_collect_missing_raw_fails(self):
        class BadBridge(RelayProviderAdapterBridge):
            def collect(self, process_handle):
                return {"stdout": "missing_raw"}
        adapter = RelayCoreAdapter("test_provider", BadBridge())
        with self.assertRaises(RuntimeError):
            adapter.collect({})

    def test_collect_non_string_raw_fails(self):
        class BadBridge(RelayProviderAdapterBridge):
            def collect(self, process_handle):
                return {"rawResponse": {}}
        adapter = RelayCoreAdapter("test_provider", BadBridge())
        with self.assertRaises(RuntimeError):
            adapter.collect({})

    def test_abort_delegates(self):
        bridge = RelayProviderAdapterBridge()
        adapter = RelayCoreAdapter("test_provider", bridge)
        adapter.abort({"provider_id": "test", "session_id": "s1"})
        self.assertEqual(len(bridge.abort_calls), 1)

    def test_classify_fail_closed(self):
        adapter = RelayCoreAdapter("test_provider", RelayProviderAdapterBridge())
        res = adapter.classify(b"not json")
        self.assertEqual(res, {"execution_state": "UNKNOWN", "success": False})

    def test_classify_never_claims_live(self):
        adapter = RelayCoreAdapter("test_provider", RelayProviderAdapterBridge())
        res = adapter.classify(b'{"answer_state": "ANSWER"}')
        self.assertEqual(res["execution_state"], "COMPLETE")
        self.assertNotIn("live_ready", res)
        self.assertNotIn("delivery", res)
        self.assertNotIn("retry", res)
        self.assertNotIn("fallback", res)

if __name__ == '__main__':
    unittest.main()
