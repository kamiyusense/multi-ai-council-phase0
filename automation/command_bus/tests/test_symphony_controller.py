from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import threading
import time
import unittest

from automation.command_bus.executor import make_executor_request
from automation.command_bus.executor_backend import ExecutorContent, GitHubExecutorBackend
from automation.command_bus.symphony_controller import (
    DEFAULT_POLL_INTERVAL_MS,
    Command,
    Reservation,
    Snapshot,
    StaticFakeAgentRunner,
    SymphonyInspiredController,
    Target,
)

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
EXPIRY = (NOW + timedelta(hours=1)).isoformat()
FakeRunner = StaticFakeAgentRunner


def command(**overrides):
    values = dict(command_id="cmd-1", logical_id="logical-1", correlation_id="corr-1",
                  generation=2, expected_target_head="target-head", expires_at=EXPIRY,
                  payload={"task": "static fixture"})
    values.update(overrides)
    return Command(**values)


class FakeTracker:
    """GitHub-shaped durable-state fake; every stored object survives a new instance."""

    def __init__(self, commands=(), *, head="target-head", tree="tree-1", generation=2, carrier="carrier-1"):
        self.commands = list(commands)
        self.head = head
        self.tree = tree
        self.generation = generation
        self.carrier = carrier
        self.claims = {}
        self.receipts = {}
        self.reserve_calls = 0
        self.receipt_writes = 0
        self.ambiguous_reservation = False
        self.ambiguous_receipt = False
        self.fail_readback = False
        self.change_head_after_claim = None

    def reconcile(self):
        return Snapshot("cycle-1", tuple(self.commands), tuple(self.claims.values()),
                        tuple(self.receipts.values()), Target("owner/repo", "target", self.head, self.tree),
                        self.carrier, self.generation)

    def reserve(self, reservation: Reservation):
        self.reserve_calls += 1
        if reservation.command_id in self.claims:
            return "CONFLICT"
        self.claims[reservation.command_id] = asdict(reservation)
        if self.change_head_after_claim is not None:
            self.head = self.change_head_after_claim
        return "AMBIGUOUS" if self.ambiguous_reservation else "ACCEPTED"

    def read_reservation(self, command_id):
        if self.fail_readback:
            raise RuntimeError("unavailable")
        return self.claims.get(command_id)

    def write_receipt(self, receipt):
        self.receipt_writes += 1
        if receipt["command_id"] in self.receipts:
            return "CONFLICT"
        self.receipts[receipt["command_id"]] = receipt
        return "AMBIGUOUS" if self.ambiguous_receipt else "ACCEPTED"

    def read_receipt(self, command_id):
        if self.fail_readback:
            raise RuntimeError("unavailable")
        return self.receipts.get(command_id)


class FakeGitHubContents:
    def __init__(self):
        self.files = {}
        self.counter = 0

    def get(self, path, ref):
        return self.files.get(path)

    def list(self, prefix, ref):
        return [value for path, value in self.files.items() if path.startswith(prefix)]

    def create(self, path, text, message, branch):
        if path in self.files:
            raise ValueError("already exists")
        self.counter += 1
        content = ExecutorContent(path, text, f"sha-{self.counter}")
        self.files[path] = content
        return content

    def update(self, path, text, sha, message, branch):
        if self.files[path].sha != sha:
            raise ValueError("stale content sha")
        self.counter += 1
        content = ExecutorContent(path, text, f"sha-{self.counter}")
        self.files[path] = content
        return content


class FakeTargetReader:
    def __init__(self, *, head="target-head", tree="tree-1", generation=2, carrier="carrier-head"):
        self.head, self.tree, self.generation, self.carrier = head, tree, generation, carrier

    def read_target(self, repository, pr_number):
        return Target(repository, f"pr/{pr_number}", self.head, self.tree)

    def read_carrier_head(self, branch):
        return self.carrier

    def read_active_generation(self, loop_id):
        return self.generation


def github_executor_tracker(*, head="target-head", tree="tree-1", generation=2):
    from automation.command_bus.symphony_controller import GitHubExecutorTracker

    client = FakeGitHubContents()
    backend = GitHubExecutorBackend(client, branch="feature/controller")
    request = make_executor_request(
        request_id="github-command-1", loop_id="loop-static-1", round=1,
        correlation_id="correlation-static-1", executor_role="static-controller",
        executor_kind="fake", action="FIXTURE_ONLY", expected_repo="owner/repo",
        expected_pr=7, expected_target_head="target-head", expected_target_tree="tree-1",
        expires_at=EXPIRY,
    )
    request.update({"symphony_profile": "SYMPHONY_INSPIRED_STATIC_V1",
                   "logical_command_id": "logical-static-1", "generation": 2})
    backend.append("request", "loop-static-1", request)
    state = {"schema_version": 1, "loop_id": "loop-static-1", "state": "RUNNING",
             "round": 0, "max_rounds": 1, "expires_at": EXPIRY,
             "stop_requested": False, "last_command_id": None, "last_receipt_id": None,
             "expected_target": "work", "retry_policy": 0}
    backend.write_state("loop-static-1", state)
    tracker = GitHubExecutorTracker(
        backend, FakeTargetReader(head=head, tree=tree, generation=generation), loop_id="loop-static-1",
        carrier_branch="feature/carrier", repository="owner/repo", target_pr=7,
    )
    return tracker, backend


def controller(tracker, runner=None):
    return SymphonyInspiredController(tracker, runner or FakeRunner())


class GitHubExecutorTrackerConstructorTests(unittest.TestCase):
    def test_default_branch_write_is_rejected(self):
        from automation.command_bus.symphony_controller import GitHubExecutorTracker

        backend = GitHubExecutorBackend(FakeGitHubContents(), branch="main")
        with self.assertRaisesRegex(ValueError, "non-default branch"):
            GitHubExecutorTracker(
                backend, FakeTargetReader(), loop_id="loop", carrier_branch="main",
                repository="owner/repo", target_pr=7,
            )


class SymphonyInspiredControllerTests(unittest.TestCase):
    def test_defaults_pin_single_turn_and_static_runner(self):
        self.assertEqual(DEFAULT_POLL_INTERVAL_MS, 30_000)
        self.assertEqual(controller(FakeTracker()).poll_interval_ms, 30_000)
        with self.assertRaisesRegex(ValueError, "static fake runner"):
            controller(FakeTracker(), type("LiveRunner", (), {"live_enabled": True})())

    def test_one_cycle_selects_at_most_one_of_several_candidates(self):
        tracker = FakeTracker([command(command_id="cmd-b", logical_id="logical-b"),
                               command(command_id="cmd-a", logical_id="logical-a")])
        runner = FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.command_id, "cmd-a")
        self.assertEqual(runner.dispatch_calls, 1)
        self.assertEqual(len(tracker.claims), 1)

    def test_run_forever_stops_gracefully_between_poll_cycles(self):
        tracker, runner = FakeTracker(), FakeRunner()
        bot = SymphonyInspiredController(tracker, runner, poll_interval_ms=10)
        thread = threading.Thread(target=bot.run_forever)
        thread.start()
        time.sleep(0.04)
        bot.stop()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(runner.dispatch_calls, 0)

    def test_idle_poll_is_silent_noop(self):
        tracker, runner = FakeTracker(), FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "NOOP")
        self.assertFalse(result.selected)
        self.assertEqual((runner.prepare_calls, runner.dispatch_calls), (0, 0))
        self.assertEqual((tracker.reserve_calls, tracker.receipt_writes), (0, 0))

    def test_one_eligible_command_claims_dispatches_once_and_reads_back(self):
        tracker, runner = FakeTracker([command()]), FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "DONE")
        self.assertEqual(result.readback, "VERIFIED")
        self.assertTrue(result.selected and result.dispatch_attempted)
        self.assertFalse(result.model_started or result.provider_started)
        self.assertEqual((tracker.reserve_calls, runner.dispatch_calls, tracker.receipt_writes), (1, 1, 1))
        self.assertEqual(tracker.receipts["cmd-1"]["retry_count"], 0)
        self.assertFalse(tracker.receipts["cmd-1"]["fallback_used"])

    def test_duplicate_poll_and_fresh_restart_never_dispatch_again(self):
        tracker, runner = FakeTracker([command()]), FakeRunner()
        first = controller(tracker, runner).cycle(now=NOW)
        restarted = controller(tracker, FakeRunner()).cycle(now=NOW)
        again = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(first.terminal_status, "DONE")
        self.assertEqual(restarted.terminal_status, "NOOP")
        self.assertEqual(again.terminal_status, "NOOP")
        self.assertEqual((runner.dispatch_calls, tracker.reserve_calls, tracker.receipt_writes), (1, 1, 1))

    def test_runner_crash_records_unknown_and_is_not_redispatched_after_restart(self):
        tracker, runner = FakeTracker([command()]), FakeRunner(fail_at="dispatch")
        result = controller(tracker, runner).cycle(now=NOW)
        recovered = controller(tracker, FakeRunner()).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "UNKNOWN")
        self.assertEqual(tracker.receipts["cmd-1"]["terminal_status"], "UNKNOWN")
        self.assertTrue(result.dispatch_attempted)
        self.assertEqual(recovered.terminal_status, "NOOP")
        self.assertEqual((runner.dispatch_calls, tracker.reserve_calls), (1, 1))

    def test_stale_target_and_generation_never_reach_runner(self):
        for kwargs in ({"head": "new-target-head"}, {"generation": 3}):
            with self.subTest(kwargs=kwargs):
                tracker = FakeTracker([command()], **kwargs)
                runner = FakeRunner()
                result = controller(tracker, runner).cycle(now=NOW)
                self.assertEqual(result.terminal_status, "NOOP")
                self.assertEqual(runner.dispatch_calls, 0)

    def test_target_tree_mismatch_never_reaches_runner(self):
        tracker, runner = FakeTracker([command(expected_target_tree="expected-tree")], tree="other-tree"), FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "NOOP")
        self.assertEqual(runner.dispatch_calls, 0)

    def test_target_change_after_claim_blocks_runner(self):
        tracker = FakeTracker([command()])
        tracker.change_head_after_claim = "raced-target-head"
        runner = FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "STALE")
        self.assertEqual(runner.dispatch_calls, 0)

    def test_expired_command_never_dispatches(self):
        tracker, runner = FakeTracker([command(expires_at=(NOW - timedelta(seconds=1)).isoformat())]), FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "NOOP")
        self.assertEqual(runner.dispatch_calls, 0)

    def test_ambiguous_reservation_is_readback_only_and_never_dispatches(self):
        tracker, runner = FakeTracker([command()]), FakeRunner()
        tracker.ambiguous_reservation = True
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "UNKNOWN")
        self.assertEqual(result.readback, "READ_ONLY")
        self.assertEqual((tracker.reserve_calls, runner.dispatch_calls), (1, 0))

    def test_ambiguous_receipt_write_uses_readback_without_resend(self):
        tracker, runner = FakeTracker([command()]), FakeRunner()
        tracker.ambiguous_receipt = True
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "DONE")
        self.assertEqual(result.readback, "VERIFIED")
        self.assertEqual((tracker.receipt_writes, runner.dispatch_calls), (1, 1))

    def test_unverifiable_receipt_write_is_unknown_without_resend(self):
        tracker, runner = FakeTracker([command()]), FakeRunner()
        tracker.ambiguous_receipt = True
        tracker.fail_readback = True
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "UNKNOWN")
        self.assertEqual(result.readback, "UNKNOWN")
        self.assertEqual((tracker.receipt_writes, runner.dispatch_calls), (1, 1))

    def test_carrier_head_does_not_stale_target(self):
        tracker, runner = FakeTracker([command()], carrier="different-carrier-head"), FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "DONE")
        self.assertEqual(tracker.receipts["cmd-1"]["observed_target_head"], "target-head")
        self.assertEqual(tracker.receipts["cmd-1"]["carrier_head"], "different-carrier-head")

    def test_multiple_idle_polls_keep_model_and_provider_counts_zero(self):
        tracker, runner = FakeTracker(), FakeRunner()
        bot = controller(tracker, runner)
        results = [bot.cycle(now=NOW + timedelta(seconds=i)) for i in range(5)]
        self.assertTrue(all(not item.selected for item in results))
        self.assertEqual((runner.dispatch_calls, tracker.reserve_calls, tracker.receipt_writes), (0, 0, 0))

    def test_duplicate_logical_identity_blocks_all_contenders(self):
        tracker = FakeTracker([command(command_id="cmd-a"), command(command_id="cmd-b")])
        runner = FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "NOOP")
        self.assertEqual(runner.dispatch_calls, 0)
        self.assertEqual(tracker.reserve_calls, 0)

    def test_prepare_crash_does_not_claim_dispatch_attempt(self):
        tracker, runner = FakeTracker([command()]), FakeRunner(fail_at="prepare")
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "UNKNOWN")
        self.assertFalse(result.dispatch_attempted)
        self.assertEqual(runner.dispatch_calls, 0)

    def test_github_adapter_reuses_executor_claim_result_receipt_and_recovery(self):
        from automation.command_bus.symphony_controller import GitHubExecutorTracker

        tracker, backend = github_executor_tracker()
        runner = FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "DONE")
        self.assertEqual(runner.dispatch_calls, 1)
        recovered = backend.recover("loop-static-1")
        self.assertEqual(recovered.status, "RECOVERED")
        ledger = recovered.record["ledger"]
        self.assertEqual((len(ledger.claims), len(ledger.results), len(ledger.receipts)), (1, 1, 1))
        self.assertEqual(ledger.results[0]["retry_count"], 0)
        self.assertFalse(ledger.results[0]["model_executed"])
        restarted = GitHubExecutorTracker(
            backend, tracker.target_reader, loop_id="loop-static-1", carrier_branch="feature/carrier",
            repository="owner/repo", target_pr=7,
        )
        replay = controller(restarted, FakeRunner()).cycle(now=NOW)
        self.assertEqual(replay.terminal_status, "NOOP")

    def test_github_adapter_generation_and_target_guards_are_independent(self):
        for head, tree, generation in (("moved-target", "tree-1", 2), ("target-head", "other-tree", 2),
                                       ("target-head", "tree-1", 3)):
            with self.subTest(head=head, tree=tree, generation=generation):
                tracker, _ = github_executor_tracker(head=head, tree=tree, generation=generation)
                runner = FakeRunner()
                result = controller(tracker, runner).cycle(now=NOW)
                self.assertEqual(result.terminal_status, "NOOP")
                self.assertEqual(runner.dispatch_calls, 0)


if __name__ == "__main__":
    unittest.main()
