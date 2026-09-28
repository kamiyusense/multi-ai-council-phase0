from __future__ import annotations

from typing import Any

COMMON_PROOFS = frozenset({
    "finite_timeout",
    "minimum_permission_profile",
    "executed_model_verification_mechanism",
    "intended_subscription_billing_route",
    "provider_specific_abort_readback",
    "final_fanout_secret_pii_private_code_policy",
    "filesystem_network_confinement",
    "zero_hidden_retry_fallback_end_to_end",
})

PROVIDER_PROOFS = {
    "openai": frozenset({
        "chatgpt_route_retry_zero",
        "no_stream_reconnect_replay",
        "no_auth_recovery_replay",
        "single_model_request_evidence",
    }),
    "anthropic": frozenset({
        "sdk_retry_zero",
        "model_fallback_disabled",
        "no_restart_recovery_extra_turn",
        "account_auth",
        "dangerous_skip_permissions_false",
        "independent_executed_model_verification",
    }),
    "google": frozenset({
        "intended_account_route",
        "api_key_cloud_billing_overage_absent",
        "internal_retry_fallback_zero",
        "executed_model_verification",
        "cancel_teardown_no_restart",
        "quota_billing_unknown_blocks",
    }),
}


def evaluate_live_readiness(provider_id: str, preflight: dict[str, Any], proofs: dict[str, Any]) -> dict[str, Any]:
    def _base_response(state: str) -> dict[str, Any]:
        return {
            "state": state,
            "live_ready": False,
            "dispatch_allowed": False,
            "human_approval_required": True,
            "retry_count": 0,
            "fallback_state": "disabled",
        }

    if not isinstance(provider_id, str) or provider_id not in PROVIDER_PROOFS:
        return _base_response("BLOCKED_UNKNOWN")

    if not isinstance(preflight, dict):
        return _base_response("BLOCKED_UNKNOWN")

    if not isinstance(proofs, dict):
        return _base_response("BLOCKED_UNKNOWN")

    if preflight.get("provider_id") != provider_id:
        return _base_response("BLOCKED_UNKNOWN")

    if preflight.get("static_configuration_status") != "PASS":
        return _base_response("BLOCKED_UNKNOWN")

    if preflight.get("live_ready") is not False:
        return _base_response("BLOCKED_UNKNOWN")

    if preflight.get("retry_count") != 0:
        return _base_response("BLOCKED_UNKNOWN")

    if preflight.get("fallback_state") != "disabled":
        return _base_response("BLOCKED_UNKNOWN")

    required_proof_keys = COMMON_PROOFS | PROVIDER_PROOFS[provider_id]

    if set(proofs.keys()) != required_proof_keys:
        return _base_response("BLOCKED_UNKNOWN")

    for key, proof in proofs.items():
        if not isinstance(proof, dict):
            return _base_response("BLOCKED_UNKNOWN")

        status = proof.get("status")
        evidence_ref = proof.get("evidence_ref")

        if status != "CONFIRMED":
            return _base_response("BLOCKED_UNKNOWN")

        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            return _base_response("BLOCKED_UNKNOWN")

    return _base_response("READY_FOR_HUMAN_APPROVAL")
