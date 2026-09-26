from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from src.relay.bridge import RelayProviderAdapterBridge
from src.relay.envelope import compute_intent_hash, validate_timeout


class DuplicateConflictGuard:
    def __init__(self) -> None:
        self.ledger: dict[tuple[str, str], str] = {}

    def check_intent(self, reservation_key: tuple[str, str], payload_hash: str) -> str:
        if reservation_key not in self.ledger:
            self.ledger[reservation_key] = payload_hash
            return "RESERVED"
        return "SAME_REQUEST" if self.ledger[reservation_key] == payload_hash else "CONFLICT"


class RelayDispatcher:
    def __init__(self, adapter: RelayProviderAdapterBridge, guard: DuplicateConflictGuard):
        self.adapter = adapter
        self.guard = guard
        self.stop_requested = False
        self.cancelled_slots: set[tuple[str, str]] = set()

    def request_stop(self) -> None:
        """Prevent every future dispatch without touching an active provider."""
        self.stop_requested = True

    def dispatch(self, slot_id: str, context: dict[str, Any], abort_signal: dict[str, Any] | None = None) -> dict[str, Any]:
        if "provider_id" in context:
            provider_id = context["provider_id"]
            if not isinstance(provider_id, str) or not provider_id:
                raise ValueError("Invalid provider_id")
        else:
            provider_id = slot_id

        reservation_key = (provider_id, slot_id)

        timeout_seconds = context.get("timeout_seconds")
        validate_timeout(timeout_seconds)
        payload = context.get("payload", {})
        blocked = {"model", "modelProvider", "serviceTier", "reasoning", "effort", "thinking",
                   "approvalPolicy", "approvalsReviewer", "sandbox", "sandboxPolicy", "cwd",
                   "config", "base", "developer", "general instructions", "plugin disabling",
                   "billing", "auth route", "timeout_seconds"}
        if blocked.intersection(payload):
            raise ValueError("Request override fields rejected.")
        payload_hash = compute_intent_hash(payload, timeout_seconds)
        base = {"live_ready": False, "live_turn_executed": False, "retry_count": 0,
                "fallback_state": "disabled", "simulated": True}
        if self.stop_requested:
            return {**base, "state": "BLOCKED", "reason": "stop_requested"}
        if reservation_key in self.cancelled_slots:
            return {**base, "state": "BLOCKED", "reason": "cancelled"}
        if abort_signal and abort_signal.get("aborted"):
            self.cancelled_slots.add(reservation_key)
            return {**base, "state": "BLOCKED", "reason": "aborted"}
        decision = self.guard.check_intent(reservation_key, payload_hash)
        if decision != "RESERVED":
            return {**base, "state": "BLOCKED", "reason": decision}
        handle: dict[str, Any] | None = None
        try:
            prepared = self.adapter.prepare({
                **context,
                "provider_id": provider_id,
                "session_id": context.get("session_id", slot_id),
                "timeout_seconds": timeout_seconds,
            })
            preflight_result = self.adapter.preflight(prepared)
            if isinstance(preflight_result, dict) and preflight_result.get("ok") is True:
                pass
            elif isinstance(preflight_result, dict) and preflight_result.get("ok") is False:
                return {**base, "state": "BLOCKED", "reason": "preflight_not_ok"}
            else:
                return {**base, "state": "UNKNOWN", "reason": "preflight_unverified"}
            handle = self.adapter.dispatch(prepared)
            if abort_signal and abort_signal.get("abort_after_dispatch"):
                self.adapter.abort(handle)
                self.cancelled_slots.add(reservation_key)
                return {**base, "state": "BLOCKED", "reason": "cancelled"}
            raw_result = self.adapter.collect(handle)
            raw_evidence = deepcopy(raw_result)
            state = self.adapter.classify(raw_result)
            return {**base, "state": "SIMULATED" if state.get("success") else state["execution_state"],
                    "provider_state": state, "raw_evidence": raw_evidence}
        except TimeoutError as exc:
            if handle is not None:
                self.adapter.abort(handle)
                self.cancelled_slots.add(reservation_key)
            return {**base, "state": "TIMEOUT", "error": str(exc)}
        except Exception as exc:
            if handle is None and isinstance(exc, RuntimeError) and str(exc) == "CLI unavailable":
                raise
            if handle is not None:
                self.adapter.abort(handle)
                self.cancelled_slots.add(reservation_key)
            return {**base, "state": "UNKNOWN", "error": str(exc)}
