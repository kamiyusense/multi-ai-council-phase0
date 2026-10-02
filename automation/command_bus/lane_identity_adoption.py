"""Static validator for a PLACEHOLDER -> DURABLE lane identity adoption diff.

It adopts nothing and writes nothing. A human-approved adoption record plus a
proposed registry are checked against the current registry; only the named
lane's identity_state may change, and its loop_id must stay as is.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .control_tower import validate_registry

_RECORD_KEYS = frozenset({
    "schema_version", "lane_loop_id", "approved_by_actor_id",
    "approval_ref", "approved_at", "decision",
})
_ACTOR_ID = re.compile(r"[0-9]{1,20}")
_REF = re.compile(r"(issue|pr|github-actions):[A-Za-z0-9_./#-]{1,120}")
_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z")


def validate_adoption_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise ValueError("adoption record shape is invalid")
    if record["schema_version"] != 1 or record["decision"] != "ADOPT_DURABLE":
        raise ValueError("adoption record decision is invalid")
    if not isinstance(record["approved_by_actor_id"], str) or not _ACTOR_ID.fullmatch(record["approved_by_actor_id"]):
        raise ValueError("approver actor id is invalid")
    if not isinstance(record["approval_ref"], str) or not _REF.fullmatch(record["approval_ref"]):
        raise ValueError("approval ref is invalid")
    if not isinstance(record["approved_at"], str) or not _TS.fullmatch(record["approved_at"]):
        raise ValueError("approved_at is invalid")
    if not isinstance(record["lane_loop_id"], str):
        raise ValueError("lane_loop_id is invalid")
    return record


def validate_lane_adoption_diff(
    *, current: dict[str, Any], proposed: dict[str, Any],
    record: dict[str, Any], allowed_approver_ids: frozenset[str],
) -> str:
    """Return the adopted loop_id, or raise ValueError."""
    rec = validate_adoption_record(record)
    if rec["approved_by_actor_id"] not in allowed_approver_ids:
        raise ValueError("approver is not allowlisted")
    cur = {e.loop_id: e for e in validate_registry(current)}
    new_entries = validate_registry(proposed)
    new = {e.loop_id: e for e in new_entries}
    if set(cur) != set(new) or len(new) != len(new_entries):
        raise ValueError("loop_id set must not change (no numeric or derived id)")
    lane = rec["lane_loop_id"]
    if lane not in cur:
        raise ValueError("adoption record names an unknown lane")
    if cur[lane].identity_state != "PLACEHOLDER" or new[lane].identity_state != "DURABLE":
        raise ValueError("lane must move PLACEHOLDER -> DURABLE")
    for loop_id, before in cur.items():
        after = new[loop_id]
        if loop_id == lane:
            if replace(before, identity_state="DURABLE") != after:
                raise ValueError("only identity_state may change on the adopted lane")
        elif before != after:
            raise ValueError("other lanes must not change")
    if lane.isdecimal():
        raise ValueError("session-like numeric id cannot be a durable loop_id")
    return lane
