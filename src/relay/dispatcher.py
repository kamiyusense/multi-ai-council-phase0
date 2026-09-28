from src.relay.bridge import RelayProviderAdapterBridge

class DuplicateConflictGuard:
    def __init__(self):
        self.ledger = {}

    def check_intent(self, slot_id, payload_hash):
        if slot_id in self.ledger:
            if self.ledger[slot_id] == payload_hash:
                return True
            else:
                raise ValueError(f"Conflict: slot {slot_id} already dispatched.")
        self.ledger[slot_id] = payload_hash
        return False

class RelayDispatcher:
    def __init__(self, adapter: RelayProviderAdapterBridge, guard: DuplicateConflictGuard):
        self.adapter = adapter
        self.guard = guard

    def dispatch(self, slot_id, context, abort_signal=None):
        payload = context.get("payload", {})
        blocked_fields = ["model", "modelProvider", "serviceTier", "reasoning", "effort", "thinking", "approvalPolicy", "approvalsReviewer", "sandbox", "sandboxPolicy", "cwd", "config", "base", "developer", "general instructions", "plugin disabling", "billing", "auth route"]
        for field in blocked_fields:
            if field in payload:
                raise ValueError("Request override fields rejected.")

        payload_hash = hash(str(payload))
        if self.guard.check_intent(slot_id, payload_hash):
            return {"state": "DELIVERED"}

        if abort_signal and abort_signal.get("aborted"):
            return {"state": "BLOCKED"}

        try:
            prepared = self.adapter.prepare(context)
            preflight = self.adapter.preflight(prepared)
            handle = self.adapter.dispatch(prepared)

            # Action before execution flag check (mocked execution)
            context["live_turn_executed"] = False

            raw_res = self.adapter.collect(handle)
            state = self.adapter.classify(raw_res)
            return {"state": "DELIVERED", "provider_state": state}
        except TimeoutError:
            return {"state": "FAILED"} # no retry
        except Exception as e:
            if "CLI unavailable" in str(e):
                raise
            return {"state": "FAILED"} # no fallback
