"""Deterministic bridge from durable transition readbacks to Status projection.

This module performs no network calls and no writes. A trusted caller must read
the referenced state, receipt, owner chain, evidence, target and provider
observation independently before calling this adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from .loop_owner import OwnerDecision, decide_owner, project_with_durable_owner, validate_owner_chain
from .loop_owner_observation import provider_observation_path, validate_provider_observation
from .loop_status_issue import StatusProjection
from .loop_status_evidence import verify_evidence_readbacks
from .validator import validate_receipt, validate_state


@dataclass(frozen=True)
class TransitionProjectionResult:
    status: str
    reason: str
    projection: StatusProjection | None
    owner_decision: OwnerDecision | None
    event_id: str | None


def project_durable_transition(
    state: dict[str, Any],
    owner_events: Iterable[dict[str, Any]] | None,
    *,
    receipt_ref: str | None,
    receipt: dict[str, Any] | None,
    target: dict[str, Any] | None,
    evidence_readbacks: dict[str, Any] | None,
    provider_observation_ref: str | None,
    provider_observation: dict[str, Any] | None,
    now: str,
    expected_loop_id: str | None = None,
    last_durable_progress: str = "UNKNOWN",
) -> TransitionProjectionResult:
    """Bind all durable readbacks before projecting human-facing status."""
    try:
        validate_state(state)
        if expected_loop_id is not None and state["loop_id"] != expected_loop_id:
            raise ValueError("state loop_id does not match requested loop")
        chain = validate_owner_chain(owner_events)
        latest = chain[-1]
        if latest["loop_id"] != state["loop_id"]:
            raise ValueError("owner/state loop mismatch")
        if state.get("last_command_id") != latest["command_id"]:
            raise ValueError("state last_command_id does not match owner event")
        if state.get("last_receipt_id") != latest["source_receipt_id"]:
            raise ValueError("state last_receipt_id does not match owner event")
        expected_state_target = {"repo": latest["expected_repo"], "pr": latest["expected_pr"], "head": latest["expected_target_head"]}
        if state.get("expected_target") != expected_state_target:
            raise ValueError("state expected_target does not match latest owner generation")
        if receipt_ref is None or receipt is None:
            raise ValueError("durable receipt readback is missing")
        if receipt_ref != latest["source_receipt_ref"]:
            raise ValueError("receipt locator does not match owner event")
        validate_receipt(receipt)
        verified_evidence_refs = verify_evidence_readbacks(latest["evidence_refs"], evidence_readbacks)

        close_event = latest["event_type"] in {"RELEASE", "TERMINAL"}
        if close_event:
            if (provider_observation_ref is None) != (provider_observation is None):
                raise ValueError("partial provider observation supplied for close event")
            if provider_observation is not None:
                expected_observation_ref = provider_observation_path(latest["loop_id"], latest["generation"])
                if provider_observation_ref != expected_observation_ref:
                    raise ValueError("provider observation locator mismatch")
                validate_provider_observation(provider_observation)
        else:
            if provider_observation_ref is None or provider_observation is None:
                raise ValueError("provider observation readback is missing for active owner")
            expected_observation_ref = provider_observation_path(latest["loop_id"], latest["generation"])
            if provider_observation_ref != expected_observation_ref:
                raise ValueError("provider observation locator mismatch")
            validate_provider_observation(provider_observation)

        decision = decide_owner(
            chain,
            state,
            target=target,
            receipt=receipt,
            evidence_refs=verified_evidence_refs,
            provider_observation=provider_observation,
            now=now,
        )
        provider_state = provider_observation["state"] if provider_observation is not None else latest["event_type"]
        projection = project_with_durable_owner(
            state,
            decision,
            provider_state=provider_state,
            last_durable_progress=last_durable_progress,
            expected_loop_id=expected_loop_id,
        )
        if decision.status == "VALID":
            status = "VALID"
            reason = "durable transition and owner evidence verified"
        elif close_event:
            if projection.display_state in {"IDLE", "STOPPED"}:
                status = "TERMINAL"
                reason = f"verified owner close event projected {projection.display_state}"
            else:
                status = "BLOCKED"
                reason = f"verified owner close event conflicts with source state {projection.source_state}"
        else:
            reason = f"owner verification failed closed: {decision.reason}"
            projection = replace(
                projection,
                display_state="BLOCKED",
                human_action="REVIEW REQUIRED",
                reason=reason,
            )
            status = "BLOCKED"
        event_id = state.get("last_receipt_id") or state.get("last_command_id")
        return TransitionProjectionResult(status, reason, projection, decision, event_id)
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return TransitionProjectionResult("UNKNOWN", str(exc), None, None, None)
