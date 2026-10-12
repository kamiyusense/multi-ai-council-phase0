"""Crash/restart matrix: real stores/controller, fixture starts only."""
from collections import Counter
from dataclasses import replace
import unittest

from automation.command_bus.symphony_attempt_store import GitHubAutonomousAttemptStore, make_attempt_id
from automation.command_bus.symphony_attempt_reconciler import AttemptFenceProof
from automation.command_bus.symphony_autonomous_controller import (
    SimulatedProcessCrash, StaticAutonomousCampaignController, StaticCampaignTaskRunner,
    StaticCrashPlan, StaticObservationReader, StaticQuotaReader, StaticTargetObserver, TaskExecutionResult,
)
from automation.command_bus.symphony_autonomous_policy import QuotaState, UnknownClass
from automation.command_bus.symphony_autonomous_policy import HARDENED_AUTONOMOUS_POLICY
from automation.command_bus.symphony_autonomous_runtime import CampaignState, CampaignTask, TaskOutcome, TaskStatus
from automation.command_bus.symphony_campaign_store import GitHubCampaignStateStore
from automation.command_bus.tests.test_symphony_autonomous_controller import FakeContents, result


class AuditedContents(FakeContents):
    def __init__(self):
        super().__init__()
        self.created_paths = []

    def create(self, path, text, message, branch):
        self.created_paths.append(path)
        return super().create(path, text, message, branch)


class SymphonyAttemptFaultTests(unittest.TestCase):
    def setUp(self):
        self.client = AuditedContents()
        self.store = GitHubCampaignStateStore(self.client, write_branch="feature/faults")
        self.attempts = GitHubAutonomousAttemptStore(self.client, write_branch="feature/faults")
        self.campaign_id = "crash-matrix"
        state = CampaignState(self.campaign_id, 1, {
            "A": CampaignTask("A", expected_target_head="h1"),
            "B": CampaignTask("B", expected_target_head="h1"),
        })
        self.assertEqual(self.store.save(state, expected_revision=0).status, "ACCEPTED")

    def controller(self, runner, **kwargs):
        return StaticAutonomousCampaignController(
            self.store, campaign_id=self.campaign_id,
            target_observer=StaticTargetObserver("h1"), runner=runner, **kwargs,
        )

    def assert_no_duplicate_effects(self, *runners):
        starts = [attempt for r in runners for attempt in r.start_calls]
        self.assertTrue(all(count == 1 for count in Counter(starts).values()), starts)
        self.assertTrue(all(count == 1 for count in Counter(self.client.created_paths).values()), self.client.created_paths)

    def test_process_crash_at_every_dispatch_and_checkpoint_boundary(self):
        for boundary in (
            "before_intent", "after_intent", "after_running_checkpoint", "before_started",
            "after_started", "before_terminal", "after_terminal", "after_result_apply", "after_result_checkpoint",
        ):
            with self.subTest(boundary=boundary):
                self.setUp()
                first = StaticCampaignTaskRunner({"A": [result("r-a")]})
                with self.assertRaises(SimulatedProcessCrash):
                    self.controller(first, crash_plan=StaticCrashPlan(boundary)).run_until_boundary()
                fresh = StaticCampaignTaskRunner({"A": [result("fresh-a")], "B": [result("r-b")]})
                finished = self.controller(fresh).run_until_boundary()
                state = self.store.restore(self.campaign_id).state
                self.assertEqual(state.tasks["B"].status, TaskStatus.COMPLETE)
                terminal_boundaries = {"before_intent", "after_terminal", "after_result_apply", "after_result_checkpoint"}
                if boundary in terminal_boundaries:
                    self.assertEqual(finished.status, "CAMPAIGN_COMPLETE")
                    self.assertEqual(state.tasks["A"].status, TaskStatus.COMPLETE)
                    self.assertEqual(state.rounds_completed, 2)
                else:
                    self.assertEqual(finished.status, "STOP_NO_SAFE_WORK")
                    self.assertEqual(state.tasks["A"].status, TaskStatus.BLOCKED)
                    self.assertNotIn("A", fresh.calls)
                self.assert_no_duplicate_effects(first, fresh)
                replay = StaticCampaignTaskRunner()
                self.assertEqual(self.controller(replay).run_until_boundary().status, finished.status)
                self.assertEqual(replay.start_calls, [])
                self.assert_no_duplicate_effects(first, fresh, replay)

    def test_intent_crash_fenced_reclaim_uses_new_attempt_identity(self):
        first = StaticCampaignTaskRunner()
        with self.assertRaises(SimulatedProcessCrash):
            self.controller(first, crash_plan=StaticCrashPlan("after_intent")).run_until_boundary()
        old = self.attempts.list_campaign(self.campaign_id)[0]
        fresh = StaticCampaignTaskRunner({"A": [result("r-a")], "B": [result("r-b")]})
        proof = AttemptFenceProof(old.identity.attempt_id, 1, "FENCED", "static:old-worker-fenced")
        self.assertEqual(self.controller(fresh, fence_proofs=(proof,)).run_until_boundary().status, "CAMPAIGN_COMPLETE")
        self.assertNotIn(old.identity.attempt_id, fresh.start_calls)
        self.assertEqual(self.store.restore(self.campaign_id).state.tasks["A"].attempts, 2)
        self.assertIsNotNone(self.attempts.restore(self.campaign_id, old.identity.attempt_id).retired)
        self.assert_no_duplicate_effects(first, fresh)

    def test_started_fault_late_terminal_unblocks_without_starting_again(self):
        first = StaticCampaignTaskRunner()
        with self.assertRaises(SimulatedProcessCrash):
            self.controller(first, crash_plan=StaticCrashPlan("after_started")).run_until_boundary()
        old = self.attempts.list_campaign(self.campaign_id)[0]
        independent = StaticCampaignTaskRunner({"B": [result("r-b")]})
        self.assertEqual(self.controller(independent).run_until_boundary().status, "STOP_NO_SAFE_WORK")
        self.assertEqual(self.attempts.append_terminal(
            campaign_id=self.campaign_id, attempt_id=old.identity.attempt_id,
            result_id="late-a", outcome="DONE", model_started=True,
        ).status, "ACCEPTED")
        fresh = StaticCampaignTaskRunner()
        self.assertEqual(self.controller(fresh).run_until_boundary().status, "CAMPAIGN_COMPLETE")
        self.assertEqual(fresh.start_calls, [])
        self.assertEqual(self.store.restore(self.campaign_id).state.rounds_completed, 2)
        self.assert_no_duplicate_effects(first, independent, fresh)

    def test_ambiguous_result_checkpoint_is_read_back_without_resend(self):
        path = f"symphony_campaigns/{self.campaign_id}/states/00000003.json"
        self.client.raise_after_create_path = path
        self.client.fail_get_paths.add(path)
        first = StaticCampaignTaskRunner({"A": [result("r-a")]})
        self.assertEqual(self.controller(first).run_until_boundary().status, "UNKNOWN_DURABILITY")
        self.client.fail_get_paths.clear()
        fresh = StaticCampaignTaskRunner({"B": [result("r-b")]})
        self.assertEqual(self.controller(fresh).run_until_boundary().status, "CAMPAIGN_COMPLETE")
        self.assertEqual(fresh.calls, ["B"])
        self.assert_no_duplicate_effects(first, fresh)

    def test_ambiguous_attempt_writes_never_resend_and_resume_independent_work(self):
        for kind in ("intent", "started", "terminal"):
            with self.subTest(kind=kind):
                self.setUp()
                attempt_id = make_attempt_id(campaign_id=self.campaign_id, task_id="A", generation=1,
                                             attempt_number=1, expected_target_head="h1")
                path = f"symphony_attempts/{self.campaign_id}/{attempt_id}/{kind}.json"
                self.client.raise_after_create_path = path
                self.client.fail_get_paths.add(path)
                first = StaticCampaignTaskRunner({"A": [result("r-a")]})
                self.assertEqual(self.controller(first).run_until_boundary().status, "UNKNOWN_DURABILITY")
                self.client.fail_get_paths.clear()
                fresh = StaticCampaignTaskRunner({"B": [result("r-b")]})
                finished = self.controller(fresh).run_until_boundary()
                self.assertEqual(finished.status, "CAMPAIGN_COMPLETE" if kind == "terminal" else "STOP_NO_SAFE_WORK")
                self.assertEqual(fresh.calls, ["B"])
                self.assert_no_duplicate_effects(first, fresh)

    def test_observation_result_crash_recovers_without_observation_or_model_replay(self):
        first = StaticCampaignTaskRunner({
            "A": [result("a-unknown", TaskOutcome.UNKNOWN, UnknownClass.TRANSIENT_UNKNOWN)],
        })
        observer = StaticObservationReader({"A": [result("a-observed")]})
        with self.assertRaises(SimulatedProcessCrash):
            self.controller(first, observation_reader=observer,
                            crash_plan=StaticCrashPlan("after_observation_evidence")).run_until_boundary()
        fresh = StaticCampaignTaskRunner({"B": [result("r-b")]})
        fresh_observer = StaticObservationReader()
        finished = self.controller(fresh, observation_reader=fresh_observer).run_until_boundary()
        self.assertEqual(finished.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(fresh_observer.calls, [])
        self.assertEqual(fresh.calls, ["B"])
        self.assert_no_duplicate_effects(first, fresh)

    def test_quota_exhaustion_still_reconciles_terminal_and_completes_observation(self):
        first = StaticCampaignTaskRunner({"A": [result("r-a")]})
        with self.assertRaises(SimulatedProcessCrash):
            self.controller(first, crash_plan=StaticCrashPlan("after_terminal")).run_until_boundary()
        fresh = StaticCampaignTaskRunner()
        finished = self.controller(fresh, quota_reader=StaticQuotaReader(QuotaState.EXHAUSTED)).run_until_boundary()
        self.assertEqual(finished.status, "STOP_QUOTA")
        self.assertEqual(self.store.restore(self.campaign_id).state.tasks["A"].status, TaskStatus.COMPLETE)
        self.assertEqual(fresh.start_calls, [])

    def test_stale_terminal_replans_and_new_attempt_does_not_adopt_old_result(self):
        first = StaticCampaignTaskRunner({"A": [result("r-a")]})
        with self.assertRaises(SimulatedProcessCrash):
            self.controller(first, crash_plan=StaticCrashPlan("after_terminal")).run_until_boundary()
        fresh = StaticCampaignTaskRunner({"A": [result("a-new")], "B": [result("b-new")]})
        finished = StaticAutonomousCampaignController(
            self.store, campaign_id=self.campaign_id, target_observer=StaticTargetObserver("h2"), runner=fresh,
        ).run_until_boundary()
        self.assertEqual(finished.status, "CAMPAIGN_COMPLETE")
        state = self.store.restore(self.campaign_id).state
        self.assertEqual(state.rounds_completed, 2)
        self.assertEqual(state.tasks["A"].attempts, 2)
        self.assertEqual(state.tasks["A"].expected_target_head, "h2")
        self.assert_no_duplicate_effects(first, fresh)

    def test_runner_fault_isolates_unresolved_attempt_and_runs_independent_task(self):
        runner = StaticCampaignTaskRunner({"B": [result("r-b")]})
        finished = self.controller(runner).run_until_boundary()
        self.assertEqual(finished.status, "STOP_NO_SAFE_WORK")
        self.assertEqual(runner.calls, ["A", "B"])
        state = self.store.restore(self.campaign_id).state
        self.assertEqual(state.tasks["A"].status, TaskStatus.BLOCKED)
        self.assertEqual(state.tasks["B"].status, TaskStatus.COMPLETE)
        snapshot = [s for s in self.attempts.list_campaign(self.campaign_id) if s.identity.task_id == "A"][0]
        self.assertEqual(snapshot.state, "STARTED_UNRESOLVED")
        self.assert_no_duplicate_effects(runner)

    def test_observation_acquisition_fault_exhausts_read_budget_and_runs_independent_task(self):
        runner = StaticCampaignTaskRunner({
            "A": [result("a-transient", TaskOutcome.UNKNOWN, UnknownClass.TRANSIENT_UNKNOWN)],
            "B": [result("r-b")],
        })
        observer = StaticObservationReader()
        finished = self.controller(runner, observation_reader=observer).run_until_boundary()
        self.assertEqual(finished.status, "STOP_NO_SAFE_WORK")
        self.assertEqual(runner.calls, ["A", "B"])
        state = self.store.restore(self.campaign_id).state
        self.assertEqual(state.tasks["A"].status, TaskStatus.BLOCKED)
        self.assertEqual(state.tasks["A"].transient_retries, 3)
        self.assertEqual(len(observer.calls), 3)
        self.assert_no_duplicate_effects(runner)

    def test_ambiguous_running_checkpoint_never_starts_worker(self):
        path = f"symphony_campaigns/{self.campaign_id}/states/00000002.json"
        self.client.raise_after_create_path = path
        self.client.fail_get_paths.add(path)
        first = StaticCampaignTaskRunner()
        self.assertEqual(self.controller(first).run_until_boundary().status, "UNKNOWN_DURABILITY")
        self.assertEqual(first.start_calls, [])
        self.client.fail_get_paths.clear()
        fresh = StaticCampaignTaskRunner({"B": [result("r-b")]})
        self.assertEqual(self.controller(fresh).run_until_boundary().status, "STOP_NO_SAFE_WORK")
        self.assertEqual(fresh.calls, ["B"])
        self.assert_no_duplicate_effects(first, fresh)

    def test_ambiguous_retirement_is_not_resent_and_fresh_restore_uses_new_identity(self):
        first = StaticCampaignTaskRunner()
        with self.assertRaises(SimulatedProcessCrash):
            self.controller(first, crash_plan=StaticCrashPlan("after_intent")).run_until_boundary()
        old = self.attempts.list_campaign(self.campaign_id)[0]
        path = f"symphony_attempts/{self.campaign_id}/{old.identity.attempt_id}/retired.json"
        self.client.raise_after_create_path = path
        self.client.fail_get_paths.add(path)
        proof = AttemptFenceProof(old.identity.attempt_id, 1, "FENCED", "static:fence")
        uncertain = StaticCampaignTaskRunner()
        self.assertEqual(self.controller(uncertain, fence_proofs=(proof,)).run_until_boundary().status, "UNKNOWN_DURABILITY")
        self.assertEqual(uncertain.start_calls, [])
        self.client.fail_get_paths.clear()
        fresh = StaticCampaignTaskRunner({"A": [result("r-a")], "B": [result("r-b")]})
        self.assertEqual(self.controller(fresh).run_until_boundary().status, "CAMPAIGN_COMPLETE")
        self.assertNotIn(old.identity.attempt_id, fresh.start_calls)
        self.assert_no_duplicate_effects(first, uncertain, fresh)

    def test_thirty_unattended_rounds_across_five_fresh_controller_sessions(self):
        client = AuditedContents()
        store = GitHubCampaignStateStore(client, write_branch="feature/overnight")
        tasks = {f"T{i:02d}": CampaignTask(f"T{i:02d}", expected_target_head="h1",
                 dependencies=(f"T{i-1:02d}",) if i else ()) for i in range(30)}
        self.assertEqual(store.save(CampaignState("overnight", 1, tasks), expected_revision=0).status, "ACCEPTED")
        starts = []
        for session in range(5):
            runner = StaticCampaignTaskRunner({f"T{i:02d}": [result(f"r-{i}")] for i in range(session*6, (session+1)*6)})
            finished = StaticAutonomousCampaignController(
                store, campaign_id="overnight", target_observer=StaticTargetObserver("h1"), runner=runner,
                policy=replace(HARDENED_AUTONOMOUS_POLICY, max_rounds=30),
            ).run_until_boundary(max_steps=6)
            self.assertEqual(finished.status, "BATCH_LIMIT")
            starts.extend(runner.start_calls)
        final = StaticAutonomousCampaignController(
            store, campaign_id="overnight", target_observer=StaticTargetObserver("h1"),
            runner=StaticCampaignTaskRunner(), policy=replace(HARDENED_AUTONOMOUS_POLICY, max_rounds=30),
        ).run_until_boundary()
        self.assertEqual(final.status, "CAMPAIGN_COMPLETE")
        state = store.restore("overnight").state
        self.assertEqual(state.rounds_completed, 30)
        self.assertEqual(len(state.processed_result_ids), 30)
        self.assertEqual(len(starts), 30)
        self.assertEqual(len(set(starts)), 30)
        self.assertTrue(all(n == 1 for n in Counter(client.created_paths).values()))


if __name__ == "__main__":
    unittest.main()
