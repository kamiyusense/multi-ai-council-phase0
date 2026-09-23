from datetime import datetime, timedelta, timezone
import json
import unittest

from automation.command_bus.jules_static import (
    ACTION, FIXED_TESTS, FIRST_TASK_PATH, LAUNCH_ROUTE, PROFILE, TARGET_BRANCH,
    first_task_objective, make_launch_attempt,
    validate_first_jules_command, validate_jules_diff,
)
from automation.command_bus.jules_launch_backend import (
    DurableJulesLaunchBackend, JulesLaunchContent, launch_attempt_path,
)

NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()
HEAD = "a" * 40
TREE = "b" * 40
LOOP = "jules-first-roundtrip-001"
COMMAND_ID = LOOP + "-000001"


def command(**changes):
    value = {
        "schema_version": 1,
        "command_id": COMMAND_ID,
        "loop_id": LOOP,
        "round": 1,
        "correlation_id": LOOP + "-round-1",
        "target": "work",
        "action": ACTION,
        "profile": PROFILE,
        "expected_repo": "kamiyusense/multi-ai-council-phase0",
        "expected_pr": 4,
        "expected_target_head": HEAD,
        "expected_target_tree": TREE,
        "workspace_integrity_profile": "TREE_IDENTITY_V1",
        "fresh_session_required": True,
        "disposable_workspace_required": True,
        "reuse_existing_jules_task": False,
        "allowed_paths": [FIRST_TASK_PATH],
        "path_policy": [
            {"path": FIRST_TASK_PATH, "allowed_ops": ["MODIFY"]}
        ],
        "test_commands": list(FIXED_TESTS),
        "requires_live_model": True,
        "requires_github_write": True,
        "user_authorization": "EXPLICIT_NEXT_BATCH_JULES_2026-09-23",
        "launch_route": LAUNCH_ROUTE,
        "starting_branch": TARGET_BRANCH,
        "issue_label_launch": False,
        "branch_selection_evidence_required": True,
        "retry": 0,
        "fallback": "disabled",
        "expires_at": EXP,
        "objective": first_task_objective(),
    }
    value.update(changes)
    return value


class FakeGitHub:
    def __init__(self):
        self.files = {}
        self.create_calls = 0
        self.counter = 0

    def get(self, path, ref):
        return self.files.get(path)

    def create(self, path, text, message, branch):
        self.create_calls += 1
        if path in self.files:
            raise ValueError("exists")
        self.counter += 1
        content = JulesLaunchContent(path, text, f"sha-{self.counter}")
        self.files[path] = content
        return content


class NoReadbackGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.hide = False

    def get(self, path, ref):
        if self.hide:
            return None
        return super().get(path, ref)

    def create(self, path, text, message, branch):
        value = super().create(path, text, message, branch)
        self.hide = True
        return value


class JulesStaticContractTests(unittest.TestCase):
    def test_first_command_is_one_file_fresh_disposable_tree_identity(self):
        value = validate_first_jules_command(command())
        self.assertEqual(value["allowed_paths"], [FIRST_TASK_PATH])
        self.assertTrue(value["fresh_session_required"])
        self.assertTrue(value["disposable_workspace_required"])
        self.assertFalse(value["reuse_existing_jules_task"])
        self.assertEqual(value["workspace_integrity_profile"], "TREE_IDENTITY_V1")
        self.assertEqual(value["retry"], 0)
        self.assertEqual(value["fallback"], "disabled")

    def test_old_task_reuse_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "old Jules task reuse"):
            validate_first_jules_command(command(reuse_existing_jules_task=True))

    def test_unknown_tree_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "target tree"):
            validate_first_jules_command(command(expected_target_tree="UNKNOWN"))

    def test_issue_label_route_is_forbidden_for_non_default_target(self):
        with self.assertRaisesRegex(ValueError, "issue-label"):
            validate_first_jules_command(command(issue_label_launch=True))

    def test_starting_branch_must_be_exact_target_branch(self):
        with self.assertRaisesRegex(ValueError, "starting branch"):
            validate_first_jules_command(command(starting_branch="main"))

    def test_launch_route_must_be_work_cloud_browser_jules_ui(self):
        with self.assertRaisesRegex(ValueError, "Cloud Browser"):
            validate_first_jules_command(command(launch_route="GITHUB_ISSUE_LABEL"))

    def test_branch_selection_evidence_is_required(self):
        with self.assertRaisesRegex(ValueError, "branch-selection evidence"):
            validate_first_jules_command(command(branch_selection_evidence_required=False))

    def test_extra_path_or_delete_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly one test file"):
            validate_first_jules_command(command(
                allowed_paths=[FIRST_TASK_PATH, "src/relay/dispatcher.py"]
            ))
        with self.assertRaisesRegex(ValueError, "path/operation policy"):
            validate_first_jules_command(command(
                path_policy=[{"path": FIRST_TASK_PATH, "allowed_ops": ["MODIFY", "DELETE"]}]
            ))

    def test_diff_must_be_exactly_one_modify(self):
        validate_jules_diff([{"path": FIRST_TASK_PATH, "operation": "MODIFY"}])
        for changed in (
            [],
            [{"path": "src/relay/dispatcher.py", "operation": "MODIFY"}],
            [{"path": FIRST_TASK_PATH, "operation": "DELETE"}],
            [
                {"path": FIRST_TASK_PATH, "operation": "MODIFY"},
                {"path": "tests/relay/test_integration.py", "operation": "MODIFY"},
            ],
        ):
            with self.assertRaises(ValueError):
                validate_jules_diff(changed)

    def test_launch_attempt_binds_head_tree_and_no_replay_policy(self):
        attempt = make_launch_attempt(
            command(), attempt_id="attempt-001", created_at=NOW.isoformat()
        )
        self.assertEqual(attempt["expected_target_head"], HEAD)
        self.assertEqual(attempt["expected_target_tree"], TREE)
        self.assertEqual(attempt["launch_route"], LAUNCH_ROUTE)
        self.assertEqual(attempt["starting_branch"], TARGET_BRANCH)
        self.assertEqual(attempt["retry"], 0)
        self.assertEqual(attempt["fallback"], "disabled")
        self.assertTrue(attempt["fresh_session_required"])
        self.assertTrue(attempt["disposable_workspace_required"])


class JulesLaunchBackendTests(unittest.TestCase):
    def test_first_reservation_is_durable_and_verified(self):
        client = FakeGitHub()
        backend = DurableJulesLaunchBackend(client, branch="feature/chat-work-command-bus")
        result = backend.reserve(
            command(), attempt_id="attempt-001", created_at=NOW.isoformat()
        )
        self.assertEqual(result["status"], "RESERVED")
        self.assertTrue(result["fresh_reservation"])
        self.assertEqual(client.create_calls, 1)
        self.assertIn(launch_attempt_path(LOOP, COMMAND_ID), client.files)

    def test_second_reservation_is_blocked_without_second_write(self):
        client = FakeGitHub()
        backend = DurableJulesLaunchBackend(client, branch="feature/chat-work-command-bus")
        first = backend.reserve(
            command(), attempt_id="attempt-001", created_at=NOW.isoformat()
        )
        second = backend.reserve(
            command(), attempt_id="attempt-002", created_at=NOW.isoformat()
        )
        self.assertEqual(first["status"], "RESERVED")
        self.assertEqual(second["status"], "BLOCKED")
        self.assertFalse(second["fresh_reservation"])
        self.assertEqual(client.create_calls, 1)

    def test_unverifiable_write_is_unknown_then_fresh_session_cannot_relaunch(self):
        client = NoReadbackGitHub()
        backend = DurableJulesLaunchBackend(client, branch="feature/chat-work-command-bus")
        first = backend.reserve(
            command(), attempt_id="attempt-001", created_at=NOW.isoformat()
        )
        self.assertEqual(first["status"], "UNKNOWN")
        self.assertFalse(first["fresh_reservation"])
        self.assertEqual(client.create_calls, 1)

        client.hide = False
        recovered = DurableJulesLaunchBackend(
            client, branch="feature/chat-work-command-bus"
        ).recover(command())
        self.assertEqual(recovered["status"], "READ")
        self.assertFalse(recovered["fresh_reservation"])

    def test_corrupt_or_moved_reservation_is_unknown(self):
        client = FakeGitHub()
        backend = DurableJulesLaunchBackend(client, branch="feature/chat-work-command-bus")
        self.assertEqual(backend.reserve(
            command(), attempt_id="attempt-001", created_at=NOW.isoformat()
        )["status"], "RESERVED")
        path = launch_attempt_path(LOOP, COMMAND_ID)
        original = client.files[path]
        damaged = json.loads(original.text)
        damaged["expected_target_tree"] = "c" * 40
        client.files[path] = JulesLaunchContent(path, json.dumps(damaged), "bad")
        recovered = DurableJulesLaunchBackend(
            client, branch="feature/chat-work-command-bus"
        ).recover(command())
        self.assertEqual(recovered["status"], "UNKNOWN")

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            launch_attempt_path("../escape", COMMAND_ID)
        with self.assertRaises(ValueError):
            launch_attempt_path(LOOP, "../../escape")


if __name__ == "__main__":
    unittest.main()
