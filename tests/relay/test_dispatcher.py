import unittest

from src.relay.dispatcher import RelayDispatcher, DuplicateConflictGuard
from src.relay.bridge import RelayProviderAdapterBridge


def make(adapter=None):
    return RelayDispatcher(adapter or RelayProviderAdapterBridge(), DuplicateConflictGuard())


class RelayDispatcherTests(unittest.TestCase):
    def test_successful_dispatch_is_simulated(self):
        result = make().dispatch("slot1", {"case_id": "1", "payload": {"q": "test"}})
        self.assertEqual(result["state"], "SIMULATED")
        self.assertFalse(result["live_turn_executed"])
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")

    def test_override_protection(self):
        with self.assertRaisesRegex(ValueError, "override"):
            make().dispatch("slot2", {"payload": {"model": "gpt-4"}})

    def test_deterministic_hash_and_duplicate_block(self):
        d = make()
        payload1 = {"b": 2, "a": 1}
        payload2 = {"a": 1, "b": 2}
        self.assertEqual(d.dispatch("slot3", {"payload": payload1})["state"], "SIMULATED")
        self.assertEqual(d.dispatch("slot3", {"payload": payload2})["state"], "BLOCKED")

    def test_conflict_blocked(self):
        d = make()
        d.dispatch("slot4", {"payload": {"a": 1}})
        self.assertEqual(d.dispatch("slot4", {"payload": {"a": 2}})["state"], "BLOCKED")

    def test_timeout_no_retry(self):
        result = make(RelayProviderAdapterBridge(simulate_timeout=True)).dispatch(
            "slot5", {"payload": {}}
        )
        self.assertEqual(result["state"], "TIMEOUT")

    def test_failure_no_fallback(self):
        result = make(RelayProviderAdapterBridge(simulate_failure=True)).dispatch(
            "slot6", {"payload": {}}
        )
        self.assertEqual(result["state"], "UNKNOWN")

    def test_malformed_not_success(self):
        result = make(RelayProviderAdapterBridge(simulate_malformed=True)).dispatch(
            "slot7", {"payload": {}}
        )
        self.assertEqual(result["state"], "INVALID_OUTPUT")
        self.assertNotEqual(result["state"], "DELIVERED")

    def test_unknown_not_success(self):
        result = make(RelayProviderAdapterBridge(simulate_unknown=True)).dispatch(
            "slot8", {"payload": {}}
        )
        self.assertEqual(result["state"], "UNKNOWN")

    def test_no_cli_no_dummy_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "CLI unavailable"):
            make(RelayProviderAdapterBridge(simulate_no_cli=True)).dispatch(
                "slot9", {"payload": {}}
            )


if __name__ == "__main__":
    unittest.main()
