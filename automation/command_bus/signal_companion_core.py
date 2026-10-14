"""Pure tray-state and notification-dedupe logic for Windows Signal Companion v1 (SF-12).

Spec: docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md sections 8.2, 8.4, 8.5, 8.6.

This module provides standard-library only, pure presentation logic:
- tray_state: evaluates Control Tower snapshot to determine system tray color and reason code.
- notification_plan: evaluates Control Tower snapshot against seen notification state to determine desktop notifications to issue and updated seen state.

Fail-passive semantics: invalid or malformed snapshots never raise exceptions.
Zero side-effects: no network calls, no file writes, no subprocesses, no system wall-clock access.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from .control_tower_snapshot import parse_control_tower_snapshot_json


class TrayState(NamedTuple):
    color: str
    reason_code: str


@dataclass(frozen=True)
class CompanionNotification:
    kind: str  # "TURN_COMPLETE" or "HUMAN_NEEDED"
    loop_id: str
    display_name: str
    event_id: str
    event_kind: str | None
    display_state: str
    human_action: str
    target_ref: str | None
    safe_detail_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "loop_id": self.loop_id,
            "display_name": self.display_name,
            "event_id": self.event_id,
            "event_kind": self.event_kind,
            "display_state": self.display_state,
            "human_action": self.human_action,
            "target_ref": self.target_ref,
            "safe_detail_ref": self.safe_detail_ref,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


def tray_state(
    snapshot_json: str | dict[str, Any] | None,
    now: datetime | None,
    max_age_seconds: int = 600,
) -> TrayState:
    """Determine tray icon color and reason code from a Control Tower snapshot.

    Priority order:
    1. RED: Any unresolved HUMAN_NEEDED or BLOCKED lane.
    2. PURPLE: Any AUTO lane active with no blocker.
    3. GREEN: Only SEMI_AUTO active with no AUTO or blocker.
    4. YELLOW: All enabled lanes idle.
    5. BLACK: All lanes stopped.
    6. WHITE: Snapshot missing, stale, or malformed.
    """
    if snapshot_json is None:
        return TrayState("WHITE", "SNAPSHOT_MISSING")

    if not isinstance(now, datetime):
        return TrayState("WHITE", "INVALID_NOW")

    if now.tzinfo is None or now.utcoffset() is None:
        return TrayState("WHITE", "INVALID_NOW")

    try:
        if isinstance(snapshot_json, str):
            snapshot = parse_control_tower_snapshot_json(snapshot_json)
        elif isinstance(snapshot_json, dict):
            raw = json.dumps(snapshot_json)
            snapshot = parse_control_tower_snapshot_json(raw)
        else:
            return TrayState("WHITE", "SNAPSHOT_MALFORMED")
    except Exception:
        return TrayState("WHITE", "SNAPSHOT_MALFORMED")

    # Staleness check
    try:
        gen_str = snapshot["generated_at"]
        gen_time = datetime.fromisoformat(gen_str.replace("Z", "+00:00"))
        if gen_time.tzinfo is None or gen_time.utcoffset() is None:
            return TrayState("WHITE", "SNAPSHOT_MALFORMED")

        age = (now - gen_time).total_seconds()
        if age < 0 or age > max_age_seconds:
            return TrayState("WHITE", "SNAPSHOT_STALE")
    except Exception:
        return TrayState("WHITE", "SNAPSHOT_MALFORMED")

    loops = snapshot.get("loops", [])
    if not isinstance(loops, list):
        return TrayState("WHITE", "SNAPSHOT_MALFORMED")

    # Priority 1: RED (any unresolved HUMAN_NEEDED or BLOCKED)
    for lane in loops:
        if not isinstance(lane, dict):
            continue
        d_state = lane.get("display_state")
        e_kind = lane.get("last_event_kind")
        h_action = lane.get("human_action")
        if (
            d_state == "BLOCKED"
            or e_kind == "HUMAN_NEEDED"
            or (isinstance(h_action, str) and h_action != "NONE")
        ):
            return TrayState("RED", "HUMAN_NEEDED")

    # Priority 2: PURPLE (AUTO active, no blocker)
    for lane in loops:
        if not isinstance(lane, dict):
            continue
        d_state = lane.get("display_state")
        if d_state == "AUTO":
            return TrayState("PURPLE", "AUTO_ACTIVE")

    # Priority 3: GREEN (only SEMI_AUTO active)
    for lane in loops:
        if not isinstance(lane, dict):
            continue
        d_state = lane.get("display_state")
        if d_state == "SEMI_AUTO":
            return TrayState("GREEN", "SEMI_AUTO_ACTIVE")

    # Priority 4: YELLOW (all enabled lanes idle)
    has_idle = any(
        isinstance(lane, dict) and lane.get("display_state") == "IDLE"
        for lane in loops
    )
    if has_idle:
        return TrayState("YELLOW", "ALL_IDLE")

    # Priority 5: BLACK (all stopped)
    all_stopped = all(
        isinstance(lane, dict) and lane.get("display_state") == "STOPPED"
        for lane in loops
    )
    if all_stopped:
        return TrayState("BLACK", "ALL_STOPPED")

    return TrayState("WHITE", "SNAPSHOT_UNKNOWN")


def notification_plan(
    snapshot_json: str | dict[str, Any] | None,
    seen_state: dict[str, Any] | set[str] | list[str] | None,
    first_run: bool = False,
) -> tuple[list[CompanionNotification], dict[str, Any]]:
    """Determine notifications to show and updated seen_state.

    Only two notification classes: TURN_COMPLETE (quiet) and HUMAN_NEEDED (strong).
    Fail-passive: malformed or missing snapshot returns no notifications and unchanged seen_state.
    """
    unchanged_seen_state, seen_ids = _normalize_seen_state(seen_state)

    if snapshot_json is None:
        return [], unchanged_seen_state

    try:
        if isinstance(snapshot_json, str):
            snapshot = parse_control_tower_snapshot_json(snapshot_json)
        elif isinstance(snapshot_json, dict):
            raw = json.dumps(snapshot_json)
            snapshot = parse_control_tower_snapshot_json(raw)
        else:
            return [], unchanged_seen_state
    except Exception:
        return [], unchanged_seen_state

    loops = snapshot.get("loops", [])
    if not isinstance(loops, list):
        return [], unchanged_seen_state

    notifications: list[CompanionNotification] = []
    updated_seen_ids = set(seen_ids)

    for lane in loops:
        if not isinstance(lane, dict):
            continue

        event_id = lane.get("last_event_id")
        if not event_id or not isinstance(event_id, str):
            continue

        event_kind = lane.get("last_event_kind")
        display_state = lane.get("display_state")
        human_action = lane.get("human_action")

        # Classify notification kind
        notif_kind: str | None = None
        if (
            display_state == "BLOCKED"
            or event_kind == "HUMAN_NEEDED"
            or (isinstance(human_action, str) and human_action != "NONE")
        ):
            notif_kind = "HUMAN_NEEDED"
        elif event_kind in ("TURN_COMPLETE", "COMPLETE"):
            notif_kind = "TURN_COMPLETE"
        else:
            # RUNNING, HEARTBEAT, IDLE, STOPPED, etc. never notify
            notif_kind = None

        if notif_kind is None:
            continue

        if first_run:
            if notif_kind == "TURN_COMPLETE":
                # Historical TURN_COMPLETE marked seen without notifying on first_run
                updated_seen_ids.add(event_id)
            elif notif_kind == "HUMAN_NEEDED":
                # Currently unresolved HUMAN_NEEDED notifies once on first_run if not seen
                if event_id not in seen_ids:
                    notifications.append(_build_notification(notif_kind, lane, event_id))
                    updated_seen_ids.add(event_id)
        else:
            # Normal run / restart: last_event_id already in seen_state never notifies again
            if event_id not in seen_ids:
                notifications.append(_build_notification(notif_kind, lane, event_id))
                updated_seen_ids.add(event_id)

    new_seen_state = _build_new_seen_state(unchanged_seen_state, updated_seen_ids)
    return notifications, new_seen_state


def _normalize_seen_state(
    seen_state: dict[str, Any] | set[str] | list[str] | None,
) -> tuple[dict[str, Any], set[str]]:
    if seen_state is None:
        return {}, set()

    if isinstance(seen_state, set):
        seen_ids = {x for x in seen_state if isinstance(x, str)}
        return {"seen_event_ids": sorted(list(seen_ids))}, seen_ids

    if isinstance(seen_state, (list, tuple)):
        seen_ids = {x for x in seen_state if isinstance(x, str)}
        return {"seen_event_ids": sorted(list(seen_ids))}, seen_ids

    if isinstance(seen_state, dict):
        base_dict = dict(seen_state)
        seen_ids: set[str] = set()

        raw_list = base_dict.get("seen_event_ids")
        if isinstance(raw_list, (list, tuple, set)):
            for item in raw_list:
                if isinstance(item, str):
                    seen_ids.add(item)

        for k, v in base_dict.items():
            if k != "seen_event_ids" and isinstance(k, str) and v:
                seen_ids.add(k)

        return base_dict, seen_ids

    return {}, set()


def _build_new_seen_state(
    base_dict: dict[str, Any],
    updated_seen_ids: set[str],
) -> dict[str, Any]:
    res = dict(base_dict)
    sorted_ids = sorted(list(updated_seen_ids))
    res["seen_event_ids"] = sorted_ids
    for eid in sorted_ids:
        res[eid] = True
    return res


def _build_notification(
    kind: str,
    lane: dict[str, Any],
    event_id: str,
) -> CompanionNotification:
    return CompanionNotification(
        kind=kind,
        loop_id=str(lane.get("loop_id", "")),
        display_name=str(lane.get("display_name", "")),
        event_id=event_id,
        event_kind=lane.get("last_event_kind"),
        display_state=str(lane.get("display_state", "")),
        human_action=str(lane.get("human_action", "NONE")),
        target_ref=lane.get("target_ref"),
        safe_detail_ref=str(lane.get("safe_detail_ref", "")),
    )
