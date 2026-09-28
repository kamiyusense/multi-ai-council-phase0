"""Prepare-only Jules provider verification-source normalization.

This module never authenticates Jules and never upgrades source material to
VERIFIED. It converts already-bounded Semi-Auto ACQUIRE material into the exact
Provider Verification Source shape consumed by SourceBoundProviderVerifier.

The output is deliberately verification_state=UNKNOWN. A separate production
VerificationSourceAuthenticator must independently authenticate the material
before durable ownership can be published.
"""
from __future__ import annotations

import re
from typing import Any

from .runtime_verifier_sources import validate_provider_verification_source
from .runtime_transition_evidence import validate_evidence_document
from .validator import validate_receipt

_SAFE_OPAQUE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._/-]{0,191}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def prepare_jules_provider_verification_source(
    *,
    provider_observation_input: dict[str, Any],
    evidence_document: dict[str, Any],
    source_receipt: dict[str, Any],
    session_id: str,
    proof_refs: list[str],
) -> dict[str, Any]:
    if not isinstance(provider_observation_input, dict):
        raise ValueError("provider observation input is required")
    if "verified" in provider_observation_input:
        raise ValueError("caller-supplied verified provider observation is forbidden")
    if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
        raise ValueError("invalid Jules session_id")
    if (
        not isinstance(proof_refs, list)
        or not proof_refs
        or len(proof_refs) > 32
        or len(proof_refs) != len(set(proof_refs))
    ):
        raise ValueError("proof_refs must be 1..32 unique safe opaque references")
    for ref in proof_refs:
        if not isinstance(ref, str) or not _SAFE_OPAQUE.fullmatch(ref) or "://" in ref:
            raise ValueError("proof_refs must be safe opaque references")

    evidence_ref = validate_evidence_document(evidence_document)
    validate_receipt(source_receipt)

    source_ref = evidence_document.get("provider_readback")
    expected_source_ref = f"jules-session:{session_id}"
    if source_ref != expected_source_ref:
        raise ValueError("Jules session source_ref mismatch")

    for field in (
        "loop_id",
        "generation",
        "expected_repo",
        "expected_pr",
        "expected_target_head",
    ):
        if provider_observation_input.get(field) != evidence_document.get(field):
            raise ValueError(f"provider observation/evidence mismatch: {field}")

    if provider_observation_input.get("state") != evidence_document.get("provider_state"):
        raise ValueError("provider state mismatch")
    if provider_observation_input.get("evidence_ref") != evidence_ref:
        raise ValueError("provider observation evidence_ref mismatch")

    for field in ("loop_id", "command_id", "correlation_id"):
        if source_receipt.get(field) != evidence_document.get(field):
            raise ValueError(f"provider receipt/evidence mismatch: {field}")
    if source_receipt.get("evidence_refs") != [evidence_ref]:
        raise ValueError("provider receipt evidence binding mismatch")

    source = {
        "schema_version": 1,
        "verification_kind": "PROVIDER_OBSERVATION",
        "source_id": f"jules-source-{session_id}",
        "source_ref": source_ref,
        "verification_state": "UNKNOWN",
        "observed_at": provider_observation_input["observed_at"],
        "expires_at": provider_observation_input["expires_at"],
        "provider_kind": "JULES",
        "provider_state": evidence_document["provider_state"],
        "observation_id": provider_observation_input["observation_id"],
        "loop_id": provider_observation_input["loop_id"],
        "owner_role": provider_observation_input["owner_role"],
        "holder_id": provider_observation_input["holder_id"],
        "generation": provider_observation_input["generation"],
        "fencing_token": provider_observation_input["fencing_token"],
        "expected_repo": provider_observation_input["expected_repo"],
        "expected_pr": provider_observation_input["expected_pr"],
        "expected_target_head": provider_observation_input["expected_target_head"],
        "command_id": evidence_document["command_id"],
        "correlation_id": evidence_document["correlation_id"],
        "source_receipt_ref": evidence_document["source_receipt_ref"],
        "evidence_ref": evidence_ref,
        "proof_refs": list(proof_refs),
    }
    validate_provider_verification_source(source)
    return source


def mark_provider_source_verified(*args: Any, **kwargs: Any) -> None:
    """Deliberately unavailable.

    Verification is a production trust decision and must come from an injected
    independent authenticator, not from this prepare-only normalizer.
    """
    raise RuntimeError(
        "prepare-only Jules source normalizer cannot mark verification_state=VERIFIED"
    )
