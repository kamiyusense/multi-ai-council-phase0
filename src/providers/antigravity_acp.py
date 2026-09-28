from typing import Any
from .base import ProviderStaticProfile
from .policy import ANTIGRAVITY_POLICY, antigravity_binary_name
from .preflight import validate_provider_static

def build_antigravity_profile(auth_kind: str | None, route_evidence: dict[str, Any], platform: str | None, architecture: str | None) -> ProviderStaticProfile:
    result = validate_provider_static(
        ANTIGRAVITY_POLICY.provider_id, auth_kind, route_evidence, platform=platform, architecture=architecture
    )
    if result.get("static_configuration_status") != "PASS":
        raise ValueError(f"Antigravity profile validation failed: {result.get('reasons', [])}")

    return ProviderStaticProfile(
        provider_id=ANTIGRAVITY_POLICY.provider_id,
        external_agent=ANTIGRAVITY_POLICY.external_agent,
        pinned_version=ANTIGRAVITY_POLICY.pinned_version,
        _static_preflight_config=result,
        binary_name=antigravity_binary_name(platform, architecture) if platform and architecture else None
    )
