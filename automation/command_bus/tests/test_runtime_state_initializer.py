from __future__ import annotations

import json
import unittest

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.runtime_state_initializer import (
    RuntimeStateInitializer,
    build_initial_prepared_state,
    runtime_state_path,
)


class Client:
    def __init__(self):
        self.data = {}
        self.creates = 0
        self.updates = 0
        self.raise_after_create = False

    def get(self, path, ref):
        return self.data.get(path)

    def list(self, prefix, ref):
        return []

    def create(self, path, text, message, branch):
        self.creates += 1
        self.data[path] = GitHubContent(path, text, "a" * 40)
        if self.raise_after_create:
            raise TimeoutError("ambiguous create")
        return self.data[path]

    def update(self, *args, **kwargs):
        self.updates += 1
        raise AssertionError("initializer must never update")


def prepared():
    return build_initial_prepared_state(
        loop_id="chatgpt-semi-auto-v1",
        expected_repo="kamiyusense/multi-ai-council-phase0",
        expected_pr=4,
        expected_target_head="a" * 40,
        expires_at="2026-09-28T06:00:00+00:00",
    )


class RuntimeStateInitializerTests(unittest.TestCase):
    def test_build_initial_state_is_prepared_and_ownerless(self):
        value = prepared()
        self.assertEqual(value["state"], "PREPARED")
        self.assertEqual(value["round"], 0)
        self.assertEqual(value["max_rounds"], 1)
        self.assertIsNone(value["last_command_id"])
        self.assertIsNone(value["last_receipt_id"])
        self.assertEqual(value["retry_policy"], 0)
        self.assertEqual(value["expected_target"]["pr"], 4)

    def test_create_only_initializer_writes_once_and_reads_back(self):
        client = Client()
        result = RuntimeStateInitializer(
            client,
            branch="feature/runtime-data",
        ).create(prepared())
        self.assertEqual(result.status, "ACCEPTED", result)
        self.assertEqual(client.creates, 1)
        self.assertEqual(client.updates, 0)
        self.assertEqual(result.state, prepared())

    def test_ambiguous_create_that_applied_is_recovered_without_resend(self):
        client = Client()
        client.raise_after_create = True
        result = RuntimeStateInitializer(
            client,
            branch="feature/runtime-data",
        ).create(prepared())
        self.assertEqual(result.status, "ACCEPTED", result)
        self.assertEqual(client.creates, 1)

    def test_existing_identical_state_is_recovered_without_create(self):
        client = Client()
        value = prepared()
        path = runtime_state_path(value["loop_id"])
        client.data[path] = GitHubContent(
            path,
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            "b" * 40,
        )
        result = RuntimeStateInitializer(
            client,
            branch="feature/runtime-data",
        ).create(value)
        self.assertEqual(result.status, "RECOVERED")
        self.assertEqual(client.creates, 0)

    def test_existing_different_state_blocks_without_overwrite(self):
        client = Client()
        value = prepared()
        changed = {**value, "state": "RUNNING"}
        path = runtime_state_path(value["loop_id"])
        client.data[path] = GitHubContent(
            path,
            json.dumps(changed, sort_keys=True, separators=(",", ":")),
            "c" * 40,
        )
        result = RuntimeStateInitializer(
            client,
            branch="feature/runtime-data",
        ).create(value)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(client.creates, 0)
        self.assertEqual(client.updates, 0)

    def test_initializer_rejects_default_branch(self):
        with self.assertRaisesRegex(ValueError, "non-default"):
            RuntimeStateInitializer(Client(), branch="main")

    def test_unsafe_loop_id_fails_before_path_creation(self):
        with self.assertRaisesRegex(ValueError, "unsafe durable loop_id"):
            build_initial_prepared_state(
                loop_id="../bad",
                expected_repo="kamiyusense/multi-ai-council-phase0",
                expected_pr=4,
                expected_target_head="a" * 40,
                expires_at="2026-09-28T06:00:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()
