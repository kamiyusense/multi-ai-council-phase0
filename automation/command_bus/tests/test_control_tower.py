from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower import (
    ControlTowerLane,
    PerLoopProjectionInput,
    build_control_tower,
    notification_marker,
    render_control_tower,
    render_snapshot,
    render_title,
    validate_registry,
)
from automation.command_bus.loop_status_issue import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    RUNTIME_END,
    RUNTIME_START,
    managed_block,
    project_state,
)
from automation.command_bus.tests.test_loop_status_issue import state


ROOT = Path(__file__).parents[1]
REGISTRY_PATH = ROOT / "config" / "control_tower_registry.json"
SCHEMA_PATH = ROOT / "schema" / "control_tower_registry.schema.json"
NOW = "2026-09-28T03:30:00+00:00"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def projection(loop_id, source_state, owner, *, receipt=None):
    raw = state(
        loop_id=loop_id,
        state=source_state,
        last_receipt_id=receipt,
    )
    return project_state(
        raw,
        owner=owner,
        provider_state="RUNNING",
        last_durable_progress=f"receipt {receipt}" if receipt else "checkpoint",
        expected_loop_id=loop_id,
    )


def lane_input(loop_id, source_state, owner, *, generation=1, target="pr:4", event_kind="RECEIPT", event_id="event-1"):
    return PerLoopProjectionInput(
        projection(loop_id, source_state, owner, receipt=event_id),
        generation,
        target,
        event_kind,
        event_id,
    )


class ControlTowerTests(unittest.TestCase):
    def test_repository_registry_and_schema_are_bounded_static_contracts(self):
        raw = registry()
        entries = validate_registry(raw)
        self.assertEqual(len(entries), 4)
        self.assertEqual(
            [entry.display_name for entry in entries],
            ["ChatGPT Semi-Auto", "Claude -> Gemini", "Claude -> Claude", "Work -> Gemini"],
        )
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["loops"]["maxItems"], 8)
        item = schema["properties"]["loops"]["items"]
        self.assertFalse(item["additionalProperties"])
        for forbidden in (
            "runtime_state",
            "owner_generation",
            "fencing_token",
            "verified",
            "provider_liveness",
            "api_key",
            "private_url",
        ):
            self.assertNotIn(forbidden, item["properties"])

    def test_zero_enabled_lanes_renders_bounded_empty_control_tower(self):
        raw = {"schema_version": 1, "loops": []}
        model = build_control_tower(raw, {}, generated_at=NOW)
        self.assertEqual(model.lanes, ())
        self.assertEqual(
            render_title(model),
            "🚦 Phase 0 — 🟢0 SEMI / 🟣0 AUTO / 🔴0 NEEDS YOU",
        )
        rendered = render_control_tower(model)
        self.assertIn("| Signal | Loop | Mode |", rendered.body)
        self.assertEqual(json.loads(rendered.snapshot_json)["loops"], [])

    def test_one_verified_lane_represents_existing_single_loop_projection(self):
        raw = {"schema_version": 1, "loops": [registry()["loops"][0]]}
        inputs = {
            "chatgpt-semi-auto": lane_input(
                "chatgpt-semi-auto", "RUNNING", "SEMI_AUTO",
                generation=18, target="pr:4", event_id="receipt-18",
            )
        }
        model = build_control_tower(raw, inputs, generated_at=NOW)
        lane = model.lanes[0]
        self.assertEqual(lane.display_state, "SEMI_AUTO")
        self.assertEqual(lane.mode, "SEMI_AUTO")
        self.assertEqual(lane.controller_kind, "CHATGPT")
        self.assertEqual(lane.worker_kind, "JULES")
        self.assertEqual(render_title(model), "🚦 Phase 0 — 🟢1 SEMI / 🟣0 AUTO / 🔴0 NEEDS YOU")

    def test_mixed_independent_states_render_together(self):
        raw = registry()
        inputs = {
            "chatgpt-semi-auto": lane_input("chatgpt-semi-auto", "RUNNING", "SEMI_AUTO", generation=18, event_id="receipt-semi"),
            "claude-gemini": lane_input("claude-gemini", "RUNNING", "AUTO", generation=4, target="pr:25", event_id="receipt-cg"),
            "claude-claude": lane_input("claude-claude", "COMPLETE", "NONE", generation=6, target=None, event_kind="TURN_COMPLETE", event_id="receipt-cc"),
            "work-gemini": lane_input("work-gemini", "BLOCKED", "AUTO", generation=3, target="pr:4", event_kind="HUMAN_NEEDED", event_id="receipt-wg"),
        }
        model = build_control_tower(raw, inputs, generated_at=NOW)
        self.assertEqual(
            [lane.display_state for lane in model.lanes],
            ["SEMI_AUTO", "AUTO", "IDLE", "BLOCKED"],
        )
        rendered = render_control_tower(model)
        self.assertEqual(rendered.title, "🚦 Phase 0 — 🟢1 SEMI / 🟣1 AUTO / 🔴1 NEEDS YOU")
        self.assertIn("## 🔴 HUMAN NEEDED", rendered.body)
        self.assertLess(rendered.body.index("## 🔴 HUMAN NEEDED"), rendered.body.index("| Signal |"))
        self.assertIn("ChatGPT → Jules", rendered.body)
        self.assertIn("Claude → Gemini", rendered.body)
        self.assertIn("Claude → Claude", rendered.body)
        self.assertIn("Work → Gemini", rendered.body)

    def test_missing_or_malformed_lane_is_unknown_without_erasing_healthy_lanes(self):
        raw = registry()
        healthy = lane_input("claude-gemini", "RUNNING", "AUTO", generation=4, event_id="good")
        malformed = lane_input("work-gemini", "RUNNING", "AUTO", generation=3, event_id="bad")
        malformed = PerLoopProjectionInput(
            malformed.projection, malformed.generation, "https://private.example/chat",
            malformed.last_event_kind, malformed.last_event_id,
        )
        model = build_control_tower(
            raw,
            {
                "claude-gemini": healthy,
                "work-gemini": malformed,
            },
            generated_at=NOW,
        )
        by_id = {lane.loop_id: lane for lane in model.lanes}
        self.assertEqual(by_id["claude-gemini"].display_state, "AUTO")
        self.assertEqual(by_id["work-gemini"].display_state, "UNKNOWN")
        self.assertEqual(by_id["chatgpt-semi-auto"].display_state, "UNKNOWN")
        self.assertEqual(by_id["claude-claude"].display_state, "UNKNOWN")
        self.assertEqual(render_title(model), "🚦 Phase 0 — 🟢0 SEMI / 🟣1 AUTO / 🔴3 NEEDS YOU")
        self.assertNotIn("private.example", render_snapshot(model))

    def test_registry_mode_is_presentation_metadata_not_runtime_truth(self):
        raw = {"schema_version": 1, "loops": [registry()["loops"][1]]}
        inputs = {
            "claude-gemini": lane_input(
                "claude-gemini", "COMPLETE", "NONE",
                generation=5, target=None, event_kind="TURN_COMPLETE", event_id="complete-5",
            )
        }
        model = build_control_tower(raw, inputs, generated_at=NOW)
        lane = model.lanes[0]
        self.assertEqual(lane.mode, "AUTO")
        self.assertEqual(lane.display_state, "IDLE")
        self.assertEqual(render_title(model), "🚦 Phase 0 — 🟢0 SEMI / 🟣0 AUTO / 🔴0 NEEDS YOU")

    def test_human_markdown_and_machine_snapshot_share_same_model(self):
        raw = {"schema_version": 1, "loops": [registry()["loops"][1]]}
        model = build_control_tower(
            raw,
            {
                "claude-gemini": lane_input(
                    "claude-gemini", "RUNNING", "AUTO",
                    generation=4, target="pr:25", event_kind="PROVIDER_READBACK", event_id="provider-4",
                )
            },
            generated_at=NOW,
        )
        rendered = render_control_tower(model)
        payload = json.loads(rendered.snapshot_json)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["loops"][0]["loop_id"], model.lanes[0].loop_id)
        self.assertEqual(payload["loops"][0]["display_state"], model.lanes[0].display_state)
        self.assertEqual(payload["loops"][0]["controller_kind"], model.lanes[0].controller_kind)
        self.assertEqual(payload["loops"][0]["worker_kind"], model.lanes[0].worker_kind)
        self.assertIn(rendered.snapshot_json, rendered.body)
        self.assertIn("<!-- phase0-control-tower-json:v1", rendered.body)
        self.assertNotIn("https://", rendered.snapshot_json)

    def test_existing_development_block_is_preserved_by_pure_renderer(self):
        raw = {"schema_version": 1, "loops": [registry()["loops"][0]]}
        model = build_control_tower(
            raw,
            {"chatgpt-semi-auto": lane_input("chatgpt-semi-auto", "RUNNING", "SEMI_AUTO")},
            generated_at=NOW,
        )
        development = managed_block(
            DEVELOPMENT_START,
            DEVELOPMENT_END,
            "## 🛠 Development progress\n\n- Relay: OPEN",
        )
        old_runtime = managed_block(RUNTIME_START, RUNTIME_END, "# ⚫ Runtime: STOPPED")
        rendered = render_control_tower(model, existing_body=old_runtime + "\n\n" + development + "\n")
        self.assertIn(development, rendered.body)
        self.assertEqual(rendered.body.count(DEVELOPMENT_START), 1)
        self.assertEqual(rendered.body.count(RUNTIME_START), 1)
        self.assertNotIn("# ⚫ Runtime: STOPPED", rendered.body)

    def test_registry_rejects_runtime_truth_private_urls_duplicates_and_overflow(self):
        base = registry()
        for field, value in (
            ("runtime_state", "AUTO"),
            ("verified", True),
            ("private_url", "https://chat.example/private"),
        ):
            bad = copy.deepcopy(base)
            bad["loops"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_registry(bad)

        bad = copy.deepcopy(base)
        bad["loops"][0]["safe_detail_ref"] = "https://github.com/private"
        with self.assertRaises(ValueError):
            validate_registry(bad)

        bad = copy.deepcopy(base)
        bad["loops"][1]["loop_id"] = bad["loops"][0]["loop_id"]
        with self.assertRaises(ValueError):
            validate_registry(bad)

        entry = copy.deepcopy(base["loops"][0])
        too_many = {"schema_version": 1, "loops": []}
        for index in range(9):
            clone = copy.deepcopy(entry)
            clone["loop_id"] = f"loop-{index}"
            clone["display_name"] = f"Loop {index}"
            clone["display_order"] = index
            too_many["loops"].append(clone)
        with self.assertRaises(ValueError):
            validate_registry(too_many)

    def test_notification_dedupe_is_loop_and_event_specific(self):
        lane = ControlTowerLane(
            "claude-gemini", "Claude -> Gemini", "AUTO", "CLAUDE", "GEMINI",
            20, "issue:33", "BLOCKED", 4, "pr:25", "HUMAN_NEEDED",
            "receipt-4", "REVIEW REQUIRED", "blocked",
        )
        marker = notification_marker(lane, "HUMAN_NEEDED")
        self.assertEqual(
            marker,
            "control-tower-receipt:HUMAN_NEEDED:claude-gemini:receipt-4",
        )
        with self.assertRaises(ValueError):
            notification_marker(lane, "RUNNING")

        no_event = copy.deepcopy(lane)
        object.__setattr__(no_event, "last_event_id", None)
        with self.assertRaises(ValueError):
            notification_marker(no_event, "HUMAN_NEEDED")

    def test_generated_at_and_lane_identity_fail_closed_locally(self):
        raw = {"schema_version": 1, "loops": [registry()["loops"][0]]}
        with self.assertRaises(ValueError):
            build_control_tower(raw, {}, generated_at="not-a-time")

        wrong = lane_input("other-loop", "RUNNING", "SEMI_AUTO")
        model = build_control_tower(
            raw,
            {"chatgpt-semi-auto": wrong},
            generated_at=NOW,
        )
        self.assertEqual(model.lanes[0].display_state, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
