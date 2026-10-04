"""STATIC tests of the production registry guard that replaced the whole-registry digest pin.

Reads committed files only. No network, no provider call, no workflow dispatch, no registry or Issue write.
The historical DURABLE_ADOPTION_APPROVAL_V1 stays bound to the committed candidate; the live registry is checked
against the approved entry (all fields except display_name).
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus import durable_adoption_approval_cli as cli
from automation.command_bus.lane_identity_adoption import registry_digest

ROOT = Path(__file__).resolve().parents[3]
LANE = "chatgpt-semi-auto"
PROD = json.loads((ROOT / cli.REGISTRY_PATH).read_text(encoding="utf-8"))
CANDIDATE = json.loads((ROOT / cli.CANDIDATE_REGISTRY_PATH).read_text(encoding="utf-8"))
APPROVAL = json.loads((ROOT / "docs/evidence/signal-step7-proof5/durable-adoption-approval.json").read_text(encoding="utf-8"))


def mutated(fn):
    reg = copy.deepcopy(PROD)
    fn(reg)
    return cli.production_registry_guard(reg, ROOT)


def row(reg, loop_id):
    return next(e for e in reg["loops"] if e["loop_id"] == loop_id)


class GuardTests(unittest.TestCase):
    def test_live_five_row_registry_passes(self):
        self.assertEqual(cli.production_registry_guard(PROD, ROOT), [])
        self.assertEqual(len(PROD["loops"]), 5)

    def test_display_name_is_the_only_field_that_may_change(self):
        self.assertEqual(mutated(lambda r: row(r, LANE).update(display_name="Anything else")), [])

    def test_each_durable_field_mutation_is_rejected(self):
        changes = {"loop_id": "chatgpt-semi-auto-2", "mode": "AUTO", "controller_kind": "CLAUDE", "worker_kind": "WORK",
                   "display_order": 99, "enabled": False, "safe_detail_ref": "issue:34", "identity_state": "PLACEHOLDER"}
        for field, value in changes.items():
            self.assertTrue(mutated(lambda r, f=field, v=value: row(r, LANE).update({f: v})), field)

    def test_extra_field_on_the_adopted_row_is_rejected(self):
        self.assertIn("ADOPTED_LANE_CHANGED", mutated(lambda r: row(r, LANE).update(note="x")))

    def test_second_durable_lane_is_rejected(self):
        for other in ("chat-work-semi-auto", "claude-jules-auto", "work-jules-auto"):
            failures = mutated(lambda r, o=other: row(r, o).update(identity_state="DURABLE"))
            self.assertIn("SECOND_DURABLE_LANE", failures, other)
            self.assertIn("ACTIVE_LANE_NOT_PLACEHOLDER", failures, other)

    def test_enabled_frozen_lane_is_rejected(self):
        self.assertIn("FROZEN_LANE_ENABLED", mutated(lambda r: row(r, "claude-claude-auto").update(enabled=True)))

    def test_active_non_placeholder_row_is_rejected(self):
        self.assertIn("ACTIVE_LANE_NOT_PLACEHOLDER",
                      mutated(lambda r: row(r, "work-jules-auto").update(identity_state="FROZEN")))

    def test_missing_adopted_row_is_rejected(self):
        self.assertIn("ADOPTED_LANE_MISSING_OR_NOT_DURABLE",
                      mutated(lambda r: r.update(loops=[e for e in r["loops"] if e["loop_id"] != LANE])))

    def test_new_placeholder_rows_alone_are_not_adoption(self):
        only_new = {"schema_version": 1, "loops": [e for e in PROD["loops"] if e["loop_id"] != LANE]}
        self.assertIn("ADOPTED_LANE_MISSING_OR_NOT_DURABLE", cli.production_registry_guard(only_new, ROOT))
        for other in ("chat-work-semi-auto", "claude-jules-auto", "work-jules-auto"):
            self.assertEqual(row(PROD, other)["identity_state"], "PLACEHOLDER")


class HistoricalApprovalTests(unittest.TestCase):
    def test_approval_stays_bound_to_the_committed_candidate_not_the_live_file(self):
        current, proposed = cli.registries_from_candidate(ROOT)
        self.assertEqual(APPROVAL["current_registry_sha256"], registry_digest(current))
        self.assertEqual(APPROVAL["proposed_registry_sha256"], registry_digest(proposed))
        self.assertEqual(proposed, CANDIDATE)
        self.assertNotEqual(registry_digest(PROD), APPROVAL["proposed_registry_sha256"])

    def test_approval_verifies_against_the_candidate(self):
        self.assertEqual(cli.verify_file(ROOT / "docs/evidence/signal-step7-proof5/durable-adoption-approval.json",
                                         ROOT, APPROVAL["approved_at"]), LANE)

    def test_the_issuer_stops_on_the_live_registry(self):
        with self.assertRaises(cli.Stop) as caught:
            cli.registries_from_production(ROOT)
        self.assertEqual(caught.exception.code, "PROPOSED_REGISTRY_IS_NOT_THE_COMMITTED_CANDIDATE")


if __name__ == "__main__":
    unittest.main()
