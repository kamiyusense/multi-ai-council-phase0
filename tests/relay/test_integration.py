import unittest

from src.relay.dispatcher import RelayDispatcher, DuplicateConflictGuard
from src.relay.bridge import RelayProviderAdapterBridge


class RelayIntegrationTests(unittest.TestCase):
    def test_three_provider_mock_integration(self):
        results = []
        for provider in ("openai", "anthropic", "google"):
            result = RelayDispatcher(
                RelayProviderAdapterBridge(), DuplicateConflictGuard()
            ).dispatch(provider, {"payload": {"q": "test"}})
            results.append(result)

        self.assertTrue(all(r["state"] == "SIMULATED" for r in results))
        self.assertTrue(
            all(r["provider_state"]["participation_state"] == "PARTICIPANT" for r in results)
        )
        self.assertTrue(all(r["live_turn_executed"] is False for r in results))
        self.assertTrue(all(r["retry_count"] == 0 for r in results))
        self.assertTrue(all(r["fallback_state"] == "disabled" for r in results))
        self.assertTrue(all(r["raw_evidence"]["rawResponse"] for r in results))

    def test_one_provider_failure_preserves_other_raw_success(self):
        openai = RelayDispatcher(
            RelayProviderAdapterBridge(), DuplicateConflictGuard()
        ).dispatch("openai", {"provider_id": "openai", "payload": {"q": "test"}})
        anthropic = RelayDispatcher(
            RelayProviderAdapterBridge(simulate_failure=True), DuplicateConflictGuard()
        ).dispatch("anthropic", {"provider_id": "anthropic", "payload": {"q": "test"}})
        google = RelayDispatcher(
            RelayProviderAdapterBridge(), DuplicateConflictGuard()
        ).dispatch("google", {"provider_id": "google", "payload": {"q": "test"}})

        self.assertEqual(anthropic["state"], "UNKNOWN")
        self.assertEqual(anthropic["fallback_state"], "disabled")
        self.assertEqual(openai["state"], "SIMULATED")
        self.assertEqual(google["state"], "SIMULATED")
        self.assertEqual(openai["raw_evidence"]["stdout"], "mock")
        self.assertEqual(google["raw_evidence"]["stdout"], "mock")


if __name__ == "__main__":
    unittest.main()
