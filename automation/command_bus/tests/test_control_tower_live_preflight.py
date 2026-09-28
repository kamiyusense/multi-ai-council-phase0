from __future__ import annotations

import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower_live_preflight import (
    ControlTowerLanePresentation,
    prepare_verified_control_tower_migration,
)
from automation.command_bus.control_tower_schedule import (
    build_semi_auto_schedule_hint,
)
from automation.command_bus.loop_owner import OwnerDecision
from automation.command_bus.loop_status_issue import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    RUNTIME_END,
    RUNTIME_START,
    StatusProjection,
    managed_block,
)
from automation.command_bus.loop_status_transition import TransitionProjectionResult


ROOT = Path(__file__).parents[1]
REGISTRY_PATH = ROOT / "config" / "control_tower_registry.json"
NOW = "2026-09-28T06:00:00+00:00"


def repository_registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def one_lane_registry(loop_id="loop-015", *, enabled=True, mode="SEMI_AUTO"):
    return {
        "schema_version": 1,
        "loops": [
            {
                "loop_id": loop_id,
                "display_name": "Loop 015",
                "mode": mode,
                "controller_kind": "CHATGPT" if mode == "SEMI_AUTO" else "CLAUDE",
                "worker_kind": "JULES" if mode == "SEMI_AUTO" else "GEMINI",
                "display_order": 10,
                "enabled": enabled,
                "safe_detail_ref": "issue:33",
            }
        ],
    }


def transition(
    loop_id="loop-015",
    *,
    result_status="VALID",
    display_state="SEMI_AUTO",
    human_action="NONE",
    event_id="receipt-015",
):
    owner = "SEMI_AUTO" if display_state == "SEMI_AUTO" else (
        "AUTO" if display_state == "AUTO" else "NONE"
    )
    source_state = "RUNNING"
    if display_state == "BLOCKED":
        source_state = "BLOCKED"
    elif display_state == "IDLE":
        source_state = "COMPLETE"
    return TransitionProjectionResult(
        result_status,
        "durable transition fixture",
        StatusProjection(
            display_state=display_state,
            source_state=source_state,
            owner=owner,
            loop_id=loop_id,
            round=1,
            max_rounds=6,
            provider_state="RUNNING" if display_state in {"SEMI_AUTO", "AUTO"} else "TERMINAL",
            last_durable_progress=f"generation 1; receipt {event_id}",
            expires_at="2026-09-28T07:00:00+00:00",
            human_action=human_action,
            reason="fixture durable projection",
        ),
        OwnerDecision(
            status="VALID",
            owner=owner,
            generation=1,
            fencing_token=1,
            reason="fixture owner decision",
        ),
        event_id,
    )


def issue(*, state="open", title="🚦 Phase 0 Loop Status — ⚫ STOPPED"):
    runtime = managed_block(RUNTIME_START, RUNTIME_END, "# ⚫ Runtime: STOPPED")
    development = managed_block(
        DEVELOPMENT_START,
        DEVELOPMENT_END,
        "## 🛠 Development progress\n\n- Relay: OPEN",
    )
    return {
        "number": 33,
        "state": state,
        "title": title,
        "body": runtime + "\n\n" + development + "\n",
    }


class ControlTowerLivePreflightTests(unittest.TestCase):
    def test_repository_placeholder_registry_without_durable_inventory_is_not_wired(self):
        result = prepare_verified_control_tower_migration(
            registry=repository_registry(),
            verified_transitions=None,
            lane_presentation={},
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "registration"))
        self.assertIsNone(result.model)
        self.assertIsNone(result.issue_plan)

    def test_all_enabled_lanes_must_have_exact_durable_transition_before_plan(self):
        raw = {
            "schema_version": 1,
            "loops": [
                one_lane_registry("loop-a")["loops"][0],
                {
                    **one_lane_registry("loop-b", mode="AUTO")["loops"][0],
                    "display_name": "Loop B",
                    "display_order": 20,
                },
            ],
        }
        result = prepare_verified_control_tower_migration(
            registry=raw,
            verified_transitions={"loop-a": transition("loop-a")},
            lane_presentation={},
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "registration"))
        self.assertEqual(result.registration.ready_loop_ids, ("loop-a",))
        self.assertEqual(result.registration.missing_loop_ids, ("loop-b",))
        self.assertIsNone(result.issue_plan)

    def test_ready_single_lane_builds_model_and_issue_plan(self):
        raw = one_lane_registry()
        result = prepare_verified_control_tower_migration(
            registry=raw,
            verified_transitions={"loop-015": transition()},
            lane_presentation={
                "loop-015": ControlTowerLanePresentation(
                    target_ref="pr:4",
                    durable_event_kind="RECEIPT",
                )
            },
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual((result.status, result.stage), ("READY", "complete"), result)
        self.assertIsNotNone(result.model)
        self.assertIsNotNone(result.issue_plan)
        self.assertEqual(result.model.lanes[0].loop_id, "loop-015")
        self.assertEqual(result.model.lanes[0].display_state, "SEMI_AUTO")
        self.assertEqual(
            result.issue_plan.expected_title,
            "🚦 Phase 0 — 🟢1 SEMI / 🟣0 AUTO / 🔴0 NEEDS YOU",
        )
        self.assertIn(DEVELOPMENT_START, result.issue_plan.expected_body)
        self.assertEqual(result.issue_plan.notifications, ())

    def test_unknown_or_mismatched_durable_transition_cannot_reach_issue_plan(self):
        raw = one_lane_registry()
        unknown = TransitionProjectionResult(
            "UNKNOWN",
            "missing evidence",
            None,
            None,
            None,
        )
        result = prepare_verified_control_tower_migration(
            registry=raw,
            verified_transitions={"loop-015": unknown},
            lane_presentation={},
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "registration"))
        self.assertIsNone(result.issue_plan)

        mismatch = prepare_verified_control_tower_migration(
            registry=raw,
            verified_transitions={"loop-015": transition("other-loop")},
            lane_presentation={},
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual((mismatch.status, mismatch.stage), ("BLOCKED", "registration"))
        self.assertIsNone(mismatch.issue_plan)

    def test_zero_enabled_lanes_do_not_migrate_issue(self):
        result = prepare_verified_control_tower_migration(
            registry=one_lane_registry(enabled=False),
            verified_transitions={},
            lane_presentation={},
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "registration"))
        self.assertIn("no enabled durable", result.reason)
        self.assertIsNone(result.issue_plan)

    def test_unregistered_presentation_metadata_blocks(self):
        result = prepare_verified_control_tower_migration(
            registry=one_lane_registry(),
            verified_transitions={"loop-015": transition()},
            lane_presentation={
                "other-loop": ControlTowerLanePresentation(target_ref="pr:4")
            },
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual((result.status, result.stage), ("BLOCKED", "presentation"))
        self.assertIsNone(result.issue_plan)

    def test_unsafe_target_or_event_metadata_blocks_before_issue_plan(self):
        for meta in (
            ControlTowerLanePresentation(target_ref="https://private.example/chat"),
            ControlTowerLanePresentation(durable_event_kind="turn complete"),
        ):
            with self.subTest(meta=meta):
                result = prepare_verified_control_tower_migration(
                    registry=one_lane_registry(),
                    verified_transitions={"loop-015": transition()},
                    lane_presentation={"loop-015": meta},
                    generated_at=NOW,
                    issue_readback=issue(),
                )
                self.assertEqual((result.status, result.stage), ("BLOCKED", "projection"))
                self.assertIsNone(result.issue_plan)

    def test_overdue_schedule_is_presentation_only_and_creates_no_notification(self):
        hint = build_semi_auto_schedule_hint(
            loop_number=39,
            acceptance_state="VERIFIED",
            accepted_at="2026-09-28T12:59:00+09:00",
            task_size="MEDIUM",
            eta_start="2026-09-28T13:15:00+09:00",
            eta_end="2026-09-28T13:25:00+09:00",
            now="2026-09-28T14:30:00+09:00",
        )
        result = prepare_verified_control_tower_migration(
            registry=one_lane_registry(),
            verified_transitions={"loop-015": transition()},
            lane_presentation={
                "loop-015": ControlTowerLanePresentation(
                    target_ref="pr:4",
                    durable_event_kind="RECEIPT",
                    schedule_hint=hint,
                )
            },
            generated_at="2026-09-28T05:30:00+00:00",
            issue_readback=issue(),
        )
        self.assertEqual(result.status, "READY", result)
        lane = result.model.lanes[0]
        self.assertEqual(lane.display_state, "SEMI_AUTO")
        self.assertEqual(lane.schedule_hint.eta_state, "OVERDUE")
        self.assertEqual(lane.human_action, "NONE")
        self.assertEqual(result.issue_plan.notifications, ())

    def test_blocked_lane_needs_explicit_durable_human_event_for_comment(self):
        blocked = transition(
            result_status="BLOCKED",
            display_state="BLOCKED",
            human_action="REVIEW REQUIRED",
            event_id="human-1",
        )
        no_event = prepare_verified_control_tower_migration(
            registry=one_lane_registry(),
            verified_transitions={"loop-015": blocked},
            lane_presentation={
                "loop-015": ControlTowerLanePresentation(
                    target_ref="pr:4",
                    durable_event_kind="RECEIPT",
                )
            },
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual(no_event.status, "READY")
        self.assertEqual(no_event.issue_plan.notifications, ())

        with_event = prepare_verified_control_tower_migration(
            registry=one_lane_registry(),
            verified_transitions={"loop-015": blocked},
            lane_presentation={
                "loop-015": ControlTowerLanePresentation(
                    target_ref="pr:4",
                    durable_event_kind="HUMAN_NEEDED",
                )
            },
            generated_at=NOW,
            issue_readback=issue(),
        )
        self.assertEqual(with_event.status, "READY")
        self.assertEqual(len(with_event.issue_plan.notifications), 1)
        self.assertEqual(with_event.issue_plan.notifications[0].event_id, "human-1")

    def test_issue_readback_failure_is_unknown_after_durable_gates(self):
        result = prepare_verified_control_tower_migration(
            registry=one_lane_registry(),
            verified_transitions={"loop-015": transition()},
            lane_presentation={},
            generated_at=NOW,
            issue_readback=issue(state="closed"),
        )
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "issue_readback"))
        self.assertIsNotNone(result.model)
        self.assertIsNone(result.issue_plan)


if __name__ == "__main__":
    unittest.main()
