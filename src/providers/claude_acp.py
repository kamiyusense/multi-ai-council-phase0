from copy import deepcopy
from typing import Any

from .base import ProviderStaticProfile
from .policy import CLAUDE_POLICY, claude_session_meta
from .preflight import validate_provider_static


def build_claude_profile(
    auth_kind: str | None,
    route_evidence: dict[str, Any],
    provider_meta: dict[str, Any] | None = None,
) -> ProviderStaticProfile:
    effective_meta = (
        claude_session_meta() if provider_meta is None else deepcopy(provider_meta)
    )
    config = {
        "auth_kind": auth_kind,
        "route_evidence": deepcopy(route_evidence),
        "provider_meta": deepcopy(effective_meta),
    }

    result = validate_provider_static(
        CLAUDE_POLICY.provider_id,
        auth_kind,
        route_evidence,
        provider_meta=effective_meta,
    )
    if result.get("static_configuration_status") != "PASS":
        raise ValueError(
            f"Claude profile validation failed: {result.get('reasons', [])}"
        )

    canonical_meta = claude_session_meta()
    return ProviderStaticProfile(
        provider_id=CLAUDE_POLICY.provider_id,
        external_agent=CLAUDE_POLICY.external_agent,
        pinned_version=CLAUDE_POLICY.pinned_version,
        _static_preflight_config=config,
        _session_meta=canonical_meta,
        binary_name="claude-agent-acp",
    )
