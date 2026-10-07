from __future__ import annotations

import json
import unittest

from automation.command_bus.claude_jules_campaign_state import (
    CampaignStateStore,
    build_deferred_decision_event,
    build_task_blocked_event,
    campaign_event_path,
    validate_campaign_event,
)
from automation.command_bus.tests.claude_jules_autoloop_fakes import DATA, FakeGitHub


NOW = "2026-10-07T00:00:00+00:00"
CAMPAIGN = "claude-auto-loop-test"


class CampaignStateTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.store = CampaignStateStore(self.github, data_branch=DATA, campaign_id=CAMPAIGN)

    def blocked(self):
        return build_task_blocked_event(
            campaign_id=CAMPAIGN, task_id="alpha-helper", reason="corrective budget exhausted",
            evidence_ref="inspection:abc", recorded_at=NOW,
        )

    def test_block_event_is_content_addressed_create_only_and_recovers(self):
        event = self.blocked()
        self.assertEqual(self.store.persist(event), "CREATED")
        writes = len(self.github.writes)
        self.assertEqual(self.store.persist(event), "RECOVERED")
        self.assertEqual(len(self.github.writes), writes)
        self.assertEqual(self.store.blocked_tasks(), {"alpha-helper"})
        path = campaign_event_path(CAMPAIGN, event["event_id"])
        self.assertEqual(json.loads(self.github.get(path, DATA).text), event)

    def test_ambiguous_create_is_resolved_by_readback_without_replay(self):
        event = self.blocked()
        self.github.create_hook = lambda path, branch: "raise-after-write"
        self.assertEqual(self.store.persist(event), "CREATED")
        path = campaign_event_path(CAMPAIGN, event["event_id"])
        self.assertEqual(sum(1 for op, b, p in self.github.writes if op == "create" and b == DATA and p == path), 1)

    def test_missing_write_is_unknown_and_not_claimed_pass(self):
        event = self.blocked()
        self.github.create_hook = lambda path, branch: "raise-before-write"
        self.assertEqual(self.store.persist(event), "UNKNOWN")
        self.assertEqual(self.store.blocked_tasks(), set())

    def test_tampered_event_fails_closed(self):
        event = self.blocked()
        event["payload"]["task_id"] = "other-task"
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_campaign_event(event)

    def test_deferred_decision_records_safe_default_without_changing_authority(self):
        event = build_deferred_decision_event(
            campaign_id=CAMPAIGN, decision_id="storage-shape-1",
            question="Which reversible cache layout should be used?",
            options=["keep-current", "split-later"], reason="No correctness dependency",
            selected_safe_default="keep-current", reversibility="fully reversible",
            affected_scope="local cache only", reconsider_condition="cache becomes a bottleneck",
            recorded_at=NOW,
        )
        self.assertEqual(self.store.persist(event), "CREATED")
        [saved] = self.store.deferred_decisions()
        self.assertEqual(saved["payload"]["selected_safe_default"], "keep-current")

    def test_deferred_default_must_be_an_option(self):
        with self.assertRaisesRegex(ValueError, "selected_safe_default"):
            build_deferred_decision_event(
                campaign_id=CAMPAIGN, decision_id="bad-default", question="q",
                options=["a", "b"], reason="r", selected_safe_default="c",
                reversibility="yes", affected_scope="local", reconsider_condition="later",
                recorded_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
