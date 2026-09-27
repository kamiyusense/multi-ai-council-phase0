from __future__ import annotations

import copy
import json
from typing import Any

class CoreAdapter:
    def __init__(self, provider_id: str):
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider_id must be a non-empty string")
        self.provider_id = provider_id

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]:
        prepared = copy.deepcopy(case_context)

        if "provider_id" in prepared:
            if prepared["provider_id"] != self.provider_id:
                raise ValueError("explicit provider_id conflicts with adapter configuration")
        else:
            prepared["provider_id"] = self.provider_id

        return prepared

    def collect(self, raw_result: dict[str, Any]) -> bytes:
        if not isinstance(raw_result, dict):
            raise ValueError("raw_result must be a dictionary")

        raw_response = raw_result.get("rawResponse")
        if not isinstance(raw_response, str):
            raise ValueError("rawResponse must be a string")

        return raw_response.encode('utf-8')

    def classify(self, raw_bytes: bytes) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_bytes)
        except (ValueError, TypeError):
            return {"execution_state": "UNKNOWN", "success": False}

        if not isinstance(parsed, dict):
            return {"execution_state": "UNKNOWN", "success": False}

        # Check for unexpected keys
        allowed_keys = {
            "schema_version", "answer_state", "conclusion_code",
            "safety_warning", "safety_reason", "evidence_refs",
            "marker_echoes", "answer_text"
        }

        # In case the json is a Relay wrapper dict, it will have things like rawResponse, etc.
        if any(key not in allowed_keys for key in parsed.keys()):
            return {"execution_state": "UNKNOWN", "success": False}

        # Validate schema_version if present
        if "schema_version" in parsed and parsed["schema_version"] != "phase0-response-v1":
            return {"execution_state": "UNKNOWN", "success": False}

        # Validate answer_state
        if "answer_state" not in parsed or not isinstance(parsed["answer_state"], str):
            return {"execution_state": "UNKNOWN", "success": False}

        # Validate conclusion_code
        if "conclusion_code" not in parsed or not isinstance(parsed["conclusion_code"], str):
            return {"execution_state": "UNKNOWN", "success": False}

        # Validate safety_warning
        if "safety_warning" not in parsed or parsed["safety_warning"] not in ("PRESENT", "ABSENT", "UNKNOWN"):
            return {"execution_state": "UNKNOWN", "success": False}

        # Validate safety_reason
        if "safety_reason" not in parsed or not (parsed["safety_reason"] is None or isinstance(parsed["safety_reason"], str)):
            return {"execution_state": "UNKNOWN", "success": False}

        # Validate evidence_refs
        if "evidence_refs" not in parsed or not isinstance(parsed["evidence_refs"], list):
            return {"execution_state": "UNKNOWN", "success": False}
        if not all(isinstance(ref, str) for ref in parsed["evidence_refs"]):
            return {"execution_state": "UNKNOWN", "success": False}

        # Validate marker_echoes
        if "marker_echoes" not in parsed or not isinstance(parsed["marker_echoes"], dict):
            return {"execution_state": "UNKNOWN", "success": False}

        expected_markers = {"head", "middle", "tail"}
        if set(parsed["marker_echoes"].keys()) != expected_markers:
            return {"execution_state": "UNKNOWN", "success": False}

        if not all((val is None or isinstance(val, str)) for val in parsed["marker_echoes"].values()):
            return {"execution_state": "UNKNOWN", "success": False}

        # Validate answer_text
        if "answer_text" not in parsed or not isinstance(parsed["answer_text"], str):
            return {"execution_state": "UNKNOWN", "success": False}

        return {"execution_state": "COMPLETE", "success": True}

    def abort(self, process_handle: dict[str, Any]) -> dict[str, bool]:
        return {"aborted": True}
