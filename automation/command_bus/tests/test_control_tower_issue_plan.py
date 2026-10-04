from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower import (
    PerLoopProjectionInput,
    build_control_tower,
)
from automation.command_bus.control_tower_issue_plan import (
    assert_issue_unchanged,
    prepare_control_tower_issue_plan,
    verify_issue_applied,
)
from automation.command_bus.loop_status_issue import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    RUNTIME_END,
    RUNTIME_START,
    managed_block,
    project_state,
)
from automation.command_bus.tests.pre_adoption_registry import adopted_snapshot
from automation.command_bus.tests.test_loop_status_issue import state


ROOT = Path(__file__).parents[1]
REGISTRY_PATH = ROOT / "config" / "control_tower_registry.json"
NOW = "2026-09-28T03:45:00+00:00"


def registry():
    # behavioural tests over the registry exactly as approved for the adoption (four lanes, old placeholder ids)
    return adopted_snapshot()


def lane_input(
    loop_id,
    source_state,
    owner,
    *,
    generation=1,
    target="pr:4",
    event_kind="RECEIPT",
    event_id="event-1",
):
    raw = state(
        loop_id=loop_id,
        state=source_state,
        last_receipt_id=event_id,
    )
    projection = project_state(
        raw,
        owner=owner,
        provider_state="RUNNING",
        last_durable_progress=f"generation {generation}; receipt {event_id}",
        expected_loop_id=loop_id,
    )
    return PerLoopProjectionInput(
        projection=projection,
        generation=generation,
        target_ref=target,
        last_event_kind=event_kind,
        last_event_id=event_id,
    )


def model():
    return build_control_tower(
        registry(),
        {
            "chatgpt-semi-auto": lane_input(
                "chatgpt-semi-auto",
                "RUNNING",
                "SEMI_AUTO",
                generation=18,
                target="pr:4",
                event_id="receipt-semi-18",
            ),
            "claude-gemini": lane_input(
                "claude-gemini",
                "RUNNING",
                "AUTO",
                generation=4,
                target="pr:25",
                event_id="receipt-cg-4",
            ),
            "claude-claude": lane_input(
                "claude-claude",
                "COMPLETE",
                "NONE",
                generation=6,
                target=None,
                event_kind="TURN_COMPLETE",
                event_id="receipt-cc-6",
            ),
            "work-gemini": lane_input(
                "work-gemini",
                "BLOCKED",
                "AUTO",
                generation=3,
                target="pr:4",
                event_kind="HUMAN_NEEDED",
                event_id="receipt-wg-3",
            ),
        },
        generated_at=NOW,
    )


def issue(body=None, title="🚦 Phase 0 Loop Status — ⚫ STOPPED", **changes):
    if body is None:
        development = managed_block(
            DEVELOPMENT_START,
            DEVELOPMENT_END,
            "## 🛠 Development progress\n\n- Relay: OPEN",
        )
        body = managed_block(
            RUNTIME_START,
            RUNTIME_END,
            "# ⚫ Runtime: STOPPED",
        ) + "\n\n" + development + "\n"
    value = {
        "number": 33,
        "state": "open",
        "title": title,
        "body": body,
    }
    value.update(changes)
    return value


class ControlTowerIssuePlanTests(unittest.TestCase):
    def test_prepare_migration_preserves_development_and_uses_multi_loop_title(self):
        original = issue()
        plan = prepare_control_tower_issue_plan(model(), original)
        self.assertTrue(plan.issue_change_required)
        self.assertEqual(
            plan.expected_title,
            "🚦 Phase 0 — 🟢1 SEMI / 🟣1 AUTO / 🔴1 NEEDS YOU",
        )
        self.assertIn("## 🔴 HUMAN NEEDED", plan.expected_body)
        self.assertIn("ChatGPT → Jules", plan.expected_body)
        self.assertIn("Claude → Gemini", plan.expected_body)
        self.assertIn("Claude → Claude", plan.expected_body)
        self.assertIn("Work → Gemini", plan.expected_body)
        self.assertIn(DEVELOPMENT_START, plan.expected_body)
        self.assertIn("Relay: OPEN", plan.expected_body)
        self.assertEqual(plan.expected_body.count(RUNTIME_START), 1)
        self.assertEqual(plan.expected_body.count(DEVELOPMENT_START), 1)
        self.assertIn("phase0-control-tower-json:v1", plan.expected_body)

    def test_prepare_only_does_not_mutate_input_issue_or_model(self):
        raw_issue = issue()
        before_issue = copy.deepcopy(raw_issue)
        tower = model()
        before_lanes = copy.deepcopy(tower.lanes)
        prepare_control_tower_issue_plan(tower, raw_issue)
        self.assertEqual(raw_issue, before_issue)
        self.assertEqual(tower.lanes, before_lanes)

    def test_issue_conflict_readback_rejects_title_body_or_state_change(self):
        base_raw = issue()
        plan = prepare_control_tower_issue_plan(model(), base_raw)

        assert_issue_unchanged(plan.base, copy.deepcopy(base_raw))

        changed = copy.deepcopy(base_raw)
        changed["title"] = "other title"
        with self.assertRaisesRegex(ValueError, "changed after"):
            assert_issue_unchanged(plan.base, changed)

        changed = copy.deepcopy(base_raw)
        changed["body"] += "\nexternal edit"
        with self.assertRaisesRegex(ValueError, "changed after"):
            assert_issue_unchanged(plan.base, changed)

        changed = copy.deepcopy(base_raw)
        changed["state"] = "closed"
        with self.assertRaises(ValueError):
            assert_issue_unchanged(plan.base, changed)

    def test_exact_post_write_readback_is_required(self):
        plan = prepare_control_tower_issue_plan(model(), issue())
        applied = issue(
            title=plan.expected_title,
            body=plan.expected_body,
        )
        verify_issue_applied(plan, applied)

        wrong = copy.deepcopy(applied)
        wrong["body"] += "\ncorrupt"
        with self.assertRaisesRegex(ValueError, "readback mismatch"):
            verify_issue_applied(plan, wrong)

    def test_only_turn_complete_and_human_needed_create_notification_plans(self):
        plan = prepare_control_tower_issue_plan(model(), issue())
        self.assertEqual(
            [(item.kind, item.loop_id) for item in plan.notifications],
            [
                ("TURN_COMPLETE", "claude-claude"),
                ("HUMAN_NEEDED", "work-gemini"),
            ],
        )
        for item in plan.notifications:
            self.assertIn(item.loop_id, item.marker)
            self.assertIn(item.event_id, item.marker)
            self.assertIn(item.marker, item.body)
        self.assertNotIn("chatgpt-semi-auto", " ".join(n.marker for n in plan.notifications))
        self.assertNotIn("claude-gemini", " ".join(n.marker for n in plan.notifications))

    def test_existing_loop_event_marker_is_replay_noop_only_for_that_lane(self):
        initial = prepare_control_tower_issue_plan(model(), issue())
        complete = initial.notifications[0]
        plan = prepare_control_tower_issue_plan(
            model(),
            issue(),
            existing_comment_bodies=[
                f"old comment\n<!-- {complete.marker} -->\n",
            ],
        )
        self.assertEqual(len(plan.notifications), 1)
        self.assertEqual(plan.notifications[0].kind, "HUMAN_NEEDED")
        self.assertEqual(plan.notifications[0].loop_id, "work-gemini")

    def test_blocked_or_unknown_display_alone_does_not_invent_notification_event(self):
        tower = build_control_tower(
            registry(),
            {
                "work-gemini": lane_input(
                    "work-gemini",
                    "BLOCKED",
                    "AUTO",
                    generation=3,
                    target="pr:4",
                    event_kind="RECEIPT",
                    event_id="receipt-blocked",
                ),
            },
            generated_at=NOW,
        )
        plan = prepare_control_tower_issue_plan(tower, issue())
        self.assertEqual(plan.notifications, ())
        by_id = {lane.loop_id: lane for lane in tower.lanes}
        self.assertEqual(by_id["work-gemini"].display_state, "BLOCKED")
        self.assertEqual(by_id["chatgpt-semi-auto"].display_state, "UNKNOWN")

    def test_notification_body_contains_only_safe_registry_refs_not_private_urls(self):
        plan = prepare_control_tower_issue_plan(model(), issue())
        combined = "\n".join(item.body for item in plan.notifications)
        self.assertNotIn("https://", combined)
        self.assertNotIn("chat.openai.com", combined)
        self.assertNotIn("claude.ai", combined)
        self.assertIn("issue:33", combined)

    def test_wrong_issue_identity_or_closed_issue_fails_before_plan(self):
        with self.assertRaisesRegex(ValueError, "Issue #33"):
            prepare_control_tower_issue_plan(model(), issue(number=34))
        with self.assertRaisesRegex(ValueError, "must be open"):
            prepare_control_tower_issue_plan(model(), issue(state="closed"))

    def test_already_matching_control_tower_issue_is_issue_noop(self):
        first = prepare_control_tower_issue_plan(model(), issue())
        matching = issue(
            title=first.expected_title,
            body=first.expected_body,
        )
        second = prepare_control_tower_issue_plan(
            model(),
            matching,
            existing_comment_bodies=[item.body for item in first.notifications],
        )
        self.assertFalse(second.issue_change_required)
        self.assertEqual(second.notifications, ())


if __name__ == "__main__":
    unittest.main()
