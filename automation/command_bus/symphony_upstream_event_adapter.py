"""Prepare-only bridge for upstream Symphony worker/stall observations.

This is an evidence adapter, not a detector, timer, scheduler or worker launcher.
Production event authentication is intentionally NOT_WIRED. Only explicit
STATIC fixtures may supply fence evidence to the existing reconciler.
"""
from dataclasses import dataclass

from .symphony_attempt_store import AttemptSnapshot, AttemptWriteResult, GitHubAutonomousAttemptStore
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
    result_id: str | None = None
    outcome: str | None = None
    unknown_class: str | None = None
    affects_campaign_authority: bool = False
    mutation_operations: tuple[str, ...] = ()


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


def capture_static_attempt_event(
    store: GitHubAutonomousAttemptStore, event: UpstreamWorkerEvent,
) -> AttemptWriteResult:
    """Map one fake upstream lifecycle event to the existing durable ledger.

    This bridge admits only explicitly marked STATIC fixtures. Worker updates,
    turns, retries and stalls remain read-only hints; no second scheduler or
    production dispatch path is introduced. The store owns create/readback.
    """
    if type(store) is not GitHubAutonomousAttemptStore or type(event) is not UpstreamWorkerEvent:
        raise ValueError("invalid STATIC upstream bridge input")
    snapshot = store.restore(event.campaign_id, event.attempt_id)
    if snapshot is None:
        return AttemptWriteResult("CONFLICT", event.attempt_id, event.event_kind, "attempt intent missing")
    identity = snapshot.identity
    if (event.campaign_id, event.task_id, event.generation, event.attempt_id,
        event.runner_generation, event.expected_target_head) != (
        identity.campaign_id, identity.task_id, identity.generation, identity.attempt_id,
        identity.runner_generation, identity.expected_target_head,
    ):
        return AttemptWriteResult("CONFLICT", event.attempt_id, event.event_kind, "upstream attempt identity mismatch")
    if event.source_authentication != "STATIC_SIMULATION" or not event.evidence_ref:
        return AttemptWriteResult("CONFLICT", event.attempt_id, event.event_kind, "STATIC source/evidence missing")
    if event.event_kind == "STARTED":
        if snapshot.started is not None:
            status = "NOOP_DUPLICATE" if snapshot.started["provider_attempt_ref"] == event.evidence_ref else "CONFLICT"
            return AttemptWriteResult(status, event.attempt_id, "started", "existing start evidence")
        return store.append_started(
            campaign_id=event.campaign_id, attempt_id=event.attempt_id,
            provider_kind="STATIC_FIXTURE", provider_attempt_ref=event.evidence_ref,
            observation_source="STATIC_SIMULATION",
        )
    if event.event_kind == "TERMINAL":
        if snapshot.started is None or not event.result_id or not event.outcome:
            return AttemptWriteResult("CONFLICT", event.attempt_id, "terminal", "terminal evidence incomplete")
        if snapshot.terminal is not None:
            status = "NOOP_DUPLICATE" if (
                snapshot.terminal["result_id"] == event.result_id
                and snapshot.terminal["outcome"] == event.outcome
                and snapshot.terminal.get("mutation_operations", []) == list(event.mutation_operations)
                and snapshot.terminal.get("unknown_class") == event.unknown_class
                and snapshot.terminal.get("affects_campaign_authority", False) == event.affects_campaign_authority
                and snapshot.terminal["evidence_refs"] == [event.evidence_ref]
            ) else "CONFLICT"
            return AttemptWriteResult(status, event.attempt_id, "terminal", "existing terminal evidence")
        return store.append_terminal(
            campaign_id=event.campaign_id, attempt_id=event.attempt_id,
            result_id=event.result_id, outcome=event.outcome, model_started=True,
            unknown_class=event.unknown_class,
            affects_campaign_authority=event.affects_campaign_authority,
            mutation_operations=event.mutation_operations,
            evidence_refs=[event.evidence_ref],
        )
    return AttemptWriteResult("READ_ONLY", event.attempt_id, event.event_kind, "upstream event does not mutate attempt")


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
