"""Prepare-only bridge for upstream Symphony worker/stall observations.

This is an evidence adapter, not a detector, timer, scheduler or worker launcher.
Production event authentication is intentionally NOT_WIRED. Only explicit
STATIC fixtures may supply fence evidence to the existing reconciler.
"""
from dataclasses import dataclass

from .symphony_attempt_store import AttemptSnapshot
from .symphony_attempt_reconciler import AttemptFenceProof


@dataclass(frozen=True)
class UpstreamWorkerEvent:
    campaign_id: str
    task_id: str
    generation: int
    attempt_id: str
    runner_generation: int
    expected_target_head: str
    event_kind: str
    evidence_ref: str
    source_authentication: str = "UNAUTHENTICATED_CAPTURE"


@dataclass(frozen=True)
class WorkerRecoveryPreparation:
    action: str
    reason: str
    fence_proof: AttemptFenceProof | None = None
    dispatch_authorized: bool = False
    production_source_authentication: str = "NOT_WIRED"


def prepare_upstream_reconciliation_hint(issue_id: str, event_kind: str) -> WorkerRecoveryPreparation:
    """Accept upstream scheduler updates as read-only wake hints.

    Official Symphony may emit an issue update without a task/attempt/thread
    identity. That is enough to refresh durable state, never to adopt a result,
    fence a worker or admit another dispatch. Its internal turn/retry loop stays
    under upstream ownership.
    """
    if not isinstance(issue_id, str) or not issue_id:
        return WorkerRecoveryPreparation("REJECT_UNKNOWN_EVENT", "upstream issue id missing")
    if event_kind not in {"WORKER_UPDATE", "STALLED", "RETRY_SCHEDULED", "TERMINAL_AVAILABLE"}:
        return WorkerRecoveryPreparation("REJECT_UNKNOWN_EVENT", "unsupported upstream hint")
    return WorkerRecoveryPreparation("RECONCILE_READ_ONLY", "refresh durable evidence for upstream issue")


def prepare_worker_recovery(snapshot: AttemptSnapshot, event: UpstreamWorkerEvent) -> WorkerRecoveryPreparation:
    if type(event) is not UpstreamWorkerEvent:
        raise ValueError("worker event must use the explicit envelope")
    identity = snapshot.identity
    if (event.campaign_id, event.task_id, event.generation, event.attempt_id,
        event.runner_generation, event.expected_target_head) != (
        identity.campaign_id, identity.task_id, identity.generation, identity.attempt_id,
        identity.runner_generation, identity.expected_target_head,
    ) or type(event.generation) is not int or type(event.runner_generation) is not int:
        return WorkerRecoveryPreparation("REJECT_STALE_EVENT", "worker event identity is not current")
    if event.source_authentication != "STATIC_SIMULATION":
        return WorkerRecoveryPreparation("READ_EVIDENCE_ONLY", "production event authentication is NOT_WIRED")
    if not isinstance(event.evidence_ref, str) or not event.evidence_ref:
        return WorkerRecoveryPreparation("READ_EVIDENCE_ONLY", "worker evidence reference missing")
    if event.event_kind not in {"STALLED", "STATUS_AVAILABLE", "TERMINAL_AVAILABLE", "STOPPED", "FENCED"}:
        return WorkerRecoveryPreparation("REJECT_UNKNOWN_EVENT", "unsupported upstream event kind")
    if (event.event_kind in {"STOPPED", "FENCED"} and snapshot.state == "CLAIMED_UNSTARTED"
            and snapshot.retired is None):
        proof = AttemptFenceProof(event.attempt_id, event.runner_generation, event.event_kind, event.evidence_ref)
        return WorkerRecoveryPreparation("RECONCILE_UNSTARTED_FENCE", "explicit STATIC stop/fence observation", proof)
    return WorkerRecoveryPreparation("RECONCILE_READ_ONLY", "stall/status events never authorize redispatch")
