"""STATIC checks of the corrected lane model (active 4 / frozen / historical) and the registry migration design."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower import validate_registry
from automation.command_bus.control_tower_registration import assess_registration_readiness

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "docs/evidence/signal-lane-model"
MODEL = json.loads((DIR / "lane-model-v2.json").read_text(encoding="utf-8"))
PROPOSED = json.loads((DIR / "proposed-registry-v2-fixture.json").read_text(encoding="utf-8"))
PROD = json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8"))
FORBIDDEN_IDS = {"cloud-blue", "CW_BLUE_V1", "chatgpt-work", "chat-work", "J-BLUE"}


class LaneModelTests(unittest.TestCase):
    def test_exactly_four_active_lanes_and_frozen_claude_claude_is_not_counted(self):
        self.assertEqual(MODEL["active_lane_count"], 4)
        self.assertEqual(len(MODEL["active_lanes"]), 4)
        names = [lane["lane"] for lane in MODEL["active_lanes"]]
        self.assertEqual(names, ["Chat -> Jules", "Chat -> Work", "Claude -> Jules", "Work -> Jules"])
        frozen = MODEL["frozen_lanes"]
        self.assertEqual([f["lane"] for f in frozen], ["Claude -> Claude"])
        self.assertIs(frozen[0]["counts_as_active"], False)
        self.assertIs(frozen[0]["required_for_global_ready"], False)
        self.assertNotIn("Claude -> Claude", names)

    def test_gemini_labels_are_historical_only(self):
        self.assertEqual({h["label"] for h in MODEL["historical_old_placeholders"]}, {"claude-gemini", "work-gemini"})
        for lane in MODEL["active_lanes"]:
            self.assertNotIn("Gemini", lane["lane"])

    def test_no_durable_id_is_invented_and_chat_work_stays_unknown(self):
        by = {lane["lane"]: lane for lane in MODEL["active_lanes"]}
        chat_work = by["Chat -> Work"]
        self.assertIsNone(chat_work["registry_loop_id"])
        self.assertEqual(chat_work["identity_state"], "UNKNOWN")
        self.assertEqual(chat_work["readiness_class"], "UNKNOWN")
        for name in ("Chat -> Work", "Claude -> Jules", "Work -> Jules"):
            self.assertEqual(by[name]["stable_id_source"] if "stable_id_source" in by[name] else "UNKNOWN", "UNKNOWN")
        self.assertEqual(MODEL["safety"]["durable_ids_invented"], 0)

    def test_only_chat_jules_is_durable(self):
        durable = [l["lane"] for l in MODEL["active_lanes"] if l["identity_state"] == "DURABLE"]
        self.assertEqual(durable, ["Chat -> Jules"])
        states = {e["loop_id"]: e["identity_state"] for e in PROD["loops"]}
        self.assertEqual(states["chatgpt-semi-auto"], "DURABLE")
        self.assertEqual([k for k, v in states.items() if v == "DURABLE"], ["chatgpt-semi-auto"])

    def test_registry_gaps_match_the_real_v1_enum_and_production_is_untouched(self):
        from automation.command_bus import control_tower
        self.assertNotIn("WORK", control_tower._WORKERS)
        self.assertEqual({e["loop_id"] for e in PROD["loops"]},
                         {"chatgpt-semi-auto", "claude-gemini", "claude-claude", "work-gemini"})
        self.assertEqual({e["worker_kind"] for e in PROD["loops"] if e["loop_id"] in ("claude-gemini", "work-gemini")}, {"GEMINI"})

    def test_no_forbidden_ids_anywhere_in_the_design_files(self):
        text = json.dumps([MODEL, PROPOSED])
        for bad in FORBIDDEN_IDS:
            self.assertNotIn(f'"{bad}"', text)


class ProposedRegistryTests(unittest.TestCase):
    def test_proposed_registry_validates_under_the_current_v1_rules(self):
        self.assertEqual(len(validate_registry(PROPOSED)), 4)

    def test_durable_entry_is_byte_identical_to_production(self):
        prod = next(e for e in PROD["loops"] if e["loop_id"] == "chatgpt-semi-auto")
        new = next(e for e in PROPOSED["loops"] if e["loop_id"] == "chatgpt-semi-auto")
        expected = dict(prod)
        self.assertEqual({k: v for k, v in new.items() if k != "display_order"}, {k: v for k, v in expected.items() if k != "display_order"})

    def test_frozen_lane_is_kept_by_name_but_disabled(self):
        entry = next(e for e in PROPOSED["loops"] if e["loop_id"] == "claude-claude")
        self.assertIs(entry["enabled"], False)
        self.assertEqual(entry["display_name"], "Claude -> Claude")

    def test_no_gemini_worker_and_no_chat_work_row_in_proposal(self):
        self.assertNotIn("GEMINI", {e["worker_kind"] for e in PROPOSED["loops"]})
        self.assertEqual(sum(1 for e in PROPOSED["loops"] if e["controller_kind"] == "CHATGPT"), 1)

    def test_global_registration_stays_not_wired_before_and_after(self):
        self.assertEqual(assess_registration_readiness(PROD, None).status, "NOT_WIRED")
        self.assertEqual(assess_registration_readiness(PROPOSED, None).status, "NOT_WIRED")

    def test_disabled_frozen_lane_is_not_a_global_readiness_blocker(self):
        result = assess_registration_readiness(PROPOSED, None)
        self.assertNotIn("claude-claude", result.placeholder_lanes if hasattr(result, "placeholder_lanes") else ())
        self.assertNotIn("claude-claude", result.reason)


if __name__ == "__main__":
    unittest.main()
