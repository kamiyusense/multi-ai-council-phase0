from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from providers.preflight import validate_provider_static
from .bridge import RelayProviderAdapterBridge


class RelayCoreAdapter:
    def __init__(self, provider_id: str, bridge: RelayProviderAdapterBridge, static_preflight_config: dict[str, Any] | None = None):
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("provider_id must be a non-empty string")
        self.provider_id = provider_id
        self.bridge = bridge
        self.static_preflight_config = deepcopy(static_preflight_config)

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
        fail_result = {
            "ok": False,
            "live_ready": False,
            "static_configuration_status": "UNKNOWN",
            "reasons": []
        }

        try:
            bridge_res = self.bridge.preflight(prepared_context)
        except Exception as e:
            fail_result["reasons"].append(f"bridge preflight exception: {e}")
            return fail_result

        if not isinstance(bridge_res, dict) or bridge_res.get("ok") is not True or bridge_res.get("live_ready") is not False:
            fail_result["reasons"].append("bridge preflight failed or returned invalid dict")
            return fail_result

        if not isinstance(self.static_preflight_config, dict):
            fail_result["reasons"].append("static_preflight_config missing or malformed")
            return fail_result

        auth_kind = self.static_preflight_config.get("auth_kind")
        route_evidence = self.static_preflight_config.get("route_evidence", {})
        platform = self.static_preflight_config.get("platform")
        architecture = self.static_preflight_config.get("architecture")
        provider_meta = self.static_preflight_config.get("provider_meta")

        val_res = validate_provider_static(
            provider_id=self.provider_id,
            auth_kind=auth_kind,
            route_evidence=route_evidence,
            platform=platform,
            architecture=architecture,
            provider_meta=provider_meta,
        )

        if val_res.get("static_configuration_status") != "PASS":
            fail_result["reasons"].extend(val_res.get("reasons", []))
            fail_result["provider_preflight"] = deepcopy(val_res)
            for k in ("provider_id", "external_agent", "pinned_version", "retry_count", "fallback_state"):
                if k in val_res:
                    fail_result[k] = val_res[k]
            return fail_result

        return {
            "ok": True,
            "mode": "static_mock",
            "live_ready": False,
            "live_readiness": "BLOCKED",
            "static_configuration_status": "PASS",
            "provider_preflight": deepcopy(val_res),
            "provider_id": val_res.get("provider_id"),
            "external_agent": val_res.get("external_agent"),
            "pinned_version": val_res.get("pinned_version"),
            "retry_count": val_res.get("retry_count"),
            "fallback_state": val_res.get("fallback_state"),
            "reasons": deepcopy(val_res.get("reasons", [])),
        }

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
