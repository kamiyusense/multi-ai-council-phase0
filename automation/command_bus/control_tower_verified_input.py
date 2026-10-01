"""Bridge verified per-loop durable transition results into Control Tower input.

This adapter does not re-run owner/liveness logic. It accepts only the existing
TransitionProjectionResult and transfers its already-projected StatusProjection
into the Control Tower presentation model.

UNKNOWN or incomplete transition results do not become healthy presentation
states; they remain unavailable so the Control Tower isolates that lane as
UNKNOWN.
"""
from __future__ import annotations

import re
from typing import Any

from .control_tower import PerLoopProjectionInput
from .loop_status_transition import TransitionProjectionResult

_TARGET_REF = re.compile(r"^(issue|pr):[1-9][0-9]{0,9}$")
_EVENT_KIND = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_ACCEPTED = {"VALID", "TERMINAL", "BLOCKED"}


def control_tower_input_from_transition(
    result: TransitionProjectionResult,
    *,
    target_ref: str | None,
    durable_event_kind: str | None = None,
) -> PerLoopProjectionInput | None:
    if not isinstance(result, TransitionProjectionResult):
        raise ValueError("TransitionProjectionResult is required")
    if result.status == "UNKNOWN":
        return None
    if result.status not in _ACCEPTED:
        raise ValueError("unsupported durable transition result status")
    if result.projection is None:
        raise ValueError("accepted durable transition result requires projection")
    if result.owner_decision is None:
        raise ValueError("accepted durable transition result requires owner decision")

    generation = result.owner_decision.generation
    if generation is not None and (
        isinstance(generation, bool) or not isinstance(generation, int) or generation < 1
    ):
        raise ValueError("invalid owner decision generation")

    if target_ref is not None and (
        not isinstance(target_ref, str)
        or not _TARGET_REF.fullmatch(target_ref)
        or "://" in target_ref
    ):
        raise ValueError("target_ref must be a bounded safe reference")

    if durable_event_kind is not None and (
        not isinstance(durable_event_kind, str)
        or not _EVENT_KIND.fullmatch(durable_event_kind)
    ):
        raise ValueError("durable_event_kind must be a bounded event label")

    event_id = result.event_id
    if event_id is not None and not isinstance(event_id, str):
        raise ValueError("durable transition event_id must be a string or null")

    return PerLoopProjectionInput(
        projection=result.projection,
        generation=generation,
        target_ref=target_ref,
        last_event_kind=durable_event_kind,
        last_event_id=event_id,
    )
