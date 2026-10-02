from copy import deepcopy
from typing import Any

from .base import ProviderStaticProfile
from .policy import CODEX_POLICY
from .preflight import validate_provider_static


def build_codex_profile(
    auth_kind: str | None,
    route_evidence: dict[str, Any],
) -> ProviderStaticProfile:
    config = {
        "auth_kind": auth_kind,
        "route_evidence": deepcopy(route_evidence),
    }
    result = validate_provider_static(
        CODEX_POLICY.provider_id,
        auth_kind,
        route_evidence,
    )
    if result.get("static_configuration_status") != "PASS":
        raise ValueError(
            f"Codex profile validation failed: {result.get('reasons', [])}"
        )

    return ProviderStaticProfile(
        provider_id=CODEX_POLICY.provider_id,
        external_agent=CODEX_POLICY.external_agent,
        pinned_version=CODEX_POLICY.pinned_version,
        _static_preflight_config=config,
        binary_name="codex-acp",
    )
