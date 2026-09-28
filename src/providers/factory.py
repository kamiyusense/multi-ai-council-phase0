from typing import Any

from src.relay.core_adapter import RelayCoreAdapter
from src.relay.bridge import RelayProviderAdapterBridge
from .base import ProviderStaticProfile
from .policy import (
    CODEX_POLICY,
    CLAUDE_POLICY,
    ANTIGRAVITY_POLICY,
    claude_session_meta,
    antigravity_binary_name,
)
from .preflight import validate_provider_static

def create_core_adapter(profile: ProviderStaticProfile, bridge: RelayProviderAdapterBridge) -> RelayCoreAdapter:
    if not isinstance(profile, ProviderStaticProfile):
        raise TypeError("profile must be a ProviderStaticProfile")

    if profile.provider_id == "openai":
        policy = CODEX_POLICY
    elif profile.provider_id == "anthropic":
        policy = CLAUDE_POLICY
    elif profile.provider_id == "google":
        policy = ANTIGRAVITY_POLICY
    else:
        raise ValueError(f"Unknown provider_id: {profile.provider_id}")

    if profile.external_agent != policy.external_agent:
        raise ValueError("Invalid external_agent for provider")
    if profile.pinned_version != policy.pinned_version:
        raise ValueError("Invalid pinned_version for provider")

    if profile.retry_count != 0:
        raise ValueError("retry_count must be 0")
    if profile.fallback_state != "disabled":
        raise ValueError("fallback_state must be disabled")
    if profile.live_ready is not False:
        raise ValueError("live_ready must be False")
    if profile.live_readiness != "BLOCKED":
        raise ValueError("live_readiness must be BLOCKED")

    config = profile.static_preflight_config
    if not isinstance(config, dict):
        raise ValueError("static_preflight_config must be a dict")

    auth_kind = config.get("auth_kind")
    route_evidence = config.get("route_evidence", {})
    platform = config.get("platform")
    architecture = config.get("architecture")
    provider_meta = config.get("provider_meta")

    val_res = validate_provider_static(
        provider_id=profile.provider_id,
        auth_kind=auth_kind,
        route_evidence=route_evidence,
        platform=platform,
        architecture=architecture,
        provider_meta=provider_meta,
    )
    if val_res.get("static_configuration_status") != "PASS":
        raise ValueError(f"Provider configuration failed static validation: {val_res.get('reasons')}")

    if profile.provider_id == "openai":
        if profile.session_meta is not None:
            raise ValueError("OpenAI profile must not have session_meta")
        if profile.binary_name is not None:
            raise ValueError("OpenAI profile must not have binary_name")
        if provider_meta is not None:
             raise ValueError("OpenAI config must not have provider_meta")

    elif profile.provider_id == "anthropic":
        expected_meta = claude_session_meta()
        if profile.session_meta != expected_meta:
            raise ValueError("Anthropic profile must have exact claude_session_meta()")
        if provider_meta != expected_meta:
             raise ValueError("Anthropic config must have exact claude_session_meta() as provider_meta")
        if profile.binary_name is not None:
            raise ValueError("Anthropic profile must not have binary_name")

    elif profile.provider_id == "google":
        if profile.session_meta is not None:
            raise ValueError("Google profile must not have session_meta")
        try:
            expected_binary = antigravity_binary_name(platform, architecture)
        except Exception as e:
            raise ValueError(f"Unsupported platform/architecture: {e}")
        if profile.binary_name != expected_binary:
            raise ValueError("Google profile must have matching antigravity_binary_name")

    from copy import deepcopy
    return RelayCoreAdapter(
        provider_id=profile.provider_id,
        bridge=bridge,
        static_preflight_config=deepcopy(config),
    )
