"""Prepare-only bridge from OIDC run evidence to provider source material.

This checks a sanitized artifact's shape and digest. A caller must separately
read it from the exact trusted GitHub Actions run; caller-supplied JSON is not
an authority proof. Even after linking, provider verification stays UNKNOWN.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .github_oidc_proof_policy_cli import BRANCH_REF, REPOSITORY, WORKFLOW_REF
from .runtime_verifier_sources import validate_provider_verification_source

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CLAIM_NAMES = {
    "iss", "aud", "exp", "iat", "nbf", "repository", "repository_id",
    "repository_owner_id", "repository_visibility", "ref", "sha",
    "workflow_ref", "workflow_sha", "run_id", "run_attempt",
    "event_name", "runner_environment",
}
_EVIDENCE_KEYS = {
    "schema_version", "proof_kind", "status", "issuer", "signature_verification",
    "issuer_binding", "audience_binding", "timestamp_validation",
    "repository_binding", "workflow_ref_sha_run_binding", "repository",
    "ref", "workflow_ref", "run_id", "exact_commit_sha", "claim_names",
    "token_retained", "provider_fact_verified", "owner_authority_issued",
    "evidence_sha256",
}


@dataclass(frozen=True)
class PreparedOidcProviderLink:
    source_document: dict[str, Any]
    workflow_run_id: str
    workflow_sha: str
    evidence_sha256: str
    verification_state: str = "UNKNOWN"


def prepare_oidc_provider_source_link(
    *, evidence: dict[str, Any], source: dict[str, Any],
    expected_run_id: str, expected_sha: str,
) -> PreparedOidcProviderLink:
    """Add only opaque workflow proof references; never issue attestation."""
    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_KEYS:
        raise ValueError("sanitized OIDC evidence shape mismatch")
    if not isinstance(expected_run_id, str) or not expected_run_id.isdigit():
        raise ValueError("expected workflow run ID is invalid")
    if not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha):
        raise ValueError("expected workflow SHA is invalid")
    if evidence["schema_version"] != 1 or evidence["proof_kind"] != "GITHUB_HOSTED_OIDC_WORKFLOW_IDENTITY":
        raise ValueError("OIDC evidence version/kind mismatch")
    for field in (
        "status", "signature_verification", "issuer_binding", "audience_binding",
        "timestamp_validation", "repository_binding", "workflow_ref_sha_run_binding",
    ):
        if evidence[field] != "PASS":
            raise ValueError(f"OIDC evidence is not PASS: {field}")
    if evidence["issuer"] != "https://token.actions.githubusercontent.com":
        raise ValueError("OIDC issuer mismatch")
    for field, expected in (
        ("repository", REPOSITORY), ("ref", BRANCH_REF),
        ("workflow_ref", WORKFLOW_REF), ("run_id", expected_run_id),
        ("exact_commit_sha", expected_sha),
    ):
        if evidence[field] != expected:
            raise ValueError(f"OIDC evidence context mismatch: {field}")
    if evidence["token_retained"] is not False or evidence["provider_fact_verified"] is not False or evidence["owner_authority_issued"] is not False:
        raise ValueError("OIDC evidence overclaims trust or retains token")
    names = evidence["claim_names"]
    if not isinstance(names, list) or not names or len(names) != len(set(names)) or not set(names) <= _SAFE_CLAIM_NAMES:
        raise ValueError("OIDC evidence claim names are unsafe")
    claimed_digest = evidence["evidence_sha256"]
    if not isinstance(claimed_digest, str) or not _DIGEST.fullmatch(claimed_digest):
        raise ValueError("OIDC evidence digest is malformed")
    body = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    actual_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if actual_digest != claimed_digest:
        raise ValueError("OIDC evidence digest mismatch")
    validate_provider_verification_source(source)
    if source["verification_state"] != "UNKNOWN":
        raise ValueError("OIDC proof alone cannot verify provider source")
    refs = list(source["proof_refs"])
    refs.extend((f"github-actions:run/{expected_run_id}", f"github-evidence:sha256/{actual_digest}"))
    if len(refs) > 32 or len(refs) != len(set(refs)):
        raise ValueError("OIDC source proof refs are duplicate or unbounded")
    linked = {**source, "proof_refs": refs}
    validate_provider_verification_source(linked)
    return PreparedOidcProviderLink(linked, expected_run_id, expected_sha, actual_digest)
