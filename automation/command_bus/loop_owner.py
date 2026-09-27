"""Fail-closed projection of an append-only durable Loop-owner event chain.

This is static protocol code: it neither writes GitHub nor starts a provider.
The caller must read the complete ledger and independently verify receipt,
evidence, and target-head observations before asking for a projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from .loop_status_issue import StatusProjection, project_state
from .validator import validate_state

OWNER_ROLES = {"SEMI_AUTO", "AUTO"}
EVENT_TYPES = {"ACQUIRE", "RENEW", "HANDOFF", "RELEASE", "TERMINAL"}


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
        "expected_target_head", "command_id", "correlation_id", "source_receipt_id",
        "evidence_refs",
    }
    if not isinstance(event, dict) or not required.issubset(event):
        raise ValueError("owner event is malformed or incomplete")
    if event["schema_version"] != 1 or event["event_type"] not in EVENT_TYPES:
        raise ValueError("unsupported owner event schema or type")
    for key in ("event_id", "loop_id", "holder_id", "expected_repo", "command_id", "correlation_id", "source_receipt_id"):
        if not isinstance(event[key], str) or not event[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if event["owner_role"] not in OWNER_ROLES:
        raise ValueError("owner role must be SEMI_AUTO or AUTO")
    if not isinstance(event["expected_pr"], int) or event["expected_pr"] <= 0:
        raise ValueError("expected_pr must be a positive integer")
    if not isinstance(event["expected_target_head"], str) or len(event["expected_target_head"]) != 40:
        raise ValueError("expected_target_head must be a full commit SHA")
    generation = event["generation"]
    if not isinstance(generation, int) or generation <= 0 or event["fencing_token"] != generation:
        raise ValueError("generation and fencing token must be matching positive integers")
    previous = event["previous_generation"]
    if previous is not None and (not isinstance(previous, int) or previous < 1):
        raise ValueError("previous_generation must be null or positive")
    claimed, expires = _time(event["claimed_at"]), _time(event["expires_at"])
    if expires <= claimed:
        raise ValueError("owner lease must expire after it is claimed")
    if not isinstance(event["evidence_refs"], list) or not event["evidence_refs"] or any(not isinstance(item, str) or not item for item in event["evidence_refs"]):
        raise ValueError("owner event requires non-empty evidence references")
    if event["event_type"] == "HANDOFF":
        if event.get("previous_owner_role") not in OWNER_ROLES or not event.get("previous_holder_id"):
            raise ValueError("handoff must bind the previous owner")
    if event["event_type"] == "TERMINAL" and not event.get("terminal_receipt_id"):
        raise ValueError("terminal event requires terminal_receipt_id")


def decide_owner(
    events: Iterable[dict[str, Any]] | None,
    state: dict[str, Any],
    *,
    target: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
    evidence_refs: set[str] | None,
    now: str,
) -> OwnerDecision:
    """Validate a complete ordered chain and its independently read evidence."""
    try:
        validate_state(state)
        if not events:
            raise ValueError("owner ledger is absent")
        chain = list(events)
        if target is None or receipt is None or evidence_refs is None:
            raise ValueError("target, receipt, or evidence readback is missing")
        seen_ids: set[str] = set()
        previous: dict[str, Any] | None = None
        terminal = False
        for index, event in enumerate(chain, 1):
            validate_owner_event(event)
            if event["event_id"] in seen_ids:
                raise ValueError("duplicate owner event")
            seen_ids.add(event["event_id"])
            if event["generation"] != index or event["previous_generation"] != (index - 1 if index > 1 else None):
                raise ValueError("stale, skipped, or reordered generation")
            if previous:
                for key in ("loop_id", "expected_repo", "expected_pr", "expected_target_head", "command_id", "correlation_id"):
                    if event[key] != previous[key]:
                        raise ValueError(f"owner chain binding changed: {key}")
                if previous["event_type"] in {"RELEASE", "TERMINAL"}:
                    raise ValueError("owner chain continued after release or terminal")
                if event["event_type"] == "ACQUIRE":
                    raise ValueError("competing or duplicate active acquisition")
                if event["event_type"] == "RENEW" and (event["owner_role"], event["holder_id"]) != (previous["owner_role"], previous["holder_id"]):
                    raise ValueError("renewal changed owner without handoff")
                if event["event_type"] == "HANDOFF" and (event.get("previous_owner_role"), event.get("previous_holder_id")) != (previous["owner_role"], previous["holder_id"]):
                    raise ValueError("handoff does not fence the previous owner")
            elif event["event_type"] != "ACQUIRE":
                raise ValueError("owner chain must start with ACQUIRE")
            if not set(event["evidence_refs"]).issubset(evidence_refs):
                raise ValueError("owner event evidence is absent from verified evidence")
            previous = event
        assert previous is not None
        if previous["event_type"] in {"RELEASE", "TERMINAL"}:
            terminal = previous["event_type"] == "TERMINAL"
            return OwnerDecision("BLOCKED", "NONE", previous["generation"], previous["fencing_token"], "owner was released or loop is terminal")
        if previous["loop_id"] != state["loop_id"]:
            raise ValueError("loop_id mismatch")
        expected_target = {"repo": previous["expected_repo"], "pr": previous["expected_pr"], "head": previous["expected_target_head"]}
        if target != expected_target:
            raise ValueError("target repository, PR, or head mismatch")
        if receipt.get("receipt_id") != previous["source_receipt_id"] or receipt.get("loop_id") != previous["loop_id"] or receipt.get("command_id") != previous["command_id"] or receipt.get("correlation_id") != previous["correlation_id"]:
            raise ValueError("receipt does not bind this owner generation")
        if receipt.get("state") != "DONE" or receipt.get("executed_once") is not True or receipt.get("retry_count") != 0 or receipt.get("fallback_used") is not False:
            raise ValueError("receipt is not a confirmed single execution")
        if set(receipt.get("evidence_refs", [])) != set(previous["evidence_refs"]):
            raise ValueError("receipt evidence differs from owner event")
        if _time(now) >= _time(previous["expires_at"]):
            raise ValueError("owner lease is expired")
        if _time(previous["claimed_at"]) > _time(now):
            raise ValueError("owner claim is from the future")
        if state["state"] not in {"RUNNING", "WAITING_FOR_EVIDENCE", "VERIFYING_POST_AUTH"}:
            raise ValueError("durable Loop state is not active")
        return OwnerDecision("VALID", previous["owner_role"], previous["generation"], previous["fencing_token"], "validated durable owner chain")
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return OwnerDecision("UNKNOWN", "NONE", None, None, str(exc))


def project_with_durable_owner(state: dict[str, Any], decision: OwnerDecision, **kwargs: Any) -> StatusProjection:
    """Only a fully valid decision may produce SEMI_AUTO/AUTO display."""
    owner = decision.owner if decision.status == "VALID" else "NONE"
    return project_state(state, owner=owner, **kwargs)

