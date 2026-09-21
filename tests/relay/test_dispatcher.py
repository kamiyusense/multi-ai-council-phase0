import pytest
from src.relay.dispatcher import RelayDispatcher, DuplicateConflictGuard
from src.relay.bridge import RelayProviderAdapterBridge

def test_successful_dispatch():
    dispatcher = RelayDispatcher(RelayProviderAdapterBridge(), DuplicateConflictGuard())
    res = dispatcher.dispatch("slot1", {"case_id": "1", "payload": {"q": "test"}})
    assert res["state"] == "DELIVERED"
    assert res["provider_state"]["execution_state"] == "COMPLETE"

def test_override_protection():
    dispatcher = RelayDispatcher(RelayProviderAdapterBridge(), DuplicateConflictGuard())
    with pytest.raises(ValueError, match="override"):
        dispatcher.dispatch("slot2", {"case_id": "2", "payload": {"model": "gpt-4"}})

def test_timeout_no_retry():
    dispatcher = RelayDispatcher(RelayProviderAdapterBridge(simulate_timeout=True), DuplicateConflictGuard())
    res = dispatcher.dispatch("slot3", {"case_id": "3", "payload": {"q": "test"}})
    assert res["state"] == "FAILED"

def test_failure_no_fallback():
    dispatcher = RelayDispatcher(RelayProviderAdapterBridge(simulate_failure=True), DuplicateConflictGuard())
    res = dispatcher.dispatch("slot4", {"case_id": "4", "payload": {"q": "test"}})
    assert res["state"] == "FAILED"

def test_malformed_result():
    dispatcher = RelayDispatcher(RelayProviderAdapterBridge(simulate_malformed=True), DuplicateConflictGuard())
    res = dispatcher.dispatch("slot5", {"case_id": "5", "payload": {"q": "test"}})
    assert res["state"] == "DELIVERED"
    assert res["provider_state"]["execution_state"] == "INVALID_OUTPUT"

def test_no_cli_fallback():
    dispatcher = RelayDispatcher(RelayProviderAdapterBridge(simulate_no_cli=True), DuplicateConflictGuard())
    with pytest.raises(Exception, match="CLI unavailable"):
        dispatcher.dispatch("slot6", {"case_id": "6", "payload": {"q": "test"}})

def test_abort_signal():
    dispatcher = RelayDispatcher(RelayProviderAdapterBridge(), DuplicateConflictGuard())
    res = dispatcher.dispatch("slot7", {"case_id": "7", "payload": {"q": "test"}}, abort_signal={"aborted": True})
    assert res["state"] == "BLOCKED"
