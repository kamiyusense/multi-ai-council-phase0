"""Configurable safety/continuation policy for the Symphony autonomous-loop line.

This module intentionally contains no provider or GitHub transport. It is the
policy layer that keeps the strict one-shot proof contract separate from the
long-running autonomous product target.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class UnknownClass(str, Enum):
    TRANSIENT_UNKNOWN = "TRANSIENT_UNKNOWN"
    RECOVERABLE_UNKNOWN = "RECOVERABLE_UNKNOWN"
    TASK_BLOCKED = "TASK_BLOCKED"
    HARD_UNKNOWN = "HARD_UNKNOWN"


class RecoveryAction(str, Enum):
    RETRY_OBSERVATION = "RETRY_OBSERVATION"
    REPLAN = "REPLAN"
    ISOLATE_TASK_CONTINUE = "ISOLATE_TASK_CONTINUE"
    STOP_CAMPAIGN = "STOP_CAMPAIGN"


class QuotaState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNKNOWN = "UNKNOWN"
    EXHAUSTED = "EXHAUSTED"


def _positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _positive_number(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class AutonomousRuntimePolicy:
    """Runtime valves shared by proof, hardened, and upstream-reference profiles."""

    profile: str
    max_rounds: int | None
    max_turns_per_task: int
    max_model_starts_per_task: int
    max_corrective_rounds_per_task: int
    max_transient_retries: int
    max_consecutive_failures: int
    max_concurrent_agents: int
    idle_observation_interval_seconds: float
    task_timeout_seconds: float
    campaign_timeout_seconds: float | None
    blind_write_retries: int = 0
    subscription_only: bool = True
    allow_metered_api_fallback: bool = False
    allow_paid_credit_fallback: bool = False
    allow_provider_fallback: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("profile must be non-empty text")
        if self.max_rounds is not None:
            _positive_int("max_rounds", self.max_rounds)
        _positive_int("max_turns_per_task", self.max_turns_per_task)
        _positive_int("max_model_starts_per_task", self.max_model_starts_per_task)
        _non_negative_int("max_corrective_rounds_per_task", self.max_corrective_rounds_per_task)
        _non_negative_int("max_transient_retries", self.max_transient_retries)
        _positive_int("max_consecutive_failures", self.max_consecutive_failures)
        _positive_int("max_concurrent_agents", self.max_concurrent_agents)
        _positive_number("idle_observation_interval_seconds", self.idle_observation_interval_seconds)
        _positive_number("task_timeout_seconds", self.task_timeout_seconds)
        if self.campaign_timeout_seconds is not None:
            _positive_number("campaign_timeout_seconds", self.campaign_timeout_seconds)
        _non_negative_int("blind_write_retries", self.blind_write_retries)
        if self.blind_write_retries != 0:
            raise ValueError("ambiguous side-effect writes must never be blindly retried")
        for name in (
            "subscription_only", "allow_metered_api_fallback",
            "allow_paid_credit_fallback", "allow_provider_fallback",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        if self.subscription_only and (
            self.allow_metered_api_fallback
            or self.allow_paid_credit_fallback
            or self.allow_provider_fallback
        ):
            raise ValueError("subscription-only policy forbids paid/metered/provider fallback")


STRICT_PROOF_POLICY = AutonomousRuntimePolicy(
    profile="STRICT_PROOF_V1",
    max_rounds=1,
    max_turns_per_task=1,
    max_model_starts_per_task=1,
    max_corrective_rounds_per_task=0,
    max_transient_retries=0,
    max_consecutive_failures=1,
    max_concurrent_agents=1,
    idle_observation_interval_seconds=30,
    task_timeout_seconds=900,
    campaign_timeout_seconds=900,
)

HARDENED_AUTONOMOUS_POLICY = AutonomousRuntimePolicy(
    profile="NEW_CHINPONEY_HARDENED_V1",
    max_rounds=20,
    max_turns_per_task=20,
    max_model_starts_per_task=3,
    max_corrective_rounds_per_task=3,
    max_transient_retries=3,
    max_consecutive_failures=5,
    max_concurrent_agents=1,
    idle_observation_interval_seconds=30,
    task_timeout_seconds=3600,
    campaign_timeout_seconds=12 * 3600,
)

UPSTREAM_SYMPHONY_REFERENCE_POLICY = AutonomousRuntimePolicy(
    profile="UPSTREAM_SYMPHONY_REFERENCE_V1",
    max_rounds=None,
    max_turns_per_task=20,
    max_model_starts_per_task=20,
    max_corrective_rounds_per_task=3,
    max_transient_retries=3,
    max_consecutive_failures=10,
    max_concurrent_agents=10,
    idle_observation_interval_seconds=30,
    task_timeout_seconds=3600,
    campaign_timeout_seconds=None,
)


def decide_unknown(
    kind: UnknownClass,
    *,
    policy: AutonomousRuntimePolicy,
    transient_retries_used: int = 0,
    independent_safe_work: bool,
    affects_campaign_authority: bool = False,
) -> RecoveryAction:
    """Choose the continuation action without guessing the UNKNOWN cause."""
    if not isinstance(kind, UnknownClass):
        raise ValueError("UNKNOWN must be explicitly classified")
    _non_negative_int("transient_retries_used", transient_retries_used)
    if affects_campaign_authority:
        return RecoveryAction.STOP_CAMPAIGN
    if kind is UnknownClass.TRANSIENT_UNKNOWN:
        if transient_retries_used < policy.max_transient_retries:
            return RecoveryAction.RETRY_OBSERVATION
        return (RecoveryAction.ISOLATE_TASK_CONTINUE
                if independent_safe_work else RecoveryAction.STOP_CAMPAIGN)
    if kind is UnknownClass.RECOVERABLE_UNKNOWN:
        return RecoveryAction.REPLAN
    if kind in {UnknownClass.TASK_BLOCKED, UnknownClass.HARD_UNKNOWN}:
        return (RecoveryAction.ISOLATE_TASK_CONTINUE
                if independent_safe_work else RecoveryAction.STOP_CAMPAIGN)
    raise AssertionError("unreachable UNKNOWN class")


def stale_head_action(
    *,
    canonical_trustworthy: bool,
    task_still_valid: bool,
    independent_safe_work: bool,
) -> RecoveryAction:
    """Treat stale HEAD as a replan condition unless canonical lineage is lost."""
    if type(canonical_trustworthy) is not bool or type(task_still_valid) is not bool:
        raise ValueError("stale HEAD flags must be boolean")
    if not canonical_trustworthy:
        return RecoveryAction.STOP_CAMPAIGN
    if task_still_valid:
        return RecoveryAction.REPLAN
    return (RecoveryAction.ISOLATE_TASK_CONTINUE
            if independent_safe_work else RecoveryAction.STOP_CAMPAIGN)


def model_work_allowed(quota_state: QuotaState, policy: AutonomousRuntimePolicy) -> bool:
    """An unreadable remaining allowance is not the same as exhausted quota."""
    if not isinstance(quota_state, QuotaState):
        raise ValueError("quota state must be explicit")
    if policy.subscription_only and quota_state is QuotaState.EXHAUSTED:
        return False
    return quota_state is not QuotaState.EXHAUSTED
