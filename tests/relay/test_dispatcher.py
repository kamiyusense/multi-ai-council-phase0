import pytest
from src.relay.dispatcher import RelayDispatcher, DuplicateConflictGuard
from src.relay.bridge import RelayProviderAdapterBridge

def make(adapter=None):
    return RelayDispatcher(adapter or RelayProviderAdapterBridge(), DuplicateConflictGuard())

def test_successful_dispatch_is_simulated():
    result = make().dispatch("slot1", {"case_id":"1", "payload":{"q":"test"}})
    assert result["state"] == "SIMULATED"
    assert result["live_turn_executed"] is False
    assert result["retry_count"] == 0
    assert result["fallback_state"] == "disabled"

def test_override_protection():
    with pytest.raises(ValueError, match="override"):
        make().dispatch("slot2", {"payload":{"model":"gpt-4"}})

def test_deterministic_hash_and_duplicate_block():
    d = make(); payload1={"b":2,"a":1}; payload2={"a":1,"b":2}
    assert d.dispatch("slot3", {"payload":payload1})["state"] == "SIMULATED"
    assert d.dispatch("slot3", {"payload":payload2})["state"] == "BLOCKED"

def test_conflict_blocked():
    d=make(); d.dispatch("slot4", {"payload":{"a":1}})
    assert d.dispatch("slot4", {"payload":{"a":2}})["state"] == "BLOCKED"

def test_timeout_no_retry():
    assert make(RelayProviderAdapterBridge(simulate_timeout=True)).dispatch("slot5", {"payload":{}})["state"] == "TIMEOUT"

def test_failure_no_fallback():
    assert make(RelayProviderAdapterBridge(simulate_failure=True)).dispatch("slot6", {"payload":{}})["state"] == "UNKNOWN"

def test_malformed_not_success():
    r=make(RelayProviderAdapterBridge(simulate_malformed=True)).dispatch("slot7", {"payload":{}})
    assert r["state"] == "INVALID_OUTPUT"
    assert r["state"] != "DELIVERED"

def test_unknown_not_success():
    assert make(RelayProviderAdapterBridge(simulate_unknown=True)).dispatch("slot8", {"payload":{}})["state"] == "UNKNOWN"

def test_no_cli_no_dummy_fallback():
    with pytest.raises(RuntimeError, match="CLI unavailable"):
        make(RelayProviderAdapterBridge(simulate_no_cli=True)).dispatch("slot9", {"payload":{}})
