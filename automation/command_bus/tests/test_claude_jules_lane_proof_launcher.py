import unittest
from unittest.mock import Mock, patch

from automation.command_bus import claude_jules_lane_proof_launcher as launcher


class _Rest:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def pull(self, number):
        self.calls.append(number)
        return self.value


class _Facts:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def dispatch_observation(self, command_id):
        self.calls.append(command_id)
        return self.value


class ClaudeJulesLaneProofLauncherTests(unittest.TestCase):
    def test_target_reader_returns_collector_shape_and_fails_closed(self):
        pr = {
            "number": 304,
            "state": "open",
            "merged": False,
            "head": {"sha": "a" * 40},
        }
        rest = _Rest(pr)
        reader = launcher.StableLaneTargetReader(rest, "kamiyusense/multi-ai-council-phase0")
        self.assertEqual(
            reader.read_target("kamiyusense/multi-ai-council-phase0", 304),
            {
                "repo": "kamiyusense/multi-ai-council-phase0",
                "pr": 304,
                "head": "a" * 40,
                "state": "open",
                "merged": False,
            },
        )
        self.assertIsNone(reader.read_target("other/repo", 304))
        self.assertEqual(rest.calls, [304])

    def test_session_reader_normalizes_existing_jules_get_shape(self):
        raw = Mock()
        raw.read_active_session.return_value = {
            "name": "sessions/12345",
            "createTime": "2026-10-04T09:00:00Z",
            "updateTime": "2026-10-04T09:01:00Z",
            "state": "IN_PROGRESS",
            "sourceContext": {
                "source": "github",
                "githubRepoContext": {"startingBranch": "jules-work/loop-999"},
            },
        }
        reader = launcher.StableLaneSessionReader(raw)
        self.assertEqual(
            reader.read_active_session("12345", expected_branch="jules-work/loop-999"),
            {
                "provider_raw_state": "IN_PROGRESS",
                "starting_branch": "jules-work/loop-999",
                "create_time": "2026-10-04T09:00:00Z",
                "update_time": "2026-10-04T09:01:00Z",
            },
        )
        raw.read_active_session.assert_called_once_with("12345", expected_branch="jules-work/loop-999")
        raw.read_active_session.return_value = {"state": "IN_PROGRESS"}
        with self.assertRaises(launcher.ProofError):
            reader.read_active_session("12345", expected_branch="jules-work/loop-999")

    def test_session_source_requires_one_successful_numeric_session(self):
        facts = _Facts({"conclusion": "success", "session_id": "12345"})
        source = launcher.CarrierSessionIdSource(facts)
        self.assertEqual(source("loop-999"), "12345")
        self.assertEqual(facts.calls, ["loop-999"])

        for value in (
            None,
            {"conclusion": "failure", "session_id": "12345"},
            {"conclusion": "success", "session_id": None},
            {"conclusion": "success", "session_id": "abc"},
        ):
            with self.subTest(value=value):
                with self.assertRaises(launcher.ProofError):
                    launcher.CarrierSessionIdSource(_Facts(value))("loop-999")

    def test_session_source_waits_for_the_carrier_run_without_touching_jules(self):
        class Later:
            def __init__(self):
                self.calls = 0

            def dispatch_observation(self, command_id):
                self.calls += 1
                return None if self.calls < 3 else {"conclusion": "success", "session_id": "12345"}

        facts, sleeps, clock = Later(), [], [0]
        source = launcher.CarrierSessionIdSource(
            facts, wait_seconds=60, interval_seconds=10, sleep=lambda n: (sleeps.append(n), clock.__setitem__(0, clock[0] + n)),
            monotonic=lambda: clock[0])
        self.assertEqual(source("loop-999"), "12345")
        self.assertEqual((facts.calls, sleeps), (3, [10, 10]))

    def test_session_source_wait_is_bounded_and_failure_ends_it_at_once(self):
        clock = [0]
        never = _Facts(None)
        source = launcher.CarrierSessionIdSource(
            never, wait_seconds=30, interval_seconds=10, sleep=lambda n: clock.__setitem__(0, clock[0] + n),
            monotonic=lambda: clock[0])
        with self.assertRaises(launcher.ProofError):
            source("loop-999")
        self.assertEqual(never.calls, ["loop-999"] * 4)
        failed = _Facts({"conclusion": "failure", "session_id": None})
        with self.assertRaises(launcher.ProofError):
            launcher.CarrierSessionIdSource(failed, wait_seconds=30, sleep=lambda n: None)("loop-999")
        self.assertEqual(len(failed.calls), 1)

    def test_builder_only_constructs_existing_ports_and_performs_no_effect(self):
        repository = "kamiyusense/multi-ai-council-phase0"
        policy = {
            "default_branch": "main",
            "data_branch": "claude/claude-jules-autoloop-data",
            "target_repo": repository,
            "carrier_branch": "feature/chat-work-command-bus",
            "allowed_target_branches": ["feature/proof-target"],
        }
        intent = {"carrier_request": {"target_repo": repository, "target_branch": "feature/proof-target"}}
        clock = Mock()
        git = Mock()
        rest = Mock()
        owner = Mock()
        guard = Mock()
        dispatcher = Mock()
        facts = Mock()
        session_reader = Mock()
        collector = Mock()

        with (
            patch.object(launcher, "validate_dispatch_intent", return_value=intent) as validate,
            patch.object(launcher, "GitLiveClient", return_value=git) as git_cls,
            patch.object(launcher, "GitHubRestReader", return_value=rest) as rest_cls,
            patch.object(launcher, "LoopOwnerGitHubBackend", return_value=owner) as owner_cls,
            patch.object(launcher, "CarrierQuietGuard", return_value=guard) as guard_cls,
            patch.object(launcher, "ClaudeJulesDispatcher", return_value=dispatcher) as dispatcher_cls,
            patch.object(launcher, "LiveResultFacts", return_value=facts) as facts_cls,
            patch.object(launcher, "JulesActiveSessionGetReader", return_value=session_reader) as session_cls,
            patch.object(launcher, "ControlTowerDurableCollector", return_value=collector) as collector_cls,
        ):
            ports = launcher.build_live_proof_ports(
                repo_dir=".",
                policy=policy,
                intent=intent,
                jules_api_key="existing-key",
                dispatches_used=4,
                scratch_dir="/tmp/proof",
                clock=clock,
            )

        validate.assert_called_once_with(intent)
        git_cls.assert_called_once_with(".")
        rest_cls.assert_called_once_with(repository)
        owner_cls.assert_called_once_with(git, branch=policy["data_branch"])
        guard_cls.assert_called_once()
        dispatcher_cls.assert_called_once()
        facts_cls.assert_called_once()
        session_cls.assert_called_once_with("existing-key")
        collector_cls.assert_called_once()
        self.assertIs(ports.client, git)
        self.assertIs(ports.dispatcher, dispatcher)
        self.assertIsInstance(ports.session_reader, launcher.StableLaneSessionReader)
        self.assertIs(ports.session_reader.reader, session_reader)
        self.assertIs(ports.collector, collector)
        self.assertIs(ports.clock, clock)
        dispatcher.dispatch.assert_not_called()
        facts.dispatch_observation.assert_not_called()
        session_reader.read_active_session.assert_not_called()
        collector.collect_transition.assert_not_called()

    def test_builder_refuses_default_branch_data_and_out_of_policy_intent(self):
        repository = "kamiyusense/multi-ai-council-phase0"
        base = {
            "default_branch": "main",
            "data_branch": "main",
            "target_repo": repository,
            "carrier_branch": "feature/chat-work-command-bus",
            "allowed_target_branches": ["feature/proof-target"],
        }
        with self.assertRaises(ValueError):
            launcher.build_live_proof_ports(
                repo_dir=".",
                policy=base,
                intent={},
                jules_api_key="existing-key",
                dispatches_used=4,
                scratch_dir="/tmp/proof",
            )

        policy = dict(base, data_branch="claude/data")
        intent = {"carrier_request": {"target_repo": repository, "target_branch": "feature/other"}}
        with patch.object(launcher, "validate_dispatch_intent", return_value=intent):
            with self.assertRaises(ValueError):
                launcher.build_live_proof_ports(
                    repo_dir=".",
                    policy=policy,
                    intent=intent,
                    jules_api_key="existing-key",
                    dispatches_used=4,
                    scratch_dir="/tmp/proof",
                )


if __name__ == "__main__":
    unittest.main()
