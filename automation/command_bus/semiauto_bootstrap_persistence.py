"""Bootstrap persistence adapter for the first ChatGPT Semi-Auto durable identity.

This adapter safely seeds ONLY the PREPARED runtime state and the canonical
source receipt on a non-default runtime data branch using the existing
create-only/readback components. It performs no live persistence itself and
does not advance the registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .jules_semiauto_owner_prepare import JulesSemiAutoAcquireBundle
from .github_backend import GitHubContentsClient
from .runtime_state_initializer import RuntimeStateInitializer
from .runtime_transition_receipt import CanonicalOwnerReceiptGitHubBackend
from .semiauto_runtime_identity import get_canonical_semiauto_loop_id


@dataclass(frozen=True)
class BootstrapPersistenceResult:
    status: str
    reason: str


def persist_semiauto_bootstrap_bundle(
    bundle: JulesSemiAutoAcquireBundle,
    client: GitHubContentsClient,
    branch: str,
) -> BootstrapPersistenceResult:
    """Persist the prepared bootstrap bundle to a non-default data branch."""
    if not isinstance(branch, str) or not branch or branch in {"main", "master"}:
        raise ValueError("bootstrap persistence requires a non-default data branch")
    if not isinstance(bundle, JulesSemiAutoAcquireBundle):
        raise ValueError("bundle must be a JulesSemiAutoAcquireBundle")

    # 1. Validate bundle internal identity and bindings
    loop_id = get_canonical_semiauto_loop_id()

    if bundle.initial_state.get("loop_id") != loop_id:
        raise ValueError("invalid initial_state loop_id")
    if bundle.owner_event.get("loop_id") != loop_id:
        raise ValueError("invalid owner_event loop_id")
    if bundle.source_receipt.get("loop_id") != loop_id:
        raise ValueError("invalid source_receipt loop_id")
    if bundle.evidence_document.get("loop_id") != loop_id:
        raise ValueError("invalid evidence_document loop_id")
    if bundle.provider_observation_input.get("loop_id") != loop_id:
        raise ValueError("invalid provider_observation_input loop_id")
    if bundle.transition_request.expected_prior_state.get("loop_id") != loop_id:
        raise ValueError("invalid expected_prior_state loop_id")
    if bundle.transition_request.desired_state.get("loop_id") != loop_id:
        raise ValueError("invalid desired_state loop_id")

    # Validate bindings consistency
    if bundle.source_receipt.get("receipt_id") != bundle.owner_event.get("source_receipt_id"):
        raise ValueError("source receipt ID mismatch")
    if bundle.source_receipt.get("evidence_refs") != bundle.owner_event.get("evidence_refs"):
        raise ValueError("evidence refs mismatch")
    if bundle.source_receipt.get("command_id") != bundle.owner_event.get("command_id"):
        raise ValueError("command ID mismatch")
    if bundle.source_receipt.get("correlation_id") != bundle.owner_event.get("correlation_id"):
        raise ValueError("correlation ID mismatch")

    expected_target_head = bundle.owner_event.get("expected_target_head")
    if bundle.transition_request.expected_prior_state.get("expected_target", {}).get("head") != expected_target_head:
        raise ValueError("expected target head mismatch in expected prior state")

    if bundle.transition_request.expected_prior_state.get("retry_policy") != 0:
        raise ValueError("retry policy must be zero")

    # Validate state and event expectations
    if bundle.initial_state.get("state") != "PREPARED":
        raise ValueError("initial state must be PREPARED")
    if bundle.initial_state.get("round") != 0:
        raise ValueError("initial state round must be 0")
    if bundle.transition_request.desired_state.get("state") != "RUNNING":
        raise ValueError("desired state must be RUNNING")

    if bundle.owner_event.get("event_type") != "ACQUIRE":
        raise ValueError("owner event must be ACQUIRE")
    if bundle.owner_event.get("owner_role") != "SEMI_AUTO":
        raise ValueError("owner event owner_role must be SEMI_AUTO")
    if bundle.owner_event.get("generation") != 1:
        raise ValueError("owner event generation must be 1")
    if bundle.owner_event.get("fencing_token") != 1:
        raise ValueError("owner event fencing token must be 1")

    # 2. Persistence order: State then Receipt
    state_init = RuntimeStateInitializer(client, branch=branch)
    state_result = state_init.create(bundle.initial_state)

    if state_result.status not in {"ACCEPTED", "RECOVERED"}:
        return BootstrapPersistenceResult(status=state_result.status, reason=state_result.reason)

    receipt_backend = CanonicalOwnerReceiptGitHubBackend(client, branch=branch)
    receipt_result = receipt_backend.write(bundle.owner_event, bundle.source_receipt)

    if receipt_result.status not in {"ACCEPTED", "RECOVERED"}:
        return BootstrapPersistenceResult(status=receipt_result.status, reason=receipt_result.reason)

    return BootstrapPersistenceResult(
        status="READY_FOR_TRUST_PROOF",
        reason="bootstrap PREPARED state and canonical receipt successfully seeded",
    )
