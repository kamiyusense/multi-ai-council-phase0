"""STATIC checks of the applied chatgpt-semi-auto DURABLE adoption (registry flip) and its guard.

Reads only committed files. No network, no provider call, no workflow dispatch.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from automation.command_bus import durable_adoption_approval as dap
from automation.command_bus import durable_adoption_approval_cli as cli
from automation.command_bus.control_tower_registration import assess_registration_readiness
from automation.command_bus.lane_identity_adoption import registry_digest
from automation.command_bus.tests import pre_adoption_registry as helper

ROOT = Path(__file__).resolve().parents[3]
LANE = "chatgpt-semi-auto"
PRODUCTION = json.loads((ROOT / cli.REGISTRY_PATH).read_text(encoding="utf-8"))
APPROVAL = json.loads(helper.APPROVAL_PATH.read_text(encoding="utf-8"))
SF8 = ROOT / "docs/evidence/signal-sf8"


def states(registry):
    return {e["loop_id"]: e["identity_state"] for e in registry["loops"]}


class AppliedAdoptionTests(unittest.TestCase):
    def test_exactly_one_lane_is_durable_and_it_is_the_approved_one(self):
        self.assertEqual(dap.durable_lanes(PRODUCTION), (LANE,))
        others = {k: v for k, v in states(PRODUCTION).items() if k != LANE}
        self.assertEqual(len(others), 3)
        self.assertEqual(set(others.values()), {"PLACEHOLDER"})

    def test_registry_equals_the_proposal_the_approval_was_bound_to(self):
        self.assertEqual(registry_digest(PRODUCTION), APPROVAL["proposed_registry_sha256"])
        self.assertEqual(registry_digest(PRODUCTION),
                         registry_digest(json.loads((SF8 / "registry-candidate-chatgpt-semi-auto-durable.json").read_text())))

    def test_committed_approval_is_valid_as_of_its_own_issue_time(self):
        self.assertEqual(cli.verify_file(helper.APPROVAL_PATH, ROOT, APPROVAL["approved_at"]), LANE)
        self.assertEqual(APPROVAL["accepted_deviation"], "MISSING_TRAILING_NEWLINE_ONLY")
        self.assertEqual(APPROVAL["approved_by_actor_id"], "20355232")
        self.assertNotIn(APPROVAL["approval_ref"].rsplit("/", 1)[-1], dap.KNOWN_AUTHORITY_RUN_IDS)

    def test_diff_against_the_pre_adoption_registry_is_one_identity_state(self):
        before = helper.pre_adoption(PRODUCTION)
        dap.check_single_lane_diff(before, PRODUCTION, LANE)
        self.assertEqual(registry_digest(before), APPROVAL["current_registry_sha256"])

    def test_global_registration_stays_not_wired_with_three_placeholder_lanes(self):
        result = assess_registration_readiness(PRODUCTION, None)
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.placeholder_loop_ids, ("claude-gemini", "claude-claude", "work-gemini"))

    def test_issue_33_candidate_stays_stopped(self):
        candidate = json.loads((ROOT / "docs/evidence/signal-step7-proof5/adoption-candidate.json").read_text())
        self.assertIs(candidate["issue33_changed_by_this_candidate"], False)
        for entry in PRODUCTION["loops"]:
            if entry["loop_id"] == LANE:
                self.assertEqual(entry["safe_detail_ref"], "issue:33")


class GuardTests(unittest.TestCase):
    def test_pre_adoption_returns_the_old_all_placeholder_registry(self):
        before = helper.pre_adoption(PRODUCTION)
        self.assertEqual(set(states(before).values()), {"PLACEHOLDER"})
        self.assertEqual(registry_digest(before), "6af0268e17fd99adf4901e6a3be294c7e24c3b38241281a7b4cb0571b36b5eb0")

    def test_a_second_durable_lane_is_refused(self):
        tampered = copy.deepcopy(PRODUCTION)
        for entry in tampered["loops"]:
            if entry["loop_id"] == "claude-gemini":
                entry["identity_state"] = "DURABLE"
        with self.assertRaises(AssertionError):
            helper.pre_adoption(tampered)

    def test_durable_lane_without_an_approval_record_is_refused(self):
        with mock.patch.object(helper, "APPROVAL_PATH", ROOT / "docs/evidence/signal-step7-proof5/missing.json"):
            with self.assertRaises(AssertionError):
                helper.pre_adoption(PRODUCTION)

    def test_registry_that_differs_from_the_approved_proposal_is_refused(self):
        tampered = copy.deepcopy(PRODUCTION)
        tampered["loops"][0]["display_order"] += 1
        with self.assertRaises(AssertionError):
            helper.pre_adoption(tampered)

    def test_an_approval_for_the_wrong_digest_fails_verification(self):
        import tempfile
        forged = dict(APPROVAL, proposed_registry_sha256="0" * 64)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "approval.json"
            path.write_text(json.dumps(forged))
            with self.assertRaises(dap.ApprovalError) as ctx:
                cli.verify_file(path, ROOT, APPROVAL["approved_at"])
        self.assertEqual(ctx.exception.code, "WRONG_PROPOSED_REGISTRY")


if __name__ == "__main__":
    unittest.main()
