"""Additive registry support: worker WORK and the FROZEN lane state. Production registry is not touched here."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower import (
    build_control_tower, render_control_tower, validate_registry,
)
from automation.command_bus.control_tower_registration import assess_registration_readiness

ROOT = Path(__file__).resolve().parents[3]
PROD = json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "automation/command_bus/schema/control_tower_registry.schema.json").read_text(encoding="utf-8"))
V3 = json.loads((ROOT / "docs/evidence/signal-lane-model/proposed-registry-v3-fixture.json").read_text(encoding="utf-8"))
NOW = "2026-10-04T00:00:00Z"


def entry_props():
    return SCHEMA["properties"]["loops"]["items"]["properties"]


class ValidatorTests(unittest.TestCase):
    def test_the_v3_design_fixture_now_validates_as_is(self):
        entries = validate_registry(V3)
        self.assertEqual([e.loop_id for e in entries],
                         ["chatgpt-semi-auto", "chat-work-semi-auto", "claude-jules-auto", "work-jules-auto", "claude-claude-auto"])

    def test_schema_enums_match_the_validator(self):
        self.assertIn("WORK", entry_props()["worker_kind"]["enum"])
        self.assertIn("FROZEN", entry_props()["identity_state"]["enum"])
        self.assertEqual(entry_props()["controller_kind"]["enum"], ["CHATGPT", "CLAUDE", "WORK", "OTHER"])

    def test_a_frozen_lane_must_be_disabled(self):
        bad = copy.deepcopy(V3)
        next(e for e in bad["loops"] if e["identity_state"] == "FROZEN")["enabled"] = True
        with self.assertRaises(ValueError):
            validate_registry(bad)

    def test_unknown_states_and_workers_are_still_rejected(self):
        for field, value in (("identity_state", "THAWED"), ("worker_kind", "GEMINI2")):
            bad = copy.deepcopy(V3)
            bad["loops"][1][field] = value
            with self.assertRaises(ValueError):
                validate_registry(bad)

    def test_production_registry_is_the_five_row_registry(self):
        self.assertEqual([e["loop_id"] for e in PROD["loops"]],
                         ["chatgpt-semi-auto", "chat-work-semi-auto", "claude-jules-auto", "symphony-codex-auto", "claude-claude-auto"])
        self.assertEqual([e["identity_state"] for e in PROD["loops"]].count("FROZEN"), 1)


class FrozenBehaviourTests(unittest.TestCase):
    def test_frozen_lane_is_not_an_active_lane_and_not_a_readiness_blocker(self):
        model = build_control_tower(V3, {}, generated_at=NOW)
        self.assertNotIn("claude-claude-auto", [lane.loop_id for lane in model.lanes])
        self.assertEqual(len(model.lanes), 4)
        self.assertEqual(model.frozen_lane_names, ("Claude -> Claude",))
        readiness = assess_registration_readiness(V3, None)
        self.assertEqual(readiness.status, "NOT_WIRED")
        self.assertNotIn("claude-claude-auto", readiness.reason)

    def test_frozen_lane_is_listed_apart_and_internal_ids_stay_out_of_the_visible_table(self):
        render = render_control_tower(build_control_tower(V3, {}, generated_at=NOW))
        self.assertIn("❄ **Frozen (not counted as active):** Claude -> Claude", render.body)
        table = render.body.split("<!-- phase0-control-tower-json:v1")[0]
        for internal in ("chat-work-semi-auto", "claude-jules-auto", "work-jules-auto", "claude-claude-auto", "chatgpt-semi-auto"):
            self.assertNotIn(internal, table)
        self.assertIn("Chat -> Work", table)

    def test_frozen_lane_does_not_change_the_title_counts(self):
        with_frozen = render_control_tower(build_control_tower(V3, {}, generated_at=NOW)).title
        without = copy.deepcopy(V3)
        without["loops"] = [e for e in without["loops"] if e["identity_state"] != "FROZEN"]
        self.assertEqual(with_frozen, render_control_tower(build_control_tower(without, {}, generated_at=NOW)).title)

    def test_registry_without_frozen_lanes_renders_exactly_as_before(self):
        four = {"schema_version": 1, "loops": [e for e in PROD["loops"] if e["identity_state"] != "FROZEN"]}
        render = render_control_tower(build_control_tower(four, {}, generated_at=NOW))
        self.assertNotIn("Frozen", render.body)
        self.assertIn("Frozen", render_control_tower(build_control_tower(PROD, {}, generated_at=NOW)).body)

    def test_work_worker_label_is_rendered(self):
        render = render_control_tower(build_control_tower(V3, {}, generated_at=NOW))
        self.assertIn("ChatGPT → Work", render.body)
        self.assertIn("Work → Jules", render.body)


if __name__ == "__main__":
    unittest.main()
