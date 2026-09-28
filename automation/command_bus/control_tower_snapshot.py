"""Strict read-only parser for the Phase 0 Control Tower snapshot.

This module is for presentation consumers such as the future Windows Signal
Companion. It does not derive runtime truth and performs no GitHub/provider
writes or owner/takeover actions.

The only accepted source shape is the bounded JSON object emitted inside the
Control Tower snapshot marker.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .control_tower import SNAPSHOT_END, SNAPSHOT_START
from .control_tower_schedule import SemiAutoScheduleHint, validate_schedule_hint

_MAX_SNAPSHOT_BYTES = 65536
_MAX_ISSUE_BODY_BYTES = 262144

_TOP_LEVEL_KEYS = {"schema_version", "project", "generated_at", "loops"}
_LANE_KEYS = {
    "loop_id",
    "display_name",
    "mode",
    "display_state",
    "controller_kind",
    "worker_kind",
    "generation",
    "target_ref",
    "last_event_kind",
    "last_event_id",
    "schedule_hint",
    "human_action",
    "safe_detail_ref",
    "identity_state",
}
_SCHEDULE_KEYS = {
    "loop_number",
    "acceptance_state",
    "accepted_at",
    "task_size",
    "eta_start",
    "eta_end",
    "eta_state",
}

_MODES = {"SEMI_AUTO", "AUTO"}
_DISPLAY_STATES = {"SEMI_AUTO", "AUTO", "IDLE", "BLOCKED", "STOPPED", "UNKNOWN"}
_CONTROLLERS = {"CHATGPT", "CLAUDE", "WORK", "OTHER"}
_WORKERS = {"JULES", "GEMINI", "CLAUDE", "OTHER"}
_IDENTITY_STATES = {"PLACEHOLDER", "DURABLE"}

_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TARGET_REF = re.compile(r"^(issue|pr):[1-9][0-9]{0,9}$")
_EVENT_KIND = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def extract_control_tower_snapshot(issue_body: str) -> dict[str, Any]:
    """Extract exactly one bounded v1 snapshot from an Issue body."""
    if not isinstance(issue_body, str):
        raise ValueError("Issue body must be a string")
    if len(issue_body.encode("utf-8")) > _MAX_ISSUE_BODY_BYTES:
        raise ValueError("Issue body exceeds bounded snapshot-reader maximum")

    count = issue_body.count(SNAPSHOT_START)
    if count != 1:
        raise ValueError("Issue body must contain exactly one Control Tower snapshot marker")

    start = issue_body.index(SNAPSHOT_START) + len(SNAPSHOT_START)
    end = issue_body.find(SNAPSHOT_END, start)
    if end < 0:
        raise ValueError("Control Tower snapshot closing marker is missing")
    if issue_body.find(SNAPSHOT_END, end + len(SNAPSHOT_END)) >= 0:
        raise ValueError("Issue body contains multiple snapshot closing markers")

    raw = issue_body[start:end].strip()
    return parse_control_tower_snapshot_json(raw)


def parse_control_tower_snapshot_json(raw: str) -> dict[str, Any]:
    """Parse and strictly validate a v1 Control Tower machine snapshot."""
    if not isinstance(raw, str):
        raise ValueError("Control Tower snapshot must be a JSON string")
    if len(raw.encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
        raise ValueError("Control Tower snapshot exceeds bounded maximum")

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Control Tower snapshot JSON is invalid") from exc
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_KEYS:
        raise ValueError("Control Tower snapshot top-level shape is invalid")
    if value["schema_version"] != 1:
        raise ValueError("unsupported Control Tower snapshot schema")
    if value["project"] != "phase0":
        raise ValueError("unexpected Control Tower snapshot project")
    _parse_time(value["generated_at"], "generated_at")

    loops = value["loops"]
    if not isinstance(loops, list) or len(loops) > 8:
        raise ValueError("Control Tower snapshot loops are invalid or exceed bounded maximum")

    seen: set[str] = set()
    for lane in loops:
        _validate_lane(lane, seen)
    return value


def _validate_lane(lane: Any, seen: set[str]) -> None:
    if not isinstance(lane, dict) or set(lane) != _LANE_KEYS:
        raise ValueError("Control Tower snapshot lane shape is invalid")

    loop_id = lane["loop_id"]
    if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
        raise ValueError("invalid snapshot loop_id")
    if loop_id in seen:
        raise ValueError("duplicate snapshot loop_id")
    seen.add(loop_id)

    display_name = lane["display_name"]
    if (
        not isinstance(display_name, str)
        or not display_name
        or len(display_name) > 64
        or "\n" in display_name
        or "\r" in display_name
        or "://" in display_name
    ):
        raise ValueError("invalid snapshot display_name")

    if lane["mode"] not in _MODES:
        raise ValueError("invalid snapshot mode")
    if lane["display_state"] not in _DISPLAY_STATES:
        raise ValueError("invalid snapshot display_state")
    if lane["controller_kind"] not in _CONTROLLERS:
        raise ValueError("invalid snapshot controller_kind")
    if lane["worker_kind"] not in _WORKERS:
        raise ValueError("invalid snapshot worker_kind")
    if lane["identity_state"] not in _IDENTITY_STATES:
        raise ValueError("invalid snapshot identity_state")

    generation = lane["generation"]
    if generation is not None and (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise ValueError("invalid snapshot generation")

    _validate_optional_ref(lane["target_ref"], "target_ref")
    _validate_optional_event_kind(lane["last_event_kind"])
    _validate_optional_event_id(lane["last_event_id"])

    human_action = lane["human_action"]
    if (
        not isinstance(human_action, str)
        or not human_action
        or len(human_action) > 64
        or "\n" in human_action
        or "\r" in human_action
        or "://" in human_action
    ):
        raise ValueError("invalid snapshot human_action")

    safe_detail_ref = lane["safe_detail_ref"]
    if (
        not isinstance(safe_detail_ref, str)
        or not _TARGET_REF.fullmatch(safe_detail_ref)
        or "://" in safe_detail_ref
    ):
        raise ValueError("invalid snapshot safe_detail_ref")

    schedule = lane["schedule_hint"]
    if schedule is not None:
        if lane["mode"] != "SEMI_AUTO":
            raise ValueError("snapshot schedule_hint is allowed only for SEMI_AUTO mode")
        if not isinstance(schedule, dict) or set(schedule) != _SCHEDULE_KEYS:
            raise ValueError("snapshot schedule_hint shape is invalid")
        try:
            hint = SemiAutoScheduleHint(**schedule)
            validate_schedule_hint(hint)
        except (TypeError, ValueError, AssertionError) as exc:
            raise ValueError("snapshot schedule_hint is invalid") from exc

    # Machine snapshot is public presentation data. Do not allow URL-bearing
    # values to appear through fields not otherwise covered above.
    if "://" in json.dumps(lane, ensure_ascii=False):
        raise ValueError("snapshot lane contains a URL-like value")


def _validate_optional_ref(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _TARGET_REF.fullmatch(value) or "://" in value:
        raise ValueError(f"invalid snapshot {field}")


def _validate_optional_event_kind(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _EVENT_KIND.fullmatch(value):
        raise ValueError("invalid snapshot last_event_kind")


def _validate_optional_event_id(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not _EVENT_ID.fullmatch(value):
        raise ValueError("invalid snapshot last_event_id")


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"snapshot {field} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"snapshot {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"snapshot {field} must include timezone")
    return parsed
