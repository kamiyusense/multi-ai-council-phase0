from typing import Any

from .policy import (
    ANTIGRAVITY_POLICY,
    CLAUDE_POLICY,
    CODEX_POLICY,
    antigravity_binary_name,
    claude_session_meta,
)

def validate_provider_static(
    provider_id: str,
    auth_kind: str | None,
    route_evidence: dict[str, bool],
    platform: str | None = None,
    architecture: str | None = None,
    provider_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []

    if provider_id == "openai":
        policy = CODEX_POLICY
    elif provider_id == "anthropic":
        policy = CLAUDE_POLICY
    elif provider_id == "google":
        policy = ANTIGRAVITY_POLICY
    else:
        return _fail_closed("UNKNOWN", ["unknown provider_id"])

    try:
        policy.assert_static_safety()
    except ValueError as e:
        return _fail_closed("UNKNOWN", [f"policy static safety failed: {e}"])

    if not policy.validate_auth_kind(auth_kind):
        return _fail_closed("UNKNOWN", [f"invalid auth_kind: {auth_kind}"])

    if route_evidence.get("api_key_present") is not False:
        return _fail_closed("UNKNOWN", ["api_key_present must be explicitly False"])
    if route_evidence.get("gateway_configured") is not False:
        return _fail_closed("UNKNOWN", ["gateway_configured must be explicitly False"])
    if route_evidence.get("external_cloud_configured") is not False:
        return _fail_closed("UNKNOWN", ["external_cloud_configured must be explicitly False"])

    if provider_id == "openai":
        if route_evidence.get("custom_model_provider_configured") is not False:
            return _fail_closed("UNKNOWN", ["custom_model_provider_configured must be explicitly False"])
        if route_evidence.get("arbitrary_codex_config_present") is not False:
            return _fail_closed("UNKNOWN", ["arbitrary_codex_config_present must be explicitly False"])
        reasons.append("provider-internal retry proof remains UNKNOWN")

    elif provider_id == "anthropic":
        if route_evidence.get("dangerous_permission_bypass") is not False:
            return _fail_closed("UNKNOWN", ["dangerous_permission_bypass must be explicitly False"])
        if route_evidence.get("hide_claude_auth") is not False:
            return _fail_closed("UNKNOWN", ["hide_claude_auth must be explicitly False"])

        expected_meta = claude_session_meta()
        if not provider_meta or provider_meta.get("claudeCode", {}).get("options", {}).get("allowDangerouslySkipPermissions") is not False:
            return _fail_closed("UNKNOWN", ["allowDangerouslySkipPermissions must be exactly False"])

        reasons.append("provider/SDK retry/fallback proof remains UNKNOWN")

    elif provider_id == "google":
        if route_evidence.get("cloud_billing_selected") is not False:
            return _fail_closed("UNKNOWN", ["cloud_billing_selected must be explicitly False"])
        if route_evidence.get("overages_enabled") is not False:
            return _fail_closed("UNKNOWN", ["overages_enabled must be explicitly False"])
        if route_evidence.get("adc_present") is not False:
            return _fail_closed("UNKNOWN", ["adc_present must be explicitly False"])
        if route_evidence.get("vertex_selected") is not False:
            return _fail_closed("UNKNOWN", ["vertex_selected must be explicitly False"])

        if not platform or not architecture:
            return _fail_closed("UNKNOWN", ["platform and architecture required for google provider"])

        try:
            antigravity_binary_name(platform, architecture)
        except ValueError:
            return _fail_closed("UNKNOWN", [f"unsupported platform/architecture: {platform}/{architecture}"])

        reasons.append("internal retry/fallback and executed-model proof remain UNKNOWN")

    return {
        "static_configuration_status": "PASS",
        "live_readiness": "BLOCKED",
        "reasons": reasons,
        "provider_id": policy.provider_id,
        "external_agent": policy.external_agent,
        "pinned_version": policy.pinned_version,
        "retry_count": 0,
        "fallback_state": "disabled",
        "live_ready": False,
    }

def _fail_closed(status: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "static_configuration_status": status,
        "live_readiness": "BLOCKED",
        "reasons": reasons,
        "provider_id": "UNKNOWN",
        "external_agent": "UNKNOWN",
        "pinned_version": "UNKNOWN",
        "retry_count": 0,
        "fallback_state": "disabled",
        "live_ready": False,
    }
