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
        adapter = RelayProviderAdapterBridge(simulate_timeout=True)
        dispatcher = make(adapter)
        result = dispatcher.dispatch(
            "slot5", {"payload": {}}
        )
        self.assertEqual(result["state"], "TIMEOUT")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(adapter.dispatch_count, 1)
        self.assertEqual(adapter.collect_count, 1)
        self.assertEqual(adapter.abort_calls, [("slot5", "slot5")])
        self.assertEqual(dispatcher.dispatch("slot5", {"payload": {}})["state"], "BLOCKED")
        self.assertEqual(adapter.dispatch_count, 1)

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
        self.assertEqual(result["raw_evidence"]["rawResponse"], "{}")

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

    def test_stop_prevents_dispatch_without_reserving_slot(self):
        adapter = RelayProviderAdapterBridge()
        dispatcher = make(adapter)
        dispatcher.request_stop()
        result = dispatcher.dispatch("slot-stop", {"payload": {"q": "test"}})
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "stop_requested")
        self.assertEqual(adapter.dispatch_count, 0)
        self.assertNotIn("slot-stop", dispatcher.guard.ledger)

    def test_cancel_is_scoped_and_never_restarts(self):
        first = RelayProviderAdapterBridge()
        second = RelayProviderAdapterBridge()
        first_dispatcher = make(first)
        second_dispatcher = make(second)

        cancelled = first_dispatcher.dispatch(
            "openai-slot",
            {"provider_id": "openai", "session_id": "openai-session", "payload": {}},
            {"abort_after_dispatch": True},
        )
        other = second_dispatcher.dispatch(
            "anthropic-slot",
            {"provider_id": "anthropic", "session_id": "anthropic-session", "payload": {}},
        )
        replay = first_dispatcher.dispatch("openai-slot", {"payload": {}})

        self.assertEqual(cancelled["state"], "BLOCKED")
        self.assertEqual(first.abort_calls, [("openai", "openai-session")])
        self.assertEqual(first.dispatch_count, 1)
        self.assertEqual(first.collect_count, 0)
        self.assertEqual(replay["state"], "BLOCKED")
        self.assertEqual(first.dispatch_count, 1)
        self.assertEqual(other["state"], "SIMULATED")
        self.assertEqual(second.abort_calls, [])


if __name__ == "__main__":
    unittest.main()
