from __future__ import annotations

from typing import Any

from .policy import (
    ANTIGRAVITY_POLICY,
    CLAUDE_POLICY,
    CODEX_POLICY,
    ProviderPolicy,
    antigravity_binary_name,
    claude_session_meta,
)


def _result(
    policy: ProviderPolicy | None,
    status: str,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "static_configuration_status": status,
        "live_readiness": "BLOCKED",
        "reasons": reasons,
        "provider_id": policy.provider_id if policy is not None else "UNKNOWN",
        "external_agent": policy.external_agent if policy is not None else "UNKNOWN",
        "pinned_version": policy.pinned_version if policy is not None else "UNKNOWN",
        "retry_count": 0,
        "fallback_state": "disabled",
        "live_ready": False,
    }


def validate_provider_static(
    provider_id: str,
    auth_kind: str | None,
    route_evidence: dict[str, bool] | Any,
    platform: str | None = None,
    architecture: str | None = None,
    provider_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider_id == "openai":
        policy = CODEX_POLICY
    elif provider_id == "anthropic":
        policy = CLAUDE_POLICY
    elif provider_id == "google":
        policy = ANTIGRAVITY_POLICY
    else:
        return _result(None, "UNKNOWN", ["unknown provider_id"])

    try:
        policy.assert_static_safety()
    except ValueError as exc:
        return _result(policy, "UNKNOWN", [f"policy static safety failed: {exc}"])

    if not policy.validate_auth_kind(auth_kind):
        return _result(policy, "UNKNOWN", [f"invalid auth_kind: {auth_kind}"])

    if not isinstance(route_evidence, dict):
        return _result(policy, "UNKNOWN", ["route_evidence must be a mapping"])

    for key in ("api_key_present", "gateway_configured", "external_cloud_configured"):
        if route_evidence.get(key) is not False:
            return _result(policy, "UNKNOWN", [f"{key} must be explicitly False"])

    reasons: list[str] = []

    if provider_id == "openai":
        for key in ("custom_model_provider_configured", "arbitrary_codex_config_present"):
            if route_evidence.get(key) is not False:
                return _result(policy, "UNKNOWN", [f"{key} must be explicitly False"])
        reasons.append("provider-internal retry proof remains UNKNOWN")

    elif provider_id == "anthropic":
        for key in ("dangerous_permission_bypass", "hide_claude_auth"):
            if route_evidence.get(key) is not False:
                return _result(policy, "UNKNOWN", [f"{key} must be explicitly False"])

        expected_meta = claude_session_meta()
        if provider_meta != expected_meta:
            return _result(
                policy,
                "UNKNOWN",
                ["provider_meta must exactly match claude_session_meta()"],
            )
        reasons.append("provider/SDK retry/fallback proof remains UNKNOWN")

    elif provider_id == "google":
        for key in (
            "cloud_billing_selected",
            "overages_enabled",
            "adc_present",
            "vertex_selected",
        ):
            if route_evidence.get(key) is not False:
                return _result(policy, "UNKNOWN", [f"{key} must be explicitly False"])

        if not isinstance(platform, str) or not platform:
            return _result(policy, "UNKNOWN", ["platform must be a non-empty string"])
        if not isinstance(architecture, str) or not architecture:
            return _result(policy, "UNKNOWN", ["architecture must be a non-empty string"])

        try:
            antigravity_binary_name(platform, architecture)
        except (AttributeError, ValueError):
            return _result(
                policy,
                "UNKNOWN",
                [f"unsupported platform/architecture: {platform}/{architecture}"],
            )

        reasons.append("internal retry/fallback and executed-model proof remain UNKNOWN")

    return _result(policy, "PASS", reasons)
