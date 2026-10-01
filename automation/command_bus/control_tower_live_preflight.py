"""Fail-closed production-facing preflight for Control Tower Issue migration.

This module creates no network traffic and performs no GitHub writes.

A live migration plan can be prepared only after every enabled registry lane is
backed by an existing accepted TransitionProjectionResult under the exact same
durable loop_id. The static display registry alone is never sufficient.

The preflight then bridges those verified durable results into the pure Control
Tower model and finally into the prepare-only Issue #33 migration plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .control_tower import (
    ControlTowerModel,
    PerLoopProjectionInput,
    build_control_tower,
    validate_registry,
)
from .control_tower_schedule import SemiAutoScheduleHint
from .control_tower_issue_plan import (
    ControlTowerIssuePlan,
    prepare_control_tower_issue_plan,
)
from .control_tower_registration import (
    ControlTowerRegistrationReadiness,
    assess_registration_readiness,
)
from .control_tower_verified_input import control_tower_input_from_transition
from .loop_status_transition import TransitionProjectionResult


@dataclass(frozen=True)
class ControlTowerLanePresentation:
    target_ref: str | None = None
    durable_event_kind: str | None = None
    schedule_hint: SemiAutoScheduleHint | None = None


@dataclass(frozen=True)
class ControlTowerMigrationPreflight:
    status: str
    stage: str
    reason: str
    registration: ControlTowerRegistrationReadiness
    model: ControlTowerModel | None = None
    issue_plan: ControlTowerIssuePlan | None = None


def prepare_verified_control_tower_migration(
    *,
    registry: dict[str, Any],
    verified_transitions: Mapping[str, TransitionProjectionResult] | None,
    lane_presentation: Mapping[str, ControlTowerLanePresentation] | None,
    generated_at: str,
    issue_readback: dict[str, Any],
    existing_comment_bodies: Iterable[str] = (),
) -> ControlTowerMigrationPreflight:
    """Prepare Issue #33 migration only after durable registration is READY."""

    try:
        entries = validate_registry(registry)
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        blocked = ControlTowerRegistrationReadiness(
            "BLOCKED",
            f"registry invalid: {exc}",
            (),
            (),
            (),
        )
        return ControlTowerMigrationPreflight(
            "BLOCKED",
            "registry",
            blocked.reason,
            blocked,
        )

    registration = assess_registration_readiness(
        registry,
        verified_transitions,
    )
    if registration.status != "READY":
        return ControlTowerMigrationPreflight(
            registration.status,
            "registration",
            registration.reason,
            registration,
        )
    if not registration.ready_loop_ids:
        return ControlTowerMigrationPreflight(
            "NOT_WIRED",
            "registration",
            "no enabled durable Control Tower lanes are registered",
            registration,
        )

    enabled_ids = {entry.loop_id for entry in entries if entry.enabled}

    if lane_presentation is None:
        lane_presentation = {}
    if not isinstance(lane_presentation, Mapping):
        return ControlTowerMigrationPreflight(
            "BLOCKED",
            "presentation",
            "lane_presentation must be a mapping",
            registration,
        )
    if any(not isinstance(key, str) for key in lane_presentation):
        return ControlTowerMigrationPreflight(
            "BLOCKED",
            "presentation",
            "lane_presentation contains a non-string loop id",
            registration,
        )
    extra_presentation = set(lane_presentation) - enabled_ids
    if extra_presentation:
        return ControlTowerMigrationPreflight(
            "BLOCKED",
            "presentation",
            "presentation metadata references unregistered lane(s): "
            + ",".join(sorted(extra_presentation)),
            registration,
        )

    assert verified_transitions is not None
    lane_inputs: dict[str, PerLoopProjectionInput] = {}

    try:
        for entry in entries:
            if not entry.enabled:
                continue
            meta = lane_presentation.get(
                entry.loop_id,
                ControlTowerLanePresentation(),
            )
            if not isinstance(meta, ControlTowerLanePresentation):
                return ControlTowerMigrationPreflight(
                    "BLOCKED",
                    "presentation",
                    f"lane {entry.loop_id} presentation metadata has invalid type",
                    registration,
                )

            lane_input = control_tower_input_from_transition(
                verified_transitions[entry.loop_id],
                target_ref=meta.target_ref,
                durable_event_kind=meta.durable_event_kind,
            )
            if lane_input is None:
                return ControlTowerMigrationPreflight(
                    "NOT_WIRED",
                    "durable_projection",
                    f"lane {entry.loop_id} durable projection is unavailable",
                    registration,
                )

            lane_inputs[entry.loop_id] = PerLoopProjectionInput(
                projection=lane_input.projection,
                generation=lane_input.generation,
                target_ref=lane_input.target_ref,
                last_event_kind=lane_input.last_event_kind,
                last_event_id=lane_input.last_event_id,
                schedule_hint=meta.schedule_hint,
            )

        model = build_control_tower(
            registry,
            lane_inputs,
            generated_at=generated_at,
        )
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return ControlTowerMigrationPreflight(
            "BLOCKED",
            "projection",
            str(exc),
            registration,
        )

    unknown = tuple(
        lane.loop_id for lane in model.lanes if lane.display_state == "UNKNOWN"
    )
    if unknown:
        return ControlTowerMigrationPreflight(
            "BLOCKED",
            "projection",
            "verified lane failed presentation projection: " + ",".join(unknown),
            registration,
        )

    try:
        issue_plan = prepare_control_tower_issue_plan(
            model,
            issue_readback,
            existing_comment_bodies=existing_comment_bodies,
        )
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return ControlTowerMigrationPreflight(
            "UNKNOWN",
            "issue_readback",
            str(exc),
            registration,
            model,
            None,
        )

    return ControlTowerMigrationPreflight(
        "READY",
        "complete",
        "durable registration and Control Tower Issue migration plan verified",
        registration,
        model,
        issue_plan,
    )
