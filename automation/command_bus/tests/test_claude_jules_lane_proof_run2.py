"""STATIC tests for the SECOND bounded Claude -> Jules stable-lane proof profile (proof 2).

Fixtures and fakes only: no network, no Jules POST/GET, no provider execution, no LIVE, no ledger/registry write.
Proof 2 must be a brand-new identity (task id, evidence directory, spent-loop list, expected ledger count) and the
spent proof 1 must stay refused.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from automation.command_bus import claude_jules_lane_proof as proof
from automation.command_bus import claude_jules_lane_proof_cli as cli
from automation.command_bus.tests.test_claude_jules_lane_proof import (
    AUTH, FORBIDDEN_SESSIONS, FakePorts, plan as plan_run1)
from automation.command_bus.tests.test_claude_jules_lane_proof_cli import REGISTRY, FixedClock
from automation.command_bus.tests.test_lane_runtime_export import PROD, adopted_registry

RUN2 = proof.PROOF_TASK_ID_2
AUTH2 = {**AUTH, "scope": "claude-jules-auto proof 2", "approval_ref": "cmsg_fixture_live_approval_2"}


def plan2(**changes):
    return plan_run1(proof_task_id=RUN2, origin_loop_id="claude-auto-loop-a-004", live_authorization=AUTH2, **changes)


class ProfileTests(unittest.TestCase):
    def test_run2_is_bound_to_ledger_count_6_and_all_spent_loops(self):
        p = plan2()
        self.assertEqual((p["proof_task_id"], p["loop_a_slots_used_before"]), (RUN2, 6))
        self.assertEqual(p["forbidden_loop_numbers"], [128, 129, 130, 131, 137, 138, 139])
        self.assertEqual(proof.RUN_PROFILES[RUN2]["slots_used_before"] + 1, 7)  # still inside the 10 cap

    def test_run1_profile_is_unchanged(self):
        p = plan_run1()
        self.assertEqual((p["proof_task_id"], p["loop_a_slots_used_before"]), (proof.PROOF_TASK_ID, 4))

    def test_unknown_run_ids_are_refused_when_building_and_validating(self):
        for bad in ("claude-jules-stable-lane-proof-3", "", "claude-jules-stable-lane-proof-2 "):
            with self.assertRaises(proof.ProofError) as caught:
                plan_run1(proof_task_id=bad)
            self.assertEqual(caught.exception.code, "PLAN_UNKNOWN_RUN")
        forged = {**copy.deepcopy(plan2()), "proof_task_id": "claude-jules-stable-lane-proof-3"}
        forged["plan_sha256"] = proof._digest(forged, "plan_sha256")
        with self.assertRaises(proof.ProofError) as caught:
            proof.validate_proof_plan(forged, registry=None)
        self.assertEqual(caught.exception.code, "PLAN_UNKNOWN_RUN")

    def test_cross_profile_tamper_is_rejected_even_when_resigned(self):
        base = plan2()
        for name, changes in {
            "run2 with run1 count": {"loop_a_slots_used_before": 4},
            "run2 with run1 loops": {"forbidden_loop_numbers": [128, 129, 130, 131]},
            "run2 over cap": {"loop_a_slots_used_before": 10},
            "run2 with a lower count": {"loop_a_slots_used_before": 5},
        }.items():
            bad = {**copy.deepcopy(base), **changes}
            bad["plan_sha256"] = proof._digest(bad, "plan_sha256")
            with self.assertRaises(proof.ProofError, msg=name):
                proof.validate_proof_plan(bad, registry=None)
        swapped = {**copy.deepcopy(plan_run1()), "proof_task_id": RUN2}  # run 1 numbers under the run 2 id
        swapped["plan_sha256"] = proof._digest(swapped, "plan_sha256")
        with self.assertRaises(proof.ProofError):
            proof.validate_proof_plan(swapped, registry=None)

    def test_evidence_paths_are_per_run_and_never_collide(self):
        marker1, receipt1 = proof.evidence_paths(proof.PROOF_TASK_ID)
        marker2, receipt2 = proof.evidence_paths(RUN2)
        self.assertEqual((marker1, receipt1), (proof.ATTEMPT_MARKER_PATH, proof.TERMINAL_RECEIPT_PATH))
        self.assertEqual(marker2, "docs/evidence/claude-jules-stable-lane-proof-2/attempt-marker.json")
        self.assertEqual(receipt2, "docs/evidence/claude-jules-stable-lane-proof-2/terminal-receipt.json")
        self.assertFalse({marker1, receipt1} & {marker2, receipt2})
        with self.assertRaises(proof.ProofError):
            proof.evidence_paths("claude-jules-stable-lane-proof-9")

    def test_session_of_proof1_is_forbidden_for_run2(self):
        self.assertIn("17540857576922617403", cli.OLD_SESSION_IDS)
        self.assertTrue(set(FORBIDDEN_SESSIONS) <= set(cli.OLD_SESSION_IDS))


class Run2DriverTests(unittest.TestCase):
    def run_it(self, p, **port_kw):
        ports = FakePorts(p, **port_kw)
        result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        return ports, result

    def test_run2_writes_only_its_own_evidence_directory_with_one_post_one_get(self):
        ports, result = self.run_it(plan2())
        self.assertEqual((result.status, result.code), ("COMPLETE", "OK"))
        self.assertEqual((ports.count("dispatch"), ports.count("read_session")), (1, 1))
        marker, receipt = proof.evidence_paths(RUN2)
        self.assertEqual(ports.files[receipt]["proof_task_id"], RUN2)
        self.assertEqual(ports.files[marker]["proof_task_id"], RUN2)
        self.assertFalse(ports.files[receipt]["rerun_allowed"])
        self.assertNotIn(proof.ATTEMPT_MARKER_PATH, ports.files)  # run 1's spent files are never touched
        self.assertNotIn(proof.TERMINAL_RECEIPT_PATH, ports.files)
        self.assertEqual(result.candidate["proof_task_id"], RUN2)

    def test_run1_spent_marker_does_not_block_run2_but_run2_marker_blocks_run2(self):
        p = plan2()
        ports = FakePorts(p)
        ports.files[proof.ATTEMPT_MARKER_PATH] = {"spent": "run 1"}
        first = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        again = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        self.assertEqual((first.status, again.code), ("COMPLETE", "ALREADY_ATTEMPTED"))
        self.assertEqual(ports.count("dispatch"), 1)

    def test_run2_marker_present_from_a_crash_refuses_with_zero_calls(self):
        p = plan2()
        ports = FakePorts(p)
        ports.files[proof.evidence_paths(RUN2)[0]] = {"crashed": True}
        result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        self.assertEqual((result.status, result.code), ("STOPPED", "ALREADY_ATTEMPTED"))
        self.assertEqual((ports.count("dispatch"), ports.count("read_session")), (0, 0))

    def test_spent_loop_number_in_a_run2_dispatch_receipt_is_refused(self):
        p = plan2()
        for number in (137, 138, 139):
            class Spent(FakePorts):
                def dispatch(self, plan_):
                    from automation.command_bus.tests.test_claude_jules_lane_proof import dispatch_receipt
                    self.calls.append(("dispatch",))
                    return dispatch_receipt(self.p, loop_id=f"loop-{number}")
            ports = Spent(p)
            result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
            self.assertNotEqual(result.status, "COMPLETE", msg=number)
            self.assertIsNone(result.candidate)

    def test_unauthorized_or_expired_run2_plan_writes_nothing(self):
        for p, now in ((plan_run1(proof_task_id=RUN2, origin_loop_id="claude-auto-loop-a-004"), "2026-10-04T10:00:00Z"),
                       (plan2(), "2026-10-06T00:00:00Z")):
            ports = FakePorts(p, now=now)
            result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
            self.assertEqual((result.status, ports.calls, ports.files), ("STOPPED", [], {}))


def _policy():
    return {"schema_version": 1, "profile": "CLAUDE_AUTO_JULES_POLICY_V1", "controller_id": "claude-auto",
            "holder_id": "h", "target_repo": "o/r", "default_branch": "main", "carrier_branch": "carrier",
            "data_branch": "data", "allowed_target_branches": ["claude/target"], "allowed_lane_ids": [],
            "expected_pr": 7, "max_rounds": 6, "live_dispatch_authorization": None}


class CliBudgetTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        os.makedirs(os.path.join(self.dir.name, "automation/command_bus/config"))
        with open(os.path.join(self.dir.name, cli.REGISTRY_PATH), "w") as handle:
            json.dump(REGISTRY, handle)

    def _write(self, name, data):
        path = os.path.join(self.dir.name, name)
        with open(path, "w") as handle:
            json.dump(data, handle)
        return path

    def _args(self, plan_doc):
        return ["run", "--repo-dir", self.dir.name, "--plan", self._write("plan.json", plan_doc),
                "--policy", self._write("p.json", _policy()), "--roadmap", self._write("r.json", {}),
                "--lane-id", "y"]

    def _run(self, plan_doc, slots):
        env = {"CLAUDE_JULES_PROOF_CONFIRM": f"RUN_ONCE_{plan_doc['plan_sha256']}", "JULES_API_KEY": "k"}
        with patch.object(cli, "GitLiveClient") as git, patch.object(cli, "GitHubRestReader"), \
                patch.object(cli, "LiveBudgetLedger") as ledger, patch.object(cli, "PrepareOnlyLoop") as loop, \
                patch.object(cli, "build_live_proof_ports") as ports, patch.dict(os.environ, env, clear=True):
            ledger.return_value.slots.return_value = list(range(slots))
            code = cli.main(self._args(plan_doc), FixedClock())
        return code, git, loop, ports

    def test_run2_plan_needs_exactly_six_ledger_slots(self):
        plan_doc = copy.deepcopy(plan2())
        plan_doc["expires_at"] = "2026-10-05T03:00:00Z"
        plan_doc["live_authorization"] = {**AUTH2, "expires_at": "2026-10-05T02:00:00Z"}
        plan_doc["plan_sha256"] = proof._digest(plan_doc, "plan_sha256")
        for slots in (0, 4, 5, 7, 10):
            code, git, loop, ports = self._run(plan_doc, slots)
            self.assertEqual(code, 2, msg=slots)
            loop.assert_not_called()  # refused before the planner and before any port is built
            ports.assert_not_called()

    def test_run1_plan_is_refused_now_that_the_ledger_is_past_it(self):
        plan_doc = copy.deepcopy(plan_run1(live_authorization=AUTH))
        plan_doc["expires_at"] = "2026-10-05T03:00:00Z"
        plan_doc["live_authorization"] = {**AUTH, "expires_at": "2026-10-05T02:00:00Z"}
        plan_doc["plan_sha256"] = proof._digest(plan_doc, "plan_sha256")
        code, _, loop, ports = self._run(plan_doc, 6)
        self.assertEqual(code, 2)
        loop.assert_not_called()
        ports.assert_not_called()

    def test_cli_plan_command_can_only_name_a_known_run(self):
        policy = self._write("policy.json", _policy())
        base = ["plan", "--repo-dir", self.dir.name, "--policy", policy, "--origin-loop-id", "claude-auto-loop-a-004",
                "--origin-generation", "1"]
        with patch.object(cli, "GitLiveClient") as git:
            git.return_value.get_branch_head.return_value = "a" * 40
            git.return_value.get_commit_tree.return_value = "b" * 40
            self.assertEqual(cli.main(base + ["--proof-task-id", "claude-jules-stable-lane-proof-3"], FixedClock()), 2)
            self.assertEqual(cli.main(base + ["--proof-task-id", RUN2], FixedClock()), 0)


if __name__ == "__main__":
    unittest.main()
