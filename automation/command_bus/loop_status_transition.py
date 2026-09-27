"""Deterministic bridge from durable transition readbacks to Status projection.

This module performs no network calls and no writes. A trusted caller must read
the referenced state, receipt, owner chain, evidence, target and provider
observation independently before calling this adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
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
        if receipt_ref is None or receipt is None:
            raise ValueError("durable receipt readback is missing")
        if receipt_ref != latest["source_receipt_ref"]:
            raise ValueError("receipt locator does not match owner event")
        validate_receipt(receipt)
        if provider_observation_ref is None or provider_observation is None:
            raise ValueError("provider observation readback is missing")
        expected_observation_ref = provider_observation_path(latest["loop_id"], latest["generation"])
        if provider_observation_ref != expected_observation_ref:
            raise ValueError("provider observation locator mismatch")
        validate_provider_observation(provider_observation)
        verified_evidence_refs = verify_evidence_readbacks(latest["evidence_refs"], evidence_readbacks)

        decision = decide_owner(
            chain,
            state,
            target=target,
            receipt=receipt,
            evidence_refs=verified_evidence_refs,
            provider_observation=provider_observation,
            now=now,
        )
        projection = project_with_durable_owner(
            state,
            decision,
            provider_state=provider_observation["state"],
            last_durable_progress=last_durable_progress,
            expected_loop_id=expected_loop_id,
        )
        if decision.status == "VALID":
            status = "VALID"
            reason = "durable transition and owner evidence verified"
        elif projection.display_state in {"IDLE", "STOPPED"}:
            status = "TERMINAL"
            reason = f"non-active runtime projected {projection.display_state}; owner is not active"
        else:
            status = "BLOCKED"
            reason = f"owner verification failed closed: {decision.reason}"
        event_id = state.get("last_receipt_id") or state.get("last_command_id")
        return TransitionProjectionResult(status, reason, projection, decision, event_id)
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return TransitionProjectionResult("UNKNOWN", str(exc), None, None, None)
