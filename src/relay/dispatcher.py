from __future__ import annotations

import hashlib
import json
from typing import Any

from src.relay.bridge import RelayProviderAdapterBridge


class DuplicateConflictGuard:
    def __init__(self) -> None:
        self.ledger: dict[str, str] = {}

    def check_intent(self, slot_id: str, payload_hash: str) -> str:
        if slot_id not in self.ledger:
            self.ledger[slot_id] = payload_hash
            return "RESERVED"
        return "SAME_REQUEST" if self.ledger[slot_id] == payload_hash else "CONFLICT"


class RelayDispatcher:
    def __init__(self, adapter: RelayProviderAdapterBridge, guard: DuplicateConflictGuard):
        self.adapter = adapter
        self.guard = guard

    def dispatch(self, slot_id: str, context: dict[str, Any], abort_signal: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = context.get("payload", {})
        blocked = {"model", "modelProvider", "serviceTier", "reasoning", "effort", "thinking",
                   "approvalPolicy", "approvalsReviewer", "sandbox", "sandboxPolicy", "cwd",
                   "config", "base", "developer", "general instructions", "plugin disabling",
                   "billing", "auth route"}
        if blocked.intersection(payload):
            raise ValueError("Request override fields rejected.")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        payload_hash = hashlib.sha256(canonical).hexdigest()
        decision = self.guard.check_intent(slot_id, payload_hash)
        base = {"live_ready": False, "live_turn_executed": False, "retry_count": 0,
                "fallback_state": "disabled", "simulated": True}
        if decision != "RESERVED":
            return {**base, "state": "BLOCKED", "reason": decision}
        if abort_signal and abort_signal.get("aborted"):
            return {**base, "state": "BLOCKED", "reason": "aborted"}
        try:
            prepared = self.adapter.prepare(context)
            self.adapter.preflight(prepared)
            handle = self.adapter.dispatch(prepared)
            state = self.adapter.classify(self.adapter.collect(handle))
            return {**base, "state": "SIMULATED" if state.get("success") else state["execution_state"],
                    "provider_state": state}
        except TimeoutError as exc:
            return {**base, "state": "TIMEOUT", "error": str(exc)}
        except RuntimeError as exc:
            if str(exc) == "CLI unavailable":
                raise
            return {**base, "state": "UNKNOWN", "error": str(exc)}
