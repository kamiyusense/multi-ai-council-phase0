from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .bridge import RelayProviderAdapterBridge


class RelayCoreAdapter:
    def __init__(self, provider_id: str, bridge: RelayProviderAdapterBridge):
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider_id must be a non-empty string")
        self.provider_id = provider_id
        self.bridge = bridge

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]:
        context_copy = deepcopy(case_context)
        explicit_id = context_copy.get("provider_id")
        if explicit_id is not None and explicit_id != self.provider_id:
            raise ValueError(f"Conflicting provider_id: expected {self.provider_id}, got {explicit_id}")
        if explicit_id is None:
            context_copy["provider_id"] = self.provider_id

        return self.bridge.prepare(context_copy)

    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.preflight(prepared_context)

    def dispatch(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.dispatch(prepared_context)

    def collect(self, process_handle: dict[str, Any]) -> bytes:
        result = self.bridge.collect(process_handle)
        raw_response = result.get("rawResponse")
        if not isinstance(raw_response, str):
            raise TypeError("rawResponse must be a string")
        return raw_response.encode("utf-8")

    def abort(self, process_handle: dict[str, Any]) -> dict[str, bool]:
        return self.bridge.abort(process_handle)

    def classify(self, raw_result: bytes) -> dict[str, Any]:
        fail_result = {"execution_state": "UNKNOWN", "success": False}
        try:
            parsed = json.loads(raw_result.decode("utf-8"))
        except (ValueError, TypeError, UnicodeDecodeError):
            return fail_result

        if not isinstance(parsed, dict):
            return fail_result

        allowed_keys = {
            "schema_version",
            "answer_state",
            "conclusion_code",
            "safety_warning",
            "safety_reason",
            "evidence_refs",
            "marker_echoes",
            "answer_text"
        }

        for k in parsed.keys():
            if k not in allowed_keys:
                return fail_result

        if "schema_version" in parsed:
            if parsed["schema_version"] != "phase0-response-v1":
                return fail_result

        req_fields = {
            "answer_state",
            "conclusion_code",
            "safety_warning",
            "safety_reason",
            "evidence_refs",
            "marker_echoes",
            "answer_text"
        }
        for f in req_fields:
            if f not in parsed:
                return fail_result

        if not isinstance(parsed["answer_state"], str): return fail_result
        if not isinstance(parsed["conclusion_code"], str): return fail_result

        sw = parsed["safety_warning"]
        if sw not in ("PRESENT", "ABSENT", "UNKNOWN"): return fail_result

        sr = parsed["safety_reason"]
        if sr is not None and not isinstance(sr, str): return fail_result

        er = parsed["evidence_refs"]
        if not isinstance(er, list): return fail_result
        for r in er:
            if not isinstance(r, str): return fail_result

        me = parsed["marker_echoes"]
        if not isinstance(me, dict): return fail_result
        if set(me.keys()) != {"head", "middle", "tail"}: return fail_result
        for mv in me.values():
            if mv is not None and not isinstance(mv, str): return fail_result

        if not isinstance(parsed["answer_text"], str): return fail_result

        return {
            "execution_state": "COMPLETE",
            "participation_state": "PARTICIPANT",
            "success": True
        }
