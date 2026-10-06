from __future__ import annotations

import json
import unittest

from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_campaign import legacy_campaign_policy
from automation.command_bus.claude_jules_inspection import InspectionStore
from automation.command_bus.claude_jules_recovery import (
    EvidenceRecoveryStore, HARD_UNKNOWN, TRANSIENT_UNKNOWN,
    recovery_path, validate_recovery_record,
)
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    DATA, LOOP, NOW, roadmap, task_spec,
)
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World


def campaign(w: World, retries: int) -> dict:
    value = legacy_campaign_policy(w.policy, campaign_id=LOOP)
    return dict(value, max_transient_retries=retries)


def controller(w: World, retries: int) -> ClaudeJulesAutoLoop:
    return ClaudeJulesAutoLoop(
        client=w.github, refs=w.github, policy=w.policy,
        owner_reader=LoopOwnerGitHubBackend(w.github, branch=DATA),
        roadmap=w.roadmap, facts=w.facts, origin_loop_id=LOOP, lane_id="J-BLUE",
        campaign_policy=campaign(w, retries),
    )


def dispatch_and_deliver(w: World, retries: int) -> str:
    dispatched = controller(w, retries).step(now=NOW)
    assert dispatched.status == "DISPATCHED", dispatched.reason
    command_id = dispatched.details["command_id"]
    w.deliver(w.jules.run(command_id))
    return command_id


class EvidenceRecoveryStoreTests(unittest.TestCase):
    def test_record_is_create_only_digest_bound_and_contiguous(self):
        w = World(plan=roadmap(task_spec("alpha-helper")))
        store = EvidenceRecoveryStore(w.github, data_branch=DATA)
        head = w.github.branches[w.policy["allowed_target_branches"][0]]
        first = store.record_failure(
            command_id="relay-dev-loop-777-recovery", candidate_head=head,
            missing=["test_evidence"], reason="runner temporarily unavailable",
            observed_at=NOW, max_retries=2,
        )
        self.assertEqual(first.status, "CREATED")
        self.assertEqual(first.record["attempt"], 1)
        self.assertFalse(first.record["mutating_action_retried"])
        self.assertEqual(validate_recovery_record(first.record), first.record)

        second = store.record_failure(
            command_id="relay-dev-loop-777-recovery", candidate_head=head,
            missing=["test_evidence"], reason="runner temporarily unavailable",
            observed_at=NOW, max_retries=2,
        )
        self.assertEqual((second.status, second.record["attempt"]), ("CREATED", 2))
        exhausted = store.record_failure(
            command_id="relay-dev-loop-777-recovery", candidate_head=head,
            missing=["test_evidence"], reason="runner temporarily unavailable",
            observed_at=NOW, max_retries=2,
        )
        self.assertEqual(exhausted.status, "EXHAUSTED")

    def test_tampered_recovery_record_is_rejected(self):
        w = World(plan=roadmap(task_spec("alpha-helper")))
        store = EvidenceRecoveryStore(w.github, data_branch=DATA)
        head = w.github.branches[w.policy["allowed_target_branches"][0]]
        result = store.record_failure(
            command_id="relay-dev-loop-778-recovery", candidate_head=head,
            missing=["compare"], reason="temporary read failure", observed_at=NOW, max_retries=2,
        )
        tampered = dict(result.record, reason="changed")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            validate_recovery_record(tampered)
        self.assertTrue(recovery_path("relay-dev-loop-778-recovery", head, 1).endswith("attempt-01.json"))


class TransientRecoveryIntegrationTests(unittest.TestCase):
    def test_transient_test_evidence_recovers_without_persisting_unknown(self):
        w = World(plan=roadmap(task_spec("alpha-helper")))
        command_id = dispatch_and_deliver(w, 2)
        original = w.facts.run_tests
        remaining = [1]

        def flaky(head):
            if remaining[0]:
                remaining[0] -= 1
                return None
            return original(head)

        w.facts.run_tests = flaky
        first = controller(w, 2).step(now=NOW)
        self.assertEqual((first.action, first.status), ("RECOVER", TRANSIENT_UNKNOWN), first.reason)
        self.assertEqual(InspectionStore(w.github, data_branch=DATA).list_all(), [])

        head = w.jules.prs[300]["head_sha"]
        retries = EvidenceRecoveryStore(w.github, data_branch=DATA).list_for(command_id, head)
        self.assertEqual([r["attempt"] for r in retries], [1])
        self.assertEqual(retries[0]["missing"], ["test_evidence"])

        inspected = controller(w, 2).step(now=NOW)
        self.assertEqual((inspected.action, inspected.status), ("INSPECT", "PASS"), inspected.reason)
        records = InspectionStore(w.github, data_branch=DATA).list_all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["verdict"], "PASS")

    def test_run_until_boundary_retries_in_same_session_then_completes(self):
        w = World(plan=roadmap(task_spec("alpha-helper")))
        dispatch_and_deliver(w, 2)
        original = w.facts.run_tests
        remaining = [1]

        def flaky(head):
            if remaining[0]:
                remaining[0] -= 1
                return None
            return original(head)

        w.facts.run_tests = flaky
        results = controller(w, 2).run_until_boundary(now=NOW, max_steps=8)
        self.assertEqual(
            [(r.action, r.status) for r in results],
            [("RECOVER", TRANSIENT_UNKNOWN), ("INSPECT", "PASS"),
             ("ADOPT", "ADOPTED"), ("COMPLETE", "COMPLETE")],
        )

    def test_retry_exhaustion_persists_one_terminal_unknown(self):
        w = World(plan=roadmap(task_spec("alpha-helper")))
        command_id = dispatch_and_deliver(w, 2)
        w.facts.run_tests = lambda head: None

        self.assertEqual(controller(w, 2).step(now=NOW).status, TRANSIENT_UNKNOWN)
        self.assertEqual(controller(w, 2).step(now=NOW).status, TRANSIENT_UNKNOWN)
        terminal = controller(w, 2).step(now=NOW)
        self.assertEqual((terminal.action, terminal.status), ("INSPECT", "UNKNOWN"), terminal.reason)

        head = w.jules.prs[300]["head_sha"]
        retries = EvidenceRecoveryStore(w.github, data_branch=DATA).list_for(command_id, head)
        self.assertEqual(len(retries), 2)
        inspections = InspectionStore(w.github, data_branch=DATA).list_all()
        self.assertEqual(len(inspections), 1)
        self.assertEqual(inspections[0]["verdict"], "UNKNOWN")

    def test_zero_retry_campaign_preserves_legacy_terminal_behavior(self):
        w = World(plan=roadmap(task_spec("alpha-helper")))
        command_id = dispatch_and_deliver(w, 0)
        w.facts.run_tests = lambda head: None
        result = controller(w, 0).step(now=NOW)
        self.assertEqual((result.action, result.status), ("INSPECT", "UNKNOWN"))
        head = w.jules.prs[300]["head_sha"]
        self.assertEqual(EvidenceRecoveryStore(w.github, data_branch=DATA).list_for(command_id, head), [])

    def test_corrupt_recovery_ledger_is_hard_unknown_not_a_retry(self):
        w = World(plan=roadmap(task_spec("alpha-helper")))
        command_id = dispatch_and_deliver(w, 2)
        head = w.jules.prs[300]["head_sha"]
        bad_path = recovery_path(command_id, head, 1)
        w.github.create(bad_path, json.dumps({"bad": True}), "bad recovery", DATA)
        w.facts.run_tests = lambda candidate: None
        result = controller(w, 2).step(now=NOW)
        self.assertEqual((result.action, result.status), ("STOP", HARD_UNKNOWN))
        self.assertIn("recovery ledger unverifiable", result.reason)


if __name__ == "__main__":
    unittest.main()
