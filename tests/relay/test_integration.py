from src.relay.dispatcher import RelayDispatcher, DuplicateConflictGuard
from src.relay.bridge import RelayProviderAdapterBridge

def test_three_provider_mock_integration():
    results=[]
    for provider in ("openai", "anthropic", "google"):
        result=RelayDispatcher(RelayProviderAdapterBridge(), DuplicateConflictGuard()).dispatch(provider, {"payload":{"q":"test"}})
        results.append(result)
    assert all(r["state"] == "SIMULATED" for r in results)
    assert all(r["provider_state"]["participation_state"] == "PARTICIPANT" for r in results)
    assert all(r["live_turn_executed"] is False for r in results)
    assert all(r["retry_count"] == 0 for r in results)
    assert all(r["fallback_state"] == "disabled" for r in results)
