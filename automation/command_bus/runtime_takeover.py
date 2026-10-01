"""Static fail-closed preflight for SEMI_AUTO <-> AUTO takeover.

This module performs no GitHub writes, owner-event publication, Status dispatch,
or provider/model launch.  It only decides whether a proposed HANDOFF generation
has enough independently verified context to be eligible for the existing
RuntimeTransitionPublisher.

Lease expiry is necessary for takeover but is never sufficient by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from .loop_owner import validate_owner_chain, validate_owner_event
from .loop_owner_observation import validate_provider_observation
from .runtime_transition_coordinator import AuthorizedOwnerContext, VerifiedProviderObservation
from .validator import validate_receipt, validate_state

_ACTIVE_STATES = {"RUNNING", "WAITING_FOR_EVIDENCE", "VERIFYING_POST_AUTH"}


@dataclass(frozen=True)
class TakeoverPlan:
    loop_id: str
    from_owner_role: str
    from_holder_id: str
    from_generation: int
    to_owner_role: str
    to_holder_id: str
    generation: int
    fencing_token: int
    expected_repo: str
    expected_pr: int
    expected_target_head: str
    command_id: str
    correlation_id: str


@dataclass(frozen=True)
class TakeoverPreflightResult:
    status: str
    stage: str
    reason: str
    plan: TakeoverPlan | None = None


def preflight_takeover(
    *,
    state: dict[str, Any],
    owner_events: Iterable[dict[str, Any]] | None,
    current_receipt: dict[str, Any] | None,
    current_evidence_refs: set[str] | None,
    current_provider_observation: dict[str, Any] | None,
    target: dict[str, Any] | None,
    proposed_event: dict[str, Any],
    proposed_receipt: dict[str, Any] | None,
    authorized_owner: AuthorizedOwnerContext | None,
    verified_provider: VerifiedProviderObservation | None,
    now: str,
) -> TakeoverPreflightResult:
    """Validate one proposed expired-owner HANDOFF without mutating anything."""
    stage = "current_owner"
    try:
        validate_state(state)
        chain = validate_owner_chain(owner_events)
        latest = chain[-1]

        if latest["event_type"] in {"RELEASE", "TERMINAL"}:
            return TakeoverPreflightResult("BLOCKED", stage, "closed owner chain cannot be taken over")
        if state.get("stop_requested") is True:
            return TakeoverPreflightResult("BLOCKED", stage, "stop_requested forbids takeover")
        if state["state"] not in _ACTIVE_STATES:
            return TakeoverPreflightResult("BLOCKED", stage, f"source state is not takeover-active: {state['state']}")

        current_target = {
            "repo": latest["expected_repo"],
            "pr": latest["expected_pr"],
            "head": latest["expected_target_head"],
        }
        if (
            state.get("loop_id") != latest["loop_id"]
            or state.get("last_command_id") != latest["command_id"]
            or state.get("last_receipt_id") != latest["source_receipt_id"]
            or state.get("expected_target") != current_target
        ):
            return TakeoverPreflightResult("BLOCKED", stage, "durable state is not bound to the latest owner generation")

        if not isinstance(target, dict) or target != current_target:
            return TakeoverPreflightResult("BLOCKED", "target", "fresh target does not match the latest durable owner target")

        if current_receipt is None or current_evidence_refs is None or current_provider_observation is None:
            return TakeoverPreflightResult("UNKNOWN", stage, "current owner receipt/evidence/provider readback is incomplete")
        validate_receipt(current_receipt)
        if (
            current_receipt.get("receipt_id") != latest["source_receipt_id"]
            or current_receipt.get("loop_id") != latest["loop_id"]
            or current_receipt.get("command_id") != latest["command_id"]
            or current_receipt.get("correlation_id") != latest["correlation_id"]
            or current_receipt.get("state") != "DONE"
        ):
            return TakeoverPreflightResult("BLOCKED", stage, "current owner receipt does not bind the latest generation")
        if set(current_receipt.get("evidence_refs", [])) != set(latest["evidence_refs"]):
            return TakeoverPreflightResult("BLOCKED", stage, "current owner receipt evidence differs from the owner event")
        if not set(latest["evidence_refs"]).issubset(current_evidence_refs):
            return TakeoverPreflightResult("UNKNOWN", stage, "current owner evidence readback is incomplete")

        validate_provider_observation(current_provider_observation)
        current_observation = current_provider_observation
        if current_observation.get("verified") is not True:
            return TakeoverPreflightResult("UNKNOWN", stage, "current provider observation is not verified")
        for key in ("loop_id", "owner_role", "holder_id", "generation", "fencing_token",
                    "expected_repo", "expected_pr", "expected_target_head"):
            if current_observation.get(key) != latest[key]:
                return TakeoverPreflightResult("BLOCKED", stage, f"current provider observation mismatch: {key}")
        if (
            current_observation.get("evidence_ref") not in latest["evidence_refs"]
            or current_observation.get("evidence_ref") not in current_evidence_refs
        ):
            return TakeoverPreflightResult("UNKNOWN", stage, "current provider evidence is not verified for the latest generation")
        if _time(current_observation["observed_at"]) < _time(latest["claimed_at"]):
            return TakeoverPreflightResult("BLOCKED", stage, "current provider observation predates the owner claim")
        if _time(current_observation["observed_at"]) > _time(latest["expires_at"]):
            return TakeoverPreflightResult("BLOCKED", stage, "current provider observation is outside the owner lease")
        if _time(current_observation["observed_at"]) > _time(now):
            return TakeoverPreflightResult("UNKNOWN", stage, "current provider observation is from the future")

        # Expiry is only the first takeover gate; authority/provider proof follows.
        if _time(now) < _time(latest["expires_at"]):
            return TakeoverPreflightResult("BLOCKED", "expiry", "current owner lease has not expired; takeover is not eligible")

        stage = "proposed_handoff"
        validate_owner_event(proposed_event)
        if proposed_event["event_type"] != "HANDOFF":
            return TakeoverPreflightResult("BLOCKED", stage, "takeover must be represented as a HANDOFF generation")
        if (
            proposed_event["loop_id"] != latest["loop_id"]
            or proposed_event["expected_repo"] != latest["expected_repo"]
            or proposed_event["expected_pr"] != latest["expected_pr"]
            or proposed_event["expected_target_head"] != latest["expected_target_head"]
        ):
            return TakeoverPreflightResult("BLOCKED", stage, "takeover cannot silently rebind loop/repository/PR/target head")
        if proposed_event["generation"] != latest["generation"] + 1:
            return TakeoverPreflightResult("BLOCKED", stage, "takeover generation is not exactly the next generation")
        if proposed_event["fencing_token"] != proposed_event["generation"]:
            return TakeoverPreflightResult("BLOCKED", stage, "takeover fencing token does not equal generation")
        if proposed_event.get("previous_generation") != latest["generation"]:
            return TakeoverPreflightResult("BLOCKED", stage, "takeover previous_generation mismatch")
        if (
            proposed_event.get("previous_owner_role"),
            proposed_event.get("previous_holder_id"),
        ) != (latest["owner_role"], latest["holder_id"]):
            return TakeoverPreflightResult("BLOCKED", stage, "takeover does not fence the exact previous owner")
        if proposed_event["owner_role"] == latest["owner_role"]:
            return TakeoverPreflightResult("BLOCKED", stage, "takeover must switch SEMI_AUTO/AUTO role")
        if proposed_event["holder_id"] == latest["holder_id"]:
            return TakeoverPreflightResult("BLOCKED", stage, "takeover must transfer to a different holder")
        if _time(proposed_event["claimed_at"]) < _time(latest["expires_at"]):
            return TakeoverPreflightResult("BLOCKED", stage, "takeover claim overlaps the previous owner lease")
        if _time(proposed_event["claimed_at"]) > _time(now):
            return TakeoverPreflightResult("BLOCKED", stage, "takeover claim is from the future")
        if _time(proposed_event["expires_at"]) <= _time(now):
            return TakeoverPreflightResult("BLOCKED", stage, "proposed takeover lease is already expired")

        # Chain validation rejects replayed command/receipt/event identities and
        # competing/stale generations.
        validate_owner_chain([*chain, proposed_event])

        if proposed_receipt is None:
            return TakeoverPreflightResult("UNKNOWN", "proposed_receipt", "takeover source receipt is missing")
        validate_receipt(proposed_receipt)
        if (
            proposed_receipt.get("receipt_id") != proposed_event["source_receipt_id"]
            or proposed_receipt.get("loop_id") != proposed_event["loop_id"]
            or proposed_receipt.get("command_id") != proposed_event["command_id"]
            or proposed_receipt.get("correlation_id") != proposed_event["correlation_id"]
            or proposed_receipt.get("state") != "DONE"
        ):
            return TakeoverPreflightResult("BLOCKED", "proposed_receipt", "takeover source receipt does not bind the proposed generation")
        if set(proposed_receipt.get("evidence_refs", [])) != set(proposed_event["evidence_refs"]):
            return TakeoverPreflightResult("BLOCKED", "proposed_receipt", "takeover source receipt evidence differs from the proposed event")

        stage = "authority"
        if authorized_owner is None:
            return TakeoverPreflightResult("NOT_WIRED", stage, "explicit takeover authority is not verified")
        if not _authority_matches(proposed_event, authorized_owner):
            return TakeoverPreflightResult("BLOCKED", stage, "verified authority does not match the proposed takeover generation")

        stage = "provider"
        if verified_provider is None:
            return TakeoverPreflightResult("NOT_WIRED", stage, "new-owner provider verification is not available")
        if not isinstance(verified_provider, VerifiedProviderObservation) or not verified_provider.source_ref:
            return TakeoverPreflightResult("UNKNOWN", stage, "new-owner provider proof is malformed")
        observation = verified_provider.observation
        validate_provider_observation(observation)
        if observation.get("verified") is not True:
            return TakeoverPreflightResult("UNKNOWN", stage, "new-owner provider observation is not verified")
        for key in ("loop_id", "owner_role", "holder_id", "generation", "fencing_token",
                    "expected_repo", "expected_pr", "expected_target_head"):
            if observation.get(key) != proposed_event[key]:
                return TakeoverPreflightResult("BLOCKED", stage, f"new-owner provider observation mismatch: {key}")
        if observation.get("evidence_ref") not in proposed_event["evidence_refs"]:
            return TakeoverPreflightResult("BLOCKED", stage, "new-owner provider evidence is not bound to the proposed generation")
        if _time(observation["observed_at"]) < _time(proposed_event["claimed_at"]):
            return TakeoverPreflightResult("BLOCKED", stage, "new-owner provider observation predates takeover claim")
        if _time(observation["observed_at"]) > _time(now):
            return TakeoverPreflightResult("UNKNOWN", stage, "new-owner provider observation is from the future")
        if _time(observation["expires_at"]) <= _time(now):
            return TakeoverPreflightResult("BLOCKED", stage, "new-owner provider observation is already expired")

        plan = TakeoverPlan(
            loop_id=proposed_event["loop_id"],
            from_owner_role=latest["owner_role"],
            from_holder_id=latest["holder_id"],
            from_generation=latest["generation"],
            to_owner_role=proposed_event["owner_role"],
            to_holder_id=proposed_event["holder_id"],
            generation=proposed_event["generation"],
            fencing_token=proposed_event["fencing_token"],
            expected_repo=proposed_event["expected_repo"],
            expected_pr=proposed_event["expected_pr"],
            expected_target_head=proposed_event["expected_target_head"],
            command_id=proposed_event["command_id"],
            correlation_id=proposed_event["correlation_id"],
        )
        return TakeoverPreflightResult(
            "READY",
            "complete",
            "expired owner, explicit authority, fencing, receipt/evidence, target, and new-owner provider proof verified",
            plan,
        )
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return TakeoverPreflightResult("UNKNOWN", stage, str(exc))


def _authority_matches(event: dict[str, Any], authority: AuthorizedOwnerContext) -> bool:
    return isinstance(authority, AuthorizedOwnerContext) and all(
        getattr(authority, field) == event[field]
        for field in AuthorizedOwnerContext.__dataclass_fields__
    )


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed
