"""STATIC checks of the lane naming policy (fixed machine ids, readable display names, reserved new ids)."""
from __future__ import annotations

import copy
import json
import os
import re
import unittest
from pathlib import Path

from automation.command_bus.control_tower import _LABEL, _LOOP_ID, validate_registry
from automation.command_bus.control_tower_registration import assess_registration_readiness
from automation.command_bus.runtime_state_initializer import runtime_state_path

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "docs/evidence/signal-lane-model"
POLICY = json.loads((DIR / "lane-naming-policy-v1.json").read_text(encoding="utf-8"))
V3 = json.loads((DIR / "proposed-registry-v3-fixture.json").read_text(encoding="utf-8"))
PROD = json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8"))
IDS = {"chatgpt-semi-auto", "chat-work-semi-auto", "claude-jules-auto", "work-jules-auto", "claude-claude-auto"}


class PolicyTests(unittest.TestCase):
    def test_the_five_ids_match_the_owner_decision_and_are_valid_and_distinct(self):
        ids = [lane["internal_id"] for lane in POLICY["lanes"]]
        self.assertEqual(set(ids), IDS)
        self.assertEqual(len(ids), len(set(ids)))
        for lane_id in ids:
            self.assertRegex(lane_id, _LOOP_ID)
        for lane in POLICY["lanes"]:
            self.assertRegex(lane["display"], _LABEL)

    def test_durable_id_is_fixed_and_new_ids_are_only_reserved_names(self):
        by = {lane["internal_id"]: lane for lane in POLICY["lanes"]}
        self.assertEqual(by["chatgpt-semi-auto"]["id_status"], "DURABLE_FIXED")
        for lane_id in IDS - {"chatgpt-semi-auto"}:
            self.assertEqual(by[lane_id]["id_status"], "RESERVED_NAME_NOT_DURABLE")
            self.assertEqual(by[lane_id]["identity_state"], "PLACEHOLDER")
        self.assertEqual(by["claude-claude-auto"]["state"], "FROZEN")

    def test_no_reserved_id_has_any_durable_state_or_evidence_on_main(self):
        for lane_id in IDS - {"chatgpt-semi-auto"}:
            self.assertFalse(os.path.exists(ROOT / runtime_state_path(lane_id)), lane_id)
            hits = [p for p in (ROOT / "docs/evidence").rglob("*.json")
                    if re.search(r"(?<![\w-])" + re.escape(lane_id) + r"(?![\w-])", p.read_text(encoding="utf-8", errors="ignore"))
                    and DIR not in p.parents]
            self.assertEqual(hits, [], lane_id)

    def test_old_labels_map_as_historical_only(self):
        self.assertEqual(POLICY["old_labels_historical"], {
            "claude-gemini": "claude-jules-auto", "work-gemini": "work-jules-auto", "claude-claude": "claude-claude-auto"})

    def test_internal_id_is_not_shown_in_the_list_view_but_in_the_detail_view(self):
        rules = POLICY["display_rules"]
        self.assertIs(rules["internal_id_in_list_view"], False)
        self.assertIn("Durable ID", rules["detail_view"])

    def test_the_runtime_table_already_hides_the_internal_id(self):
        text = (ROOT / "automation/command_bus/control_tower.py").read_text(encoding="utf-8")
        table = text[text.index("def _render_runtime_content"):text.index("def _cell")]
        self.assertNotIn("lane.loop_id", table.split("SNAPSHOT_START")[0])

    def test_registry_change_list_names_the_whole_digest_pin_hazard(self):
        joined = " ".join(POLICY["registry_changes_needed_not_applied"])
        self.assertIn("WHOLE production registry digest", joined)
        self.assertIn("WORK", joined)


class FixtureTests(unittest.TestCase):
    def test_chatgpt_semi_auto_row_differs_from_production_only_by_display_name(self):
        prod = next(e for e in PROD["loops"] if e["loop_id"] == "chatgpt-semi-auto")
        new = next(e for e in V3["loops"] if e["loop_id"] == "chatgpt-semi-auto")
        diff = {k for k in prod if prod[k] != new[k]}
        self.assertEqual(diff, {"display_name"})
        self.assertEqual(new["identity_state"], "DURABLE")

    def test_only_one_durable_and_frozen_lane_is_disabled(self):
        self.assertEqual([e["loop_id"] for e in V3["loops"] if e["identity_state"] == "DURABLE"], ["chatgpt-semi-auto"])
        frozen = [e for e in V3["loops"] if e["identity_state"] == "FROZEN"]
        self.assertEqual([e["loop_id"] for e in frozen], ["claude-claude-auto"])
        self.assertIs(frozen[0]["enabled"], False)

    def test_v1_rejects_exactly_the_two_missing_features(self):
        with self.assertRaises(ValueError):
            validate_registry(V3)
        adapted = copy.deepcopy(V3)
        for entry in adapted["loops"]:
            if entry["worker_kind"] == "WORK":
                entry["worker_kind"] = "OTHER"
            if entry["identity_state"] == "FROZEN":
                entry["identity_state"] = "PLACEHOLDER"
        self.assertEqual(len(validate_registry(adapted)), 5)
        self.assertEqual(assess_registration_readiness(adapted, None).status, "NOT_WIRED")

    def test_production_registry_is_untouched(self):
        self.assertEqual([e["loop_id"] for e in PROD["loops"]],
                         ["chatgpt-semi-auto", "claude-gemini", "claude-claude", "work-gemini"])
        self.assertEqual(PROD["loops"][0]["display_name"], "ChatGPT Semi-Auto")


if __name__ == "__main__":
    unittest.main()
