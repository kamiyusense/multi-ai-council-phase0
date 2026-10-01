"""Bind verified Jules session timing to Control Tower Semi-Auto schedule hints.

This bridge is the preferred production-facing constructor for Semi-Auto timing
presentation. Callers do not provide accepted_at directly. A verified timestamp
comes only from JulesSessionAcceptance, which is derived from the provider
Create Session response createTime.

If no verified acceptance record is available, the bridge returns an UNKNOWN
schedule with no accepted/ETA timestamps.
"""
from __future__ import annotations

from .control_tower_schedule import (
    SemiAutoScheduleHint,
    build_semi_auto_schedule_hint,
)
from .jules_session_acceptance import (
    JulesSessionAcceptance,
    JulesSessionTimingReadback,
    verify_timing_readback_matches_acceptance,
)


def build_jules_semi_auto_schedule_hint(
    *,
    acceptance: JulesSessionAcceptance | None,
    loop_number: int | None,
    task_size: str | None,
    eta_start: str | None,
    eta_end: str | None,
    now: str,
    timing_readback: JulesSessionTimingReadback | None = None,
) -> SemiAutoScheduleHint:
    """Create presentation timing without caller-supplied accepted_at."""
    if acceptance is None:
        if timing_readback is not None:
            raise ValueError("timing readback cannot establish acceptance without Create Session evidence")
        if eta_start is not None or eta_end is not None:
            raise ValueError("unverified Jules acceptance forbids ETA timestamps")
        return build_semi_auto_schedule_hint(
            loop_number=loop_number,
            acceptance_state="UNKNOWN",
            accepted_at=None,
            task_size=task_size,
            eta_start=None,
            eta_end=None,
            now=now,
        )

    if not isinstance(acceptance, JulesSessionAcceptance):
        raise ValueError("JulesSessionAcceptance is required")
    if timing_readback is not None:
        verify_timing_readback_matches_acceptance(acceptance, timing_readback)

    return build_semi_auto_schedule_hint(
        loop_number=loop_number,
        acceptance_state="VERIFIED",
        accepted_at=acceptance.accepted_at_jst,
        task_size=task_size,
        eta_start=eta_start,
        eta_end=eta_end,
        now=now,
    )
