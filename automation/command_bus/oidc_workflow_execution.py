"""OIDC-verified GitHub workflow execution, bound to a fresh Actions run readback.

What this proves, and only this: a sanitized OIDC proof artifact (digest-checked,
complete PASS) belongs to one exact GitHub Actions run whose independently read
metadata matches an exact reviewed workflow profile (repository, workflow file,
branch, commit, event, first attempt, completed success, no reusable workflows).

It does NOT prove Jules/provider state, owner authority, durable ownership, or a
final loop id. Provider and authority trust are separate authenticators below,
each requiring this execution proof plus its own independent facts.

No network I/O here: callers inject an ActionsRunReader.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .github_oidc_proof_policy_cli import REPOSITORY, OidcProofProfile
from .runtime_verifier_sources import (
    VerifiedSourceAttestation,
    validate_authority_verification_source,
    validate_provider_verification_source,
)

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_V2_KEYS = {
    "schema_version", "proof_kind", "status", "terminal_stage", "safe_error_code",
    "run_id", "exact_commit_sha", "expected_workflow_identity", "evidence_payload_sha256",
}


class ActionsRunReader(Protocol):
    """Fresh read of one GitHub Actions run (REST workflow-run object) or None."""

    def read_run(self, run_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class VerifiedWorkflowExecution:
    profile_name: str
    workflow_identity: str
    run_id: str
    head_sha: str
    event: str
    actor_id: str
    triggering_actor_id: str
    created_at: str
    evidence_sha256: str

    @property
    def proof_refs(self) -> tuple[str, str]:
        return (f"github-actions:run/{self.run_id}", f"github-evidence:sha256/{self.evidence_sha256}")


def verify_oidc_workflow_execution(
    *, evidence: Any, run_reader: ActionsRunReader | None, profile: OidcProofProfile,
    expected_run_id: str, expected_sha: str,
) -> VerifiedWorkflowExecution | None:
    """Return a VerifiedWorkflowExecution or None (fail closed on any mismatch)."""
    try:
        if run_reader is None or not isinstance(profile, OidcProofProfile):
            return None
        if not isinstance(expected_run_id, str) or not expected_run_id.isascii() or not expected_run_id.isdigit():
            return None
        if not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha):
            return None
        digest = _checked_evidence_digest(evidence, profile, expected_run_id, expected_sha)
        run = run_reader.read_run(expected_run_id)
        if not isinstance(run, dict):
            return None
        repo = (run.get("repository") or {}).get("full_name")
        head_repo = (run.get("head_repository") or {}).get("full_name")
        path = run.get("path")
        if isinstance(path, str) and "@" in path:  # tolerate "<path>@<ref>" spelling
            path = path.split("@", 1)[0]
        checks = (
            str(run.get("id")) == expected_run_id,
            repo == REPOSITORY and head_repo == REPOSITORY,
            path == profile.workflow_path,
            run.get("head_sha") == expected_sha,
            "refs/heads/" + str(run.get("head_branch")) == profile.branch_ref,
            run.get("event") == profile.event,
            run.get("run_attempt") == 1,
            run.get("status") == "completed" and run.get("conclusion") == "success",
            not run.get("referenced_workflows"),
        )
        if not all(checks):
            return None
        actor = run.get("actor") or {}
        trigger = run.get("triggering_actor") or {}
        actor_id, trigger_id = str(actor.get("id", "")), str(trigger.get("id", ""))
        created_at = run.get("created_at")
        if not (actor_id.isdigit() and trigger_id.isdigit() and isinstance(created_at, str) and created_at):
            return None
        return VerifiedWorkflowExecution(
            profile.name, profile.workflow_ref, expected_run_id, expected_sha,
            profile.event, actor_id, trigger_id, created_at, digest,
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _checked_evidence_digest(
    evidence: Any, profile: OidcProofProfile, run_id: str, sha: str,
) -> str:
    if not isinstance(evidence, dict) or set(evidence) != _V2_KEYS:
        raise ValueError("OIDC evidence shape mismatch")
    if (evidence["schema_version"] != 2
            or evidence["proof_kind"] != "GITHUB_HOSTED_OIDC_WORKFLOW_IDENTITY"
            or evidence["status"] != "PASS" or evidence["terminal_stage"] != "COMPLETE"
            or evidence["safe_error_code"] != "NONE"):
        raise ValueError("OIDC evidence is not a complete PASS")
    for field, expected in (
        ("run_id", run_id), ("exact_commit_sha", sha),
        ("expected_workflow_identity", profile.workflow_ref),
    ):
        if evidence[field] != expected:
            raise ValueError(f"OIDC evidence context mismatch: {field}")
    claimed = evidence["evidence_payload_sha256"]
    if not isinstance(claimed, str) or not _DIGEST.fullmatch(claimed):
        raise ValueError("OIDC evidence digest malformed")
    body = {k: v for k, v in evidence.items() if k != "evidence_payload_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != claimed:
        raise ValueError("OIDC evidence digest mismatch")
    return claimed


def _has_execution_refs(source: dict[str, Any], execution: VerifiedWorkflowExecution) -> bool:
    refs = source.get("proof_refs")
    return isinstance(refs, list) and set(execution.proof_refs).issubset(set(refs))


class OidcBoundProviderAuthenticator:
    """Provider source authenticator = OIDC-verified execution + inner fresh readbacks.

    Roles stay separate: the OIDC execution says the right workflow ran; the inner
    authenticator (JulesDirectReadbackAuthenticator) fresh-reads Jules and the PR
    target and compares them exactly. Neither alone yields an attestation.
    """

    def __init__(self, *, execution: VerifiedWorkflowExecution | None, inner: Any):
        self.execution = execution
        self.inner = inner

    def authenticate(self, source: dict[str, Any], *, expected: dict[str, Any]) -> VerifiedSourceAttestation | None:
        try:
            if not isinstance(self.execution, VerifiedWorkflowExecution) or self.inner is None:
                return None
            validate_provider_verification_source(source)
            if not _has_execution_refs(source, self.execution):
                return None
            return self.inner.authenticate(source, expected=expected)
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class AuthorityIssuerPolicy:
    """Who may be the root of an owner-authority grant.

    A push-triggered run performed by the same account/session that implements
    the change cannot show an independent human decision, so the default accepts
    only a deliberate manual dispatch by an allowlisted account.
    """
    allowed_events: frozenset[str] = frozenset({"workflow_dispatch"})
    allowed_actor_ids: frozenset[str] = frozenset()


class OidcBoundAuthorityAuthenticator:
    """Authority source authenticator = OIDC execution of an issuer run + exact policy."""

    def __init__(
        self, *, execution: VerifiedWorkflowExecution | None, policy: AuthorityIssuerPolicy,
        provider_execution: VerifiedWorkflowExecution | None = None,
    ):
        self.execution = execution
        self.policy = policy
        self.provider_execution = provider_execution

    def authenticate(self, source: dict[str, Any], *, expected: dict[str, Any]) -> VerifiedSourceAttestation | None:
        try:
            ex = self.execution
            if not isinstance(ex, VerifiedWorkflowExecution) or not isinstance(self.policy, AuthorityIssuerPolicy):
                return None
            if not self.policy.allowed_actor_ids or ex.event not in self.policy.allowed_events:
                return None
            if ex.actor_id != ex.triggering_actor_id or ex.actor_id not in self.policy.allowed_actor_ids:
                return None
            prov = self.provider_execution
            if prov is not None and (prov.run_id == ex.run_id or prov.workflow_identity == ex.workflow_identity):
                return None  # provider and authority paths must be distinct executions
            validate_authority_verification_source(source)
            if not _has_execution_refs(source, ex) or not isinstance(expected, dict):
                return None
            if source["verification_state"] != "VERIFIED":
                return None
            if any(source.get(k) != v for k, v in expected.items()):
                return None
            return VerifiedSourceAttestation(
                source["verification_kind"], source["source_id"],
                source["source_ref"], source["observed_at"],
            )
        except (KeyError, TypeError, ValueError):
            return None
