"""Main-branch policy authenticator for durable owner authority.

This module does not issue grants and does not write GitHub. It authenticates
an already-normalized AUTHORITY_GRANT verification source against a fresh
readback of a static policy document from main.

The repository config defaults to zero policies, so merging this code alone
grants no owner authority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .runtime_verifier_sources import (
    VerifiedSourceAttestation,
    validate_authority_verification_source,
)

_POLICY_PATH = "automation/command_bus/config/runtime_owner_policy.json"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOOP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_EVENT_TYPES = {"ACQUIRE", "RENEW", "HANDOFF", "RELEASE", "TERMINAL"}
_ROLES = {"SEMI_AUTO", "AUTO"}


@dataclass(frozen=True)
class RuntimeOwnerPolicyReadback:
    document: dict[str, Any]
    ref: str
    commit_sha: str
    path: str = _POLICY_PATH


class RuntimeOwnerPolicyReader(Protocol):
    def read_policy(self) -> RuntimeOwnerPolicyReadback | None: ...


class RuntimeOwnerPolicyClock(Protocol):
    def now(self) -> str: ...


def validate_runtime_owner_policy(document: dict[str, Any]) -> None:
    if not isinstance(document, dict) or set(document) != {"schema_version", "policies"}:
        raise ValueError("runtime owner policy shape is invalid")
    if document["schema_version"] != 1:
        raise ValueError("unsupported runtime owner policy schema")
    policies = document["policies"]
    if not isinstance(policies, list) or len(policies) > 16:
        raise ValueError("runtime owner policies are invalid or exceed bounded maximum")

    seen_ids: set[str] = set()
    enabled_keys: set[tuple[str, str, str, str, int]] = set()
    for policy in policies:
        _validate_policy_entry(policy)
        policy_id = policy["policy_id"]
        if policy_id in seen_ids:
            raise ValueError("duplicate runtime owner policy_id")
        seen_ids.add(policy_id)
        if policy["enabled"]:
            key = (
                policy["loop_id"],
                policy["owner_role"],
                policy["holder_id"],
                policy["expected_repo"],
                policy["expected_pr"],
            )
            if key in enabled_keys:
                raise ValueError("duplicate enabled runtime owner policy binding")
            enabled_keys.add(key)


class MainPolicyAuthorityAuthenticator:
    """Authenticate authority source against fresh current-main policy readback."""

    def __init__(
        self,
        *,
        policy_reader: RuntimeOwnerPolicyReader | None,
        clock: RuntimeOwnerPolicyClock | None,
    ):
        self.policy_reader = policy_reader
        self.clock = clock

    def authenticate(
        self,
        source: dict[str, Any],
        *,
        expected: dict[str, Any],
    ) -> VerifiedSourceAttestation | None:
        try:
            validate_authority_verification_source(source)
            if self.policy_reader is None or self.clock is None:
                return None
            if source.get("verification_state") != "VERIFIED":
                return None
            if not isinstance(expected, dict):
                return None
            for key, value in expected.items():
                if source.get(key) != value:
                    return None

            now = _time(self.clock.now())
            observed = _time(source["observed_at"])
            expires = _time(source["expires_at"])
            if now < observed or now >= expires:
                return None

            readback = self.policy_reader.read_policy()
            if not isinstance(readback, RuntimeOwnerPolicyReadback):
                return None
            if readback.ref != "main":
                return None
            if readback.path != _POLICY_PATH:
                return None
            if not isinstance(readback.commit_sha, str) or not _SHA.fullmatch(readback.commit_sha):
                return None
            validate_runtime_owner_policy(readback.document)

            matches = [
                policy
                for policy in readback.document["policies"]
                if _policy_matches(policy, source)
            ]
            if len(matches) != 1:
                return None
            policy = matches[0]

            lease_seconds = int((expires - observed).total_seconds())
            if lease_seconds <= 0 or lease_seconds > policy["max_lease_seconds"]:
                return None

            required_proofs = {
                f"policy:{policy['policy_id']}",
                f"github-main:{readback.commit_sha}",
            }
            if not required_proofs.issubset(set(source["proof_refs"])):
                return None

            return VerifiedSourceAttestation(
                source["verification_kind"],
                source["source_id"],
                source["source_ref"],
                source["observed_at"],
            )
        except (KeyError, TypeError, ValueError):
            return None


def _validate_policy_entry(policy: Any) -> None:
    required = {
        "policy_id",
        "enabled",
        "loop_id",
        "owner_role",
        "holder_id",
        "expected_repo",
        "expected_pr",
        "allowed_event_types",
        "max_lease_seconds",
    }
    if not isinstance(policy, dict) or set(policy) != required:
        raise ValueError("runtime owner policy entry shape is invalid")
    if not isinstance(policy["policy_id"], str) or not _ID.fullmatch(policy["policy_id"]):
        raise ValueError("invalid runtime owner policy_id")
    if not isinstance(policy["enabled"], bool):
        raise ValueError("runtime owner policy enabled must be boolean")
    if not isinstance(policy["loop_id"], str) or not _LOOP.fullmatch(policy["loop_id"]):
        raise ValueError("invalid runtime owner policy loop_id")
    if policy["owner_role"] not in _ROLES:
        raise ValueError("invalid runtime owner policy role")
    if not isinstance(policy["holder_id"], str) or not _ID.fullmatch(policy["holder_id"]):
        raise ValueError("invalid runtime owner policy holder_id")
    if not isinstance(policy["expected_repo"], str) or not _REPO.fullmatch(policy["expected_repo"]):
        raise ValueError("invalid runtime owner policy repository")
    if (
        isinstance(policy["expected_pr"], bool)
        or not isinstance(policy["expected_pr"], int)
        or policy["expected_pr"] < 1
    ):
        raise ValueError("invalid runtime owner policy PR")
    events = policy["allowed_event_types"]
    if (
        not isinstance(events, list)
        or not events
        or len(events) > 5
        or len(events) != len(set(events))
        or any(event not in _EVENT_TYPES for event in events)
    ):
        raise ValueError("invalid runtime owner policy event types")
    lease = policy["max_lease_seconds"]
    if (
        isinstance(lease, bool)
        or not isinstance(lease, int)
        or lease < 60
        or lease > 14400
    ):
        raise ValueError("invalid runtime owner policy max lease")


def _policy_matches(policy: dict[str, Any], source: dict[str, Any]) -> bool:
    return (
        policy["enabled"] is True
        and policy["loop_id"] == source["loop_id"]
        and policy["owner_role"] == source["owner_role"]
        and policy["holder_id"] == source["holder_id"]
        and policy["expected_repo"] == source["expected_repo"]
        and policy["expected_pr"] == source["expected_pr"]
        and source["event_type"] in policy["allowed_event_types"]
    )


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed
