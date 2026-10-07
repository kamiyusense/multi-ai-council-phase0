"""STATIC Issue-to-attempt fixture; this never starts Official Symphony or Codex."""
from __future__ import annotations

import unittest

from automation.command_bus.symphony_autonomous_controller import (
    StaticAutonomousCampaignController, StaticCampaignTaskRunner,
    StaticSubscriptionRouteReader, StaticTargetObserver, TaskExecutionResult,
)
from automation.command_bus.symphony_autonomous_runtime import (
    CampaignState, CampaignTask, TaskOutcome, TaskStatus,
)
from automation.command_bus.symphony_attempt_store import GitHubAutonomousAttemptStore
from automation.command_bus.symphony_campaign_store import GitHubCampaignStateStore
from automation.command_bus.symphony_upstream_event_adapter import prepare_upstream_reconciliation_hint
from automation.command_bus.tests.test_symphony_autonomous_controller import FakeContents


class MinimalLivePreflightTests(unittest.TestCase):
    def test_issue_route_attempt_stale_discard_and_restart(self):
        # Upstream GitHub's candidate is an Issue, not PR #320. The unique
        # label is configured in the workflow; upstream owns polling/filtering.
        candidate = {"number": 4321, "state": "open", "labels": [
            {"name": "symphony-minimal-live-proof"}], "title": "STATIC fixture"}
        self.assertEqual(candidate["labels"][0]["name"], "symphony-minimal-live-proof")
        self.assertNotIn("pull_request", candidate)
        self.assertEqual(
            prepare_upstream_reconciliation_hint(str(candidate["number"]), "WORKER_UPDATE").action,
            "RECONCILE_READ_ONLY",
        )

        client = FakeContents()
        store = GitHubCampaignStateStore(client, write_branch="codex/fixture-ledger")
        campaign_id = "issue-4321"
        self.assertEqual(store.save(CampaignState(campaign_id, 1, {
            "proof": CampaignTask("proof", expected_target_head="h1"),
        }), expected_revision=0).status, "ACCEPTED")
        denied = StaticSubscriptionRouteReader({"auth_state": "API_KEY_ROUTE_VIOLATION"}, ("PATH",))
        blocked = StaticAutonomousCampaignController(
            store, campaign_id=campaign_id, target_observer=StaticTargetObserver("h1"),
            runner=StaticCampaignTaskRunner(), subscription_route_reader=denied,
        ).run_until_boundary()
        self.assertEqual(blocked.status, "NEW_WORKER_ROUTE_BLOCKED")
        self.assertEqual(GitHubAutonomousAttemptStore(
            client, write_branch="codex/fixture-ledger").list_campaign(campaign_id), [])

        allowed = StaticSubscriptionRouteReader({
            "auth_state": "CHATGPT_ACCOUNT", "ordinary_usage_allowed": "UNKNOWN",
        }, ("PATH",))
        first_runner = StaticCampaignTaskRunner({
            "proof": [TaskExecutionResult("old-result", TaskOutcome.DONE, mutation_operations=("ADD",))],
        })
        first = StaticAutonomousCampaignController(
            store, campaign_id=campaign_id,
            target_observer=StaticTargetObserver("h1", read_sequence=("h1", "h1", "h2")),
            runner=first_runner, subscription_route_reader=allowed,
        ).run_until_boundary(max_steps=1)
        self.assertEqual(first.status, "BATCH_LIMIT")
        self.assertEqual(allowed.calls, 1)
        self.assertEqual(len(first_runner.start_calls), 1)
        attempts = GitHubAutonomousAttemptStore(client, write_branch="codex/fixture-ledger").list_campaign(campaign_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].state, "TERMINAL")
        self.assertIsNotNone(attempts[0].started)
        self.assertEqual(attempts[0].terminal["outcome"], "STALE")
        self.assertEqual(store.restore(campaign_id).state.tasks["proof"].status, TaskStatus.STALE)

        next_runner = StaticCampaignTaskRunner({
            "proof": [TaskExecutionResult("new-result", TaskOutcome.DONE, mutation_operations=("ADD",))],
        })
        resumed = StaticAutonomousCampaignController(
            store, campaign_id=campaign_id, target_observer=StaticTargetObserver("h2"),
            runner=next_runner, subscription_route_reader=StaticSubscriptionRouteReader({
                "auth_state": "CHATGPT_ACCOUNT", "ordinary_usage_allowed": "UNKNOWN",
            }, ("PATH",)),
        ).run_until_boundary()
        self.assertEqual(resumed.status, "CAMPAIGN_COMPLETE")
        self.assertEqual(len(next_runner.start_calls), 1)
        self.assertEqual(store.restore(campaign_id).state.rounds_completed, 1)
        attempts = GitHubAutonomousAttemptStore(client, write_branch="codex/fixture-ledger").list_campaign(campaign_id)
        self.assertEqual({item.identity.expected_target_head: item.terminal["outcome"]
                          for item in attempts}, {"h1": "STALE", "h2": "DONE"})


if __name__ == "__main__":
    unittest.main()
