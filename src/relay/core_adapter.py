import json
from copy import deepcopy
from typing import Any
from src.relay.bridge import RelayProviderAdapterBridge

class RelayCoreAdapter:
    def __init__(self, provider_id: str, bridge: RelayProviderAdapterBridge):
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider_id must be a non-empty string")
        self.provider_id = provider_id
        self.bridge = bridge

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]:
        ctx = deepcopy(case_context)
        if "provider_id" not in ctx:
            ctx["provider_id"] = self.provider_id
        elif ctx["provider_id"] != self.provider_id:
            raise ValueError(f"Conflicting provider_id: {ctx['provider_id']} != {self.provider_id}")
        return self.bridge.prepare(ctx)

    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.preflight(prepared_context)

    def dispatch(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.dispatch(prepared_context)

    def abort(self, process_handle: dict[str, Any]) -> dict[str, bool]:
        return self.bridge.abort(process_handle)

    def collect(self, process_handle: dict[str, Any]) -> bytes:
        res = self.bridge.collect(process_handle)
        raw = res.get("rawResponse")
        if not isinstance(raw, str):
            raise RuntimeError("rawResponse missing or not a string")
        return raw.encode("utf-8")

    def classify(self, raw_bytes: bytes) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
            return {
                "execution_state": "COMPLETE",
                "participation_state": "PARTICIPANT",
                "success": True,
                "rawResponse": parsed,
            }
        except Exception:
            return {"execution_state": "UNKNOWN", "success": False}
