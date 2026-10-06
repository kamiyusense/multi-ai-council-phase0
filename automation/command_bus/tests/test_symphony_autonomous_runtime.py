from __future__ import annotations

import unittest

from automation.command_bus.symphony_autonomous_policy import (
    AutonomousRuntimePolicy,
    HARDENED_AUTONOMOUS_POLICY,
    QuotaState,
    RecoveryAction,
    STRICT_PROOF_POLICY,
    UPSTREAM_SYMPHONY_REFERENCE_POLICY,
    UnknownClass,
    decide_unknown,
    model_work_allowed,
    stale_head_action,
)
from automation.command_bus.symphony_autonomous_runtime import (
    ActionKind,
    AutonomousCampaignKernel,
    CampaignState,
    CampaignTask,
    TaskOutcome,
    TaskStatus,
)


class SymphonyAutonomousPolicyTests(unittest.TestCase):
    def test_profiles_keep_strict_proof_separate_from_openable_runtime_valves(self):
        self.assertEqual(
            (STRICT_PROOF_POLICY.max_rounds, STRICT_PROOF_POLICY.max_turns_per_task,
             STRICT_PROOF_POLICY.max_model_starts_per_task, STRICT_PROOF_POLICY.max_concurrent_agents),
            (1, 1, 1, 1),
        )
        self.assertGreater(HARDENED_AUTONOMOUS_POLICY.max_rounds, 1)
        self.assertEqual(HARDENED_AUTONOMOUS_POLICY.max_turns_per_task, 20)
        self.assertEqual(UPSTREAM_SYMPHONY_REFERENCE_POLICY.max_concurrent_agents, 10)
        self.assertIsNone(UPSTREAM_SYMPHONY_REFERENCE_POLICY.max_rounds)

    def test_policy_rejects_paid_fallback_and_blind_write_retry(self):
        common = dict(
            profile="bad", max_rounds=2, max_turns_per_task=2, max_model_starts_per_task=2,
            max_corrective_rounds_per_task=1, max_transient_retries=1,
            max_consecutive_failures=2, max_concurrent_agents=1,
            idle_observation_interval_seconds=30, task_timeout_seconds=60,
            campaign_timeout_seconds=120,
        )
        with self.assertRaisesRegex(ValueError, "blindly retried"):
            AutonomousRuntimePolicy(**common, blind_write_retries=1)
        with self.assertRaisesRegex(ValueError, "subscription-only"):
            AutonomousRuntimePolicy(**common, allow_metered_api_fallback=True)

    def test_unknown_taxonomy_prefers_recovery_or_isolation_before_campaign_stop(self):
        self.assertEqual(
            decide_unknown(
                UnknownClass.TRANSIENT_UNKNOWN,
                policy=HARDENED_AUTONOMOUS_POLICY,
                transient_retries_used=0,
                independent_safe_work=False,
            ),
            RecoveryAction.RETRY_OBSERVATION,
        )
        self.assertEqual(
            decide_unknown(
                UnknownClass.HARD_UNKNOWN,
                policy=HARDENED_AUTONOMOUS_POLICY,
                independent_safe_work=True,
            ),
            RecoveryAction.ISOLATE_TASK_CONTINUE,
        )
        self.assertEqual(
            decide_unknown(
                UnknownClass.HARD_UNKNOWN,
                policy=HARDENED_AUTONOMOUS_POLICY,
                independent_safe_work=True,
                affects_campaign_authority=True,
            ),
            RecoveryAction.STOP_CAMPAIGN,
        )

    def test_stale_head_and_quota_unknown_do_not_become_automatic_stop(self):
        self.assertEqual(
            stale_head_action(
                canonical_trustworthy=True,
                task_still_valid=True,
                independent_safe_work=False,
            ),
            RecoveryAction.REPLAN,
        )
        self.assertTrue(model_work_allowed(QuotaState.UNKNOWN, HARDENED_AUTONOMOUS_POLICY))
        self.assertFalse(model_work_allowed(QuotaState.EXHAUSTED, HARDENED_AUTONOMOUS_POLICY))


class SymphonyAutonomousRuntimeTests(unittest.TestCase):
    def chain_state(self):
        return CampaignState(
            "campaign-1",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", dependencies=("A",), expected_target_head="h1"),
                "C": CampaignTask("C", dependencies=("B",), expected_target_head="h1"),
            },
        )

    def test_three_round_success_flows_directly_to_next_task_without_human_gate(self):
        kernel = AutonomousCampaignKernel(self.chain_state())
        for task_id in ("A", "B", "C"):
            action = kernel.next_action(canonical_head="h1")
            self.assertEqual((action.kind, action.task_id), (ActionKind.DISPATCH_TASK, task_id))
            kernel.mark_dispatched(task_id, canonical_head="h1")
            result = kernel.record_result(
                result_id=f"result-{task_id}",
                task_id=task_id,
                outcome=TaskOutcome.DONE,
            )
            self.assertEqual(result.kind, ActionKind.ISOLATE_TASK_CONTINUE)
        self.assertEqual(kernel.next_action(canonical_head="h1").kind, ActionKind.CAMPAIGN_COMPLETE)
        self.assertEqual(kernel.state.rounds_completed, 3)

    def test_failure_creates_new_corrective_identity_then_unblocks_dependency_chain(self):
        state = CampaignState(
            "campaign-corrective",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", dependencies=("A",), expected_target_head="h1"),
            },
        )
        kernel = AutonomousCampaignKernel(state)
        kernel.mark_dispatched("A", canonical_head="h1")
        corrective = kernel.record_result(
            result_id="result-a-fail", task_id="A", outcome=TaskOutcome.FAILED,
        )
        self.assertEqual(corrective.kind, ActionKind.CORRECTIVE_TASK_CREATED)
        self.assertEqual(corrective.task_id, "A::corrective::1")
        self.assertEqual(kernel.next_action(canonical_head="h1").task_id, "A::corrective::1")
        kernel.mark_dispatched("A::corrective::1", canonical_head="h1")
        kernel.record_result(
            result_id="result-a-fix",
            task_id="A::corrective::1",
            outcome=TaskOutcome.DONE,
        )
        self.assertEqual(kernel.state.tasks["A"].status, TaskStatus.COMPLETE)
        self.assertEqual(kernel.next_action(canonical_head="h1").task_id, "B")

    def test_multiple_correctives_do_not_prevent_campaign_completion_after_later_success(self):
        state = CampaignState(
            "campaign-corrective-chain",
            1,
            {"A": CampaignTask("A", expected_target_head="h1")},
        )
        kernel = AutonomousCampaignKernel(state)
        kernel.mark_dispatched("A", canonical_head="h1")
        first = kernel.record_result(
            result_id="fail-root", task_id="A", outcome=TaskOutcome.FAILED,
        )
        kernel.mark_dispatched(first.task_id, canonical_head="h1")
        second = kernel.record_result(
            result_id="fail-c1", task_id=first.task_id, outcome=TaskOutcome.FAILED,
        )
        self.assertEqual(kernel.state.tasks[first.task_id].status, TaskStatus.SUPERSEDED)
        kernel.mark_dispatched(second.task_id, canonical_head="h1")
        kernel.record_result(
            result_id="pass-c2", task_id=second.task_id, outcome=TaskOutcome.DONE,
        )
        self.assertEqual(kernel.state.tasks["A"].status, TaskStatus.COMPLETE)
        self.assertEqual(kernel.next_action(canonical_head="h1").kind, ActionKind.CAMPAIGN_COMPLETE)

    def test_recoverable_unknown_requires_replan_before_model_dispatch(self):
        state = CampaignState(
            "campaign-replan-unknown",
            1,
            {"A": CampaignTask("A", status=TaskStatus.RUNNING, expected_target_head="old")},
        )
        kernel = AutonomousCampaignKernel(state)
        action = kernel.record_result(
            result_id="recoverable-1", task_id="A", outcome=TaskOutcome.UNKNOWN,
            unknown_class=UnknownClass.RECOVERABLE_UNKNOWN,
        )
        self.assertEqual(action.kind, ActionKind.REPLAN_TASK)
        self.assertEqual(kernel.state.tasks["A"].status, TaskStatus.STALE)
        self.assertEqual(kernel.next_action(canonical_head="new").kind, ActionKind.REPLAN_TASK)
        kernel.replan_stale_task("A", canonical_head="new", task_still_valid=True)
        self.assertEqual(kernel.next_action(canonical_head="new").kind, ActionKind.DISPATCH_TASK)

    def test_transient_unknown_retries_then_isolates_and_continues_independent_task(self):
        policy = AutonomousRuntimePolicy(
            profile="retry-one", max_rounds=10, max_turns_per_task=2, max_model_starts_per_task=2,
            max_corrective_rounds_per_task=1, max_transient_retries=1,
            max_consecutive_failures=3, max_concurrent_agents=1,
            idle_observation_interval_seconds=1, task_timeout_seconds=60,
            campaign_timeout_seconds=600,
        )
        state = CampaignState(
            "campaign-transient",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", expected_target_head="h1"),
            },
        )
        kernel = AutonomousCampaignKernel(state, policy=policy)
        kernel.mark_dispatched("A", canonical_head="h1")
        first = kernel.record_result(
            result_id="u1", task_id="A", outcome=TaskOutcome.UNKNOWN,
            unknown_class=UnknownClass.TRANSIENT_UNKNOWN,
        )
        self.assertEqual(first.kind, ActionKind.RETRY_OBSERVATION)
        self.assertEqual(kernel.state.tasks["A"].status, TaskStatus.WAITING)
        self.assertEqual(
            kernel.next_action(canonical_head="h1", quota_state=QuotaState.EXHAUSTED).kind,
            ActionKind.RETRY_OBSERVATION,
        )
        # A second transient observation failure consumes observation retry
        # budget without redispatching the model task.
        second = kernel.record_result(
            result_id="u2", task_id="A", outcome=TaskOutcome.UNKNOWN,
            unknown_class=UnknownClass.TRANSIENT_UNKNOWN,
        )
        self.assertEqual(second.kind, ActionKind.ISOLATE_TASK_CONTINUE)
        self.assertEqual(kernel.state.tasks["A"].status, TaskStatus.BLOCKED)
        self.assertEqual(kernel.next_action(canonical_head="h1").task_id, "B")

    def test_stale_head_replans_when_valid_and_isolates_when_invalid(self):
        state = CampaignState(
            "campaign-stale",
            1,
            {
                "A": CampaignTask("A", expected_target_head="old"),
                "B": CampaignTask("B", expected_target_head="new"),
            },
        )
        kernel = AutonomousCampaignKernel(state)
        self.assertEqual(kernel.next_action(canonical_head="new").kind, ActionKind.REPLAN_TASK)
        replanned = kernel.replan_stale_task("A", canonical_head="new", task_still_valid=True)
        self.assertEqual(replanned.kind, ActionKind.REPLAN_TASK)
        self.assertEqual(kernel.state.tasks["A"].expected_target_head, "new")
        invalid = kernel.replan_stale_task("A", canonical_head="newer", task_still_valid=False)
        self.assertEqual(invalid.kind, ActionKind.ISOLATE_TASK_CONTINUE)
        self.assertEqual(kernel.next_action(canonical_head="new").task_id, "B")

    def test_restart_restore_preserves_duplicate_guard_and_continues(self):
        state = CampaignState(
            "campaign-restart",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", expected_target_head="h1"),
            },
        )
        kernel = AutonomousCampaignKernel(state)
        kernel.mark_dispatched("A", canonical_head="h1")
        kernel.record_result(result_id="r1", task_id="A", outcome=TaskOutcome.DONE)
        durable = kernel.state.to_dict()
        restored = AutonomousCampaignKernel.restore(durable)
        duplicate = restored.record_result(result_id="r1", task_id="A", outcome=TaskOutcome.DONE)
        self.assertEqual(duplicate.kind, ActionKind.NOOP_DUPLICATE)
        self.assertEqual(restored.next_action(canonical_head="h1").task_id, "B")

    def test_running_task_reclaim_requires_duplicate_fence(self):
        state = CampaignState(
            "campaign-reclaim",
            1,
            {"A": CampaignTask("A", status=TaskStatus.RUNNING, expected_target_head="h1")},
        )
        kernel = AutonomousCampaignKernel(state)
        self.assertEqual(
            kernel.reclaim_after_restart(
                ownership_chain_verified=True,
                old_attempt_stopped_or_fenced=False,
            ),
            0,
        )
        self.assertEqual(kernel.state.tasks["A"].status, TaskStatus.RUNNING)
        self.assertEqual(
            kernel.reclaim_after_restart(
                ownership_chain_verified=True,
                old_attempt_stopped_or_fenced=True,
            ),
            1,
        )
        self.assertEqual(kernel.state.tasks["A"].status, TaskStatus.READY)
        self.assertEqual(kernel.state.generation, 2)

    def test_campaign_hard_unknown_stops_only_when_authority_is_affected(self):
        state = CampaignState(
            "campaign-hard",
            1,
            {
                "A": CampaignTask("A", status=TaskStatus.RUNNING, expected_target_head="h1"),
                "B": CampaignTask("B", expected_target_head="h1"),
            },
        )
        kernel = AutonomousCampaignKernel(state)
        isolated = kernel.record_result(
            result_id="hard-task", task_id="A", outcome=TaskOutcome.UNKNOWN,
            unknown_class=UnknownClass.HARD_UNKNOWN,
            affects_campaign_authority=False,
        )
        self.assertEqual(isolated.kind, ActionKind.ISOLATE_TASK_CONTINUE)
        self.assertEqual(kernel.next_action(canonical_head="h1").task_id, "B")

        state2 = CampaignState(
            "campaign-authority",
            1,
            {"A": CampaignTask("A", status=TaskStatus.RUNNING, expected_target_head="h1")},
        )
        kernel2 = AutonomousCampaignKernel(state2)
        stopped = kernel2.record_result(
            result_id="hard-authority", task_id="A", outcome=TaskOutcome.UNKNOWN,
            unknown_class=UnknownClass.HARD_UNKNOWN,
            affects_campaign_authority=True,
        )
        self.assertEqual(stopped.kind, ActionKind.STOP_HARD_UNKNOWN)
        self.assertIsNotNone(kernel2.state.terminal_reason)

    def test_unreadable_quota_allows_work_but_confirmed_exhaustion_stops_new_model_work(self):
        kernel = AutonomousCampaignKernel(CampaignState(
            "campaign-quota", 1, {"A": CampaignTask("A", expected_target_head="h1")},
        ))
        self.assertEqual(
            kernel.next_action(canonical_head="h1", quota_state=QuotaState.UNKNOWN).kind,
            ActionKind.DISPATCH_TASK,
        )
        self.assertEqual(
            kernel.next_action(canonical_head="h1", quota_state=QuotaState.EXHAUSTED).kind,
            ActionKind.STOP_QUOTA,
        )


if __name__ == "__main__":
    unittest.main()
