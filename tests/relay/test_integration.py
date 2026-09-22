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


if __name__ == "__main__":
    unittest.main()
