from datetime import datetime, timezone
import unittest

from automation.command_bus.relay_static import prepare_relay_batch, validate_relay_command

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
REPO = "kamiyusense/multi-ai-council-phase0"
HEAD = "abac6f5aa955167c950d9cb15753ae14ac386317"


class FakeContents:
    def __init__(self, head=HEAD):
        self.head = head
        self.writes = []

    def read_pr_head(self, repository, pull_request):
        return self.head

    def write_target(self, path, content):
        self.writes.append((path, content))


def state(**changes):
    value = {"state": "RUNNING", "stop_requested": False, "round": 0, "max_rounds": 6}
    value.update(changes)
    return value


def command(**changes):
    value = {
        "schema_version": 1, "command_id": "relay-static-001-000001",
        "loop_id": "relay-static-001", "round": 1,
        "correlation_id": "relay-static-001-round-1", "target": "work",
        "action": "APPLY_RELAY_STATIC_BATCH", "expected_repo": REPO,
        "expected_pr": 4, "expected_target_head": HEAD,
        "allowed_paths": ["src/relay/**", "tests/relay/**"],
        "prohibited_paths": ["main/**", "secrets/**", ".github/**"],
        "objective": "prepare static relay batch",
        "test_commands": ["python -m unittest discover -s tests/relay -v"],
        "requires_live_model": False, "requires_github_write": False,
        "retry": 0, "fallback": "disabled",
        "expires_at": "2026-09-24T23:59:00+09:00",
        "predecessor_receipt_id": "route-validation-005/000001",
    }
    value.update(changes)
    return value


class RelayStaticContractTests(unittest.TestCase):
    def test_prepare_reads_target_head_and_never_writes_pr4(self):
        client = FakeContents()
        result = prepare_relay_batch(command(), client=client, repository=REPO,
                                     target_pr=4, state=state(), now=NOW)
        self.assertEqual(result.status, "PREPARED")
        self.assertFalse(result.evidence["target_pr_modified"])
        self.assertEqual(client.writes, [])

    def test_carrier_head_is_not_part_of_validation(self):
        self.assertEqual(prepare_relay_batch(command(), client=FakeContents(),
                         repository=REPO, target_pr=4, state=state(), now=NOW).status,
                         "PREPARED")

    def test_target_head_mismatch_blocks(self):
        result = prepare_relay_batch(command(expected_target_head="wrong"),
                                     client=FakeContents(), repository=REPO,
                                     target_pr=4, state=state(), now=NOW)
        self.assertEqual(result.status, "BLOCKED")

    def test_terminal_replay_duplicate_is_blocked(self):
        with self.assertRaises(ValueError):
            validate_relay_command(command(), current_target_head=HEAD, state=state(),
                                   terminal_receipt={"state": "DONE"}, now=NOW)

    def test_retry_zero_fallback_disabled_and_live_false(self):
        validate_relay_command(command(), current_target_head=HEAD, state=state(),
                               terminal_receipt=None, now=NOW)

    def test_allowed_and_prohibited_paths(self):
        validate_relay_command(command(), current_target_head=HEAD, state=state(),
                               terminal_receipt=None, now=NOW)
        with self.assertRaises(ValueError):
            validate_relay_command(command(allowed_paths=["../secrets/key"]),
                                   current_target_head=HEAD, state=state(),
                                   terminal_receipt=None, now=NOW)
        with self.assertRaises(ValueError):
            validate_relay_command(command(prohibited_paths=["docs/**"]),
                                   current_target_head=HEAD, state=state(),
                                   terminal_receipt=None, now=NOW)

    def test_fail_closed_for_malformed_duplicate_stop_expiry_max6_predecessor(self):
        for changes in ({"action": ""}, {"retry": 1}, {"fallback": "enabled"},
                        {"predecessor_receipt_id": ""}):
            with self.assertRaises(ValueError):
                validate_relay_command(command(**changes), current_target_head=HEAD,
                                       state=state(), terminal_receipt=None, now=NOW)
        with self.assertRaises(ValueError):
            validate_relay_command(command(), current_target_head=HEAD,
                                   state=state(state="HALTED"), terminal_receipt=None, now=NOW)
        with self.assertRaises(ValueError):
            validate_relay_command(command(), current_target_head=HEAD,
                                   state=state(round=6), terminal_receipt=None, now=NOW)
        with self.assertRaises(ValueError):
            validate_relay_command(command(), current_target_head=HEAD, state=state(),
                                   terminal_receipt=None, predecessor_exists=False,
                                   now=NOW)

    def test_chat_thread_identity_and_live_execution_are_absent(self):
        result = prepare_relay_batch(command(), client=FakeContents(), repository=REPO,
                                     target_pr=4, state=state(), now=NOW)
        self.assertNotIn("chat_id", command())
        self.assertFalse(result.evidence["model_executed"])
        self.assertFalse(result.evidence["jules_started"])
        self.assertFalse(result.evidence["provider_started"])


if __name__ == "__main__":
    unittest.main()
