"""Pure durable-state kernel for the hardened Symphony/New Chinponey track.

The kernel does not dispatch a model and performs no GitHub writes. It defines
serializable campaign/task state and deterministic continuation decisions so a
fresh controller can restore work without relying on session memory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .symphony_autonomous_policy import (
    AutonomousRuntimePolicy,
    HARDENED_AUTONOMOUS_POLICY,
    QuotaState,
    RecoveryAction,
    UnknownClass,
    decide_unknown,
    model_work_allowed,
    stale_head_action,
)


class TaskStatus(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    COMPLETE = "COMPLETE"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class ActionKind(str, Enum):
    DISPATCH_TASK = "DISPATCH_TASK"
    REPLAN_TASK = "REPLAN_TASK"
    RETRY_OBSERVATION = "RETRY_OBSERVATION"
    CORRECTIVE_TASK_CREATED = "CORRECTIVE_TASK_CREATED"
    ISOLATE_TASK_CONTINUE = "ISOLATE_TASK_CONTINUE"
    NOOP_DUPLICATE = "NOOP_DUPLICATE"
    CAMPAIGN_COMPLETE = "CAMPAIGN_COMPLETE"
    STOP_QUOTA = "STOP_QUOTA"
    STOP_CONFIG_LIMIT = "STOP_CONFIG_LIMIT"
    STOP_NO_SAFE_WORK = "STOP_NO_SAFE_WORK"
    STOP_HARD_UNKNOWN = "STOP_HARD_UNKNOWN"


class TaskOutcome(str, Enum):
    DONE = "DONE"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass
class CampaignTask:
    task_id: str
    dependencies: tuple[str, ...] = ()
    status: TaskStatus = TaskStatus.READY
    expected_target_head: str | None = None
    corrective_for: str | None = None
    corrective_round: int = 0
    transient_retries: int = 0
    attempts: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(item, str) and item for item in self.dependencies
        ):
            raise ValueError("dependencies must be a tuple of task ids")
        if not isinstance(self.status, TaskStatus):
            self.status = TaskStatus(self.status)
        for name in ("corrective_round", "transient_retries", "attempts"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["dependencies"] = list(self.dependencies)
        record["status"] = self.status.value
        return record

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> "CampaignTask":
        value = dict(record)
        value["dependencies"] = tuple(value.get("dependencies", ()))
        value["status"] = TaskStatus(value.get("status", TaskStatus.READY.value))
        return cls(**value)


@dataclass
class PlannedAction:
    kind: ActionKind
    task_id: str | None = None
    reason: str | None = None


@dataclass
class CampaignState:
    campaign_id: str
    generation: int
    tasks: dict[str, CampaignTask]
    rounds_completed: int = 0
    consecutive_failures: int = 0
    processed_result_ids: set[str] = field(default_factory=set)
    blockers: list[dict[str, str]] = field(default_factory=list)
    deferred_decisions: list[dict[str, str]] = field(default_factory=list)
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.campaign_id, str) or not self.campaign_id:
            raise ValueError("campaign_id must be non-empty")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("generation must be a positive integer")
        for name in ("rounds_completed", "consecutive_failures"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if len(self.tasks) != len(set(self.tasks)):
            raise ValueError("duplicate task ids")
        for task_id, task in self.tasks.items():
            if task_id != task.task_id:
                raise ValueError("task map key mismatch")
        missing = {
            dependency
            for task in self.tasks.values()
            for dependency in task.dependencies
            if dependency not in self.tasks
        }
        if missing:
            raise ValueError(f"missing task dependencies: {sorted(missing)!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "campaign_id": self.campaign_id,
            "generation": self.generation,
            "tasks": {key: self.tasks[key].to_dict() for key in sorted(self.tasks)},
            "rounds_completed": self.rounds_completed,
            "consecutive_failures": self.consecutive_failures,
            "processed_result_ids": sorted(self.processed_result_ids),
            "blockers": list(self.blockers),
            "deferred_decisions": list(self.deferred_decisions),
            "terminal_reason": self.terminal_reason,
        }

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> "CampaignState":
        if record.get("schema_version") != 1:
            raise ValueError("unsupported campaign schema")
        return cls(
            campaign_id=record["campaign_id"],
            generation=record["generation"],
            tasks={key: CampaignTask.from_dict(value) for key, value in record["tasks"].items()},
            rounds_completed=record.get("rounds_completed", 0),
            consecutive_failures=record.get("consecutive_failures", 0),
            processed_result_ids=set(record.get("processed_result_ids", [])),
            blockers=list(record.get("blockers", [])),
            deferred_decisions=list(record.get("deferred_decisions", [])),
            terminal_reason=record.get("terminal_reason"),
        )


class AutonomousCampaignKernel:
    """Deterministic Track-B continuation kernel over durable campaign records."""

    def __init__(
        self,
        state: CampaignState,
        *,
        policy: AutonomousRuntimePolicy = HARDENED_AUTONOMOUS_POLICY,
    ):
        self.state = state
        self.policy = policy

    @classmethod
    def restore(
        cls,
        record: dict[str, Any],
        *,
        policy: AutonomousRuntimePolicy = HARDENED_AUTONOMOUS_POLICY,
    ) -> "AutonomousCampaignKernel":
        return cls(CampaignState.from_dict(record), policy=policy)

    def _dependencies_complete(self, task: CampaignTask) -> bool:
        return all(self.state.tasks[item].status is TaskStatus.COMPLETE for item in task.dependencies)

    def _ready(self, *, exclude: str | None = None) -> list[CampaignTask]:
        return sorted(
            (
                task for task in self.state.tasks.values()
                if task.task_id != exclude
                and task.status is TaskStatus.READY
                and self._dependencies_complete(task)
            ),
            key=lambda item: item.task_id,
        )

    def _independent_safe_work(self, task_id: str) -> bool:
        return bool(self._ready(exclude=task_id))

    def next_action(
        self,
        *,
        canonical_head: str,
        quota_state: QuotaState = QuotaState.UNKNOWN,
        canonical_trustworthy: bool = True,
    ) -> PlannedAction:
        if self.state.terminal_reason:
            return PlannedAction(ActionKind.STOP_HARD_UNKNOWN, reason=self.state.terminal_reason)
        if not isinstance(canonical_head, str) or not canonical_head:
            self.state.terminal_reason = "canonical target HEAD unavailable"
            return PlannedAction(ActionKind.STOP_HARD_UNKNOWN, reason=self.state.terminal_reason)
        if type(canonical_trustworthy) is not bool or not canonical_trustworthy:
            self.state.terminal_reason = "canonical target lineage is not trustworthy"
            return PlannedAction(ActionKind.STOP_HARD_UNKNOWN, reason=self.state.terminal_reason)
        if self.policy.max_rounds is not None and self.state.rounds_completed >= self.policy.max_rounds:
            return PlannedAction(ActionKind.STOP_CONFIG_LIMIT, reason="max_rounds reached")
        if self.state.consecutive_failures >= self.policy.max_consecutive_failures:
            return PlannedAction(ActionKind.STOP_CONFIG_LIMIT, reason="max_consecutive_failures reached")
        if all(
            task.status in {TaskStatus.COMPLETE, TaskStatus.SUPERSEDED}
            for task in self.state.tasks.values()
        ):
            return PlannedAction(ActionKind.CAMPAIGN_COMPLETE)
        waiting = sorted(
            (
                task for task in self.state.tasks.values()
                if task.status is TaskStatus.WAITING and self._dependencies_complete(task)
            ),
            key=lambda item: item.task_id,
        )
        if waiting:
            return PlannedAction(
                ActionKind.RETRY_OBSERVATION, waiting[0].task_id,
                "retry non-destructive observation/evidence acquisition",
            )
        stale = sorted(
            (
                task for task in self.state.tasks.values()
                if task.status is TaskStatus.STALE and self._dependencies_complete(task)
            ),
            key=lambda item: item.task_id,
        )
        if stale:
            return PlannedAction(ActionKind.REPLAN_TASK, stale[0].task_id, "task requires safe replan")
        ready = self._ready()
        if ready and not model_work_allowed(quota_state, self.policy):
            return PlannedAction(ActionKind.STOP_QUOTA, reason="subscription allowance exhausted")
        if ready:
            task = ready[0]
            if task.expected_target_head not in {None, canonical_head}:
                return PlannedAction(ActionKind.REPLAN_TASK, task.task_id, "target HEAD changed")
            return PlannedAction(ActionKind.DISPATCH_TASK, task.task_id)
        return PlannedAction(
            ActionKind.STOP_NO_SAFE_WORK,
            reason="no dependency-satisfied READY task remains",
        )

    def mark_dispatched(self, task_id: str, *, canonical_head: str) -> None:
        task = self.state.tasks[task_id]
        if task.status is not TaskStatus.READY or not self._dependencies_complete(task):
            raise ValueError("task is not dispatch-ready")
        if task.expected_target_head not in {None, canonical_head}:
            raise ValueError("task must be replanned to the canonical HEAD before dispatch")
        task.expected_target_head = canonical_head
        task.status = TaskStatus.RUNNING
        task.attempts += 1

    def replan_stale_task(
        self,
        task_id: str,
        *,
        canonical_head: str,
        task_still_valid: bool,
        canonical_trustworthy: bool = True,
    ) -> PlannedAction:
        task = self.state.tasks[task_id]
        action = stale_head_action(
            canonical_trustworthy=canonical_trustworthy,
            task_still_valid=task_still_valid,
            independent_safe_work=self._independent_safe_work(task_id),
        )
        if action is RecoveryAction.REPLAN:
            task.expected_target_head = canonical_head
            task.status = TaskStatus.READY
            self.state.deferred_decisions.append({
                "decision_id": f"stale-replan:{task_id}:{self.state.generation}",
                "question": "rebase task intent onto fresh canonical HEAD",
                "selected_safe_default": "replan",
                "affected_scope": task_id,
            })
            return PlannedAction(ActionKind.REPLAN_TASK, task_id, "replanned onto fresh canonical HEAD")
        if action is RecoveryAction.ISOLATE_TASK_CONTINUE:
            # The task was explicitly found invalid on the new canonical state.
            # Mark it BLOCKED so the planner can continue independent READY work
            # instead of trying to replan the same invalid task forever.
            task.status = TaskStatus.BLOCKED
            self.state.blockers.append({
                "task_id": task_id,
                "reason": "task invalidated by intervening target changes",
            })
            return PlannedAction(ActionKind.ISOLATE_TASK_CONTINUE, task_id)
        self.state.terminal_reason = "stale target cannot be safely replanned"
        return PlannedAction(ActionKind.STOP_HARD_UNKNOWN, task_id, self.state.terminal_reason)

    def record_result(
        self,
        *,
        result_id: str,
        task_id: str,
        outcome: TaskOutcome,
        unknown_class: UnknownClass | None = None,
        affects_campaign_authority: bool = False,
    ) -> PlannedAction:
        if not isinstance(result_id, str) or not result_id:
            raise ValueError("result_id must be non-empty")
        if result_id in self.state.processed_result_ids:
            return PlannedAction(ActionKind.NOOP_DUPLICATE, task_id, "duplicate result event")
        task = self.state.tasks[task_id]
        if task.status not in {TaskStatus.RUNNING, TaskStatus.WAITING}:
            raise ValueError("task result does not match an active task")
        self.state.processed_result_ids.add(result_id)

        if outcome is TaskOutcome.DONE:
            task.status = TaskStatus.COMPLETE
            self.state.rounds_completed += 1
            self.state.consecutive_failures = 0
            if task.corrective_for and task.corrective_for in self.state.tasks:
                self.state.tasks[task.corrective_for].status = TaskStatus.COMPLETE
            return PlannedAction(ActionKind.ISOLATE_TASK_CONTINUE, task_id, "task complete; select next task")

        if outcome is TaskOutcome.FAILED:
            self.state.rounds_completed += 1
            self.state.consecutive_failures += 1
            root_id = task.corrective_for or task.task_id
            next_round = task.corrective_round + 1
            if next_round <= self.policy.max_corrective_rounds_per_task:
                # A failed corrective is an attempt in the root task lineage, not a
                # permanent campaign blocker once a later corrective succeeds.
                task.status = (
                    TaskStatus.SUPERSEDED if task.corrective_for else TaskStatus.BLOCKED
                )
                corrective_id = f"{root_id}::corrective::{next_round}"
                if corrective_id in self.state.tasks:
                    raise ValueError("corrective task identity already exists")
                self.state.tasks[corrective_id] = CampaignTask(
                    corrective_id,
                    dependencies=task.dependencies,
                    expected_target_head=task.expected_target_head,
                    corrective_for=root_id,
                    corrective_round=next_round,
                )
                return PlannedAction(
                    ActionKind.CORRECTIVE_TASK_CREATED,
                    corrective_id,
                    f"new corrective task for {root_id}",
                )
            task.status = TaskStatus.BLOCKED
            self.state.blockers.append({"task_id": task_id, "reason": "corrective limit exhausted"})
            return PlannedAction(ActionKind.ISOLATE_TASK_CONTINUE, task_id, "task blocked")

        if outcome is TaskOutcome.BLOCKED:
            task.status = TaskStatus.BLOCKED
            self.state.blockers.append({"task_id": task_id, "reason": "task reported blocked"})
            return PlannedAction(ActionKind.ISOLATE_TASK_CONTINUE, task_id)

        if outcome is not TaskOutcome.UNKNOWN or unknown_class is None:
            raise ValueError("UNKNOWN result requires explicit unknown_class")
        independent = self._independent_safe_work(task_id)
        action = decide_unknown(
            unknown_class,
            policy=self.policy,
            transient_retries_used=task.transient_retries,
            independent_safe_work=independent,
            affects_campaign_authority=affects_campaign_authority,
        )
        if action is RecoveryAction.RETRY_OBSERVATION:
            task.transient_retries += 1
            # WAITING means retry read/status/evidence acquisition. It must not
            # fall back into DISPATCH_TASK and accidentally resend model work.
            task.status = TaskStatus.WAITING
            return PlannedAction(ActionKind.RETRY_OBSERVATION, task_id)
        if action is RecoveryAction.REPLAN:
            task.status = TaskStatus.STALE
            return PlannedAction(ActionKind.REPLAN_TASK, task_id)
        if action is RecoveryAction.ISOLATE_TASK_CONTINUE:
            task.status = TaskStatus.BLOCKED
            self.state.blockers.append({"task_id": task_id, "reason": unknown_class.value})
            return PlannedAction(ActionKind.ISOLATE_TASK_CONTINUE, task_id)
        self.state.terminal_reason = (
            "campaign authority/correctness UNKNOWN"
            if affects_campaign_authority
            else f"{unknown_class.value} with no independent safe work"
        )
        return PlannedAction(ActionKind.STOP_HARD_UNKNOWN, task_id, self.state.terminal_reason)

    def mark_observation_recovered(self, task_id: str) -> None:
        """Return a WAITING task to READY only after safe read/evidence recovery."""
        task = self.state.tasks[task_id]
        if task.status is not TaskStatus.WAITING:
            raise ValueError("task is not waiting for observation recovery")
        task.status = TaskStatus.READY

    def reclaim_after_restart(
        self,
        *,
        ownership_chain_verified: bool,
        old_attempt_stopped_or_fenced: bool,
    ) -> int:
        """Reclaim RUNNING tasks only when duplicate execution has been excluded."""
        if type(ownership_chain_verified) is not bool or type(old_attempt_stopped_or_fenced) is not bool:
            raise ValueError("reclaim evidence must be boolean")
        if not ownership_chain_verified or not old_attempt_stopped_or_fenced:
            return 0
        reclaimed = 0
        for task in self.state.tasks.values():
            if task.status is TaskStatus.RUNNING:
                task.status = TaskStatus.READY
                reclaimed += 1
        if reclaimed:
            self.state.generation += 1
        return reclaimed
