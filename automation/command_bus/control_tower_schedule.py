"""Presentation-only schedule hints for Control Tower Semi-Auto lanes.

These hints help humans know when to check back. They are deliberately excluded
from runtime correctness, owner validity, provider liveness, timeout, failure,
and takeover decisions.

A verified acceptance time means the caller has independently confirmed that
Jules accepted the session. This module does not perform that verification
itself and never derives acceptance from command creation time, Action queue
time, commit time, or chat time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_TASK_SIZES = {"SHORT", "MEDIUM", "LONG"}
_ACCEPTANCE_STATES = {"VERIFIED", "UNKNOWN"}
_ETA_STATES = {"UNKNOWN", "BEFORE_WINDOW", "WITHIN_WINDOW", "OVERDUE"}
_JST = timezone(timedelta(hours=9))

_TASK_SIZE_LABELS = {
    "SHORT": "短",
    "MEDIUM": "中",
    "LONG": "長",
}


@dataclass(frozen=True)
class SemiAutoScheduleHint:
    loop_number: int | None
    acceptance_state: str
    accepted_at: str | None
    task_size: str | None
    eta_start: str | None
    eta_end: str | None
    eta_state: str

    @property
    def task_size_label(self) -> str:
        if self.task_size is None:
            return "UNKNOWN"
        return _TASK_SIZE_LABELS[self.task_size]


def build_semi_auto_schedule_hint(
    *,
    loop_number: int | None,
    acceptance_state: str,
    accepted_at: str | None,
    task_size: str | None,
    eta_start: str | None,
    eta_end: str | None,
    now: str,
) -> SemiAutoScheduleHint:
    """Build a bounded display hint without touching runtime state.

    acceptance_state=VERIFIED requires a JST Jules-session-accepted timestamp
    and a complete JST ETA window. acceptance_state=UNKNOWN forbids all three
    timestamps so the caller cannot silently invent them.
    """
    _validate_loop_number(loop_number)
    if acceptance_state not in _ACCEPTANCE_STATES:
        raise ValueError("invalid semi-auto acceptance_state")
    if task_size is not None and task_size not in _TASK_SIZES:
        raise ValueError("invalid semi-auto task_size")
    now_dt = _parse_time(now, "now")

    if acceptance_state == "UNKNOWN":
        if accepted_at is not None or eta_start is not None or eta_end is not None:
            raise ValueError("UNKNOWN Jules acceptance forbids accepted_at and ETA timestamps")
        return SemiAutoScheduleHint(
            loop_number=loop_number,
            acceptance_state="UNKNOWN",
            accepted_at=None,
            task_size=task_size,
            eta_start=None,
            eta_end=None,
            eta_state="UNKNOWN",
        )

    accepted_dt = _parse_jst(accepted_at, "accepted_at")
    eta_start_dt = _parse_jst(eta_start, "eta_start")
    eta_end_dt = _parse_jst(eta_end, "eta_end")
    if eta_start_dt < accepted_dt:
        raise ValueError("eta_start cannot precede Jules session acceptance")
    if eta_end_dt < eta_start_dt:
        raise ValueError("eta_end cannot precede eta_start")
    if task_size is None:
        raise ValueError("verified semi-auto schedule requires task_size")
    if loop_number is None:
        raise ValueError("verified semi-auto schedule requires loop_number")

    now_jst = now_dt.astimezone(_JST)
    if now_jst < eta_start_dt:
        eta_state = "BEFORE_WINDOW"
    elif now_jst <= eta_end_dt:
        eta_state = "WITHIN_WINDOW"
    else:
        eta_state = "OVERDUE"

    return SemiAutoScheduleHint(
        loop_number=loop_number,
        acceptance_state="VERIFIED",
        accepted_at=_canonical(accepted_dt),
        task_size=task_size,
        eta_start=_canonical(eta_start_dt),
        eta_end=_canonical(eta_end_dt),
        eta_state=eta_state,
    )


def schedule_snapshot(hint: SemiAutoScheduleHint | None) -> dict[str, Any] | None:
    if hint is None:
        return None
    validate_schedule_hint(hint)
    return {
        "loop_number": hint.loop_number,
        "acceptance_state": hint.acceptance_state,
        "accepted_at": hint.accepted_at,
        "task_size": hint.task_size,
        "eta_start": hint.eta_start,
        "eta_end": hint.eta_end,
        "eta_state": hint.eta_state,
    }


def schedule_compact_text(hint: SemiAutoScheduleHint | None) -> str:
    if hint is None:
        return "-"
    validate_schedule_hint(hint)
    size = hint.task_size_label
    loop_text = f"Loop {hint.loop_number:03d}" if hint.loop_number is not None else "Loop UNKNOWN"
    if hint.acceptance_state == "UNKNOWN":
        return f"{loop_text} / {size} / 投入時刻 UNKNOWN"

    accepted = _hhmm(hint.accepted_at)
    eta_start = _hhmm(hint.eta_start)
    eta_end = _hhmm(hint.eta_end)
    text = f"{loop_text} / {size} / {accepted} → {eta_start}–{eta_end}"
    if hint.eta_state == "OVERDUE":
        text += " / ⏱️ ETA exceeded"
    return text


def validate_schedule_hint(hint: SemiAutoScheduleHint) -> None:
    if not isinstance(hint, SemiAutoScheduleHint):
        raise ValueError("SemiAutoScheduleHint is required")
    rebuilt = build_semi_auto_schedule_hint(
        loop_number=hint.loop_number,
        acceptance_state=hint.acceptance_state,
        accepted_at=hint.accepted_at,
        task_size=hint.task_size,
        eta_start=hint.eta_start,
        eta_end=hint.eta_end,
        now=_now_for_state_validation(hint),
    )
    if rebuilt != hint:
        raise ValueError("semi-auto schedule hint is not canonical")


def _now_for_state_validation(hint: SemiAutoScheduleHint) -> str:
    if hint.acceptance_state == "UNKNOWN":
        return "2000-01-01T00:00:00+00:00"
    assert hint.eta_start is not None
    assert hint.eta_end is not None
    start = _parse_jst(hint.eta_start, "eta_start")
    end = _parse_jst(hint.eta_end, "eta_end")
    if hint.eta_state == "BEFORE_WINDOW":
        probe = start - timedelta(seconds=1)
    elif hint.eta_state == "WITHIN_WINDOW":
        probe = start
    elif hint.eta_state == "OVERDUE":
        probe = end + timedelta(seconds=1)
    else:
        raise ValueError("invalid verified eta_state")
    return probe.isoformat()


def _validate_loop_number(value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 999999:
        raise ValueError("invalid semi-auto loop_number")


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed


def _parse_jst(value: Any, field: str) -> datetime:
    parsed = _parse_time(value, field)
    if parsed.utcoffset() != timedelta(hours=9):
        raise ValueError(f"{field} must be JST (+09:00)")
    return parsed


def _canonical(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _hhmm(value: str | None) -> str:
    if value is None:
        return "UNKNOWN"
    return _parse_jst(value, "display time").strftime("%H:%M")
