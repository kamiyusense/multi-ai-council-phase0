"""STATIC checks of the SF-10 lane inventory and the open-PR classification (committed files only)."""
from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SF10 = ROOT / "docs/evidence/signal-sf10"
SUMMARY = json.loads((SF10 / "lane-inventory.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8"))
PRS = json.loads((SF10 / "open-pr-classification.json").read_text(encoding="utf-8"))
OTHER_LANES = ("claude-gemini", "claude-claude", "work-gemini")
CLASSES = {"DURABLE_READY", "READY_FOR_LIVE_PROOF", "STATIC_READY", "BLOCKED", "UNKNOWN"}
STATUS = {"PRESENT", "PARTIAL", "ABSENT", "UNKNOWN"}
FORBIDDEN_IDS = {"cloud-blue", "CW_BLUE_V1", "J-RED", "J-BLUE", "J-YELLOW", "J-GREEN", "auto-claude-gemini"}
PATH_REF = re.compile(r"^[A-Za-z0-9_./-]+\.[A-Za-z0-9]+(:[0-9,-]+)?$")


def lane(name):
    return json.loads((SF10 / "lane-inventory" / f"{name}.json").read_text(encoding="utf-8"))


def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


class InventoryShapeTests(unittest.TestCase):
    def test_summary_covers_the_four_registry_lanes_with_valid_classes(self):
        ids = [entry["lane_id"] for entry in SUMMARY["lanes"]]
        self.assertEqual(ids, [e["loop_id"] for e in REGISTRY["loops"]])
        for entry in SUMMARY["lanes"]:
            self.assertIn(entry["readiness_class"], CLASSES)
            self.assertTrue(entry["reason"])

    def test_identity_states_match_the_production_registry(self):
        states = {e["loop_id"]: e["identity_state"] for e in REGISTRY["loops"]}
        for entry in SUMMARY["lanes"]:
            self.assertEqual(entry["identity_state"].split()[0], states[entry["lane_id"]])

    def test_durable_lane_is_durable_ready_and_the_others_are_blocked(self):
        by_id = {e["lane_id"]: e for e in SUMMARY["lanes"]}
        self.assertEqual(by_id["chatgpt-semi-auto"]["readiness_class"], "DURABLE_READY")
        for name in OTHER_LANES:
            self.assertEqual(by_id[name]["readiness_class"], "BLOCKED", name)
            self.assertTrue(by_id[name]["missing_requirements"])
            self.assertIs(by_id[name]["new_live_needed"], True)
            self.assertIs(by_id[name]["human_approval_needed"], True)

    def test_no_lane_is_ready_for_live_so_no_proof_candidate_is_named(self):
        self.assertIsNone(SUMMARY["next_proof_candidate"])
        self.assertIsNone(SUMMARY["next_recommended_lane"])
        self.assertIs(SUMMARY["live_needed_now"], False)


class NoInventedIdentityTests(unittest.TestCase):
    def test_no_durable_loop_id_is_invented_for_any_lane(self):
        for name in OTHER_LANES:
            data = lane(name)
            stable = data["stable_durable_loop_id"]
            self.assertIs(stable["exists"], False, name)
            self.assertIsNone(stable["value_or_null"], name)
            self.assertEqual(data["current_identity_state"].split()[0], "PLACEHOLDER")
            self.assertNotIn(stable["value_or_null"], FORBIDDEN_IDS)

    def test_lane_ids_are_distinct_and_claude_lanes_do_not_share_an_identity(self):
        values = [lane(n)["lane_id"] for n in OTHER_LANES]
        self.assertEqual(len(set(values)), 3)
        self.assertEqual(values, list(OTHER_LANES))

    def test_every_lane_record_has_the_full_inventory_shape(self):
        required = {"controller_implementation", "worker_provider", "stable_durable_loop_id", "state_file", "owner_event_chain",
                    "generation", "fencing", "source_receipt", "canonical_evidence", "provider_verification",
                    "fresh_target_binding", "accepted_durable_transition", "collector_readback", "lane_registration_readiness",
                    "existing_live_proof", "existing_static_proof", "current_blockers", "minimum_next_component",
                    "new_live_needed", "human_approval_needed", "readiness_class", "readiness_reason",
                    "missing_requirements", "next_task"}
        for name in OTHER_LANES:
            data = lane(name)
            self.assertLessEqual(required, set(data), name)
            self.assertLessEqual({"upstream_accepted_source", "small_component", "existing_local_destination", "do", "do_not", "exit"},
                                 set(data["next_task"]), name)
            self.assertIn(data["readiness_class"], CLASSES)
            for key in ("state_file", "owner_event_chain", "generation", "fencing", "source_receipt", "canonical_evidence",
                        "provider_verification", "fresh_target_binding", "accepted_durable_transition",
                        "collector_readback", "lane_registration_readiness"):
                self.assertIn(data[key]["status"], STATUS, f"{name}.{key}")

    def test_no_past_live_proof_is_reused_as_adoption_authority(self):
        for name in OTHER_LANES:
            text = json.dumps(lane(name)["existing_live_proof"]).lower()
            self.assertTrue("proof 5" in text or "none" in text or "no " in text, name)
            self.assertNotIn("reuse as authority: yes", text)

    def test_cited_source_files_exist(self):
        for name in OTHER_LANES:
            for key, value in walk(lane(name)):
                if key == "source_refs":
                    for ref in value:
                        if PATH_REF.match(ref):
                            self.assertTrue(os.path.exists(ROOT / ref.split(":")[0]), f"{name}: {ref}")


class PrClassificationTests(unittest.TestCase):
    def test_classification_values_and_no_destructive_actions(self):
        allowed = {"SUPERSEDED", "HISTORICAL_EVIDENCE", "ACTIVE_DEPENDENCY", "KEEP_OPEN", "SAFE_TO_CLOSE", "UNKNOWN"}
        for item in PRS["prs"]:
            self.assertIn(item["class"], allowed)
        self.assertEqual((PRS["prs_closed"], PRS["branches_deleted"]), (0, 0))
        by_number = {item["number"]: item["class"] for item in PRS["prs"]}
        self.assertEqual(by_number[286], "ACTIVE_DEPENDENCY")
        self.assertEqual(by_number[278], "ACTIVE_DEPENDENCY")


if __name__ == "__main__":
    unittest.main()
