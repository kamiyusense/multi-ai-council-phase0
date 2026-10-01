from __future__ import annotations

from typing import Any

from .policy import ANTIGRAVITY_POLICY, CLAUDE_POLICY, CODEX_POLICY, ProviderPolicy


COMMON_PROOFS = frozenset(
    {
        "finite_timeout",
        "minimum_permission_profile",
        "executed_model_verification_mechanism",
        "intended_subscription_billing_route",
        "provider_specific_abort_readback",
        "final_fanout_secret_pii_private_code_policy",
        "filesystem_network_confinement",
        "zero_hidden_retry_fallback_end_to_end",
    }
)

PROVIDER_PROOFS = {
    "openai": frozenset(
        {
            "chatgpt_route_retry_zero",
            "no_stream_reconnect_replay",
            "no_auth_recovery_replay",
            "single_model_request_evidence",
        }
    ),
    "anthropic": frozenset(
        {
            "sdk_retry_zero",
            "model_fallback_disabled",
            "no_restart_recovery_extra_turn",
            "account_auth",
            "dangerous_skip_permissions_false",
            "independent_executed_model_verification",
        }
    ),
    "google": frozenset(
        {
            "intended_account_route",
            "api_key_cloud_billing_overage_absent",
            "internal_retry_fallback_zero",
            "executed_model_verification",
            "cancel_teardown_no_restart",
            "quota_billing_unknown_blocks",
        }
    ),
}

_POLICIES: dict[str, ProviderPolicy] = {
    "openai": CODEX_POLICY,
    "anthropic": CLAUDE_POLICY,
    "google": ANTIGRAVITY_POLICY,
}


def _base_response(state: str) -> dict[str, Any]:
    return {
        "state": state,
        "live_ready": False,
        "dispatch_allowed": False,
        "human_approval_required": True,
        "retry_count": 0,
        "fallback_state": "disabled",
    }


def _preflight_is_consistent(provider_id: str, preflight: dict[str, Any]) -> bool:
    policy = _POLICIES[provider_id]

    required_keys = {
        "static_configuration_status",
        "live_readiness",
        "reasons",
        "provider_id",
        "external_agent",
        "pinned_version",
        "retry_count",
        "fallback_state",
        "live_ready",
    }
    if set(preflight) != required_keys:
        return False

    if preflight["provider_id"] != provider_id:
        return False
    if preflight["external_agent"] != policy.external_agent:
        return False
    if preflight["pinned_version"] != policy.pinned_version:
        return False
    if preflight["static_configuration_status"] != "PASS":
        return False
    if preflight["live_readiness"] != "BLOCKED":
        return False
    if preflight["live_ready"] is not False:
        return False
    if preflight["retry_count"] != 0:
        return False
    if preflight["fallback_state"] != "disabled":
        return False

    reasons = preflight["reasons"]
    if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
        return False

    return True


def _proofs_are_complete(provider_id: str, proofs: dict[str, Any]) -> bool:
    required_keys = COMMON_PROOFS | PROVIDER_PROOFS[provider_id]
    if set(proofs) != required_keys:
        return False

    for proof in proofs.values():
        if not isinstance(proof, dict):
            return False
        if set(proof) != {"status", "evidence_ref"}:
            return False
        if proof["status"] != "CONFIRMED":
            return False
        evidence_ref = proof["evidence_ref"]
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            return False

    return True


def evaluate_live_readiness(
    provider_id: str,
    preflight: dict[str, Any],
    proofs: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate static evidence only; never authorize provider dispatch."""

    if not isinstance(provider_id, str) or provider_id not in _POLICIES:
        return _base_response("BLOCKED_UNKNOWN")
    if not isinstance(preflight, dict) or not isinstance(proofs, dict):
        return _base_response("BLOCKED_UNKNOWN")
    if not _preflight_is_consistent(provider_id, preflight):
        return _base_response("BLOCKED_UNKNOWN")
    if not _proofs_are_complete(provider_id, proofs):
        return _base_response("BLOCKED_UNKNOWN")

    return _base_response("READY_FOR_HUMAN_APPROVAL")
