"""Prepare-only bridge from takeover preflight to RuntimeTransitionPublisher.

No GitHub writes, owner publication, provider launch, or Status dispatch occur
here.  The function reuses the fail-closed takeover preflight and then binds the
proposed HANDOFF, canonical evidence, provider observation input, prior state,
and desired state into one TransitionRequest.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable

from .loop_owner_observation import validate_provider_observation
from .runtime_takeover import TakeoverPlan, preflight_takeover
from .runtime_transition_coordinator import (
    AuthorizedOwnerContext,
    TransitionRequest,
    VerifiedProviderObservation,
)
from .runtime_transition_evidence import validate_evidence_document
from .validator import validate_state


@dataclass(frozen=True)
class PreparedTakeoverTransition:
    status: str
    stage: str
    reason: str
    plan: TakeoverPlan | None = None
    request: TransitionRequest | None = None


def prepare_takeover_transition(
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
    evidence_document: dict[str, Any],
    provider_observation_input: dict[str, Any],
    desired_state: dict[str, Any],
    now: str,
) -> PreparedTakeoverTransition:
    """Return a publisher-ready TransitionRequest only after all static gates pass."""
    preflight = preflight_takeover(
        state=state,
        owner_events=owner_events,
        current_receipt=current_receipt,
        current_evidence_refs=current_evidence_refs,
        current_provider_observation=current_provider_observation,
        target=target,
        proposed_event=proposed_event,
        proposed_receipt=proposed_receipt,
        authorized_owner=authorized_owner,
        verified_provider=verified_provider,
        now=now,
    )
    if preflight.status != "READY" or preflight.plan is None:
        return PreparedTakeoverTransition(
            preflight.status,
            f"preflight:{preflight.stage}",
            preflight.reason,
        )

    stage = "evidence"
    try:
        evidence_ref = validate_evidence_document(evidence_document)
        if proposed_event["evidence_refs"] != [evidence_ref]:
            return PreparedTakeoverTransition(
                "BLOCKED", stage, "proposed HANDOFF must bind exactly one canonical takeover evidence document"
            )

        evidence_keys = (
            "loop_id",
            "generation",
            "command_id",
            "correlation_id",
            "expected_repo",
            "expected_pr",
            "expected_target_head",
            "source_receipt_ref",
        )
        for key in evidence_keys:
            if evidence_document[key] != proposed_event[key]:
                return PreparedTakeoverTransition("BLOCKED", stage, f"takeover evidence/event mismatch: {key}")
        if evidence_document["provider_state"] != verified_provider.observation["state"]:
            return PreparedTakeoverTransition("BLOCKED", stage, "takeover evidence/provider state mismatch")
        if evidence_document["provider_readback"] != verified_provider.source_ref:
            return PreparedTakeoverTransition("BLOCKED", stage, "takeover evidence/provider proof source mismatch")

        stage = "provider_input"
        if not isinstance(provider_observation_input, dict) or "verified" in provider_observation_input:
            return PreparedTakeoverTransition(
                "BLOCKED", stage, "publisher input must not contain caller-supplied verified"
            )
        candidate = {**provider_observation_input, "verified": True}
        validate_provider_observation(candidate)
        if candidate != verified_provider.observation:
            return PreparedTakeoverTransition(
                "BLOCKED", stage, "publisher provider input does not match independently verified observation"
            )
        if candidate["evidence_ref"] != evidence_ref:
            return PreparedTakeoverTransition("BLOCKED", stage, "provider observation evidence_ref mismatch")

        stage = "desired_state"
        validate_state(state)
        validate_state(desired_state)
        if desired_state["loop_id"] != proposed_event["loop_id"]:
            return PreparedTakeoverTransition("BLOCKED", stage, "desired state loop mismatch")
        if desired_state["state"] not in {"RUNNING", "WAITING_FOR_EVIDENCE", "VERIFYING_POST_AUTH"}:
            return PreparedTakeoverTransition("BLOCKED", stage, "takeover desired state must remain active")
        expected_target = {
            "repo": proposed_event["expected_repo"],
            "pr": proposed_event["expected_pr"],
            "head": proposed_event["expected_target_head"],
        }
        if desired_state.get("expected_target") != expected_target:
            return PreparedTakeoverTransition("BLOCKED", stage, "desired state target mismatch")
        if desired_state.get("last_command_id") != proposed_event["command_id"]:
            return PreparedTakeoverTransition("BLOCKED", stage, "desired state command mismatch")
        if desired_state.get("last_receipt_id") != proposed_event["source_receipt_id"]:
            return PreparedTakeoverTransition("BLOCKED", stage, "desired state receipt mismatch")
        if desired_state.get("retry_policy") != 0:
            return PreparedTakeoverTransition("BLOCKED", stage, "desired state retry policy must remain zero")

        request = TransitionRequest(
            owner_event=copy.deepcopy(proposed_event),
            evidence_document=copy.deepcopy(evidence_document),
            provider_observation_input=copy.deepcopy(provider_observation_input),
            expected_prior_state=copy.deepcopy(state),
            desired_state=copy.deepcopy(desired_state),
        )
        return PreparedTakeoverTransition(
            "READY",
            "complete",
            "takeover preflight and publisher request bindings verified",
            preflight.plan,
            request,
        )
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return PreparedTakeoverTransition("UNKNOWN", stage, str(exc))
