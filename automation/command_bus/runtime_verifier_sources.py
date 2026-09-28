"""Fail-closed source contracts for Runtime authority/provider verification.

A source document is transport material, not trust by itself.  These adapters
require both exact context binding and an independently injected authenticator.
A JSON field such as verification_state="VERIFIED" never grants authority or
provider verification on its own.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .loop_owner_authority import AuthorityGrantProof, validate_authority_grant
from .loop_owner_observation import validate_provider_observation
from .loop_status_evidence import validate_evidence_ref
from .runtime_transition_coordinator import VerifiedProviderObservation
from .runtime_transition_evidence import validate_evidence_document
from .validator import validate_receipt

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOOP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SAFE_REF = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._/-]{0,191}$")
_PROVIDER = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_PROVIDER_STATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ -]{0,63}$")
_VERIFICATION_STATES = {"VERIFIED", "REJECTED", "UNKNOWN"}

_AUTHORITY_KEYS = {
    "schema_version", "verification_kind", "source_id", "source_ref",
    "verification_state", "observed_at", "expires_at", "authority_id",
    "loop_id", "owner_role", "holder_id", "generation", "fencing_token",
    "previous_generation", "event_type", "expected_repo", "expected_pr",
    "expected_target_head", "command_id", "correlation_id", "proof_refs",
}
_PROVIDER_KEYS = {
    "schema_version", "verification_kind", "source_id", "source_ref",
    "verification_state", "observed_at", "expires_at", "provider_kind",
    "provider_state", "observation_id", "loop_id", "owner_role", "holder_id",
    "generation", "fencing_token", "expected_repo", "expected_pr",
    "expected_target_head", "command_id", "correlation_id",
    "source_receipt_ref", "evidence_ref", "proof_refs",
}


@dataclass(frozen=True)
class VerifiedSourceAttestation:
    verification_kind: str
    source_id: str
    source_ref: str
    observed_at: str


class VerificationSourceReader(Protocol):
    """Read normalized source material. Reading it does not verify it."""

    def read(self, source_ref: str) -> dict[str, Any] | None: ...


class VerificationSourceAuthenticator(Protocol):
    """Independently authenticate normalized material against expected context."""

    def authenticate(
        self,
        source: dict[str, Any],
        *,
        expected: dict[str, Any],
    ) -> VerifiedSourceAttestation | None: ...


def validate_authority_verification_source(source: dict[str, Any]) -> None:
    if not isinstance(source, dict) or set(source) != _AUTHORITY_KEYS:
        raise ValueError("authority verification source is malformed")
    _common_source(source, "AUTHORITY_GRANT")
    if not isinstance(source["authority_id"], str) or not _ID.fullmatch(source["authority_id"]):
        raise ValueError("invalid authority source authority_id")
    _owner_context(source)
    if source["event_type"] not in {"ACQUIRE", "RENEW", "HANDOFF", "RELEASE", "TERMINAL"}:
        raise ValueError("invalid authority source event_type")
    validate_evidence_ref(source["source_ref"])
    prefix = f"automation/command_bus/evidence/{source['loop_id']}/"
    if not source["source_ref"].startswith(prefix):
        raise ValueError("authority source_ref loop mismatch")


def validate_provider_verification_source(source: dict[str, Any]) -> None:
    if not isinstance(source, dict) or set(source) != _PROVIDER_KEYS:
        raise ValueError("provider verification source is malformed")
    _common_source(source, "PROVIDER_OBSERVATION")
    _owner_context(source)
    for field in ("observation_id", "command_id", "correlation_id"):
        if not isinstance(source[field], str) or not _ID.fullmatch(source[field]):
            raise ValueError(f"invalid provider source {field}")
    if not isinstance(source["provider_kind"], str) or not _PROVIDER.fullmatch(source["provider_kind"]):
        raise ValueError("invalid provider source provider_kind")
    if not isinstance(source["provider_state"], str) or not _PROVIDER_STATE.fullmatch(source["provider_state"]):
        raise ValueError("invalid provider source provider_state")
    if not isinstance(source["source_receipt_ref"], str):
        raise ValueError("invalid provider source receipt ref")
    receipt_prefix = f"automation/command_bus/receipts/{source['loop_id']}/"
    if not re.fullmatch(re.escape(receipt_prefix) + r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json", source["source_receipt_ref"]):
        raise ValueError("invalid provider source receipt ref")
    validate_evidence_ref(source["evidence_ref"])
    if not source["evidence_ref"].startswith(f"automation/command_bus/evidence/{source['loop_id']}/"):
        raise ValueError("provider evidence_ref loop mismatch")
    if not isinstance(source["source_ref"], str) or not _SAFE_REF.fullmatch(source["source_ref"]) or "://" in source["source_ref"]:
        raise ValueError("provider source_ref must be a safe opaque reference")


class SourceBoundAuthorityGrantVerifier:
    """Existing AuthorityGrantVerifier contract backed by independent source proof."""

    def __init__(
        self,
        reader: VerificationSourceReader | None,
        authenticator: VerificationSourceAuthenticator | None,
    ):
        self.reader = reader
        self.authenticator = authenticator

    def verify(self, grant, event, prior_state, target, receipt, chain):
        try:
            validate_authority_grant(grant)
            if self.reader is None or self.authenticator is None:
                return None
            source = self.reader.read(grant["verification_ref"])
            validate_authority_verification_source(source)
            expected = _authority_expected(grant, event)
            if source["verification_state"] != "VERIFIED":
                return None
            if any(source.get(key) != value for key, value in expected.items()):
                return None
            issued = _time(grant["issued_at"])
            observed = _time(source["observed_at"])
            expires = _time(source["expires_at"])
            if observed < issued or expires != _time(grant["expires_at"]) or observed >= expires:
                return None
            attestation = self.authenticator.authenticate(dict(source), expected=dict(expected))
            if not _attestation_matches(attestation, source):
                return None
            return AuthorityGrantProof(dict(grant), source["source_ref"])
        except (KeyError, TypeError, ValueError):
            return None


class SourceBoundProviderVerifier:
    """Existing ProviderVerifier contract backed by independent source proof."""

    def __init__(
        self,
        reader: VerificationSourceReader | None,
        authenticator: VerificationSourceAuthenticator | None,
    ):
        self.reader = reader
        self.authenticator = authenticator

    def verify(self, candidate, evidence, receipt):
        try:
            if not isinstance(candidate, dict) or "verified" in candidate:
                return None
            evidence_ref = validate_evidence_document(evidence)
            validate_receipt(receipt)
            source_ref = evidence.get("provider_readback")
            if not isinstance(source_ref, str) or not source_ref:
                return None
            if self.reader is None or self.authenticator is None:
                return None
            source = self.reader.read(source_ref)
            validate_provider_verification_source(source)
            observation = {**candidate, "verified": True}
            validate_provider_observation(observation)
            expected = _provider_expected(
                observation=observation,
                evidence=evidence,
                evidence_ref=evidence_ref,
                receipt=receipt,
            )
            if source["verification_state"] != "VERIFIED":
                return None
            if any(source.get(key) != value for key, value in expected.items()):
                return None
            observed = _time(source["observed_at"])
            expires = _time(source["expires_at"])
            if observed >= expires:
                return None
            attestation = self.authenticator.authenticate(dict(source), expected=dict(expected))
            if not _attestation_matches(attestation, source):
                return None
            return VerifiedProviderObservation(observation, source_ref)
        except (KeyError, TypeError, ValueError):
            return None


def _common_source(source: dict[str, Any], expected_kind: str) -> None:
    if type(source["schema_version"]) is not int or source["schema_version"] != 1:
        raise ValueError("unsupported verification source schema")
    if source["verification_kind"] != expected_kind:
        raise ValueError("verification source kind mismatch")
    if not isinstance(source["source_id"], str) or not _ID.fullmatch(source["source_id"]):
        raise ValueError("invalid verification source_id")
    if source["verification_state"] not in _VERIFICATION_STATES:
        raise ValueError("invalid verification source state")
    observed = _time(source["observed_at"])
    expires = _time(source["expires_at"])
    if expires <= observed:
        raise ValueError("verification source expiry must follow observation")
    refs = source["proof_refs"]
    if (
        not isinstance(refs, list)
        or not refs
        or len(refs) > 32
        or len(refs) != len(set(refs))
        or any(not isinstance(ref, str) or not _SAFE_REF.fullmatch(ref) or "://" in ref for ref in refs)
    ):
        raise ValueError("verification proof_refs must be unique safe opaque references")


def _owner_context(source: dict[str, Any]) -> None:
    if not isinstance(source["loop_id"], str) or not _LOOP.fullmatch(source["loop_id"]):
        raise ValueError("invalid source loop_id")
    if source["owner_role"] not in {"SEMI_AUTO", "AUTO"}:
        raise ValueError("invalid source owner_role")
    if not isinstance(source["holder_id"], str) or not _ID.fullmatch(source["holder_id"]):
        raise ValueError("invalid source holder_id")
    generation = source["generation"]
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("invalid source generation")
    if isinstance(source["fencing_token"], bool) or source["fencing_token"] != generation:
        raise ValueError("source fencing_token must equal generation")
    if "previous_generation" in source:
        previous = source["previous_generation"]
        if generation == 1:
            if previous is not None:
                raise ValueError("first source generation cannot name previous generation")
        elif isinstance(previous, bool) or previous != generation - 1:
            raise ValueError("source previous_generation mismatch")
    if not isinstance(source["expected_repo"], str) or not _REPO.fullmatch(source["expected_repo"]):
        raise ValueError("invalid source expected_repo")
    if isinstance(source["expected_pr"], bool) or not isinstance(source["expected_pr"], int) or source["expected_pr"] < 1:
        raise ValueError("invalid source expected_pr")
    if not isinstance(source["expected_target_head"], str) or not _SHA.fullmatch(source["expected_target_head"]):
        raise ValueError("invalid source expected_target_head")
    for field in ("command_id", "correlation_id"):
        if field in source and (not isinstance(source[field], str) or not _ID.fullmatch(source[field])):
            raise ValueError(f"invalid source {field}")


def _authority_expected(grant: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "authority_id", "loop_id", "owner_role", "holder_id", "generation",
        "fencing_token", "previous_generation", "event_type", "expected_repo",
        "expected_pr", "expected_target_head", "command_id", "correlation_id",
    )
    expected = {key: grant[key] for key in keys}
    for key in keys[1:]:
        if grant[key] != event[key]:
            raise ValueError(f"authority source context mismatch: {key}")
    expected.update(
        verification_kind="AUTHORITY_GRANT",
        source_ref=grant["verification_ref"],
        expires_at=grant["expires_at"],
    )
    return expected


def _provider_expected(
    *,
    observation: dict[str, Any],
    evidence: dict[str, Any],
    evidence_ref: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    for field in ("loop_id", "generation", "expected_repo", "expected_pr", "expected_target_head"):
        if observation[field] != evidence[field]:
            raise ValueError(f"provider observation/evidence mismatch: {field}")
    if observation["state"] != evidence["provider_state"]:
        raise ValueError("provider state mismatch")
    if observation["evidence_ref"] != evidence_ref:
        raise ValueError("provider observation evidence_ref mismatch")
    for field in ("loop_id", "command_id", "correlation_id"):
        if receipt.get(field) != evidence[field]:
            raise ValueError(f"provider receipt/evidence mismatch: {field}")
    return {
        "verification_kind": "PROVIDER_OBSERVATION",
        "source_ref": evidence["provider_readback"],
        "provider_kind": evidence["provider_kind"],
        "provider_state": evidence["provider_state"],
        "observation_id": observation["observation_id"],
        "loop_id": observation["loop_id"],
        "owner_role": observation["owner_role"],
        "holder_id": observation["holder_id"],
        "generation": observation["generation"],
        "fencing_token": observation["fencing_token"],
        "expected_repo": observation["expected_repo"],
        "expected_pr": observation["expected_pr"],
        "expected_target_head": observation["expected_target_head"],
        "command_id": evidence["command_id"],
        "correlation_id": evidence["correlation_id"],
        "source_receipt_ref": evidence["source_receipt_ref"],
        "evidence_ref": evidence_ref,
        "observed_at": observation["observed_at"],
        "expires_at": observation["expires_at"],
    }


def _attestation_matches(attestation: Any, source: dict[str, Any]) -> bool:
    return (
        isinstance(attestation, VerifiedSourceAttestation)
        and attestation.verification_kind == source["verification_kind"]
        and attestation.source_id == source["source_id"]
        and attestation.source_ref == source["source_ref"]
        and attestation.observed_at == source["observed_at"]
    )


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed
