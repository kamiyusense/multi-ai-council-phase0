from __future__ import annotations

import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower import (
    PerLoopProjectionInput,
    build_control_tower,
    render_control_tower,
)
from automation.command_bus.control_tower_issue_plan import (
    prepare_control_tower_issue_plan,
)
from automation.command_bus.control_tower_schedule import (
    build_semi_auto_schedule_hint,
    schedule_compact_text,
    schedule_snapshot,
)
from automation.command_bus.loop_status_issue import project_state
from automation.command_bus.tests.test_loop_status_issue import state


ROOT = Path(__file__).parents[1]
REGISTRY_PATH = ROOT / "config" / "control_tower_registry.json"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def semi_projection(loop_id="chatgpt-semi-auto"):
    raw = state(
        loop_id=loop_id,
        state="RUNNING",
        last_receipt_id="receipt-semi-39",
    )
    return project_state(
        raw,
        owner="SEMI_AUTO",
        provider_state="RUNNING",
        last_durable_progress="generation 39; receipt receipt-semi-39",
        expected_loop_id=loop_id,
    )


def schedule(now, **changes):
    values = {
        "loop_number": 39,
        "acceptance_state": "VERIFIED",
        "accepted_at": "2026-09-28T12:59:00+09:00",
        "task_size": "MEDIUM",
        "eta_start": "2026-09-28T13:15:00+09:00",
        "eta_end": "2026-09-28T13:25:00+09:00",
        "now": now,
    }
    values.update(changes)
    return build_semi_auto_schedule_hint(**values)


def semi_input(hint):
    return PerLoopProjectionInput(
        projection=semi_projection(),
        generation=39,
        target_ref="pr:4",
        last_event_kind="RECEIPT",
        last_event_id="receipt-semi-39",
        schedule_hint=hint,
    )


class ControlTowerSemiAutoTimingTests(unittest.TestCase):
    def test_eta_state_is_derived_from_time_not_caller_runtime_state(self):
        before = schedule("2026-09-28T13:10:00+09:00")
        within = schedule("2026-09-28T13:20:00+09:00")
        overdue = schedule("2026-09-28T13:26:00+09:00")
        self.assertEqual(before.eta_state, "BEFORE_WINDOW")
        self.assertEqual(within.eta_state, "WITHIN_WINDOW")
        self.assertEqual(overdue.eta_state, "OVERDUE")

    def test_verified_schedule_requires_jst_acceptance_and_ordered_eta(self):
        with self.assertRaisesRegex(ValueError, "JST"):
            schedule(
                "2026-09-28T13:20:00+09:00",
                accepted_at="2026-09-28T03:59:00+00:00",
            )
        with self.assertRaisesRegex(ValueError, "eta_start"):
            schedule(
                "2026-09-28T13:20:00+09:00",
                eta_start="2026-09-28T12:58:00+09:00",
            )
        with self.assertRaisesRegex(ValueError, "eta_end"):
            schedule(
                "2026-09-28T13:20:00+09:00",
                eta_end="2026-09-28T13:14:00+09:00",
            )

    def test_unknown_acceptance_forbids_invented_time_or_eta(self):
        hint = build_semi_auto_schedule_hint(
            loop_number=39,
            acceptance_state="UNKNOWN",
            accepted_at=None,
            task_size="MEDIUM",
            eta_start=None,
            eta_end=None,
            now="2026-09-28T13:20:00+09:00",
        )
        self.assertEqual(hint.eta_state, "UNKNOWN")
        self.assertIsNone(hint.accepted_at)
        self.assertIsNone(hint.eta_start)
        self.assertIsNone(hint.eta_end)
        self.assertEqual(
            schedule_compact_text(hint),
            "Loop 039 / 中 / 投入時刻 UNKNOWN",
        )
        with self.assertRaisesRegex(ValueError, "forbids"):
            build_semi_auto_schedule_hint(
                loop_number=39,
                acceptance_state="UNKNOWN",
                accepted_at="2026-09-28T12:59:00+09:00",
                task_size="MEDIUM",
                eta_start=None,
                eta_end=None,
                now="2026-09-28T13:20:00+09:00",
            )

    def test_task_size_is_bounded_presentation_enum(self):
        for machine, human in (
            ("SHORT", "短"),
            ("MEDIUM", "中"),
            ("LONG", "長"),
        ):
            hint = schedule(
                "2026-09-28T13:20:00+09:00",
                task_size=machine,
            )
            self.assertEqual(hint.task_size_label, human)

        with self.assertRaisesRegex(ValueError, "task_size"):
            schedule(
                "2026-09-28T13:20:00+09:00",
                task_size="HUGE",
            )

    def test_overdue_schedule_keeps_runtime_semi_auto_and_only_adds_visual_hint(self):
        hint = schedule("2026-09-28T13:26:00+09:00")
        raw = {"schema_version": 1, "loops": [registry()["loops"][0]]}
        tower = build_control_tower(
            raw,
            {"chatgpt-semi-auto": semi_input(hint)},
            generated_at="2026-09-28T04:26:00+00:00",
        )
        lane = tower.lanes[0]
        self.assertEqual(lane.display_state, "SEMI_AUTO")
        self.assertEqual(lane.schedule_hint.eta_state, "OVERDUE")

        rendered = render_control_tower(tower)
        self.assertIn(
            "Loop 039 / 中 / 12:59 → 13:15–13:25 / ⏱️ ETA exceeded",
            rendered.body,
        )
        payload = json.loads(rendered.snapshot_json)
        schedule_json = payload["loops"][0]["schedule_hint"]
        self.assertEqual(schedule_json["loop_number"], 39)
        self.assertEqual(schedule_json["accepted_at"], "2026-09-28T12:59:00+09:00")
        self.assertEqual(schedule_json["task_size"], "MEDIUM")
        self.assertEqual(schedule_json["eta_start"], "2026-09-28T13:15:00+09:00")
        self.assertEqual(schedule_json["eta_end"], "2026-09-28T13:25:00+09:00")
        self.assertEqual(schedule_json["eta_state"], "OVERDUE")

    def test_eta_overdue_does_not_create_notification_or_human_needed(self):
        hint = schedule("2026-09-28T13:26:00+09:00")
        raw = {"schema_version": 1, "loops": [registry()["loops"][0]]}
        tower = build_control_tower(
            raw,
            {"chatgpt-semi-auto": semi_input(hint)},
            generated_at="2026-09-28T04:26:00+00:00",
        )
        plan = prepare_control_tower_issue_plan(
            tower,
            {
                "number": 33,
                "state": "open",
                "title": "🚦 Phase 0 Loop Status — ⚫ STOPPED",
                "body": "",
            },
        )
        self.assertEqual(tower.lanes[0].display_state, "SEMI_AUTO")
        self.assertEqual(tower.lanes[0].human_action, "NONE")
        self.assertEqual(plan.notifications, ())

    def test_schedule_hint_is_semi_auto_only_and_does_not_change_other_lane(self):
        hint = schedule("2026-09-28T13:20:00+09:00")
        auto_entry = registry()["loops"][1]
        auto_raw = state(
            loop_id="claude-gemini",
            state="RUNNING",
            last_receipt_id="receipt-auto",
        )
        auto_projection = project_state(
            auto_raw,
            owner="AUTO",
            provider_state="RUNNING",
            last_durable_progress="receipt receipt-auto",
            expected_loop_id="claude-gemini",
        )
        tower = build_control_tower(
            {"schema_version": 1, "loops": [auto_entry]},
            {
                "claude-gemini": PerLoopProjectionInput(
                    auto_projection,
                    4,
                    "pr:25",
                    "RECEIPT",
                    "receipt-auto",
                    hint,
                )
            },
            generated_at="2026-09-28T04:20:00+00:00",
        )
        self.assertEqual(tower.lanes[0].display_state, "UNKNOWN")
        self.assertIsNone(tower.lanes[0].schedule_hint)

    def test_schedule_snapshot_is_nested_presentation_metadata_only(self):
        hint = schedule("2026-09-28T13:20:00+09:00")
        snap = schedule_snapshot(hint)
        self.assertEqual(
            set(snap),
            {
                "loop_number",
                "acceptance_state",
                "accepted_at",
                "task_size",
                "eta_start",
                "eta_end",
                "eta_state",
            },
        )
        for forbidden in (
            "runtime_state",
            "owner",
            "generation",
            "fencing_token",
            "provider_state",
            "takeover",
            "verified",
        ):
            self.assertNotIn(forbidden, snap)


if __name__ == "__main__":
    unittest.main()
