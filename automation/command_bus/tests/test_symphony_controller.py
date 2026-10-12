from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import threading
import time
import unittest
import json
import tempfile
import queue
from pathlib import Path
from unittest.mock import patch

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

# Keep the fixture clock far in the future because GitHubExecutorTracker.reserve()
# correctly uses the real wall clock for durable claim timestamps. A historical
# fixed date makes the suite start failing once that fixture expiry passes.
NOW = datetime(2099, 1, 1, 12, tzinfo=timezone.utc)
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


class FakeLiveCapableTracker(FakeTracker):
    supports_live_model_execution = True


class FakeGitHubContents:
    def __init__(self):
        self.files = {}
        self.counter = 0
        self.create_calls = 0
        self.raise_after_create_path = None
        self.fail_get_paths = set()

    def get(self, path, ref):
        if path in self.fail_get_paths and path in self.files:
            raise RuntimeError("fake readback unavailable")
        return self.files.get(path)

    def list(self, prefix, ref):
        return [value for path, value in self.files.items() if path.startswith(prefix)]

    def create(self, path, text, message, branch):
        self.create_calls += 1
        if path in self.files:
            raise ValueError("already exists")
        self.counter += 1
        content = ExecutorContent(path, text, f"sha-{self.counter}")
        self.files[path] = content
        if self.raise_after_create_path == path:
            self.raise_after_create_path = None
            raise RuntimeError("ambiguous response after durable create")
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


class FakeLiveTargetReader:
    def __init__(self, *, head="target-head", tree="tree-1", generation=2,
                 repository="owner/repo", branch="proof/symphony-live-one-round-v1"):
        self.head, self.tree, self.generation = head, tree, generation
        self.repository, self.branch = repository, branch

    def read_target(self, repository, pr_number):
        return Target(self.repository, self.branch, self.head, self.tree)

    def read_carrier_head(self, branch):
        return "carrier-head"

    def read_active_generation(self, loop_id):
        return self.generation


def live_command_record():
    return {
        "record_type": "SYMPHONY_LIVE_COMMAND_V1", "protocol_version": "SYMPHONY_LIVE_V1",
        "command_id": "live-cmd-1", "logical_id": "live-logical-1", "correlation_id": "live-corr-1",
        "generation": 2, "target_repository": "owner/repo",
        "target_branch": "proof/symphony-live-one-round-v1", "default_branch": "main",
        "expected_target_head": "target-head",
        "expected_target_tree": "tree-1", "expires_at": EXPIRY,
        "allowed_paths": ["evidence/symphony_live_one_round_v1.txt"],
        "exact_task": "Create evidence/symphony_live_one_round_v1.txt with exact content "
                       "SYMPHONY_LIVE_ONE_ROUND_V1_PASS and no other changes.",
        "verification": {"exact_content": "SYMPHONY_LIVE_ONE_ROUND_V1_PASS"},
        "live_provider_or_model_allowed": True, "max_concurrent_agents": 1,
        "max_model_starts": 1, "max_turns": 1, "retry": 0,
        "fallback": "disabled", "status": "READY",
    }


from contextlib import contextmanager


@contextmanager
def fake_codex_transport(result=None):
    from automation.command_bus.symphony_codex_app_server import (
        CodexDispatchResult, GitWorkspaceVerifier, JsonlCodexAppServer,
    )

    answer = result or CodexDispatchResult("DONE", True, True, "thread-1", "turn-1", ())
    evidence = ({"status": "LOCAL_PASS", "proof_path": "evidence/symphony_live_one_round_v1.txt",
                 "proof_content": "SYMPHONY_LIVE_ONE_ROUND_V1_PASS"},
                ("evidence/symphony_live_one_round_v1.txt",), "a" * 40)
    with patch.object(JsonlCodexAppServer, "execute_one_turn", return_value=answer) as dispatch, \
         patch.object(GitWorkspaceVerifier, "prepare", return_value=("target-head", "tree-1", "main-head")), \
         patch.object(GitWorkspaceVerifier, "verify", return_value=evidence):
        yield dispatch


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

    def test_concrete_github_contents_write_is_single_request_and_blocks_default_branch(self):
        from automation.command_bus.symphony_github_adapter import GitHubExecutorContentsClient

        client = GitHubExecutorContentsClient("fake-token", "owner/repo")
        calls = []

        def request(method, path, body=None):
            calls.append((method, path, body))
            return 201, {"content": {"sha": "content-sha"}}

        client._request = request
        written = client.create("execution_results/loop/id.json", "{}", "write result", "feature/proof")
        self.assertEqual(written.sha, "content-sha")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "PUT")
        with self.assertRaisesRegex(ValueError, "default branch"):
            client.create("record.json", "{}", "unsafe", "main")
        self.assertEqual(len(calls), 1)


class SymphonyLiveDurableTrackerTests(unittest.TestCase):
    def make_tracker(self, client, reader=None):
        from automation.command_bus.symphony_live_store import GitHubSymphonyLiveTracker

        return GitHubSymphonyLiveTracker(
            client, reader or FakeLiveTargetReader(), loop_id="loop-live-1", repository="owner/repo",
            target_pr=9, target_branch="proof/symphony-live-one-round-v1",
            carrier_branch="feature/controller-carrier", write_branch="feature/controller-records",
        )

    def test_live_records_are_separate_create_only_and_terminal_replay_is_noop(self):
        from automation.command_bus.symphony_codex_app_server import CodexAppServerAgentRunner
        from automation.command_bus.symphony_live_store import RESULT_TYPE

        client = FakeGitHubContents()
        tracker = self.make_tracker(client)
        command_path = "symphony_live/commands/live-cmd-1.json"
        client.raise_after_create_path = command_path
        self.assertEqual(tracker.create_command(live_command_record()), "ACCEPTED")
        self.assertEqual(tracker.create_command(live_command_record()), "CONFLICT")
        duplicate_logical = live_command_record()
        duplicate_logical["command_id"] = "live-cmd-2"
        self.assertEqual(tracker.create_command(duplicate_logical), "CONFLICT")
        self.assertIn(command_path, client.files)
        self.assertNotIn("execution_requests/loop-live-1/live-cmd-1.json", client.files)

        result_path = "symphony_live/results/live-cmd-1.json"
        client.raise_after_create_path = result_path
        with fake_codex_transport() as starts:
            runner = CodexAppServerAgentRunner(cwd=Path(__file__).resolve().parents[3], live_enabled=True)
            first = controller(tracker, runner).cycle(now=NOW)
            self.assertEqual(first.terminal_status, "UNKNOWN")
            self.assertEqual(first.readback, "UNKNOWN")
        stored = __import__("json").loads(client.files[result_path].text)
        self.assertEqual(stored["record_type"], RESULT_TYPE)
        self.assertEqual((stored["dispatch_count"], stored["model_start_count"], stored["retry_count"]), (1, 1, 0))
        self.assertTrue(stored["terminal"])
        self.assertEqual(stored["head_before"], stored["head_after"])
        self.assertEqual(client.create_calls, 3)
        restarted = self.make_tracker(client)
        replay = controller(restarted, CodexAppServerAgentRunner(
            cwd=Path(__file__).resolve().parents[3], live_enabled=True,
        )).cycle(now=NOW)
        self.assertEqual(replay.terminal_status, "NOOP")
        self.assertEqual(starts.call_count, 1)
        self.assertEqual(client.create_calls, 3)

    def test_unverifiable_ambiguous_live_result_is_not_recreated_after_restart(self):
        from automation.command_bus.symphony_codex_app_server import CodexAppServerAgentRunner

        client = FakeGitHubContents()
        tracker = self.make_tracker(client)
        self.assertEqual(tracker.create_command(live_command_record()), "ACCEPTED")
        result_path = "symphony_live/results/live-cmd-1.json"
        client.raise_after_create_path = result_path
        client.fail_get_paths.add(result_path)
        cwd = Path(__file__).resolve().parents[3]
        from automation.command_bus.symphony_codex_app_server import CodexDispatchResult
        answer = CodexDispatchResult("UNKNOWN", True, None, None, None, (), "timeout")
        with fake_codex_transport(answer) as starts:
            result = controller(tracker, CodexAppServerAgentRunner(
                cwd=cwd, live_enabled=True,
            )).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "UNKNOWN")
        self.assertIn(result_path, client.files)
        self.assertEqual(client.create_calls, 3)
        client.fail_get_paths.clear()
        replay = controller(self.make_tracker(client), CodexAppServerAgentRunner(
            cwd=cwd, live_enabled=True,
        )).cycle(now=NOW)
        self.assertEqual(replay.terminal_status, "NOOP")
        self.assertEqual((starts.call_count, client.create_calls), (1, 3))

    def test_live_command_stale_head_or_generation_is_rejected_before_write(self):
        for reader in (FakeLiveTargetReader(head="moved-head"), FakeLiveTargetReader(generation=3)):
            with self.subTest(head=reader.head, generation=reader.generation):
                client = FakeGitHubContents()
                tracker = self.make_tracker(client, reader)
                self.assertEqual(tracker.create_command(live_command_record()), "CONFLICT")
                self.assertEqual(client.create_calls, 0)

    def test_live_command_requires_exact_one_turn_retry_zero_and_fallback_off(self):
        from automation.command_bus.symphony_live_store import validate_live_command

        for key, value in (("max_concurrent_agents", 2), ("max_model_starts", 2),
                           ("max_turns", 2), ("retry", 1), ("fallback", "enabled")):
            bad = live_command_record()
            bad[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "limits"):
                validate_live_command(bad)

    def test_live_pass_evidence_requires_remote_readback_and_all_no_mutation_counts(self):
        from automation.command_bus.symphony_live_store import _has_complete_pass_evidence

        head_before = "1" * 40
        head_after = "2" * 40
        verification = {
            "status": "PASS", "proof_path": "evidence/symphony_live_one_round_v1.txt",
            "proof_content": "SYMPHONY_LIVE_ONE_ROUND_V1_PASS", "commit_parent": head_before,
            "normal_commit": True, "force_push_count": 0, "merge_count": 0,
            "default_branch_mutation_count": 0, "max_turns": 1, "remote_readback": "PASS",
        }
        self.assertTrue(_has_complete_pass_evidence(
            verification, head_before=head_before, head_after=head_after, dispatch_count=1,
            model_start_count=1, changed_paths=["evidence/symphony_live_one_round_v1.txt"],
            proof_commit_sha=head_after,
        ))
        verification["force_push_count"] = 1
        self.assertFalse(_has_complete_pass_evidence(
            verification, head_before=head_before, head_after=head_after, dispatch_count=1,
            model_start_count=1, changed_paths=["evidence/symphony_live_one_round_v1.txt"],
            proof_commit_sha=head_after,
        ))


class SymphonyRemoteProofVerificationTests(unittest.TestCase):
    def test_remote_verifier_pushes_once_without_force_and_requires_exact_readbacks(self):
        from automation.command_bus.symphony_codex_app_server import (
            GitWorkspaceVerifier, PreparedCodexCommand,
        )

        branch = "proof/symphony-live-one-round-v1"
        head_before, head_after, main_head = "1" * 40, "2" * 40, "3" * 40
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory) / "evidence/symphony_live_one_round_v1.txt"
            proof.parent.mkdir(parents=True)
            proof.write_text("SYMPHONY_LIVE_ONE_ROUND_V1_PASS", encoding="utf-8")
            payload = {
                "target_branch": branch, "target_repository": "owner/repo", "default_branch": "main",
            }
            prepared = PreparedCodexCommand(
                command(payload=payload), directory, "create exact proof", head_before, "tree-before", main_head,
            )
            target_ref_reads = [0]

            def git_read(_cwd, *args):
                if args == ("rev-parse", "HEAD"):
                    return head_after
                if args == ("branch", "--show-current"):
                    return branch
                if args == ("status", "--porcelain", "--untracked-files=all"):
                    return ""
                if args[:4] == ("rev-list", "--parents", "-n", "1"):
                    return f"{head_after} {head_before}"
                if args[:3] == ("diff", "--name-only", "--no-renames"):
                    return "evidence/symphony_live_one_round_v1.txt"
                if args[:2] == ("rev-list", "--count"):
                    return "1"
                if args[:2] == ("ls-remote", "--exit-code") and args[-1] == f"refs/heads/{branch}":
                    target_ref_reads[0] += 1
                    value = head_before if target_ref_reads[0] == 1 else head_after
                    return f"{value}\trefs/heads/{branch}"
                if args[:2] == ("ls-remote", "--exit-code") and args[-1] == "refs/heads/main":
                    return f"{main_head}\trefs/heads/main"
                raise AssertionError(f"unexpected git read: {args}")

            pushes = []

            def push_once(argv, **kwargs):
                pushes.append((argv, kwargs))
                return __import__("subprocess").CompletedProcess(argv, 0, "ok", "")

            with patch.object(GitWorkspaceVerifier, "_git", side_effect=git_read), \
                 patch.object(GitWorkspaceVerifier, "_proof_pr_count", return_value=0), \
                 patch("automation.command_bus.symphony_codex_app_server.subprocess.run", side_effect=push_once):
                evidence, paths, commit_sha = GitWorkspaceVerifier.verify(prepared)

        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["remote_readback"], "PASS")
        self.assertEqual(evidence["force_push_count"], 0)
        self.assertEqual(evidence["merge_count"], 0)
        self.assertEqual(evidence["default_branch_mutation_count"], 0)
        self.assertEqual(pushes[0][0], ["git", "push", "origin", f"HEAD:refs/heads/{branch}"])
        self.assertEqual(len(pushes), 1)
        self.assertEqual(target_ref_reads[0], 2)
        self.assertEqual(paths, ("evidence/symphony_live_one_round_v1.txt",))
        self.assertEqual(commit_sha, head_after)


class SymphonyInspiredControllerTests(unittest.TestCase):
    def test_defaults_pin_single_turn_and_static_runner(self):
        self.assertEqual(DEFAULT_POLL_INTERVAL_MS, 30_000)
        self.assertEqual(controller(FakeTracker()).poll_interval_ms, 30_000)
        with self.assertRaisesRegex(ValueError, "static fake runner"):
            controller(FakeTracker(), type("LiveRunner", (), {"live_enabled": True})())

    def test_only_exact_codex_app_server_runner_is_admitted(self):
        from automation.command_bus.symphony_codex_app_server import CodexAppServerAgentRunner

        with self.assertRaisesRegex(ValueError, "CodexAppServerAgentRunner"):
            controller(FakeTracker(), type("OtherLiveRunner", (), {"live_enabled": True})())
        cwd = Path(__file__).resolve().parents[3]
        disabled = CodexAppServerAgentRunner(cwd=cwd)
        with self.assertRaisesRegex(ValueError, "LIVE flag"):
            controller(FakeLiveCapableTracker(), disabled)
        runner = CodexAppServerAgentRunner(cwd=cwd, live_enabled=True)
        with self.assertRaisesRegex(ValueError, "truthfully persist LIVE"):
            controller(FakeTracker(), runner)
        self.assertIsInstance(controller(FakeLiveCapableTracker(), runner), SymphonyInspiredController)

    def test_codex_adapter_is_off_by_default_and_hard_limits_one_start(self):
        from automation.command_bus.symphony_codex_app_server import CodexAppServerAgentRunner

        cwd = Path(__file__).resolve().parents[3]
        runner = CodexAppServerAgentRunner(cwd=cwd)
        with self.assertRaisesRegex(RuntimeError, "LIVE flag is off"):
            runner.prepare(command(payload={"task": "one exact task"}))
        valid_task = "Create evidence/symphony_live_one_round_v1.txt with exact content SYMPHONY_LIVE_ONE_ROUND_V1_PASS only."
        proof_scope = {"allowed_paths": ["evidence/symphony_live_one_round_v1.txt"],
                       "verification": {"exact_content": "SYMPHONY_LIVE_ONE_ROUND_V1_PASS"}}
        with fake_codex_transport() as starts:
            live_runner = CodexAppServerAgentRunner(cwd=cwd, live_enabled=True)
            prepared = live_runner.prepare(command(payload={
                **proof_scope, "task": valid_task, "retry": 0, "fallback": "disabled",
                "target_repository": "owner/repo", "target_branch": "proof/symphony-live-one-round-v1",
                "default_branch": "main",
                "concurrency": 1, "max_turns": 1, "max_model_starts": 1,
            }))
            result = live_runner.dispatch(prepared)
            self.assertEqual(live_runner.classify_result(result), "DONE")
            self.assertTrue(result.model_started)
            with self.assertRaisesRegex(RuntimeError, "maximum model starts"):
                live_runner.dispatch(prepared)
            self.assertEqual(starts.call_count, 1)
        for key, unsafe in (("retry", 1), ("fallback", "enabled"), ("concurrency", 2),
                            ("max_turns", 2), ("max_model_starts", 2), ("max_turns", True)):
            policy = {**proof_scope, "task": valid_task, "retry": 0, "fallback": "disabled",
                      "concurrency": 1, "max_turns": 1, "max_model_starts": 1}
            policy[key] = unsafe
            with self.subTest(key=key, unsafe=unsafe), self.assertRaisesRegex(ValueError, "policy"):
                CodexAppServerAgentRunner(cwd=cwd, live_enabled=True).prepare(
                    command(payload=policy))

    def test_codex_strict_start_budget_is_per_task_not_runner_lifetime(self):
        from automation.command_bus.symphony_codex_app_server import CodexAppServerAgentRunner

        cwd = Path(__file__).resolve().parents[3]
        valid_task = "Create evidence/symphony_live_one_round_v1.txt with exact content SYMPHONY_LIVE_ONE_ROUND_V1_PASS only."
        payload = {
            "allowed_paths": ["evidence/symphony_live_one_round_v1.txt"],
            "verification": {"exact_content": "SYMPHONY_LIVE_ONE_ROUND_V1_PASS"},
            "task": valid_task, "retry": 0, "fallback": "disabled",
            "target_repository": "owner/repo",
            "target_branch": "proof/symphony-live-one-round-v1",
            "default_branch": "main", "concurrency": 1,
            "max_turns": 1, "max_model_starts": 1,
        }
        first = command(payload=payload)
        second = command(
            command_id="cmd-2", logical_id="logical-2", correlation_id="corr-2",
            payload=payload,
        )
        with fake_codex_transport() as starts:
            runner = CodexAppServerAgentRunner(cwd=cwd, live_enabled=True)
            prepared_first = runner.prepare(first)
            self.assertEqual(runner.classify_result(runner.dispatch(prepared_first)), "DONE")
            with self.assertRaisesRegex(RuntimeError, "for task"):
                runner.dispatch(prepared_first)

            prepared_second = runner.prepare(second)
            self.assertEqual(runner.classify_result(runner.dispatch(prepared_second)), "DONE")
            self.assertEqual(starts.call_count, 2)

    def test_codex_ambiguous_submit_is_unknown_and_never_retried(self):
        from automation.command_bus.symphony_codex_app_server import CodexAppServerAgentRunner, CodexDispatchResult

        cwd = Path(__file__).resolve().parents[3]
        ambiguous = CodexDispatchResult("UNKNOWN", True, None, None, None, (), "timeout")
        live_tracker = FakeLiveCapableTracker([command(payload={
            "allowed_paths": ["evidence/symphony_live_one_round_v1.txt"],
            "verification": {"exact_content": "SYMPHONY_LIVE_ONE_ROUND_V1_PASS"},
            "task": "Create evidence/symphony_live_one_round_v1.txt with exact content SYMPHONY_LIVE_ONE_ROUND_V1_PASS only.",
            "retry": 0, "fallback": "disabled",
            "concurrency": 1, "max_turns": 1, "max_model_starts": 1,
        })])
        with fake_codex_transport(ambiguous) as starts:
            runner = CodexAppServerAgentRunner(cwd=cwd, live_enabled=True)
            result = controller(live_tracker, runner).cycle(now=NOW)
            replay = controller(live_tracker, runner).cycle(now=NOW)
        self.assertEqual(result.terminal_status, "UNKNOWN")
        self.assertIsNone(result.model_started)
        self.assertEqual(replay.terminal_status, "NOOP")
        self.assertEqual((starts.call_count, live_tracker.receipt_writes), (1, 1))
        self.assertIsNone(live_tracker.receipts["cmd-1"]["model_start_count"])

    def test_jsonl_app_server_protocol_uses_one_turn_and_captures_terminal_events(self):
        from automation.command_bus.symphony_codex_app_server import JsonlCodexAppServer

        class FakeStdout:
            def __init__(self):
                self.lines = queue.Queue()

            def __iter__(self):
                return self

            def __next__(self):
                line = self.lines.get()
                if line is None:
                    raise StopIteration
                return line

        class FakeStdin:
            def __init__(self, stdout, calls):
                self.stdout, self.calls = stdout, calls

            def write(self, line):
                request = json.loads(line)
                self.calls.append(request.get("method"))
                if request.get("method") == "initialized":
                    return
                if request.get("method") == "turn/start":
                    for event in (
                        {"jsonrpc": "2.0", "method": "turn/started", "params": {"turn": {"id": "turn-1"}}},
                        {"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}},
                    ):
                        self.stdout.lines.put(json.dumps(event) + "\n")
                result = {"thread": {"id": "thread-1"}, "modelProvider": "openai"} if request.get("method") == "thread/start" else (
                    {"turn": {"id": "turn-1", "status": "inProgress"}} if request.get("method") == "turn/start" else {})
                if request.get("method") == "account/read":
                    result = {"requiresOpenaiAuth": True, "account": {"type": "chatgpt", "planType": "plus"}}
                elif request.get("method") == "config/read":
                    result = {"config": {"model_provider": "openai"}}
                self.stdout.lines.put(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}) + "\n")

            def flush(self):
                pass

            def close(self):
                pass

        class FakeProcess:
            def __init__(self):
                self.stdout = FakeStdout()
                self.calls = []
                self.stdin = FakeStdin(self.stdout, self.calls)

            def terminate(self):
                self.stdout.lines.put(None)

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.terminate()

        process = FakeProcess()
        cwd = Path(__file__).resolve().parents[3]
        with patch.dict("os.environ", {"PATH": "/bin", "HOME": "/STATIC_HOME",
                                      "GITHUB_TOKEN": "fixture-key", "SYMPHONY_G5_OBSERVER_EVENTS": "/STATIC_EVENTS"}, clear=True):
            with patch("automation.command_bus.symphony_codex_app_server.subprocess.Popen", return_value=process) as popen:
                result = JsonlCodexAppServer().execute_one_turn(cwd=str(cwd), prompt="one turn", live_enabled=True)
        self.assertEqual(result.status, "DONE")
        self.assertTrue(result.dispatch_attempted and result.model_started)
        self.assertEqual(process.calls.count("turn/start"), 1)
        self.assertEqual(popen.call_args.args[0][-1], "app-server")
        self.assertNotIn("OPENAI_API_KEY", popen.call_args.kwargs["env"])
        self.assertNotIn("CODEX_API_KEY", popen.call_args.kwargs["env"])
        self.assertNotIn("GITHUB_TOKEN", popen.call_args.kwargs["env"])
        self.assertNotIn("SYMPHONY_G5_OBSERVER_EVENTS", popen.call_args.kwargs["env"])
        self.assertLess(process.calls.index("account/read"), process.calls.index("turn/start"))

    def test_one_cycle_selects_at_most_one_of_several_candidates(self):
        tracker = FakeTracker([command(command_id="cmd-b", logical_id="logical-b"),
                               command(command_id="cmd-a", logical_id="logical-a")])
        runner = FakeRunner()
        result = controller(tracker, runner).cycle(now=NOW)
        self.assertEqual(result.command_id, "cmd-a")
        self.assertEqual(runner.dispatch_calls, 1)
        self.assertEqual(len(tracker.claims), 1)

    def test_concurrent_cycles_enforce_single_controller_dispatch(self):
        tracker = FakeTracker([command(command_id="cmd-a", logical_id="logical-a"),
                               command(command_id="cmd-b", logical_id="logical-b")])
        runner = FakeRunner()
        entered, release = threading.Event(), threading.Event()

        def blocked_dispatch(prepared):
            runner.dispatch_calls += 1
            entered.set()
            release.wait(timeout=2)
            return "DONE"

        runner.dispatch = blocked_dispatch
        bot = controller(tracker, runner)
        first_results = []
        worker = threading.Thread(target=lambda: first_results.append(bot.cycle(now=NOW)))
        worker.start()
        self.assertTrue(entered.wait(timeout=1))
        concurrent = bot.cycle(now=NOW)
        release.set()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(concurrent.terminal_status, "NOOP")
        self.assertEqual((runner.dispatch_calls, tracker.reserve_calls), (1, 1))

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
