"""STATIC multi-round controller for the hardened Symphony/New Chinponey track.

This module exercises the real durable campaign kernel/store without starting a
provider or model. It is the integration seam for future LIVE adapters after
explicit authorization. Claim-before-dispatch checkpoints, result checkpoints,
restart restore, stale replan, observation recovery and blocker isolation are
all driven here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .symphony_autonomous_policy import (
    AutonomousRuntimePolicy,
    HARDENED_AUTONOMOUS_POLICY,
    QuotaState,
    UnknownClass,
)
from .symphony_autonomous_runtime import (
    ActionKind,
    AutonomousCampaignKernel,
    CampaignTask,
    TaskOutcome,
)
from .symphony_campaign_store import GitHubCampaignStateStore
from .symphony_attempt_store import GitHubAutonomousAttemptStore, make_attempt_id
from .symphony_attempt_reconciler import AttemptFenceProof, reconcile_attempts
from .symphony_result_adoption import AdoptionAction, decide_result_adoption
from .symphony_upstream_event_adapter import UpstreamWorkerEvent, capture_static_attempt_event


@dataclass(frozen=True)
class TargetObservation:
    head: str
    trustworthy: bool = True


@dataclass(frozen=True)
class TaskExecutionResult:
    result_id: str
    outcome: TaskOutcome
    unknown_class: UnknownClass | None = None
    affects_campaign_authority: bool = False
    mutation_operations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.result_id, str) or not self.result_id or not isinstance(self.outcome, TaskOutcome):
            raise ValueError("invalid STATIC result identity/outcome")
        if self.outcome is TaskOutcome.UNKNOWN and not isinstance(self.unknown_class, UnknownClass):
            raise ValueError("UNKNOWN requires explicit class")
        if self.outcome is not TaskOutcome.UNKNOWN and self.unknown_class is not None:
            raise ValueError("unknown class only belongs to UNKNOWN")
        if type(self.affects_campaign_authority) is not bool:
            raise ValueError("result authority scope must be boolean")
        if not isinstance(self.mutation_operations, tuple) or any(
            type(item) is not str for item in self.mutation_operations
        ):
            raise ValueError("mutation operations must be a tuple of strings")


@dataclass(frozen=True)
class BatchResult:
    status: str
    revision: int
    steps: int
    task_id: str | None = None
    reason: str | None = None


class StaticTargetObserver:
    def __init__(self, head: str, *, trustworthy: bool = True, read_sequence: tuple[str, ...] = ()):
        self.head = head
        self.trustworthy = trustworthy
        self.read_sequence = list(read_sequence)

    def read(self) -> TargetObservation:
        if self.read_sequence:
            self.head = self.read_sequence.pop(0)
        return TargetObservation(self.head, self.trustworthy)


class StaticQuotaReader:
    def __init__(self, state: QuotaState = QuotaState.UNKNOWN):
        self.state = state

    def read(self) -> QuotaState:
        return self.state


class StaticReplanner:
    def __init__(self, validity: dict[str, bool] | None = None):
        self.validity = dict(validity or {})

    def task_still_valid(self, task: CampaignTask, target: TargetObservation) -> bool:
        return self.validity.get(task.task_id, True)


class _ResultQueue:
    def __init__(self, outcomes: dict[str, Iterable[TaskExecutionResult]] | None = None):
        self._outcomes = {
            task_id: list(results) for task_id, results in (outcomes or {}).items()
        }
        self.calls: list[str] = []

    def _next(self, task_id: str) -> TaskExecutionResult:
        self.calls.append(task_id)
        queue = self._outcomes.get(task_id, [])
        if not queue:
            raise RuntimeError(f"no STATIC result configured for {task_id}")
        result = queue.pop(0)
        if not isinstance(result, TaskExecutionResult):
            raise RuntimeError("invalid STATIC task result")
        return result


class StaticCampaignTaskRunner(_ResultQueue):
    """Fixture runner with no process, network, provider, or model path."""

    live_enabled = False

    def __init__(self, outcomes=None):
        super().__init__(outcomes)
        self.start_calls: list[str] = []

    def start_attempt(self, attempt_id: str) -> None:
        if attempt_id in self.start_calls:
            raise RuntimeError("duplicate STATIC attempt start")
        self.start_calls.append(attempt_id)

    def run(self, task: CampaignTask, target: TargetObservation) -> TaskExecutionResult:
        return self._next(task.task_id)


class StaticObservationReader(_ResultQueue):
    """Fixture read/evidence recovery path. It cannot dispatch model work."""

    live_enabled = False

    def observe(self, task: CampaignTask, target: TargetObservation) -> TaskExecutionResult:
        return self._next(task.task_id)


class SimulatedProcessCrash(BaseException):
    """Process death fixture: intentionally bypasses ordinary exception recovery."""


class StaticCrashPlan:
    def __init__(self, boundary: str):
        self.boundary = boundary
        self.fired = False

    def check(self, boundary: str) -> None:
        if boundary == self.boundary and not self.fired:
            self.fired = True
            raise SimulatedProcessCrash(boundary)


class StaticAutonomousCampaignController:
    """Drive multiple durable Track-B actions until a real/configured boundary."""

    _TERMINAL_ACTIONS = {
        ActionKind.CAMPAIGN_COMPLETE,
        ActionKind.STOP_QUOTA,
        ActionKind.STOP_CONFIG_LIMIT,
        ActionKind.STOP_NO_SAFE_WORK,
        ActionKind.STOP_HARD_UNKNOWN,
    }

    def __init__(
        self,
        store: GitHubCampaignStateStore,
        *,
        campaign_id: str,
        target_observer: StaticTargetObserver,
        runner: StaticCampaignTaskRunner,
        observation_reader: StaticObservationReader | None = None,
        replanner: StaticReplanner | None = None,
        quota_reader: StaticQuotaReader | None = None,
        policy: AutonomousRuntimePolicy = HARDENED_AUTONOMOUS_POLICY,
        attempt_store: GitHubAutonomousAttemptStore | None = None,
        fence_proofs: tuple[AttemptFenceProof, ...] = (),
        crash_plan: StaticCrashPlan | None = None,
    ):
        # This integration proof must stay incapable of accidentally becoming a
        # LIVE dispatcher merely because a duck-typed object has a run() method.
        if type(target_observer) is not StaticTargetObserver:
            raise ValueError("only the built-in STATIC target observer is admitted")
        if type(runner) is not StaticCampaignTaskRunner:
            raise ValueError("only the built-in STATIC campaign runner is admitted")
        if observation_reader is not None and type(observation_reader) is not StaticObservationReader:
            raise ValueError("only the built-in STATIC observation reader is admitted")
        if replanner is not None and type(replanner) is not StaticReplanner:
            raise ValueError("only the built-in STATIC replanner is admitted")
        if quota_reader is not None and type(quota_reader) is not StaticQuotaReader:
            raise ValueError("only the built-in STATIC quota reader is admitted")
        if crash_plan is not None and type(crash_plan) is not StaticCrashPlan:
            raise ValueError("only built-in STATIC crash plans are admitted")
        if attempt_store is not None and (
            type(attempt_store) is not GitHubAutonomousAttemptStore
            or attempt_store.client is not store.client
            or attempt_store.write_branch != store.write_branch
        ):
            raise ValueError("campaign and attempt stores must share the durable branch/client")
        self.store = store
        self.campaign_id = campaign_id
        self.target_observer = target_observer
        self.runner = runner
        self.observation_reader = observation_reader or StaticObservationReader()
        self.replanner = replanner or StaticReplanner()
        self.quota_reader = quota_reader or StaticQuotaReader()
        self.policy = policy
        self.attempt_store = attempt_store or GitHubAutonomousAttemptStore(
            store.client, write_branch=store.write_branch, default_branch=store.default_branch,
        )
        self.fence_proofs = fence_proofs
        self.crash_plan = crash_plan

    def _crash(self, boundary: str) -> None:
        if self.crash_plan is not None:
            self.crash_plan.check(boundary)

    @staticmethod
    def _save_failure(status: str, revision: int, steps: int, task_id: str | None, reason: str | None) -> BatchResult:
        label = "STALE_CONTROLLER" if status == "CONFLICT" else "UNKNOWN_DURABILITY"
        return BatchResult(label, revision, steps, task_id, reason or status)

    def run_until_boundary(self, *, max_steps: int | None = None) -> BatchResult:
        if max_steps is not None and (
            isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1
        ):
            raise ValueError("max_steps must be a positive integer or None")
        checkpoint = self.store.restore(self.campaign_id)
        if checkpoint is None:
            return BatchResult("MISSING_CAMPAIGN", 0, 0, reason="no durable campaign checkpoint")
        revision = checkpoint.revision
        kernel = AutonomousCampaignKernel(checkpoint.state, policy=self.policy)
        steps = 0
        target = self.target_observer.read()
        reconciled = reconcile_attempts(
            kernel, self.attempt_store, canonical_head=target.head,
            canonical_trustworthy=target.trustworthy, fence_proofs=self.fence_proofs,
            task_validity=lambda task: self.replanner.task_still_valid(task, target),
        )
        if reconciled.changed:
            saved = self.store.save(kernel.state, expected_revision=revision)
            if saved.status != "ACCEPTED":
                return self._save_failure(saved.status, revision, steps, None, saved.reason)
            revision = saved.revision or revision
        if reconciled.status != "RECONCILED":
            return BatchResult(reconciled.status, revision, steps, reason=reconciled.reason)

        while True:
            if max_steps is not None and steps >= max_steps:
                return BatchResult("BATCH_LIMIT", revision, steps)

            target = self.target_observer.read()
            quota_state = self.quota_reader.read()
            action = kernel.next_action(
                canonical_head=target.head,
                quota_state=quota_state,
                canonical_trustworthy=target.trustworthy,
            )
            if action.kind in self._TERMINAL_ACTIONS:
                return BatchResult(action.kind.value, revision, steps, action.task_id, action.reason)

            if action.kind is ActionKind.DISPATCH_TASK:
                assert action.task_id is not None
                task = kernel.state.tasks[action.task_id]
                self._crash("before_intent")
                intent = self.attempt_store.append_intent(
                    campaign_id=self.campaign_id, task_id=task.task_id,
                    generation=kernel.state.generation, attempt_number=task.attempts + 1,
                    expected_target_head=target.head, runner_generation=kernel.state.generation,
                    scope={"mode": "STATIC", "task": task.to_dict()},
                )
                if intent.status != "ACCEPTED":
                    return self._save_failure(intent.status, revision, steps, task.task_id, intent.reason)
                attempt_id = intent.attempt_id
                self._crash("after_intent")
                kernel.mark_dispatched(task.task_id, canonical_head=target.head)
                claimed = self.store.save(kernel.state, expected_revision=revision)
                if claimed.status != "ACCEPTED":
                    return self._save_failure(
                        claimed.status, revision, steps, task.task_id, claimed.reason,
                    )
                revision = claimed.revision or revision
                self._crash("after_running_checkpoint")
                self.runner.start_attempt(attempt_id)
                self._crash("before_started")
                started = capture_static_attempt_event(self.attempt_store, UpstreamWorkerEvent(
                    campaign_id=self.campaign_id, task_id=task.task_id,
                    generation=kernel.state.generation, attempt_id=attempt_id,
                    runner_generation=kernel.state.generation, expected_target_head=target.head,
                    event_kind="STARTED", evidence_ref=attempt_id,
                    source_authentication="STATIC_SIMULATION",
                ))
                if started.status != "ACCEPTED":
                    return self._save_failure(started.status, revision, steps, task.task_id, started.reason)
                self._crash("after_started")
                try:
                    result = self.runner.run(task, target)
                except Exception as exc:
                    # An exception is not proof the worker never started/stopped.
                    # Preserve STARTED_UNRESOLVED, isolate only this task, and
                    # continue independent work instead of ending the batch.
                    kernel.isolate_unresolved_attempt(task.task_id, attempt_id,
                                                      f"STATIC runner fault: {type(exc).__name__}")
                    persisted = self.store.save(kernel.state, expected_revision=revision)
                    if persisted.status != "ACCEPTED":
                        return self._save_failure(persisted.status, revision, steps, task.task_id, persisted.reason)
                    revision = persisted.revision or revision
                    steps += 1
                    continue
                try:
                    if (result.result_id in kernel.state.processed_result_ids
                            and kernel.state.result_attempt_ids.get(result.result_id) != attempt_id):
                        raise ValueError("result id already belongs to another attempt")
                    reported_operations = result.mutation_operations
                    # Upstream owns all turns/retries. Only adoption takes a new
                    # canonical read and validates this task's result.
                    adoption_target = self.target_observer.read()
                    adoption = decide_result_adoption(
                        expected_head=task.expected_target_head,
                        canonical_head=adoption_target.head,
                        canonical_trustworthy=adoption_target.trustworthy,
                        task_still_valid=self.replanner.task_still_valid(task, adoption_target),
                        mutation_operations=result.mutation_operations,
                    )
                    if adoption.action is AdoptionAction.HOLD_AUTHORITY:
                        return BatchResult("UNKNOWN_DURABILITY", revision, steps, task.task_id, adoption.reason)
                    if adoption.action is AdoptionAction.STALE_REPLAN:
                        result = TaskExecutionResult(result.result_id, TaskOutcome.STALE)
                    elif adoption.action is AdoptionAction.ISOLATE_TASK:
                        result = TaskExecutionResult(result.result_id, TaskOutcome.BLOCKED)
                    self._crash("before_terminal")
                    terminal = capture_static_attempt_event(self.attempt_store, UpstreamWorkerEvent(
                        campaign_id=self.campaign_id, task_id=task.task_id,
                        generation=kernel.state.generation, attempt_id=attempt_id,
                        runner_generation=kernel.state.generation, expected_target_head=target.head,
                        event_kind="TERMINAL", evidence_ref=f"static:{attempt_id}",
                        source_authentication="STATIC_SIMULATION", result_id=result.result_id,
                        outcome=result.outcome.value,
                        unknown_class=result.unknown_class.value if result.unknown_class else None,
                        affects_campaign_authority=result.affects_campaign_authority,
                        mutation_operations=reported_operations,
                    ))
                    if terminal.status != "ACCEPTED":
                        return self._save_failure(terminal.status, revision, steps, task.task_id, terminal.reason)
                    self._crash("after_terminal")
                    kernel.record_result(
                        result_id=result.result_id,
                        task_id=task.task_id,
                        outcome=result.outcome,
                        unknown_class=result.unknown_class,
                        affects_campaign_authority=result.affects_campaign_authority,
                    )
                    kernel.state.result_attempt_ids[result.result_id] = attempt_id
                    self._crash("after_result_apply")
                except (KeyError, ValueError) as exc:
                    return BatchResult(
                        "INVALID_STATIC_RESULT", revision, steps, task.task_id, str(exc),
                    )
                persisted = self.store.save(kernel.state, expected_revision=revision)
                steps += 1
                if persisted.status != "ACCEPTED":
                    return self._save_failure(
                        persisted.status, revision, steps, task.task_id, persisted.reason,
                    )
                revision = persisted.revision or revision
                self._crash("after_result_checkpoint")
                continue

            if action.kind is ActionKind.RETRY_OBSERVATION:
                assert action.task_id is not None
                task = kernel.state.tasks[action.task_id]
                try:
                    result = self.observation_reader.observe(task, target)
                except Exception as exc:
                    # Read-only acquisition failure may consume a bounded
                    # observation retry, never a second model dispatch.
                    result = TaskExecutionResult(
                        f"observation-fault:{task.task_id}:{task.attempts}:{task.transient_retries + 1}",
                        TaskOutcome.UNKNOWN, UnknownClass.TRANSIENT_UNKNOWN,
                    )
                try:
                    attempt_id = make_attempt_id(
                        campaign_id=self.campaign_id, task_id=task.task_id,
                        generation=kernel.state.generation, attempt_number=task.attempts,
                        expected_target_head=task.expected_target_head,
                    )
                    observed = self.attempt_store.append_observation(
                        self.campaign_id, attempt_id, result_id=result.result_id,
                        outcome=result.outcome.value,
                        unknown_class=result.unknown_class.value if result.unknown_class else None,
                        affects_campaign_authority=result.affects_campaign_authority,
                        evidence_refs=[f"static-observation:{attempt_id}"],
                    )
                    if observed.status != "ACCEPTED":
                        return self._save_failure(observed.status, revision, steps, task.task_id, observed.reason)
                    self._crash("after_observation_evidence")
                    kernel.record_result(
                        result_id=result.result_id,
                        task_id=task.task_id,
                        outcome=result.outcome,
                        unknown_class=result.unknown_class,
                        affects_campaign_authority=result.affects_campaign_authority,
                    )
                    kernel.state.result_attempt_ids[result.result_id] = attempt_id
                except (KeyError, ValueError) as exc:
                    return BatchResult(
                        "INVALID_STATIC_RESULT", revision, steps, task.task_id, str(exc),
                    )
                persisted = self.store.save(kernel.state, expected_revision=revision)
                steps += 1
                if persisted.status != "ACCEPTED":
                    return self._save_failure(
                        persisted.status, revision, steps, task.task_id, persisted.reason,
                    )
                revision = persisted.revision or revision
                continue

            if action.kind is ActionKind.REPLAN_TASK:
                assert action.task_id is not None
                task = kernel.state.tasks[action.task_id]
                valid = self.replanner.task_still_valid(task, target)
                kernel.replan_stale_task(
                    task.task_id,
                    canonical_head=target.head,
                    task_still_valid=valid,
                    canonical_trustworthy=target.trustworthy,
                )
                persisted = self.store.save(kernel.state, expected_revision=revision)
                steps += 1
                if persisted.status != "ACCEPTED":
                    return self._save_failure(
                        persisted.status, revision, steps, task.task_id, persisted.reason,
                    )
                revision = persisted.revision or revision
                continue

            return BatchResult(
                "UNSUPPORTED_ACTION", revision, steps, action.task_id, action.kind.value,
            )
