"""Normalize a Jules Session GET into provider-verification source material.

This module never authenticates the provider. A normalized source document is
transport material only. Even verification_state=VERIFIED must still pass the
existing independently injected VerificationSourceAuthenticator inside
SourceBoundProviderVerifier before it can become a VerifiedProviderObservation.

The raw Jules state is preserved exactly. No QUEUED/RUNNING/COMPLETED mapping is
invented here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Iterable

from .jules_semiauto_owner_prepare import JulesSemiAutoAcquireBundle
from .jules_session_acceptance import extract_session_timing_readback
from .loop_owner_observation import validate_provider_observation
from .runtime_transition_coordinator import TransitionRequest
from .runtime_transition_evidence import validate_evidence_document
from .runtime_verifier_sources import validate_provider_verification_source

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PROVIDER_STATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ -]{0,63}$")
_VERIFICATION_STATES = {"VERIFIED", "REJECTED", "UNKNOWN"}


@dataclass(frozen=True)
class JulesProviderReadbackCandidate:
    source_id: str
    source_ref: str
    observed_at: str
    expires_at: str
    provider_kind: str
    provider_state: str
    observation_id: str
    loop_id: str
    owner_role: str
    holder_id: str
    generation: int
    fencing_token: int
    expected_repo: str
    expected_pr: int
    expected_target_head: str
    command_id: str
    correlation_id: str
    source_receipt_ref: str
    evidence_ref: str
    proof_refs: tuple[str, ...]


@dataclass(frozen=True)
class JulesProviderReadbackBinding:
    candidate: JulesProviderReadbackCandidate
    evidence_document: dict[str, Any]
    provider_observation_input: dict[str, Any]
    transition_request: TransitionRequest


def prepare_jules_provider_readback_candidate(
    *,
    bundle: JulesSemiAutoAcquireBundle,
    session_readback: dict[str, Any],
) -> JulesProviderReadbackCandidate:
    if not isinstance(bundle, JulesSemiAutoAcquireBundle):
        raise ValueError("JulesSemiAutoAcquireBundle is required")
    if not isinstance(session_readback, dict):
        raise ValueError("Jules Session GET response must be an object")

    observed = extract_session_timing_readback(
        session_readback,
        expected_session_id=bundle.acceptance_session_id,
    )
    event = bundle.owner_event
    evidence = bundle.evidence_document
    observation = bundle.provider_observation_input

    if observed.session_create_time != event["claimed_at"]:
        raise ValueError("Jules Session GET createTime does not match owner claim")

    provider_state = session_readback.get("state")
    if (
        not isinstance(provider_state, str)
        or not _PROVIDER_STATE.fullmatch(provider_state)
    ):
        raise ValueError("Jules Session GET state is invalid")

    update_time = _time(
        session_readback.get("updateTime"),
        "Jules Session updateTime",
    )
    claimed = _time(event["claimed_at"], "owner claimed_at")
    expires = _time(event["expires_at"], "owner expires_at")
    if update_time < claimed:
        raise ValueError("Jules Session updateTime predates session acceptance")
    if update_time >= expires:
        raise ValueError("Jules Session readback is outside owner lease")

    source_ref = evidence["provider_readback"]
    expected_source_ref = f"jules-session:{bundle.acceptance_session_id}"
    if source_ref != expected_source_ref:
        raise ValueError("provider readback source_ref/session mismatch")

    source_id = f"jules-session-{bundle.acceptance_session_id}-g{event['generation']}"
    observation_id = observation["observation_id"]
    for field, value in (
        ("source_id", source_id),
        ("observation_id", observation_id),
    ):
        if not _ID.fullmatch(value):
            raise ValueError(f"invalid {field}")

    proof_refs = (
        f"jules-api:sessions/{bundle.acceptance_session_id}",
        source_ref,
        f"github-pr:{event['expected_pr']}",
        f"github-head:{event['expected_target_head']}",
        f"github-branch:{bundle.target_branch}",
        f"jules-branch:{bundle.provider_starting_branch}",
    )
    candidate = JulesProviderReadbackCandidate(
        source_id=source_id,
        source_ref=source_ref,
        observed_at=_canonical(update_time),
        expires_at=event["expires_at"],
        provider_kind="JULES",
        provider_state=provider_state,
        observation_id=observation_id,
        loop_id=event["loop_id"],
        owner_role=event["owner_role"],
        holder_id=event["holder_id"],
        generation=event["generation"],
        fencing_token=event["fencing_token"],
        expected_repo=event["expected_repo"],
        expected_pr=event["expected_pr"],
        expected_target_head=event["expected_target_head"],
        command_id=event["command_id"],
        correlation_id=event["correlation_id"],
        source_receipt_ref=event["source_receipt_ref"],
        evidence_ref=observation["evidence_ref"],
        proof_refs=proof_refs,
    )
    # Structural self-check only. UNKNOWN does not grant verification.
    build_provider_verification_source(candidate, verification_state="UNKNOWN")
    return candidate



def bind_jules_active_provider_readback(
    *,
    bundle: JulesSemiAutoAcquireBundle,
    candidate: JulesProviderReadbackCandidate,
) -> JulesProviderReadbackBinding:
    """Rebind provider evidence to a later independently-read RUNNING state."""
    if not isinstance(bundle, JulesSemiAutoAcquireBundle):
        raise ValueError("JulesSemiAutoAcquireBundle is required")
    if not isinstance(candidate, JulesProviderReadbackCandidate):
        raise ValueError("JulesProviderReadbackCandidate is required")
    if candidate.provider_state != "RUNNING":
        raise ValueError(
            "active durable ACQUIRE requires an explicit RUNNING Jules readback"
        )

    event = bundle.owner_event
    observation = bundle.provider_observation_input
    evidence = bundle.evidence_document

    expected = {
        "loop_id": event["loop_id"],
        "owner_role": event["owner_role"],
        "holder_id": event["holder_id"],
        "generation": event["generation"],
        "fencing_token": event["fencing_token"],
        "expected_repo": event["expected_repo"],
        "expected_pr": event["expected_pr"],
        "expected_target_head": event["expected_target_head"],
        "command_id": event["command_id"],
        "correlation_id": event["correlation_id"],
        "source_receipt_ref": event["source_receipt_ref"],
        "evidence_ref": observation["evidence_ref"],
        "source_ref": evidence["provider_readback"],
    }
    actual = {
        "loop_id": candidate.loop_id,
        "owner_role": candidate.owner_role,
        "holder_id": candidate.holder_id,
        "generation": candidate.generation,
        "fencing_token": candidate.fencing_token,
        "expected_repo": candidate.expected_repo,
        "expected_pr": candidate.expected_pr,
        "expected_target_head": candidate.expected_target_head,
        "command_id": candidate.command_id,
        "correlation_id": candidate.correlation_id,
        "source_receipt_ref": candidate.source_receipt_ref,
        "evidence_ref": candidate.evidence_ref,
        "source_ref": candidate.source_ref,
    }
    if actual != expected:
        raise ValueError("Jules provider candidate context mismatch")

    refreshed_evidence = {
        **evidence,
        "provider_state": candidate.provider_state,
        "observed_at": candidate.observed_at,
    }
    if validate_evidence_document(refreshed_evidence) != candidate.evidence_ref:
        raise ValueError("refreshed Jules evidence path mismatch")

    refreshed_observation = {
        **observation,
        "state": candidate.provider_state,
        "observed_at": candidate.observed_at,
    }
    validate_provider_observation({**refreshed_observation, "verified": True})

    transition_request = TransitionRequest(
        owner_event=bundle.owner_event,
        evidence_document=refreshed_evidence,
        provider_observation_input=refreshed_observation,
        expected_prior_state=bundle.transition_request.expected_prior_state,
        desired_state=bundle.transition_request.desired_state,
    )
    return JulesProviderReadbackBinding(
        candidate=candidate,
        evidence_document=refreshed_evidence,
        provider_observation_input=refreshed_observation,
        transition_request=transition_request,
    )

def build_provider_verification_source(
    candidate: JulesProviderReadbackCandidate,
    *,
    verification_state: str,
    proof_refs: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build normalized source material; this function does not authenticate it."""
    if not isinstance(candidate, JulesProviderReadbackCandidate):
        raise ValueError("JulesProviderReadbackCandidate is required")
    if verification_state not in _VERIFICATION_STATES:
        raise ValueError("invalid verification_state")

    refs = tuple(candidate.proof_refs if proof_refs is None else proof_refs)
    if not refs or len(refs) > 32 or len(refs) != len(set(refs)):
        raise ValueError("proof_refs must be unique and bounded")

    source = {
        "schema_version": 1,
        "verification_kind": "PROVIDER_OBSERVATION",
        "source_id": candidate.source_id,
        "source_ref": candidate.source_ref,
        "verification_state": verification_state,
        "observed_at": candidate.observed_at,
        "expires_at": candidate.expires_at,
        "provider_kind": candidate.provider_kind,
        "provider_state": candidate.provider_state,
        "observation_id": candidate.observation_id,
        "loop_id": candidate.loop_id,
        "owner_role": candidate.owner_role,
        "holder_id": candidate.holder_id,
        "generation": candidate.generation,
        "fencing_token": candidate.fencing_token,
        "expected_repo": candidate.expected_repo,
        "expected_pr": candidate.expected_pr,
        "expected_target_head": candidate.expected_target_head,
        "command_id": candidate.command_id,
        "correlation_id": candidate.correlation_id,
        "source_receipt_ref": candidate.source_receipt_ref,
        "evidence_ref": candidate.evidence_ref,
        "proof_refs": list(refs),
    }
    validate_provider_verification_source(source)
    return source


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed


def _canonical(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")
