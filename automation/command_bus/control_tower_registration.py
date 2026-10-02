"""Fail-closed registration readiness for Control Tower runtime lanes.

This module does not discover durable loops and does not trust registry IDs by
themselves. READY requires an existing TransitionProjectionResult for every
enabled registry lane, keyed by the same durable loop_id.

It performs no GitHub reads/writes, provider/model execution, or Issue mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .control_tower import validate_registry
from .loop_status_transition import TransitionProjectionResult

_ACCEPTED_TRANSITION_STATUSES = {"VALID", "TERMINAL", "BLOCKED"}


@dataclass(frozen=True)
class ControlTowerRegistrationReadiness:
    status: str
    reason: str
    ready_loop_ids: tuple[str, ...]
    missing_loop_ids: tuple[str, ...]
    unknown_loop_ids: tuple[str, ...]
    placeholder_loop_ids: tuple[str, ...] = ()


def assess_registration_readiness(
    registry: dict,
    verified_transitions: Mapping[str, TransitionProjectionResult] | None,
) -> ControlTowerRegistrationReadiness:
    """Check whether enabled registry lanes have verified durable identities.

    Registry loop_id values are never sufficient by themselves. Each enabled
    entry must have an existing durable TransitionProjectionResult whose
    projection.loop_id exactly matches the registry loop_id.
    """
    entries = validate_registry(registry)
    enabled = tuple(entry for entry in entries if entry.enabled)
    enabled_ids = tuple(entry.loop_id for entry in enabled)
    placeholder_ids = tuple(
        entry.loop_id for entry in enabled if entry.identity_state == "PLACEHOLDER"
    )
    if placeholder_ids:
        return ControlTowerRegistrationReadiness(
            "NOT_WIRED",
            "enabled Control Tower lane identity is still PLACEHOLDER: "
            + ",".join(placeholder_ids),
            (),
            (),
            (),
            placeholder_ids,
        )

    if verified_transitions is None:
        return ControlTowerRegistrationReadiness(
            "NOT_WIRED",
            "verified durable transition inventory is unavailable",
            (),
            enabled_ids,
            (),
        )
    if not isinstance(verified_transitions, Mapping):
        return ControlTowerRegistrationReadiness(
            "BLOCKED",
            "verified transition inventory must be a mapping",
            (),
            enabled_ids,
            (),
        )

    extra = set(verified_transitions) - set(enabled_ids)
    if any(not isinstance(key, str) for key in verified_transitions):
        return ControlTowerRegistrationReadiness(
            "BLOCKED",
            "transition inventory contains a non-string loop id",
            (),
            enabled_ids,
            (),
        )

    ready = []
    missing = []
    unknown = []

    for entry in enabled:
        result = verified_transitions.get(entry.loop_id)
        if result is None:
            missing.append(entry.loop_id)
            continue
        if not isinstance(result, TransitionProjectionResult):
            return ControlTowerRegistrationReadiness(
                "BLOCKED",
                f"lane {entry.loop_id} is not backed by TransitionProjectionResult",
                tuple(ready),
                tuple(missing),
                tuple(unknown),
            )
        if result.status == "UNKNOWN":
            unknown.append(entry.loop_id)
            continue
        if result.status not in _ACCEPTED_TRANSITION_STATUSES:
            return ControlTowerRegistrationReadiness(
                "BLOCKED",
                f"lane {entry.loop_id} has unsupported transition status {result.status}",
                tuple(ready),
                tuple(missing),
                tuple(unknown),
            )
        if result.projection is None or result.owner_decision is None:
            return ControlTowerRegistrationReadiness(
                "BLOCKED",
                f"lane {entry.loop_id} has incomplete accepted durable projection",
                tuple(ready),
                tuple(missing),
                tuple(unknown),
            )
        if result.projection.loop_id != entry.loop_id:
            return ControlTowerRegistrationReadiness(
                "BLOCKED",
                f"lane {entry.loop_id} durable projection loop_id mismatch",
                tuple(ready),
                tuple(missing),
                tuple(unknown),
            )
        ready.append(entry.loop_id)

    if missing or unknown:
        parts = []
        if missing:
            parts.append("missing=" + ",".join(missing))
        if unknown:
            parts.append("unknown=" + ",".join(unknown))
        if extra:
            parts.append("unregistered verified transitions ignored=" + ",".join(sorted(extra)))
        return ControlTowerRegistrationReadiness(
            "NOT_WIRED",
            "; ".join(parts),
            tuple(ready),
            tuple(missing),
            tuple(unknown),
        )

    reason = "all enabled registry lanes are backed by existing durable transition projections"
    if extra:
        reason += "; unregistered verified transitions ignored=" + ",".join(sorted(extra))
    return ControlTowerRegistrationReadiness(
        "READY",
        reason,
        tuple(ready),
        (),
        (),
    )


def assess_lane_registration_readiness(
    registry: dict,
    loop_id: str,
    verified_transition: TransitionProjectionResult | None,
) -> ControlTowerRegistrationReadiness:
    """Verify one already-adopted durable lane without weakening global readiness.

    This is for the per-lane adoption transaction only. Other enabled lanes may
    still be PLACEHOLDER. Issue #33 migration must continue to use
    assess_registration_readiness(), which requires every enabled lane.
    """
    try:
        entries = validate_registry(registry)
    except (ValueError, TypeError, KeyError, AssertionError) as exc:
        return ControlTowerRegistrationReadiness(
            "BLOCKED", f"registry invalid: {exc}", (), (), ()
        )
    if not isinstance(loop_id, str) or not loop_id:
        return ControlTowerRegistrationReadiness(
            "BLOCKED", "lane loop_id must be a non-empty string", (), (), ()
        )
    matches = tuple(entry for entry in entries if entry.loop_id == loop_id)
    if len(matches) != 1:
        return ControlTowerRegistrationReadiness(
            "BLOCKED", f"lane {loop_id} is not uniquely registered", (), (), ()
        )
    entry = matches[0]
    if not entry.enabled:
        return ControlTowerRegistrationReadiness(
            "BLOCKED", f"lane {loop_id} is disabled", (), (), ()
        )
    if entry.identity_state != "DURABLE":
        return ControlTowerRegistrationReadiness(
            "NOT_WIRED",
            f"lane {loop_id} identity is still PLACEHOLDER",
            (), (), (), (loop_id,),
        )
    if verified_transition is None:
        return ControlTowerRegistrationReadiness(
            "NOT_WIRED",
            f"lane {loop_id} durable transition is unavailable",
            (), (loop_id,), (),
        )
    if not isinstance(verified_transition, TransitionProjectionResult):
        return ControlTowerRegistrationReadiness(
            "BLOCKED",
            f"lane {loop_id} is not backed by TransitionProjectionResult",
            (), (), (),
        )
    if verified_transition.status == "UNKNOWN":
        return ControlTowerRegistrationReadiness(
            "NOT_WIRED",
            f"lane {loop_id} durable transition is UNKNOWN",
            (), (), (loop_id,),
        )
    if verified_transition.status not in _ACCEPTED_TRANSITION_STATUSES:
        return ControlTowerRegistrationReadiness(
            "BLOCKED",
            f"lane {loop_id} has unsupported transition status {verified_transition.status}",
            (), (), (),
        )
    if verified_transition.projection is None or verified_transition.owner_decision is None:
        return ControlTowerRegistrationReadiness(
            "BLOCKED",
            f"lane {loop_id} has incomplete accepted durable projection",
            (), (), (),
        )
    if verified_transition.projection.loop_id != loop_id:
        return ControlTowerRegistrationReadiness(
            "BLOCKED",
            f"lane {loop_id} durable projection loop_id mismatch",
            (), (), (),
        )
    return ControlTowerRegistrationReadiness(
        "READY",
        f"lane {loop_id} is DURABLE and backed by an accepted transition projection",
        (loop_id,), (), (),
    )
