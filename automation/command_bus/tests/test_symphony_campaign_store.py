from __future__ import annotations

import json
import unittest

from automation.command_bus.executor_backend import ExecutorContent
from automation.command_bus.symphony_autonomous_policy import QuotaState
from automation.command_bus.symphony_autonomous_runtime import (
    ActionKind,
    AutonomousCampaignKernel,
    CampaignState,
    CampaignTask,
    TaskOutcome,
)
from automation.command_bus.symphony_campaign_store import GitHubCampaignStateStore


class FakeCampaignContents:
    def __init__(self):
        self.files = {}
        self.counter = 0
        self.create_calls = 0
        self.raise_after_create_path = None
        self.fail_get_paths = set()

    def get(self, path, ref):
        if path in self.fail_get_paths and path in self.files:
            raise RuntimeError("fake campaign readback unavailable")
        return self.files.get(path)

    def list(self, prefix, ref):
        return sorted(
            (content for path, content in self.files.items() if path.startswith(prefix)),
            key=lambda content: content.path,
        )

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
        raise AssertionError("campaign store must stay create-only")


def state(campaign_id="campaign-1"):
    return CampaignState(
        campaign_id,
        1,
        {
            "A": CampaignTask("A", expected_target_head="h1"),
            "B": CampaignTask("B", dependencies=("A",), expected_target_head="h1"),
        },
    )


class SymphonyCampaignStoreTests(unittest.TestCase):
    def test_save_restore_and_fresh_kernel_continue_from_durable_checkpoint(self):
        client = FakeCampaignContents()
        store = GitHubCampaignStateStore(client, write_branch="feature/controller-records")
        kernel = AutonomousCampaignKernel(state())
        kernel.mark_dispatched("A", canonical_head="h1")
        kernel.record_result(result_id="result-a", task_id="A", outcome=TaskOutcome.DONE)

        saved = store.save(kernel.state, expected_revision=0)
        self.assertEqual(saved.status, "ACCEPTED")
        self.assertEqual(saved.revision, 1)

        restored = store.restore("campaign-1")
        self.assertIsNotNone(restored)
        fresh = AutonomousCampaignKernel(restored.state)
        duplicate = fresh.record_result(
            result_id="result-a", task_id="A", outcome=TaskOutcome.DONE,
        )
        self.assertEqual(duplicate.kind, ActionKind.NOOP_DUPLICATE)
        self.assertEqual(
            fresh.next_action(canonical_head="h1", quota_state=QuotaState.UNKNOWN).task_id,
            "B",
        )

    def test_stale_controller_revision_cannot_overwrite_newer_checkpoint(self):
        client = FakeCampaignContents()
        store = GitHubCampaignStateStore(client, write_branch="feature/controller-records")
        first = store.save(state(), expected_revision=0)
        self.assertEqual(first.status, "ACCEPTED")

        stale = store.save(state(), expected_revision=0)
        self.assertEqual(stale.status, "CONFLICT")
        self.assertEqual(stale.revision, 1)
        self.assertEqual(client.create_calls, 1)

    def test_ambiguous_create_is_resolved_by_one_readback_without_resend(self):
        client = FakeCampaignContents()
        store = GitHubCampaignStateStore(client, write_branch="feature/controller-records")
        path = "symphony_campaigns/campaign-1/states/00000001.json"
        client.raise_after_create_path = path
        result = store.save(state(), expected_revision=0)

        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(client.create_calls, 1)
        self.assertEqual(store.restore("campaign-1").revision, 1)

    def test_unverifiable_ambiguous_create_is_not_retried_and_later_restore_recovers_it(self):
        client = FakeCampaignContents()
        store = GitHubCampaignStateStore(client, write_branch="feature/controller-records")
        path = "symphony_campaigns/campaign-1/states/00000001.json"
        client.raise_after_create_path = path
        client.fail_get_paths.add(path)

        result = store.save(state(), expected_revision=0)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(client.create_calls, 1)

        client.fail_get_paths.clear()
        restored = store.restore("campaign-1")
        self.assertEqual(restored.revision, 1)
        self.assertEqual(client.create_calls, 1)

    def test_checkpoint_chain_detects_tamper(self):
        client = FakeCampaignContents()
        store = GitHubCampaignStateStore(client, write_branch="feature/controller-records")
        first_state = state()
        self.assertEqual(store.save(first_state, expected_revision=0).status, "ACCEPTED")

        kernel = AutonomousCampaignKernel(first_state)
        kernel.mark_dispatched("A", canonical_head="h1")
        kernel.record_result(result_id="result-a", task_id="A", outcome=TaskOutcome.DONE)
        self.assertEqual(store.save(kernel.state, expected_revision=1).status, "ACCEPTED")

        path = "symphony_campaigns/campaign-1/states/00000002.json"
        record = json.loads(client.files[path].text)
        record["state"]["rounds_completed"] = 99
        client.files[path] = ExecutorContent(
            path,
            json.dumps(record, sort_keys=True, separators=(",", ":")),
            client.files[path].sha,
        )
        with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            store.restore("campaign-1")

    def test_default_branch_checkpoint_write_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-default"):
            GitHubCampaignStateStore(FakeCampaignContents(), write_branch="main")


if __name__ == "__main__":
    unittest.main()
