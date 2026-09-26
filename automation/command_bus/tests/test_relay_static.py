from datetime import datetime, timezone
import unittest

from automation.command_bus.relay_static import (
    EXECUTE_ACTION,
    PREPARE_ACTION,
    REQUIRED_PROHIBITED_PATHS,
    REQUIRED_PROFILE,
    REQUIRED_TEST_COMMANDS,
    REQUIRED_PATH_POLICY,
    prepare_relay_batch,
    validate_relay_command,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
REPO = "kamiyusense/multi-ai-council-phase0"
HEAD = "ffcdff208d12620d423592df78af1fd1eb88950e"
TREE = "62e681613be4de68ee5987634a075078f6bb522a"
LOOP = "relay-static-002"


class FakeContents:
    def __init__(self, head=HEAD):
        self.head = head
        self.reads = []

    def read_pr_head(self, repository, pull_request):
        self.reads.append((repository, pull_request))
        return self.head


def state(**changes):
    value = {
        "loop_id": LOOP,
        "state": "RUNNING",
        "stop_requested": False,
        "round": 0,
        "max_rounds": 6,
        "expires_at": "2026-09-24T23:59:00+09:00",
    }
    value.update(changes)
    return value


def command(**changes):
    value = {
        "schema_version": 1,
        "command_id": f"{LOOP}-000001",
        "loop_id": LOOP,
        "round": 1,
        "correlation_id": f"{LOOP}-round-1",
        "target": "work",
        "action": PREPARE_ACTION,
        "expected_repo": REPO,
        "expected_pr": 4,
        "expected_target_head": HEAD,
        "allowed_paths": ["src/relay/**", "src/providers/**", "tests/relay/**"],
        "prohibited_paths": sorted(REQUIRED_PROHIBITED_PATHS),
        "objective": "prepare static relay batch",
        "test_commands": list(REQUIRED_TEST_COMMANDS),
        "requires_live_model": False,
        "requires_github_write": False,
        "retry": 0,
        "fallback": "disabled",
        "expires_at": "2026-09-24T23:59:00+09:00",
        "predecessor_receipt_id": "route-validation-006/000001",
        "execution_mode": "PREPARE_ONLY",
        "profile": REQUIRED_PROFILE,
    }
    value.update(changes)
    return value


class RelayStaticContractTests(unittest.TestCase):
    def test_prepare_reads_target_head_and_never_writes_pr4(self):
        client = FakeContents()
        result = prepare_relay_batch(
            command(), client=client, repository=REPO,
            target_pr=4, state=state(), now=NOW,
        )
        self.assertEqual(result.status, "PREPARED")
        self.assertEqual(result.evidence["execution_mode"], "PREPARE_ONLY")
        self.assertFalse(result.evidence["target_pr_modified"])
        self.assertEqual(client.reads, [(REPO, 4)])

    def test_execute_action_requires_explicit_static_write_mode(self):
        execute = command(
            action=EXECUTE_ACTION,
            execution_mode="STATIC_WRITE",
            requires_github_write=True,
            expected_target_tree=TREE,
            path_policy=[
                {"path": item["path"], "allowed_ops": list(item["allowed_ops"])}
                for item in REQUIRED_PATH_POLICY
            ],
        )
        result = prepare_relay_batch(
            execute, client=FakeContents(), repository=REPO,
            target_pr=4, state=state(), now=NOW,
        )
        self.assertEqual(result.status, "PREPARED")
        self.assertEqual(result.evidence["action"], EXECUTE_ACTION)
        self.assertEqual(result.evidence["execution_mode"], "STATIC_WRITE")

        valid_policy = [
            {"path": item["path"], "allowed_ops": list(item["allowed_ops"])}
            for item in REQUIRED_PATH_POLICY
        ]
        for bad in (
            command(
                action=EXECUTE_ACTION, execution_mode="PREPARE_ONLY",
                requires_github_write=True, expected_target_tree=TREE,
                path_policy=valid_policy,
            ),
            command(
                action=EXECUTE_ACTION, execution_mode="STATIC_WRITE",
                requires_github_write=False, expected_target_tree=TREE,
                path_policy=valid_policy,
            ),
            command(action=PREPARE_ACTION, execution_mode="STATIC_WRITE", requires_github_write=False),
            command(action=PREPARE_ACTION, execution_mode="PREPARE_ONLY", requires_github_write=True),
        ):
            with self.assertRaises(ValueError):
                validate_relay_command(
                    bad, current_target_head=HEAD, state=state(),
                    terminal_receipt=None, now=NOW,
                )

    def test_profile_is_fixed(self):
        with self.assertRaises(ValueError):
            validate_relay_command(
                command(profile="OTHER"), current_target_head=HEAD,
                state=state(), terminal_receipt=None, now=NOW,
            )

    def test_execute_requires_exact_target_tree_and_operation_policy(self):
        base = dict(
            action=EXECUTE_ACTION,
            execution_mode="STATIC_WRITE",
            requires_github_write=True,
            expected_target_tree=TREE,
            path_policy=[
                {"path": item["path"], "allowed_ops": list(item["allowed_ops"])}
                for item in REQUIRED_PATH_POLICY
            ],
        )
        validate_relay_command(
            command(**base), current_target_head=HEAD,
            state=state(), terminal_receipt=None, now=NOW,
        )
        with self.assertRaises(ValueError):
            validate_relay_command(
                command(**{**base, "expected_target_tree": ""}),
                current_target_head=HEAD, state=state(),
                terminal_receipt=None, now=NOW,
            )
        unsafe = [
            {"path": item["path"], "allowed_ops": list(item["allowed_ops"])}
            for item in REQUIRED_PATH_POLICY
        ]
        unsafe[0]["allowed_ops"].append("DELETE")
        with self.assertRaises(ValueError):
            validate_relay_command(
                command(**{**base, "path_policy": unsafe}),
                current_target_head=HEAD, state=state(),
                terminal_receipt=None, now=NOW,
            )

    def test_wrong_repo_or_pr_blocks_before_target_read(self):
        client = FakeContents()
        result = prepare_relay_batch(
            command(expected_repo="other/repo"), client=client,
            repository=REPO, target_pr=4, state=state(), now=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(client.reads, [])

    def test_carrier_head_is_not_part_of_validation(self):
        result = prepare_relay_batch(
            command(), client=FakeContents(), repository=REPO,
            target_pr=4, state=state(), now=NOW,
        )
        self.assertEqual(result.status, "PREPARED")

    def test_target_head_mismatch_blocks(self):
        result = prepare_relay_batch(
            command(expected_target_head="wrong"), client=FakeContents(),
            repository=REPO, target_pr=4, state=state(), now=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_terminal_replay_and_duplicate_block(self):
        with self.assertRaises(ValueError):
            validate_relay_command(
                command(), current_target_head=HEAD, state=state(),
                terminal_receipt={"state": "DONE"}, now=NOW,
            )
        result = prepare_relay_batch(
            command(), client=FakeContents(), repository=REPO,
            target_pr=4, state=state(), terminal_receipt={"state": "DONE"}, now=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")
        result = prepare_relay_batch(
            command(), client=FakeContents(), repository=REPO,
            target_pr=4, state=state(), duplicate_command=True, now=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_retry_zero_fallback_disabled_and_live_false(self):
        validate_relay_command(
            command(), current_target_head=HEAD, state=state(),
            terminal_receipt=None, now=NOW,
        )

    def test_path_scope_is_exact_and_prohibited_scope_complete(self):
        validate_relay_command(
            command(), current_target_head=HEAD, state=state(),
            terminal_receipt=None, now=NOW,
        )
        for bad in (["../secrets/key"], ["docs/RELAY_STATIC_CHECKPOINT.md.evil"]):
            with self.assertRaises(ValueError):
                validate_relay_command(
                    command(allowed_paths=bad), current_target_head=HEAD,
                    state=state(), terminal_receipt=None, now=NOW,
                )
        incomplete = sorted(REQUIRED_PROHIBITED_PATHS - {"billing/**"})
        with self.assertRaises(ValueError):
            validate_relay_command(
                command(prohibited_paths=incomplete), current_target_head=HEAD,
                state=state(), terminal_receipt=None, now=NOW,
            )

    def test_test_commands_are_fixed_allowlist(self):
        with self.assertRaises(ValueError):
            validate_relay_command(
                command(test_commands=["echo unsafe"]), current_target_head=HEAD,
                state=state(), terminal_receipt=None, now=NOW,
            )

    def test_loop_command_and_correlation_are_exact(self):
        for changes in (
            {"command_id": "other-000001"},
            {"correlation_id": "wrong"},
        ):
            with self.assertRaises(ValueError):
                validate_relay_command(
                    command(**changes), current_target_head=HEAD,
                    state=state(), terminal_receipt=None, now=NOW,
                )
        with self.assertRaises(ValueError):
            validate_relay_command(
                command(), current_target_head=HEAD,
                state=state(loop_id="wrong"), terminal_receipt=None, now=NOW,
            )

    def test_fail_closed_for_stop_expiry_max6_and_predecessor(self):
        for changes in (
            {"action": ""},
            {"retry": 1},
            {"fallback": "enabled"},
            {"predecessor_receipt_id": ""},
        ):
            with self.assertRaises(ValueError):
                validate_relay_command(
                    command(**changes), current_target_head=HEAD,
                    state=state(), terminal_receipt=None, now=NOW,
                )
        for bad_state in (
            state(state="HALTED"),
            state(stop_requested=True),
            state(round=6),
            state(expires_at="2026-09-22T11:59:00+00:00"),
        ):
            with self.assertRaises(ValueError):
                validate_relay_command(
                    command(), current_target_head=HEAD,
                    state=bad_state, terminal_receipt=None, now=NOW,
                )
        with self.assertRaises(ValueError):
            validate_relay_command(
                command(), current_target_head=HEAD, state=state(),
                terminal_receipt=None, predecessor_exists=False, now=NOW,
            )

    def test_chat_thread_identity_and_live_execution_are_absent(self):
        result = prepare_relay_batch(
            command(), client=FakeContents(), repository=REPO,
            target_pr=4, state=state(), now=NOW,
        )
        self.assertNotIn("chat_id", command())
        self.assertNotIn("thread_id", command())
        self.assertFalse(result.evidence["model_executed"])
        self.assertFalse(result.evidence["jules_started"])
        self.assertFalse(result.evidence["provider_started"])


if __name__ == "__main__":
    unittest.main()
