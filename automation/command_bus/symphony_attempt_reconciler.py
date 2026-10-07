"""Track-B durable recovery overlay, without provider dispatch or a scheduler.

Upstream owns worker/stall observation. This adapter consumes validated ledger
snapshots and explicit attempt-bound fence evidence; a timeout is never a fence.
The caller must checkpoint changed campaign state before selecting model work.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .symphony_attempt_store import AttemptLineageError, GitHubAutonomousAttemptStore
from .symphony_autonomous_policy import UnknownClass
from .symphony_autonomous_runtime import AutonomousCampaignKernel, CampaignTask, TaskOutcome, TaskStatus
from .symphony_result_adoption import AdoptionAction, decide_result_adoption


@dataclass(frozen=True)
class AttemptFenceProof:
    attempt_id: str
    runner_generation: int
    state: str
    evidence_ref: str

    def to_dict(self) -> dict:
        if (self.state not in {"STOPPED", "FENCED"} or not self.evidence_ref
                or type(self.runner_generation) is not int or self.runner_generation < 1):
            raise ValueError("invalid explicit fence evidence")
        return dict(attempt_id=self.attempt_id, runner_generation=self.runner_generation,
                    state=self.state, evidence_ref=self.evidence_ref)


@dataclass(frozen=True)
class ReconciliationResult:
    status: str
    changed: bool
    applied: int = 0
    isolated: int = 0
    reclaimed: int = 0
    reason: str | None = None


def reconcile_attempts(
    kernel: AutonomousCampaignKernel,
    store: GitHubAutonomousAttemptStore,
    *,
    canonical_head: str,
    canonical_trustworthy: bool = True,
    fence_proofs: tuple[AttemptFenceProof, ...] = (),
    task_validity: Callable[[CampaignTask], bool] | None = None,
) -> ReconciliationResult:
    """Restore evidence before dispatch; no model work occurs in this function."""
    before = kernel.state.to_dict()
    state = kernel.state
    applied = isolated = reclaimed = 0

    def finish(status="RECONCILED", reason=None):
        return ReconciliationResult(status, before != state.to_dict(), applied, isolated, reclaimed, reason)

    def hard(reason):
        state.terminal_reason = reason
        return finish("HARD_UNKNOWN", reason)

    if type(canonical_trustworthy) is not bool or not canonical_trustworthy or not canonical_head:
        return hard("attempt reconciliation canonical lineage unverified")
    proofs = {}
    for proof in fence_proofs:
        if type(proof) is not AttemptFenceProof or proof.attempt_id in proofs:
            return hard("ambiguous attempt fence evidence")
        proofs[proof.attempt_id] = proof.to_dict()
    try:
        snapshots = store.list_campaign(state.campaign_id)
    except AttemptLineageError as exc:
        return hard(f"attempt evidence lineage invalid: {exc}")
    except Exception as exc:
        return finish("UNKNOWN_DURABILITY", f"attempt evidence unavailable: {type(exc).__name__}")

    # Preflight the whole set before applying any evidence or retiring an intent.
    result_owners = dict(state.result_attempt_ids)
    active_tasks = set()
    for snapshot in snapshots:
        identity = snapshot.identity
        if identity.campaign_id != state.campaign_id:
            return hard("attempt campaign identity mismatch")
        if identity.generation > state.generation:
            return hard("attempt from future campaign generation")
        if identity.generation < state.generation:
            continue
        if identity.task_id not in state.tasks:
            return hard("attempt references unknown campaign task")
        task = state.tasks[identity.task_id]
        if snapshot.terminal:
            result_id = snapshot.terminal["result_id"]
            if result_id in result_owners and result_owners[result_id] != identity.attempt_id:
                return hard("terminal result identity reused across attempts")
            result_owners[result_id] = identity.attempt_id
        if not snapshot.terminal and not snapshot.retired:
            if identity.task_id in active_tasks:
                return hard("multiple unresolved attempts for one task")
            active_tasks.add(identity.task_id)

    for snapshot in sorted(snapshots, key=lambda s: (s.identity.generation, s.identity.task_id, s.identity.attempt_number)):
        identity = snapshot.identity
        if identity.generation < state.generation:
            continue
        task = state.tasks[identity.task_id]
        attempt_id = identity.attempt_id
        if snapshot.retired:
            if attempt_id not in state.retired_attempt_ids and task.attempts <= identity.attempt_number:
                kernel.reclaim_unstarted_attempt(task.task_id, attempt_id, identity.attempt_number)
                reclaimed += 1
            continue
        if snapshot.terminal:
            terminal = snapshot.terminal
            result_id = terminal["result_id"]
            if result_id in state.processed_result_ids:
                continue
            if identity.attempt_number < task.attempts:
                # Historical terminal from an older attempt is never applied to
                # the current attempt, even if target HEAD happens to match.
                continue
            if identity.attempt_number != task.attempts:
                kernel.isolate_unresolved_attempt(task.task_id, attempt_id, "terminal attempt counter mismatch")
                isolated += 1
                continue
            adoption = decide_result_adoption(
                expected_head=identity.expected_target_head,
                canonical_head=canonical_head,
                canonical_trustworthy=canonical_trustworthy,
                task_still_valid=(task_validity(task) if task_validity is not None else True)
                and identity.expected_target_head == task.expected_target_head,
                mutation_operations=tuple(terminal.get("mutation_operations", [])),
            )
            if adoption.action is AdoptionAction.HOLD_AUTHORITY:
                return hard(adoption.reason)
            if adoption.action is AdoptionAction.STALE_REPLAN:
                state.processed_result_ids.add(result_id)
                state.result_attempt_ids[result_id] = attempt_id
                if task.status not in {TaskStatus.COMPLETE, TaskStatus.SUPERSEDED}:
                    task.status = TaskStatus.STALE
                    state.deferred_decisions.append({
                        "decision_id": f"stale-terminal:{attempt_id}", "affected_scope": task.task_id,
                        "selected_safe_default": "fresh-head-replan-without-old-result-adoption",
                    })
                continue
            if adoption.action is AdoptionAction.ISOLATE_TASK:
                state.processed_result_ids.add(result_id)
                state.result_attempt_ids[result_id] = attempt_id
                kernel.isolate_unresolved_attempt(task.task_id, attempt_id, adoption.reason)
                isolated += 1
                continue
            # STALE terminal is a replan signal, not a successful new-HEAD result.
            if terminal["outcome"] == "STALE":
                task.status = TaskStatus.STALE
                state.processed_result_ids.add(result_id)
                state.result_attempt_ids[result_id] = attempt_id
                continue
            try:
                kernel.record_result(
                    result_id=result_id, task_id=task.task_id,
                    outcome=TaskOutcome(terminal["outcome"]),
                    unknown_class=UnknownClass(terminal["unknown_class"]) if terminal.get("unknown_class") else None,
                    affects_campaign_authority=terminal.get("affects_campaign_authority", False),
                    allow_blocked_recovery=True, recovery_attempt_id=attempt_id,
                )
            except ValueError as exc:
                kernel.isolate_unresolved_attempt(task.task_id, attempt_id, f"terminal recovery rejected: {exc}")
                isolated += 1
                continue
            state.result_attempt_ids[result_id] = attempt_id
            applied += 1
            if state.terminal_reason:
                return finish("HARD_UNKNOWN", state.terminal_reason)
            continue
        if snapshot.state == "STARTED_UNRESOLVED":
            kernel.isolate_unresolved_attempt(task.task_id, attempt_id, "STARTED_UNRESOLVED; no redispatch")
            isolated += 1
            continue
        proof = proofs.get(attempt_id)
        if proof is None:
            kernel.isolate_unresolved_attempt(task.task_id, attempt_id, "unstarted intent has no explicit fence")
            isolated += 1
            continue
        if proof["runner_generation"] != identity.runner_generation:
            return hard("attempt fence runner generation mismatch")
        retired = store.retire_unstarted(state.campaign_id, attempt_id, fence_proof=proof)
        if retired.status != "ACCEPTED":
            kernel.isolate_unresolved_attempt(task.task_id, attempt_id, "retirement durability unverified")
            isolated += 1
            return finish("UNKNOWN_DURABILITY", retired.reason)
        kernel.reclaim_unstarted_attempt(task.task_id, attempt_id, identity.attempt_number)
        reclaimed += 1
    return finish()
