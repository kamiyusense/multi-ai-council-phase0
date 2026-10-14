"""Unit tests for Windows Signal Companion v1 core logic (SF-12).

Tests:
- tray_state color priority and staleness validation
- tray_state fail-passive handling for missing/malformed inputs
- notification_plan classification (TURN_COMPLETE, HUMAN_NEEDED)
- notification_plan deduplication and first_run behavior
- notification_plan fail-passive handling for missing/malformed inputs
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from automation.command_bus.signal_companion_core import (
    CompanionNotification,
    TrayState,
    notification_plan,
    tray_state,
)

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
_GEN_AT = "2026-09-28T11:55:00Z"  # 300 seconds before _NOW


def _make_snapshot(
    loops: list[dict],
    generated_at: str = _GEN_AT,
    schema_version: int = 1,
    project: str = "phase0",
) -> str:
    return json.dumps(
        {
            "schema_version": schema_version,
            "project": project,
            "generated_at": generated_at,
            "loops": loops,
        }
    )


def _make_lane(
    loop_id: str = "auto-claude-gemini",
    display_name: str = "Claude -> Gemini",
    mode: str = "AUTO",
    display_state: str = "AUTO",
    controller_kind: str = "CLAUDE",
    worker_kind: str = "GEMINI",
    identity_state: str = "DURABLE",
    generation: int | None = 4,
    target_ref: str | None = "pr:10",
    last_event_kind: str | None = "RUNNING",
    last_event_id: str | None = "receipt-100",
    schedule_hint: dict | None = None,
    human_action: str = "NONE",
    safe_detail_ref: str = "issue:33",
) -> dict:
    return {
        "loop_id": loop_id,
        "display_name": display_name,
        "mode": mode,
        "display_state": display_state,
        "controller_kind": controller_kind,
        "worker_kind": worker_kind,
        "identity_state": identity_state,
        "generation": generation,
        "target_ref": target_ref,
        "last_event_kind": last_event_kind,
        "last_event_id": last_event_id,
        "schedule_hint": schedule_hint,
        "human_action": human_action,
        "safe_detail_ref": safe_detail_ref,
    }


class TrayStateTests(unittest.TestCase):
    def test_priority_red_on_blocked_display_state(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    mode="AUTO",
                    display_state="AUTO",
                ),
                _make_lane(
                    loop_id="loop-2",
                    mode="AUTO",
                    display_state="BLOCKED",
                    last_event_kind="HUMAN_NEEDED",
                    human_action="REVIEW",
                ),
            ]
        )
        res = tray_state(snap, _NOW)
        self.assertEqual(res, TrayState("RED", "HUMAN_NEEDED"))
        self.assertEqual(res.color, "RED")
        self.assertEqual(res.reason_code, "HUMAN_NEEDED")

    def test_priority_red_on_human_action_needed(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    mode="SEMI_AUTO",
                    display_state="SEMI_AUTO",
                    human_action="REVIEW",
                )
            ]
        )
        res = tray_state(snap, _NOW)
        self.assertEqual(res.color, "RED")

    def test_priority_purple_on_auto_active_no_blocker(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    mode="SEMI_AUTO",
                    display_state="SEMI_AUTO",
                ),
                _make_lane(
                    loop_id="loop-2",
                    mode="AUTO",
                    display_state="AUTO",
                ),
            ]
        )
        res = tray_state(snap, _NOW)
        self.assertEqual(res, TrayState("PURPLE", "AUTO_ACTIVE"))

    def test_priority_green_on_only_semi_auto_active(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    mode="SEMI_AUTO",
                    display_state="SEMI_AUTO",
                ),
                _make_lane(
                    loop_id="loop-2",
                    mode="AUTO",
                    display_state="IDLE",
                ),
            ]
        )
        res = tray_state(snap, _NOW)
        self.assertEqual(res, TrayState("GREEN", "SEMI_AUTO_ACTIVE"))

    def test_priority_yellow_on_all_idle(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    mode="SEMI_AUTO",
                    display_state="IDLE",
                ),
                _make_lane(
                    loop_id="loop-2",
                    mode="AUTO",
                    display_state="STOPPED",
                ),
            ]
        )
        res = tray_state(snap, _NOW)
        self.assertEqual(res, TrayState("YELLOW", "ALL_IDLE"))

    def test_priority_black_on_all_stopped(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    mode="SEMI_AUTO",
                    display_state="STOPPED",
                ),
                _make_lane(
                    loop_id="loop-2",
                    mode="AUTO",
                    display_state="STOPPED",
                ),
            ]
        )
        res = tray_state(snap, _NOW)
        self.assertEqual(res, TrayState("BLACK", "ALL_STOPPED"))

    def test_empty_loops_returns_black(self):
        snap = _make_snapshot([])
        res = tray_state(snap, _NOW)
        self.assertEqual(res, TrayState("BLACK", "ALL_STOPPED"))

    def test_staleness_returns_white(self):
        # generated 700s ago (older than default max_age_seconds=600)
        old_gen = "2026-09-28T11:48:20Z"
        snap = _make_snapshot([_make_lane()], generated_at=old_gen)
        res = tray_state(snap, _NOW)
        self.assertEqual(res, TrayState("WHITE", "SNAPSHOT_STALE"))

        # Custom max_age_seconds=1000 accepts 700s age
        res_custom = tray_state(snap, _NOW, max_age_seconds=1000)
        self.assertEqual(res_custom.color, "PURPLE")

    def test_future_snapshot_returns_white_stale(self):
        future_gen = "2026-09-28T12:05:00Z"  # 300s in future
        snap = _make_snapshot([_make_lane()], generated_at=future_gen)
        res = tray_state(snap, _NOW)
        self.assertEqual(res, TrayState("WHITE", "SNAPSHOT_STALE"))

    def test_fail_passive_on_invalid_inputs(self):
        self.assertEqual(tray_state(None, _NOW), TrayState("WHITE", "SNAPSHOT_MISSING"))
        self.assertEqual(tray_state(_make_snapshot([_make_lane()]), None), TrayState("WHITE", "INVALID_NOW"))

        # Naive datetime
        naive_now = datetime(2026, 9, 28, 12, 0, 0)
        self.assertEqual(tray_state(_make_snapshot([_make_lane()]), naive_now), TrayState("WHITE", "INVALID_NOW"))

        # Invalid JSON
        self.assertEqual(tray_state("not-json", _NOW), TrayState("WHITE", "SNAPSHOT_MALFORMED"))

        # Dict input invalid schema
        self.assertEqual(tray_state({"invalid": "schema"}, _NOW), TrayState("WHITE", "SNAPSHOT_MALFORMED"))


class NotificationPlanTests(unittest.TestCase):
    def test_first_run_marks_historical_turn_complete_seen_without_notifying(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    last_event_kind="TURN_COMPLETE",
                    last_event_id="receipt-1",
                ),
            ]
        )
        notifs, new_seen = notification_plan(snap, seen_state={}, first_run=True)
        self.assertEqual(notifs, [])
        self.assertIn("receipt-1", new_seen["seen_event_ids"])
        self.assertTrue(new_seen.get("receipt-1"))

    def test_first_run_notifies_unresolved_human_needed_once(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    mode="AUTO",
                    display_state="BLOCKED",
                    last_event_kind="HUMAN_NEEDED",
                    last_event_id="receipt-blocked-1",
                    human_action="REVIEW",
                ),
            ]
        )
        notifs, new_seen = notification_plan(snap, seen_state={}, first_run=True)
        self.assertEqual(len(notifs), 1)
        self.assertEqual(notifs[0].kind, "HUMAN_NEEDED")
        self.assertEqual(notifs[0].loop_id, "loop-1")
        self.assertEqual(notifs[0].event_id, "receipt-blocked-1")
        self.assertEqual(notifs[0]["human_action"], "REVIEW")
        self.assertIn("receipt-blocked-1", new_seen["seen_event_ids"])

        # Subsequent call with updated seen_state does not notify again
        notifs_2, new_seen_2 = notification_plan(snap, seen_state=new_seen, first_run=False)
        self.assertEqual(notifs_2, [])
        self.assertEqual(new_seen_2["seen_event_ids"], new_seen["seen_event_ids"])

    def test_normal_run_notifies_new_turn_complete_and_dedupes(self):
        snap_1 = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    last_event_kind="TURN_COMPLETE",
                    last_event_id="receipt-10",
                ),
            ]
        )
        seen_1 = {"seen_event_ids": ["receipt-9"]}
        notifs_1, seen_2 = notification_plan(snap_1, seen_state=seen_1, first_run=False)
        self.assertEqual(len(notifs_1), 1)
        self.assertEqual(notifs_1[0].kind, "TURN_COMPLETE")
        self.assertEqual(notifs_1[0].event_id, "receipt-10")
        self.assertIn("receipt-10", seen_2["seen_event_ids"])
        self.assertIn("receipt-9", seen_2["seen_event_ids"])

        # Same snapshot again -> deduplicated, no notification
        notifs_repeat, seen_repeat = notification_plan(snap_1, seen_state=seen_2, first_run=False)
        self.assertEqual(notifs_repeat, [])
        self.assertEqual(seen_repeat["seen_event_ids"], seen_2["seen_event_ids"])

    def test_running_and_heartbeat_events_never_notify(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    last_event_kind="RUNNING",
                    last_event_id="receipt-run",
                ),
                _make_lane(
                    loop_id="loop-2",
                    last_event_kind="HEARTBEAT",
                    last_event_id="receipt-hb",
                ),
            ]
        )
        notifs, _ = notification_plan(snap, seen_state={}, first_run=False)
        self.assertEqual(notifs, [])

    def test_lane_without_event_id_never_notifies(self):
        snap = _make_snapshot(
            [
                _make_lane(
                    loop_id="loop-1",
                    last_event_kind="TURN_COMPLETE",
                    last_event_id=None,
                ),
            ]
        )
        notifs, _ = notification_plan(snap, seen_state={}, first_run=False)
        self.assertEqual(notifs, [])

    def test_fail_passive_on_malformed_inputs(self):
        seen_orig = {"seen_event_ids": ["receipt-1"]}
        notifs_none, seen_out_none = notification_plan(None, seen_state=seen_orig)
        self.assertEqual(notifs_none, [])
        self.assertEqual(seen_out_none, seen_orig)

        notifs_bad_json, seen_out_bad = notification_plan("bad-json", seen_state=seen_orig)
        self.assertEqual(notifs_bad_json, [])
        self.assertEqual(seen_out_bad, seen_orig)

    def test_companion_notification_dataclass_methods(self):
        notif = CompanionNotification(
            kind="TURN_COMPLETE",
            loop_id="loop-1",
            display_name="Loop 1",
            event_id="receipt-1",
            event_kind="TURN_COMPLETE",
            display_state="IDLE",
            human_action="NONE",
            target_ref="pr:5",
            safe_detail_ref="issue:33",
        )
        d = notif.to_dict()
        self.assertEqual(d["kind"], "TURN_COMPLETE")
        self.assertEqual(d["loop_id"], "loop-1")
        self.assertEqual(notif["kind"], "TURN_COMPLETE")
        self.assertEqual(notif["display_name"], "Loop 1")


if __name__ == "__main__":
    unittest.main()
