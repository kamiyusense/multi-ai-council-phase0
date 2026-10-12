"""Restart acceptance tests over real stores and the pure campaign kernel."""
import json
import unittest

from automation.command_bus.executor_backend import ExecutorContent
from automation.command_bus.symphony_attempt_store import GitHubAutonomousAttemptStore, make_attempt_id
from automation.command_bus.symphony_attempt_reconciler import AttemptFenceProof, reconcile_attempts
from automation.command_bus.symphony_autonomous_runtime import (
    AutonomousCampaignKernel, CampaignState, CampaignTask, TaskStatus,
)
from automation.command_bus.tests.test_symphony_autonomous_controller import FakeContents


class SymphonyAttemptReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeContents()
        self.store = GitHubAutonomousAttemptStore(self.client, write_branch="feature/recovery")
        self.kernel = AutonomousCampaignKernel(CampaignState("recovery", 2, {
            "A": CampaignTask("A", status=TaskStatus.RUNNING, expected_target_head="h1", attempts=1),
            "B": CampaignTask("B", expected_target_head="h1"),
        }))

    def intent(self, generation=2, head="h1", number=1, task="A"):
        result = self.store.append_intent(
            campaign_id="recovery", task_id=task, generation=generation,
            attempt_number=number, expected_target_head=head, runner_generation=7, scope={"task": task},
        )
        self.assertEqual(result.status, "ACCEPTED")
        return result.attempt_id

    def started(self, attempt_id):
        self.assertEqual(self.store.append_started(
            campaign_id="recovery", attempt_id=attempt_id, provider_kind="STATIC",
            provider_attempt_ref=attempt_id, observation_source="STATIC_SIMULATION",
        ).status, "ACCEPTED")

    def terminal(self, attempt_id, outcome="DONE", unknown=None, authority=False, result_id="r-a"):
        self.assertEqual(self.store.append_terminal(
            campaign_id="recovery", attempt_id=attempt_id, result_id=result_id,
            outcome=outcome, unknown_class=unknown, affects_campaign_authority=authority,
            model_started=True,
        ).status, "ACCEPTED")

    def reconcile(self, **kwargs):
        kwargs.setdefault("task_validity", lambda task: True)
        return reconcile_attempts(self.kernel, self.store, canonical_head="h1", **kwargs)

    def test_terminal_survives_crash_and_selects_next_task_without_dispatch(self):
        attempt = self.intent()
        self.started(attempt)
        self.terminal(attempt)
        created = self.client.create_calls
        result = self.reconcile()
        self.assertEqual(result.applied, 1)
        self.assertEqual(self.client.create_calls, created)
        self.assertEqual(self.kernel.state.tasks["A"].status, TaskStatus.COMPLETE)
        self.assertEqual(self.kernel.next_action(canonical_head="h1").task_id, "B")

    def test_terminal_recovery_rechecks_task_validity_before_done_adoption(self):
        attempt = self.intent()
        self.started(attempt)
        self.terminal(attempt)
        result = self.reconcile(task_validity=lambda task: task.task_id != "A")
        self.assertEqual(result.applied, 0)
        self.assertEqual(result.isolated, 1)
        self.assertEqual(self.kernel.state.tasks["A"].status, TaskStatus.BLOCKED)
        self.assertEqual(self.kernel.next_action(canonical_head="h1").task_id, "B")

    def test_terminal_cannot_be_adopted_without_task_validity_reader(self):
        attempt = self.intent()
        self.started(attempt)
        self.terminal(attempt)
        self.assertEqual(self.reconcile(task_validity=None).status, "HARD_UNKNOWN")
        self.assertEqual(self.kernel.state.rounds_completed, 0)

    def test_terminal_recovery_refuses_destructive_mutation_claim(self):
        attempt = self.intent()
        self.started(attempt)
        self.assertEqual(self.store.append_terminal(
            campaign_id="recovery", attempt_id=attempt, result_id="unsafe-result",
            outcome="DONE", model_started=True, mutation_operations=["FORCE_PUSH"],
        ).status, "ACCEPTED")
        result = self.reconcile()
        self.assertEqual(result.applied, 0)
        self.assertEqual(result.isolated, 1)
        self.assertEqual(self.kernel.state.tasks["A"].status, TaskStatus.BLOCKED)

    def test_started_unresolved_isolated_even_with_fence_and_independent_continues(self):
        attempt = self.intent()
        self.started(attempt)
        proof = AttemptFenceProof(attempt, 7, "FENCED", "static:fence")
        result = self.reconcile(fence_proofs=(proof,))
        self.assertEqual(result.reclaimed, 0)
        self.assertEqual(self.kernel.state.tasks["A"].status, TaskStatus.BLOCKED)
        self.assertEqual(self.kernel.next_action(canonical_head="h1").task_id, "B")
        self.assertEqual(self.store.restore("recovery", attempt).state, "STARTED_UNRESOLVED")

    def test_late_terminal_recovers_blocked_task_without_model_redispatch(self):
        attempt = self.intent()
        self.started(attempt)
        self.reconcile()
        self.kernel = AutonomousCampaignKernel.restore(self.kernel.state.to_dict())
        self.terminal(attempt)
        self.assertEqual(self.reconcile().applied, 1)
        self.assertEqual(self.kernel.state.tasks["A"].status, TaskStatus.COMPLETE)
        self.assertEqual(self.kernel.state.tasks["A"].attempts, 1)

    def test_unstarted_no_fence_isolates_and_does_not_write(self):
        attempt = self.intent()
        writes = self.client.create_calls
        self.reconcile()
        self.assertEqual(self.client.create_calls, writes)
        self.assertEqual(self.kernel.state.tasks["A"].status, TaskStatus.BLOCKED)
        self.assertEqual(self.store.restore("recovery", attempt).state, "CLAIMED_UNSTARTED")

    def test_unstarted_fenced_is_retired_and_next_identity_changes(self):
        attempt = self.intent()
        self.reconcile(fence_proofs=(AttemptFenceProof(attempt, 7, "STOPPED", "static:stopped"),))
        task = self.kernel.state.tasks["A"]
        self.assertEqual(task.status, TaskStatus.READY)
        self.assertIsNotNone(self.store.restore("recovery", attempt).retired)
        new_id = make_attempt_id(campaign_id="recovery", task_id="A", generation=2,
                                 attempt_number=task.attempts + 1, expected_target_head="h1")
        self.assertNotEqual(new_id, attempt)
        self.assertEqual(self.reconcile().reclaimed, 0)

    def test_unknown_classes_and_authority_survive_restart(self):
        for kind, expected in [("TRANSIENT_UNKNOWN", TaskStatus.WAITING),
                               ("RECOVERABLE_UNKNOWN", TaskStatus.STALE),
                               ("TASK_BLOCKED", TaskStatus.BLOCKED),
                               ("HARD_UNKNOWN", TaskStatus.BLOCKED)]:
            with self.subTest(kind=kind):
                self.setUp()
                attempt = self.intent()
                self.started(attempt)
                self.terminal(attempt, "UNKNOWN", kind)
                self.kernel = AutonomousCampaignKernel.restore(self.kernel.state.to_dict())
                self.reconcile()
                self.assertEqual(self.kernel.state.tasks["A"].status, expected)
                self.assertIsNone(self.kernel.state.terminal_reason)

    def test_task_local_hard_unknown_continues_independent_work(self):
        attempt = self.intent()
        self.started(attempt)
        self.terminal(attempt, "UNKNOWN", "HARD_UNKNOWN")
        self.reconcile()
        self.assertEqual(self.kernel.next_action(canonical_head="h1").task_id, "B")

    def test_campaign_authority_hard_unknown_stops(self):
        attempt = self.intent()
        self.started(attempt)
        self.terminal(attempt, "UNKNOWN", "HARD_UNKNOWN", True)
        self.assertEqual(self.reconcile().status, "HARD_UNKNOWN")
        self.assertEqual(self.kernel.next_action(canonical_head="h1").kind.value, "STOP_HARD_UNKNOWN")

    def test_old_generation_terminal_is_historical(self):
        attempt = self.intent(generation=1)
        self.started(attempt)
        self.terminal(attempt)
        self.assertFalse(self.reconcile().changed)
        self.assertNotIn("r-a", self.kernel.state.processed_result_ids)
        self.assertEqual(self.kernel.state.generation, 2)

    def test_future_generation_is_campaign_hard_unknown(self):
        self.intent(generation=3)
        self.assertEqual(self.reconcile().status, "HARD_UNKNOWN")
        self.assertEqual(self.kernel.state.generation, 2)

    def test_stale_target_result_is_not_adopted_on_new_head(self):
        attempt = self.intent(head="old")
        self.started(attempt)
        self.terminal(attempt)
        self.reconcile()
        self.assertEqual(self.kernel.state.tasks["A"].status, TaskStatus.STALE)
        self.assertEqual(self.kernel.state.rounds_completed, 0)
        self.assertFalse(self.reconcile().changed)

    def test_duplicate_terminal_is_noop_after_state_restore(self):
        attempt = self.intent()
        self.started(attempt)
        self.terminal(attempt)
        self.reconcile()
        self.kernel = AutonomousCampaignKernel.restore(self.kernel.state.to_dict())
        writes = self.client.create_calls
        duplicate = self.reconcile()
        self.assertFalse(duplicate.changed)
        self.assertEqual(duplicate.applied, 0)
        self.assertEqual(self.kernel.state.rounds_completed, 1)
        self.assertEqual(self.client.create_calls, writes)

    def test_fence_bound_to_wrong_worker_generation_is_hard_unknown(self):
        attempt = self.intent()
        result = self.reconcile(fence_proofs=(AttemptFenceProof(attempt, 8, "FENCED", "static:fence"),))
        self.assertEqual(result.status, "HARD_UNKNOWN")
        self.assertIsNone(self.store.restore("recovery", attempt).retired)

    def test_unrelated_blocker_does_not_allow_blocked_result_recovery(self):
        attempt = self.intent()
        self.started(attempt)
        self.terminal(attempt)
        self.kernel.state.tasks["A"].status = TaskStatus.BLOCKED
        self.kernel.state.blockers.append({"task_id": "A", "reason": "unrelated"})
        self.assertEqual(self.reconcile().applied, 0)
        self.assertEqual(self.kernel.state.tasks["A"].status, TaskStatus.BLOCKED)

    def test_duplicate_result_id_across_tasks_is_rejected_before_apply(self):
        for task_id in ("A", "B"):
            attempt = self.intent(task=task_id)
            self.started(attempt)
            self.terminal(attempt)
        self.assertEqual(self.reconcile().status, "HARD_UNKNOWN")
        self.assertEqual(self.kernel.state.rounds_completed, 0)

    def test_scope_tampering_is_hard_unknown(self):
        attempt = self.intent()
        path = f"symphony_attempts/recovery/{attempt}/intent.json"
        old = self.client.files[path]
        record = json.loads(old.text)
        record["scope"]["task"] = "tampered"
        self.client.files[path] = ExecutorContent(path, json.dumps(record), old.sha)
        self.assertEqual(self.reconcile().status, "HARD_UNKNOWN")

    def test_transient_transport_failure_does_not_corrupt_campaign_authority(self):
        attempt = self.intent()
        self.client.fail_get_paths.add(f"symphony_attempts/recovery/{attempt}/intent.json")
        self.assertEqual(self.reconcile().status, "UNKNOWN_DURABILITY")
        self.assertIsNone(self.kernel.state.terminal_reason)

    def test_retirement_crash_recovers_reclaim_without_retirement_resend(self):
        attempt = self.intent()
        proof = AttemptFenceProof(attempt, 7, "FENCED", "static:fence")
        self.assertEqual(self.store.retire_unstarted("recovery", attempt, fence_proof=proof.to_dict()).status, "ACCEPTED")
        creates = self.client.create_calls
        self.assertEqual(self.reconcile().reclaimed, 1)
        self.assertEqual(self.client.create_calls, creates)


if __name__ == "__main__":
    unittest.main()
