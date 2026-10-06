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


@dataclass(frozen=True)
class BatchResult:
    status: str
    revision: int
    steps: int
    task_id: str | None = None
    reason: str | None = None


class StaticTargetObserver:
    def __init__(self, head: str, *, trustworthy: bool = True):
        self.head = head
        self.trustworthy = trustworthy

    def read(self) -> TargetObservation:
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

    def run(self, task: CampaignTask, target: TargetObservation) -> TaskExecutionResult:
        return self._next(task.task_id)


class StaticObservationReader(_ResultQueue):
    """Fixture read/evidence recovery path. It cannot dispatch model work."""

    live_enabled = False

    def observe(self, task: CampaignTask, target: TargetObservation) -> TaskExecutionResult:
        return self._next(task.task_id)


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
        self.store = store
        self.campaign_id = campaign_id
        self.target_observer = target_observer
        self.runner = runner
        self.observation_reader = observation_reader or StaticObservationReader()
        self.replanner = replanner or StaticReplanner()
        self.quota_reader = quota_reader or StaticQuotaReader()
        self.policy = policy

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
                kernel.mark_dispatched(task.task_id, canonical_head=target.head)
                claimed = self.store.save(kernel.state, expected_revision=revision)
                if claimed.status != "ACCEPTED":
                    return self._save_failure(
                        claimed.status, revision, steps, task.task_id, claimed.reason,
                    )
                revision = claimed.revision or revision
                try:
                    result = self.runner.run(task, target)
                except Exception as exc:
                    # STATIC-only failure. Leave RUNNING durable state intact;
                    # restart reclaim needs explicit stopped/fenced evidence.
                    return BatchResult(
                        "STATIC_RUNNER_FAULT", revision, steps, task.task_id, type(exc).__name__,
                    )
                try:
                    kernel.record_result(
                        result_id=result.result_id,
                        task_id=task.task_id,
                        outcome=result.outcome,
                        unknown_class=result.unknown_class,
                        affects_campaign_authority=result.affects_campaign_authority,
                    )
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

            if action.kind is ActionKind.RETRY_OBSERVATION:
                assert action.task_id is not None
                task = kernel.state.tasks[action.task_id]
                try:
                    result = self.observation_reader.observe(task, target)
                except Exception as exc:
                    return BatchResult(
                        "STATIC_OBSERVATION_FAULT", revision, steps, task.task_id, type(exc).__name__,
                    )
                try:
                    kernel.record_result(
                        result_id=result.result_id,
                        task_id=task.task_id,
                        outcome=result.outcome,
                        unknown_class=result.unknown_class,
                        affects_campaign_authority=result.affects_campaign_authority,
                    )
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
