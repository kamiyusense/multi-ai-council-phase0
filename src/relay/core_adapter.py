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
        if "provider_id" in context_copy:
            explicit_id = context_copy["provider_id"]
            if explicit_id != self.provider_id:
                raise ValueError(
                    f"Conflicting provider_id: expected {self.provider_id}, got {explicit_id}"
                )
        else:
            context_copy["provider_id"] = self.provider_id

        return self.bridge.prepare(context_copy)

    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.preflight(prepared_context)

    def dispatch(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return self.bridge.dispatch(prepared_context)

    def collect(self, process_handle: dict[str, Any]) -> bytes:
        result = self.bridge.collect(process_handle)
        if not isinstance(result, dict):
            raise TypeError("bridge.collect must return a dictionary")
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
            "answer_text",
        }

        for key in parsed:
            if key not in allowed_keys:
                return fail_result

        if "schema_version" in parsed:
            if parsed["schema_version"] != "phase0-response-v1":
                return fail_result

        required_fields = {
            "answer_state",
            "conclusion_code",
            "safety_warning",
            "safety_reason",
            "evidence_refs",
            "marker_echoes",
            "answer_text",
        }
        for field in required_fields:
            if field not in parsed:
                return fail_result

        if not isinstance(parsed["answer_state"], str):
            return fail_result
        if not isinstance(parsed["conclusion_code"], str):
            return fail_result

        safety_warning = parsed["safety_warning"]
        if safety_warning not in ("PRESENT", "ABSENT", "UNKNOWN"):
            return fail_result

        safety_reason = parsed["safety_reason"]
        if safety_reason is not None and not isinstance(safety_reason, str):
            return fail_result

        evidence_refs = parsed["evidence_refs"]
        if not isinstance(evidence_refs, list):
            return fail_result
        if not all(isinstance(ref, str) for ref in evidence_refs):
            return fail_result

        marker_echoes = parsed["marker_echoes"]
        if not isinstance(marker_echoes, dict):
            return fail_result
        if set(marker_echoes) != {"head", "middle", "tail"}:
            return fail_result
        if not all(value is None or isinstance(value, str) for value in marker_echoes.values()):
            return fail_result

        if not isinstance(parsed["answer_text"], str):
            return fail_result

        return {
            "execution_state": "COMPLETE",
            "participation_state": "PARTICIPANT",
            "success": True,
        }
