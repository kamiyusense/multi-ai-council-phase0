"""STATIC dry-run of the Control Tower body for the proposed registry. Pure rendering; nothing is written anywhere."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower import build_control_tower, render_control_tower

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "docs/evidence/signal-lane-model"
V3 = json.loads((DIR / "proposed-registry-v3-fixture.json").read_text(encoding="utf-8"))
SAVED = (DIR / "issue33-dry-run-render-v3.md").read_text(encoding="utf-8")
NOW = "2026-10-04T00:00:00Z"


class DryRunTests(unittest.TestCase):
    def setUp(self):
        self.render = render_control_tower(build_control_tower(V3, {}, generated_at=NOW))

    def test_the_saved_dry_run_equals_a_fresh_render(self):
        header, _, rest = SAVED.partition("\n")
        self.assertTrue(header.startswith("<!-- DRY RUN ONLY"))
        self.assertEqual(rest, self.render.title + "\n\n" + self.render.body)

    def test_no_lane_state_is_guessed_without_verified_input(self):
        states = {lane["display_state"] for lane in json.loads(self.render.snapshot_json)["loops"]}
        self.assertEqual(states, {"UNKNOWN"})
        for forbidden in ("STOPPED", "IDLE", "RUNNING", "🟢1", "🟣1"):
            self.assertNotIn(forbidden, self.render.title)

    def test_four_active_lanes_one_frozen_and_readable_names(self):
        loops = json.loads(self.render.snapshot_json)["loops"]
        self.assertEqual([l["display_name"] for l in loops], ["Chat -> Jules", "Chat -> Work", "Claude -> Jules", "Work -> Jules"])
        self.assertEqual([l["identity_state"] for l in loops], ["DURABLE", "PLACEHOLDER", "PLACEHOLDER", "PLACEHOLDER"])
        self.assertIn("Frozen (not counted as active):** Claude -> Claude", self.render.body)
        self.assertNotIn("claude-claude-auto", self.render.snapshot_json)

    def test_visible_part_hides_internal_ids(self):
        visible = self.render.body.split("<!-- phase0-control-tower-json:v1")[0]
        for internal in ("chatgpt-semi-auto", "chat-work-semi-auto", "claude-jules-auto", "work-jules-auto", "claude-claude-auto"):
            self.assertNotIn(internal, visible)

    def test_the_dry_run_writes_nothing(self):
        source = (ROOT / "automation/command_bus/control_tower.py").read_text(encoding="utf-8")
        for marker in ("urllib", "requests", "subprocess", "open("):
            self.assertNotIn(marker, source)


if __name__ == "__main__":
    unittest.main()
