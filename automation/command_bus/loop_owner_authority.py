"""Durable Loop-wide owner authority grant protocol.

A grant record is not sufficient by itself. DurableOwnerAuthority also requires
an independently supplied AuthorityGrantVerifier proof. No Chat/thread identity,
provider activity, PR timestamp, or request-scoped executor/reviewer claim is an
authority source.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .github_backend import GitHubContentsClient
from .loop_owner import validate_owner_chain, validate_owner_event
from .loop_status_evidence import validate_evidence_ref
from .runtime_transition_coordinator import AuthorizedOwnerContext
from .validator import validate_receipt, validate_state

_ROOT = "automation/command_bus/loop_owner_authorities"
_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_OWNER_ROLES = {"SEMI_AUTO", "AUTO"}
_EVENT_TYPES = {"ACQUIRE", "RENEW", "HANDOFF", "RELEASE", "TERMINAL"}
_KEYS = {
    "schema_version", "authority_id", "loop_id", "owner_role", "holder_id",
    "generation", "fencing_token", "previous_generation", "event_type",
    "expected_repo", "expected_pr", "expected_target_head", "command_id",
    "correlation_id", "issued_at", "expires_at", "verification_ref",
    "grant_state",
}


@dataclass(frozen=True)
class AuthorityGrantWriteResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


@dataclass(frozen=True)
class AuthorityGrantProof:
    grant: dict[str, Any]
    source_ref: str


class AuthorityGrantVerifier(Protocol):
    def verify(
        self,
        grant: dict[str, Any],
        event: dict[str, Any],
        prior_state: dict[str, Any],
        target: dict[str, Any],
        receipt: dict[str, Any],
        chain: list[dict[str, Any]],
    ) -> AuthorityGrantProof | None: ...


class Clock(Protocol):
    def now(self) -> str: ...


class UtcClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


def authority_grant_path(loop_id: str, generation: int) -> str:
    if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
        raise ValueError("unsafe loop_id")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("generation must be a positive integer")
    return f"{_ROOT}/{loop_id}/{generation:06d}.json"


def validate_authority_grant(grant: dict[str, Any]) -> None:
    if not isinstance(grant, dict) or set(grant) != _KEYS:
        raise ValueError("authority grant is malformed")
    if isinstance(grant["schema_version"], bool) or grant["schema_version"] != 1:
        raise ValueError("unsupported authority grant schema")
    for key in ("authority_id", "loop_id", "holder_id", "command_id", "correlation_id"):
        value = grant[key]
        pattern = _LOOP_ID if key == "loop_id" else _ID
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ValueError(f"unsafe authority grant {key}")
    if grant["owner_role"] not in _OWNER_ROLES:
        raise ValueError("invalid authority owner_role")
    if grant["event_type"] not in _EVENT_TYPES:
        raise ValueError("invalid authority event_type")
    generation = grant["generation"]
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("invalid authority generation")
    if isinstance(grant["fencing_token"], bool) or grant["fencing_token"] != generation:
        raise ValueError("authority fencing token must equal generation")
    previous = grant["previous_generation"]
    if generation == 1:
        if previous is not None:
            raise ValueError("first authority grant must not name previous generation")
    elif isinstance(previous, bool) or previous != generation - 1:
        raise ValueError("authority previous_generation mismatch")
    if not isinstance(grant["expected_repo"], str) or grant["expected_repo"].count("/") != 1:
        raise ValueError("invalid authority expected_repo")
    if isinstance(grant["expected_pr"], bool) or not isinstance(grant["expected_pr"], int) or grant["expected_pr"] < 1:
        raise ValueError("invalid authority expected_pr")
    if not isinstance(grant["expected_target_head"], str) or not _HEX40.fullmatch(grant["expected_target_head"]):
        raise ValueError("invalid authority expected_target_head")
    issued = _time(grant["issued_at"])
    expires = _time(grant["expires_at"])
    if expires <= issued:
        raise ValueError("authority grant expiry must follow issuance")
    validate_evidence_ref(grant["verification_ref"])
    prefix = f"automation/command_bus/evidence/{grant['loop_id']}/"
    if not grant["verification_ref"].startswith(prefix):
        raise ValueError("authority verification_ref loop mismatch")
    if grant["grant_state"] != "GRANTED":
        raise ValueError("authority grant is not GRANTED")


def grant_for_event(
    event: dict[str, Any],
    *,
    authority_id: str,
    issued_at: str,
    verification_ref: str,
) -> dict[str, Any]:
    validate_owner_event(event)
    grant = {
        "schema_version": 1,
        "authority_id": authority_id,
        "loop_id": event["loop_id"],
        "owner_role": event["owner_role"],
        "holder_id": event["holder_id"],
        "generation": event["generation"],
        "fencing_token": event["fencing_token"],
        "previous_generation": event["previous_generation"],
        "event_type": event["event_type"],
        "expected_repo": event["expected_repo"],
        "expected_pr": event["expected_pr"],
        "expected_target_head": event["expected_target_head"],
        "command_id": event["command_id"],
        "correlation_id": event["correlation_id"],
        "issued_at": issued_at,
        "expires_at": event["expires_at"],
        "verification_ref": verification_ref,
        "grant_state": "GRANTED",
    }
    validate_authority_grant(grant)
    return grant


class AuthorityGrantGitHubBackend:
    """Create-only grant ledger. It does not decide who may issue a grant."""

    def __init__(self, client: GitHubContentsClient, *, branch: str):
        if not isinstance(branch, str) or not branch or branch in {"main", "master"}:
            raise ValueError("authority grant backend requires a non-default data branch")
        self.client = client
        self.branch = branch

    def read(self, loop_id: str, generation: int) -> dict[str, Any] | None:
        path = authority_grant_path(loop_id, generation)
        content = self.client.get(path, self.branch)
        if content is None:
            return None
        record = json.loads(content.text)
        validate_authority_grant(record)
        return record

    def write(self, grant: dict[str, Any]) -> AuthorityGrantWriteResult:
        try:
            validate_authority_grant(grant)
            path = authority_grant_path(grant["loop_id"], grant["generation"])
            existing = self.client.get(path, self.branch)
            if existing is not None:
                record = json.loads(existing.text)
                validate_authority_grant(record)
                if _canonical(record) == _canonical(grant):
                    return AuthorityGrantWriteResult("RECOVERED", "identical authority grant already exists", record)
                return AuthorityGrantWriteResult("BLOCKED", "conflicting authority grant already exists", record)
            try:
                self.client.create(
                    path,
                    _canonical(grant),
                    f"append owner authority {grant['loop_id']} generation {grant['generation']}",
                    self.branch,
                )
            except Exception:
                pass
            readback = self.client.get(path, self.branch)
            if readback is None:
                return AuthorityGrantWriteResult("UNKNOWN", "authority grant write readback unavailable")
            record = json.loads(readback.text)
            validate_authority_grant(record)
            if _canonical(record) != _canonical(grant):
                return AuthorityGrantWriteResult("UNKNOWN", "authority grant write readback mismatch", record)
            return AuthorityGrantWriteResult("ACCEPTED", "authority grant written and verified", record)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return AuthorityGrantWriteResult("UNKNOWN", str(exc))


class DurableOwnerAuthority:
    """Read/verify durable Loop-wide authority without issuing it."""

    def __init__(
        self,
        client: GitHubContentsClient,
        *,
        branch: str,
        verifier: AuthorityGrantVerifier | None,
        clock: Clock | None = None,
    ):
        self.backend = AuthorityGrantGitHubBackend(client, branch=branch)
        self.verifier = verifier
        self.clock = clock or UtcClock()

    def authorize(
        self,
        event: dict[str, Any],
        prior_state: dict[str, Any],
        target: dict[str, Any],
        receipt: dict[str, Any],
        chain: list[dict[str, Any]],
    ) -> AuthorizedOwnerContext | None:
        try:
            validate_owner_event(event)
            validate_state(prior_state)
            validate_receipt(receipt)
            effective_chain = _effective_chain(chain, event)
            if event["generation"] > 1:
                candidates: list[dict[str, Any]] = []
                if chain and chain[-1] == event:
                    candidates.append(event)
                    if len(chain) > 1:
                        candidates.append(chain[-2])
                elif chain:
                    candidates.append(chain[-1])
                if not candidates or not any(_state_matches_generation(prior_state, item) for item in candidates):
                    return None
            grant = self.backend.read(event["loop_id"], event["generation"])
            if grant is None:
                return None
            _bind_grant(grant, event)
            now = _time(self.clock.now())
            issued = _time(grant["issued_at"])
            expires = _time(grant["expires_at"])
            claimed = _time(event["claimed_at"])
            event_expires = _time(event["expires_at"])
            if issued > claimed or expires != event_expires or now < issued or now >= expires:
                return None
            if target != {
                "repo": event["expected_repo"],
                "pr": event["expected_pr"],
                "head": event["expected_target_head"],
            }:
                return None
            if (
                receipt.get("loop_id") != event["loop_id"]
                or receipt.get("command_id") != event["command_id"]
                or receipt.get("correlation_id") != event["correlation_id"]
                or receipt.get("receipt_id") != event["source_receipt_id"]
            ):
                return None
            if prior_state["loop_id"] != event["loop_id"]:
                return None
            if self.verifier is None:
                return None
            proof = self.verifier.verify(grant, event, prior_state, target, receipt, effective_chain)
            if (
                not isinstance(proof, AuthorityGrantProof)
                or _canonical(proof.grant) != _canonical(grant)
                or proof.source_ref != grant["verification_ref"]
            ):
                return None
            return AuthorizedOwnerContext(
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
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None


def _effective_chain(chain: list[dict[str, Any]], event: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(chain, list):
        raise ValueError("owner chain is malformed")
    generation = event["generation"]
    if generation == len(chain) + 1:
        return validate_owner_chain([*chain, event])
    if generation == len(chain) and chain and chain[-1] == event:
        return validate_owner_chain(chain)
    raise ValueError("authority event does not match owner chain frontier")


def _state_matches_generation(state: dict[str, Any], event: dict[str, Any]) -> bool:
    return (
        state.get("last_command_id") == event["command_id"]
        and state.get("last_receipt_id") == event["source_receipt_id"]
        and state.get("expected_target") == {
            "repo": event["expected_repo"],
            "pr": event["expected_pr"],
            "head": event["expected_target_head"],
        }
    )


def _bind_grant(grant: dict[str, Any], event: dict[str, Any]) -> None:
    validate_authority_grant(grant)
    mapping = {
        "loop_id": "loop_id",
        "owner_role": "owner_role",
        "holder_id": "holder_id",
        "generation": "generation",
        "fencing_token": "fencing_token",
        "previous_generation": "previous_generation",
        "event_type": "event_type",
        "expected_repo": "expected_repo",
        "expected_pr": "expected_pr",
        "expected_target_head": "expected_target_head",
        "command_id": "command_id",
        "correlation_id": "correlation_id",
    }
    for grant_key, event_key in mapping.items():
        if grant[grant_key] != event[event_key]:
            raise ValueError(f"authority grant/event mismatch: {grant_key}")


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed
