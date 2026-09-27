from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .bridge import RelayProviderAdapterBridge


class RelayCoreAdapter:
    """Relay-side compatibility adapter that wraps a RelayProviderAdapterBridge
    to conform to the Core boundary protocol (which expects bytes from collect()
    and a provider_id attribute)."""

    def __init__(self, provider_id: str, bridge: RelayProviderAdapterBridge):
        self._provider_id = provider_id
        self._bridge = bridge

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]:
        return self._bridge.prepare(deepcopy(case_context))

    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return self._bridge.preflight(prepared_context)

    def dispatch(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return self._bridge.dispatch(prepared_context)

    def collect(self, process_handle: dict[str, Any]) -> bytes:
        raw_result = self._bridge.collect(process_handle)

        if not isinstance(raw_result, dict):
            raise RuntimeError("Expected dict from bridge collect")

        raw_response = raw_result.get("rawResponse")
        if not isinstance(raw_response, str):
            raise RuntimeError("Missing or non-string rawResponse in collect")

        return json.dumps(raw_result, sort_keys=True).encode("utf-8")

    def abort(self, process_handle: dict[str, Any]) -> dict[str, bool]:
        return self._bridge.abort(process_handle)

    def classify(self, result_bytes: bytes) -> dict[str, Any]:
        try:
            raw_result = json.loads(result_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raw_result = {}

        bridge_state = self._bridge.classify(raw_result)

        return {
            **bridge_state,
            "simulated": True,
            "live_ready": False,
            "live_turn_executed": False,
            "retry_count": 0,
            "fallback_state": "disabled",
        }
