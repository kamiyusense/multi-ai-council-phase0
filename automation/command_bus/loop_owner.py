"""Fail-closed projection of an append-only durable Loop-owner event chain.

This is static protocol code: it neither writes GitHub nor starts a provider.
The caller must read the complete ledger and independently verify receipt,
evidence, and target-head observations before asking for a projection.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import datetime
from typing import Any, Iterable

from .loop_status_issue import StatusProjection, project_state
from .loop_status_evidence import validate_evidence_ref
from .loop_owner_observation import validate_provider_observation
from .validator import validate_state

OWNER_ROLES = {"SEMI_AUTO", "AUTO"}
EVENT_TYPES = {"ACQUIRE", "RENEW", "HANDOFF", "RELEASE", "TERMINAL"}
_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_RECEIPT_REF = re.compile(r"^automation/command_bus/receipts/[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$")
_OWNER_EVENT_KEYS = {
    "schema_version", "event_id", "event_type", "loop_id", "owner_role",
    "holder_id", "generation", "fencing_token", "previous_generation",
    "claimed_at", "expires_at", "expected_repo", "expected_pr",
    "expected_target_head", "command_id", "correlation_id", "source_receipt_id", "source_receipt_ref",
    "evidence_refs", "previous_owner_role", "previous_holder_id", "terminal_receipt_id",
}


@dataclass(frozen=True)
class OwnerDecision:
    status: str
    owner: str
    generation: int | None
    fencing_token: int | None
    reason: str


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def validate_owner_event(event: dict[str, Any]) -> None:
    required = {
        "schema_version", "event_id", "event_type", "loop_id", "owner_role",
        "holder_id", "generation", "fencing_token", "previous_generation",
        "claimed_at", "expires_at", "expected_repo", "expected_pr",
        "expected_target_head", "command_id", "correlation_id", "source_receipt_id", "source_receipt_ref",
        "evidence_refs",
    }
    if not isinstance(event, dict) or not required.issubset(event) or not set(event).issubset(_OWNER_EVENT_KEYS):
        raise ValueError("owner event is malformed or incomplete")
    if isinstance(event["schema_version"], bool) or event["schema_version"] != 1 or event["event_type"] not in EVENT_TYPES:
        raise ValueError("unsupported owner event schema or type")
    for key in ("event_id", "loop_id", "holder_id", "expected_repo", "command_id", "correlation_id", "source_receipt_id", "source_receipt_ref"):
        if not isinstance(event[key], str) or not event[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if not _LOOP_ID.fullmatch(event["loop_id"]):
        raise ValueError("loop_id must be a safe durable path component")
    if not _RECEIPT_REF.fullmatch(event["source_receipt_ref"]):
        raise ValueError("source_receipt_ref must be a safe durable receipt path")
    if not event["source_receipt_ref"].startswith(f"automation/command_bus/receipts/{event['loop_id']}/"):
        raise ValueError("source_receipt_ref must belong to the owner loop")
    if event["owner_role"] not in OWNER_ROLES:
        raise ValueError("owner role must be SEMI_AUTO or AUTO")
    if isinstance(event["expected_pr"], bool) or not isinstance(event["expected_pr"], int) or event["expected_pr"] <= 0:
        raise ValueError("expected_pr must be a positive integer")
    if not isinstance(event["expected_target_head"], str) or not _HEX40.fullmatch(event["expected_target_head"]):
        raise ValueError("expected_target_head must be a full lowercase hexadecimal commit SHA")
    generation = event["generation"]
    if isinstance(generation, bool) or not isinstance(generation, int) or generation <= 0 or isinstance(event["fencing_token"], bool) or event["fencing_token"] != generation:
        raise ValueError("generation and fencing token must be matching positive integers")
    previous = event["previous_generation"]
    if previous is not None and (isinstance(previous, bool) or not isinstance(previous, int) or previous < 1):
        raise ValueError("previous_generation must be null or positive")
    claimed, expires = _time(event["claimed_at"]), _time(event["expires_at"])
    if expires <= claimed:
        raise ValueError("owner lease must expire after it is claimed")
    if not isinstance(event["evidence_refs"], list) or not event["evidence_refs"]:
        raise ValueError("owner event requires non-empty evidence references")
    if len(event["evidence_refs"]) != len(set(event["evidence_refs"])):
        raise ValueError("owner event evidence references must be unique")
    for item in event["evidence_refs"]:
        validate_evidence_ref(item)
        if not item.startswith(f"automation/command_bus/evidence/{event['loop_id']}/"):
            raise ValueError("evidence ref must belong to the owner loop")
    if event["event_type"] == "HANDOFF":
        if event.get("previous_owner_role") not in OWNER_ROLES or not event.get("previous_holder_id"):
            raise ValueError("handoff must bind the previous owner")
    if event["event_type"] == "TERMINAL":
        if not event.get("terminal_receipt_id"):
            raise ValueError("terminal event requires terminal_receipt_id")
        if event["terminal_receipt_id"] != event["source_receipt_id"]:
            raise ValueError("terminal receipt must be the terminal event source receipt")


def validate_owner_chain(
    events: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Validate append-only owner generations without trusting runtime evidence."""
    if not events:
        raise ValueError("owner ledger is absent")
    chain = list(events)
    seen_ids: set[str] = set()
    seen_commands: set[str] = set()
    seen_receipt_ids: set[str] = set()
    seen_receipt_refs: set[str] = set()
    previous: dict[str, Any] | None = None
    for index, event in enumerate(chain, 1):
        validate_owner_event(event)
        if event["event_id"] in seen_ids:
            raise ValueError("duplicate owner event")
        if event["command_id"] in seen_commands:
            raise ValueError("owner generation reused command_id")
        if event["source_receipt_id"] in seen_receipt_ids:
            raise ValueError("owner generation reused source_receipt_id")
        if event["source_receipt_ref"] in seen_receipt_refs:
            raise ValueError("owner generation reused source_receipt_ref")
        seen_ids.add(event["event_id"])
        seen_commands.add(event["command_id"])
        seen_receipt_ids.add(event["source_receipt_id"])
        seen_receipt_refs.add(event["source_receipt_ref"])
        if event["generation"] != index or event["previous_generation"] != (index - 1 if index > 1 else None):
            raise ValueError("stale, skipped, or reordered generation")
        if previous:
            for key in ("loop_id", "expected_repo", "expected_pr"):
                if event[key] != previous[key]:
                    raise ValueError(f"owner chain binding changed: {key}")
            if previous["event_type"] in {"RELEASE", "TERMINAL"}:
                raise ValueError("owner chain continued after release or terminal")
            if event["event_type"] == "ACQUIRE":
                raise ValueError("competing or duplicate active acquisition")
            if event["event_type"] == "RENEW" and (event["owner_role"], event["holder_id"]) != (previous["owner_role"], previous["holder_id"]):
                raise ValueError("renewal changed owner without handoff")
            if event["event_type"] == "HANDOFF":
                if (event.get("previous_owner_role"), event.get("previous_holder_id")) != (previous["owner_role"], previous["holder_id"]):
                    raise ValueError("handoff does not fence the previous owner")
                if (event["owner_role"], event["holder_id"]) == (previous["owner_role"], previous["holder_id"]):
                    raise ValueError("handoff must transfer to a different owner")
        elif event["event_type"] != "ACQUIRE":
            raise ValueError("owner chain must start with ACQUIRE")
        previous = event
    return chain


def decide_owner(
    events: Iterable[dict[str, Any]] | None,
    state: dict[str, Any],
    *,
    target: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
    evidence_refs: set[str] | None,
    provider_observation: dict[str, Any] | None,
    now: str,
) -> OwnerDecision:
    """Validate a complete ordered chain and its independently read evidence."""
    try:
        validate_state(state)
        if target is None or receipt is None or evidence_refs is None:
            raise ValueError("target, receipt, or evidence readback is missing")
        chain = validate_owner_chain(events)
        previous = chain[-1]
        if not set(previous["evidence_refs"]).issubset(evidence_refs):
            raise ValueError("latest owner evidence is absent from verified evidence")
        if previous["loop_id"] != state["loop_id"]:
            raise ValueError("loop_id mismatch")
        if state.get("last_command_id") != previous["command_id"]:
            raise ValueError("state last_command_id does not bind latest owner generation")
        if state.get("last_receipt_id") != previous["source_receipt_id"]:
            raise ValueError("state last_receipt_id does not bind latest owner generation")
        expected_target = {"repo": previous["expected_repo"], "pr": previous["expected_pr"], "head": previous["expected_target_head"]}
        if target != expected_target:
            raise ValueError("target repository, PR, or head mismatch")
        if receipt.get("receipt_id") != previous["source_receipt_id"] or receipt.get("loop_id") != previous["loop_id"] or receipt.get("command_id") != previous["command_id"] or receipt.get("correlation_id") != previous["correlation_id"]:
            raise ValueError("receipt does not bind this owner generation")
        if receipt.get("state") != "DONE" or receipt.get("executed_once") is not True or receipt.get("retry_count") != 0 or receipt.get("fallback_used") is not False:
            raise ValueError("receipt is not a confirmed single execution")
        if set(receipt.get("evidence_refs", [])) != set(previous["evidence_refs"]):
            raise ValueError("receipt evidence differs from owner event")
        if previous["event_type"] in {"RELEASE", "TERMINAL"}:
            return OwnerDecision("BLOCKED", "NONE", previous["generation"], previous["fencing_token"], "verified owner release or terminal event")
        if provider_observation is None:
            raise ValueError("provider observation readback is missing for active owner")
        observation = provider_observation
        validate_provider_observation(observation)
        if observation.get("verified") is not True or observation.get("loop_id") != previous["loop_id"] or observation.get("owner_role") != previous["owner_role"] or observation.get("holder_id") != previous["holder_id"]:
            raise ValueError("provider observation is unverified or bound to another owner")
        if observation.get("generation") != previous["generation"] or observation.get("fencing_token") != previous["fencing_token"]:
            raise ValueError("provider observation generation/fencing mismatch")
        if observation.get("expected_repo") != previous["expected_repo"] or observation.get("expected_pr") != previous["expected_pr"] or observation.get("expected_target_head") != previous["expected_target_head"]:
            raise ValueError("provider observation target mismatch")
        if not isinstance(observation.get("state"), str) or not observation["state"].strip():
            raise ValueError("provider state is missing")
        if observation.get("evidence_ref") not in evidence_refs or observation.get("evidence_ref") not in previous["evidence_refs"]:
            raise ValueError("provider observation evidence is not verified for this generation")
        if _time(now) >= _time(previous["expires_at"]):
            raise ValueError("owner lease is expired")
        if _time(previous["claimed_at"]) > _time(now):
            raise ValueError("owner claim is from the future")
        if _time(observation.get("observed_at")) < _time(previous["claimed_at"]) or _time(observation.get("observed_at")) > _time(now):
            raise ValueError("provider observation is stale or from the future")
        if _time(observation.get("expires_at")) <= _time(now):
            raise ValueError("provider observation has expired")
        if state["state"] not in {"RUNNING", "WAITING_FOR_EVIDENCE", "VERIFYING_POST_AUTH"}:
            raise ValueError("durable Loop state is not active")
        return OwnerDecision("VALID", previous["owner_role"], previous["generation"], previous["fencing_token"], "validated durable owner chain")
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return OwnerDecision("UNKNOWN", "NONE", None, None, str(exc))


def project_with_durable_owner(state: dict[str, Any], decision: OwnerDecision, **kwargs: Any) -> StatusProjection:
    """Only a fully valid decision may produce SEMI_AUTO/AUTO display."""
    owner = decision.owner if decision.status == "VALID" else "NONE"
    return project_state(state, owner=owner, **kwargs)

