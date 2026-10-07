from __future__ import annotations

import unittest

from automation.command_bus.executor_backend import ExecutorContent
from automation.command_bus.symphony_autonomous_controller import (
    StaticAutonomousCampaignController,
    StaticCampaignTaskRunner,
    StaticObservationReader,
    StaticQuotaReader,
    StaticReplanner,
    StaticTargetObserver,
    TaskExecutionResult,
)
from automation.command_bus.symphony_autonomous_policy import QuotaState, UnknownClass
from automation.command_bus.symphony_autonomous_runtime import (
    CampaignState,
    CampaignTask,
    TaskOutcome,
    TaskStatus,
)
from automation.command_bus.symphony_campaign_store import GitHubCampaignStateStore


class FakeContents:
    def __init__(self):
        self.files = {}
        self.counter = 0
        self.create_calls = 0
        self.raise_after_create_path = None
        self.fail_get_paths = set()

    def get(self, path, ref):
        if path in self.fail_get_paths and path in self.files:
            raise RuntimeError("readback unavailable")
        return self.files.get(path)

    def list(self, prefix, ref):
        return sorted(
            (value for path, value in self.files.items() if path.startswith(prefix)),
            key=lambda item: item.path,
        )

    def create(self, path, text, message, branch):
        self.create_calls += 1
        if path in self.files:
            raise ValueError("already exists")
        self.counter += 1
        value = ExecutorContent(path, text, f"sha-{self.counter}")
        self.files[path] = value
        if self.raise_after_create_path == path:
            self.raise_after_create_path = None
            raise RuntimeError("ambiguous create")
        return value

    def update(self, path, text, sha, message, branch):
        raise AssertionError("campaign store must stay create-only")


def result(result_id, outcome=TaskOutcome.DONE, unknown_class=None):
    return TaskExecutionResult(result_id, outcome, unknown_class)


def make_store(client=None):
    client = client or FakeContents()
    return client, GitHubCampaignStateStore(client, write_branch="feature/controller-records")


def bootstrap(store, state):
    saved = store.save(state, expected_revision=0)
    if saved.status != "ACCEPTED":
        raise AssertionError(saved)


class SymphonyAutonomousControllerTests(unittest.TestCase):
    def test_head_advance_after_worker_result_discards_old_done_then_replans(self):
        _, store = make_store()
        bootstrap(store, CampaignState("adoption-head", 1, {
            "A": CampaignTask("A", expected_target_head="h1"),
        }))
        first = StaticAutonomousCampaignController(
            store, campaign_id="adoption-head",
            target_observer=StaticTargetObserver("h1", read_sequence=("h1", "h1", "h2")),
            runner=StaticCampaignTaskRunner({"A": [result("old-done")]}),
        ).run_until_boundary(max_steps=1)
        self.assertEqual(first.status, "BATCH_LIMIT")
        checkpoint = store.restore("adoption-head")
        self.assertEqual(checkpoint.state.tasks["A"].status, TaskStatus.STALE)
        self.assertEqual(checkpoint.state.rounds_completed, 0)
        second = StaticAutonomousCampaignController(
            store, campaign_id="adoption-head", target_observer=StaticTargetObserver("h2"),
            runner=StaticCampaignTaskRunner({"A": [result("new-done")]}),
        ).run_until_boundary()
        self.assertEqual(second.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(store.restore("adoption-head").state.rounds_completed, 1)

    def test_destructive_result_is_isolated_and_independent_task_continues(self):
        _, store = make_store()
        bootstrap(store, CampaignState("adoption-risk", 1, {
            "A": CampaignTask("A", expected_target_head="h1"),
            "B": CampaignTask("B", expected_target_head="h1"),
        }))
        runner = StaticCampaignTaskRunner({
            "A": [TaskExecutionResult("unsafe", TaskOutcome.DONE, mutation_operations=("DELETE",))],
            "B": [result("safe")],
        })
        finished = StaticAutonomousCampaignController(
            store, campaign_id="adoption-risk", target_observer=StaticTargetObserver("h1"),
            runner=runner,
        ).run_until_boundary()
        self.assertEqual(finished.status, "STOP_NO_SAFE_WORK")
        self.assertEqual(runner.calls, ["A", "B"])
        state = store.restore("adoption-risk").state
        self.assertEqual(state.tasks["A"].status, TaskStatus.BLOCKED)
        self.assertEqual(state.tasks["B"].status, TaskStatus.COMPLETE)
        self.assertEqual(state.rounds_completed, 1)

    def test_three_round_campaign_runs_to_completion_without_human_gate(self):
        _, store = make_store()
        state = CampaignState(
            "campaign-three",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", dependencies=("A",), expected_target_head="h1"),
                "C": CampaignTask("C", dependencies=("B",), expected_target_head="h1"),
            },
        )
        bootstrap(store, state)
        runner = StaticCampaignTaskRunner({
            "A": [result("r-a")],
            "B": [result("r-b")],
            "C": [result("r-c")],
        })
        controller = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-three",
            target_observer=StaticTargetObserver("h1"),
            runner=runner,
        )

        finished = controller.run_until_boundary()

        self.assertEqual(finished.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(finished.steps, 3)
        self.assertEqual(runner.calls, ["A", "B", "C"])
        restored = store.restore("campaign-three")
        self.assertEqual(restored.state.rounds_completed, 3)

    def test_failure_creates_corrective_then_continues_downstream(self):
        _, store = make_store()
        state = CampaignState(
            "campaign-corrective-driver",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", dependencies=("A",), expected_target_head="h1"),
            },
        )
        bootstrap(store, state)
        runner = StaticCampaignTaskRunner({
            "A": [result("a-fail", TaskOutcome.FAILED)],
            "A::corrective::1": [result("a-fix")],
            "B": [result("b-pass")],
        })
        controller = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-corrective-driver",
            target_observer=StaticTargetObserver("h1"),
            runner=runner,
        )

        finished = controller.run_until_boundary()

        self.assertEqual(finished.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(
            runner.calls, ["A", "A::corrective::1", "B"],
        )

    def test_fresh_controller_resumes_after_batch_boundary(self):
        _, store = make_store()
        state = CampaignState(
            "campaign-restart-driver",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", dependencies=("A",), expected_target_head="h1"),
            },
        )
        bootstrap(store, state)
        first_runner = StaticCampaignTaskRunner({"A": [result("a-pass")]})
        first = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-restart-driver",
            target_observer=StaticTargetObserver("h1"),
            runner=first_runner,
        ).run_until_boundary(max_steps=1)
        self.assertEqual(first.status, "BATCH_LIMIT")
        self.assertEqual(first_runner.calls, ["A"])

        second_runner = StaticCampaignTaskRunner({"B": [result("b-pass")]})
        second = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-restart-driver",
            target_observer=StaticTargetObserver("h1"),
            runner=second_runner,
        ).run_until_boundary()
        self.assertEqual(second.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(second_runner.calls, ["B"])

    def test_transient_unknown_recovers_by_observation_without_model_redispatch(self):
        _, store = make_store()
        state = CampaignState(
            "campaign-observe",
            1,
            {"A": CampaignTask("A", expected_target_head="h1")},
        )
        bootstrap(store, state)
        runner = StaticCampaignTaskRunner({
            "A": [result("a-unknown", TaskOutcome.UNKNOWN, UnknownClass.TRANSIENT_UNKNOWN)],
        })
        observer = StaticObservationReader({"A": [result("a-observed-pass")]})
        finished = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-observe",
            target_observer=StaticTargetObserver("h1"),
            runner=runner,
            observation_reader=observer,
        ).run_until_boundary()

        self.assertEqual(finished.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(runner.calls, ["A"])
        self.assertEqual(observer.calls, ["A"])

    def test_stale_head_replans_then_dispatches_on_fresh_head(self):
        _, store = make_store()
        state = CampaignState(
            "campaign-stale-driver",
            1,
            {"A": CampaignTask("A", expected_target_head="old")},
        )
        bootstrap(store, state)
        runner = StaticCampaignTaskRunner({"A": [result("a-pass")]})
        finished = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-stale-driver",
            target_observer=StaticTargetObserver("new"),
            runner=runner,
            replanner=StaticReplanner({"A": True}),
        ).run_until_boundary()

        self.assertEqual(finished.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(runner.calls, ["A"])
        self.assertEqual(store.restore("campaign-stale-driver").state.tasks["A"].expected_target_head, "new")

    def test_blocked_task_is_isolated_and_independent_task_still_runs(self):
        _, store = make_store()
        state = CampaignState(
            "campaign-blocker-driver",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", expected_target_head="h1"),
            },
        )
        bootstrap(store, state)
        runner = StaticCampaignTaskRunner({
            "A": [result("a-blocked", TaskOutcome.BLOCKED)],
            "B": [result("b-pass")],
        })
        finished = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-blocker-driver",
            target_observer=StaticTargetObserver("h1"),
            runner=runner,
        ).run_until_boundary()

        self.assertEqual(finished.status, "STOP_NO_SAFE_WORK")
        self.assertEqual(runner.calls, ["A", "B"])
        restored = store.restore("campaign-blocker-driver")
        self.assertEqual(restored.state.tasks["A"].status, TaskStatus.BLOCKED)
        self.assertEqual(restored.state.tasks["B"].status, TaskStatus.COMPLETE)

    def test_confirmed_quota_exhaustion_stops_new_model_work_but_unknown_does_not(self):
        _, store = make_store()
        state = CampaignState(
            "campaign-quota-driver",
            1,
            {"A": CampaignTask("A", expected_target_head="h1")},
        )
        bootstrap(store, state)
        runner = StaticCampaignTaskRunner({"A": [result("a-pass")]})
        stopped = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-quota-driver",
            target_observer=StaticTargetObserver("h1"),
            runner=runner,
            quota_reader=StaticQuotaReader(QuotaState.EXHAUSTED),
        ).run_until_boundary()
        self.assertEqual(stopped.status, "STOP_QUOTA")
        self.assertEqual(runner.calls, [])

        allowed = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-quota-driver",
            target_observer=StaticTargetObserver("h1"),
            runner=runner,
            quota_reader=StaticQuotaReader(QuotaState.UNKNOWN),
        ).run_until_boundary()
        self.assertEqual(allowed.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(runner.calls, ["A"])

    def test_ambiguous_result_checkpoint_is_not_resent_and_fresh_controller_recovers(self):
        client, store = make_store()
        state = CampaignState(
            "campaign-ambiguous-driver",
            1,
            {
                "A": CampaignTask("A", expected_target_head="h1"),
                "B": CampaignTask("B", dependencies=("A",), expected_target_head="h1"),
            },
        )
        bootstrap(store, state)
        # revision 2 is the pre-dispatch claim; revision 3 is the post-result state.
        result_path = "symphony_campaigns/campaign-ambiguous-driver/states/00000003.json"
        client.raise_after_create_path = result_path
        client.fail_get_paths.add(result_path)
        first_runner = StaticCampaignTaskRunner({"A": [result("a-pass")]})
        uncertain = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-ambiguous-driver",
            target_observer=StaticTargetObserver("h1"),
            runner=first_runner,
        ).run_until_boundary()

        self.assertEqual(uncertain.status, "UNKNOWN_DURABILITY")
        self.assertEqual(first_runner.calls, ["A"])
        create_calls = client.create_calls

        client.fail_get_paths.clear()
        second_runner = StaticCampaignTaskRunner({"B": [result("b-pass")]})
        recovered = StaticAutonomousCampaignController(
            store,
            campaign_id="campaign-ambiguous-driver",
            target_observer=StaticTargetObserver("h1"),
            runner=second_runner,
        ).run_until_boundary()

        self.assertEqual(recovered.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(second_runner.calls, ["B"])
        self.assertGreater(client.create_calls, create_calls)

    def test_non_static_runner_cannot_be_smuggled_into_static_controller(self):
        _, store = make_store()
        bootstrap(store, CampaignState(
            "campaign-gate", 1, {"A": CampaignTask("A", expected_target_head="h1")},
        ))
        fake_live = type("FakeLive", (), {"live_enabled": True, "run": lambda *args: None})()
        with self.assertRaisesRegex(ValueError, "STATIC campaign runner"):
            StaticAutonomousCampaignController(
                store,
                campaign_id="campaign-gate",
                target_observer=StaticTargetObserver("h1"),
                runner=fake_live,
            )


if __name__ == "__main__":
    unittest.main()
