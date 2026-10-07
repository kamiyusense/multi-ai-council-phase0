from __future__ import annotations

import json
import pathlib
import unittest

from automation.command_bus.claude_jules_campaign import (
    HARD_UNKNOWN,
    RECOVERABLE_UNKNOWN,
    TASK_BLOCKED,
    TRANSIENT_UNKNOWN,
    campaign_policy_from_legacy,
    classify_boundary,
    validate_campaign_policy,
)
from automation.command_bus.claude_jules_dispatch import validate_policy
from automation.command_bus.tests.claude_jules_autoloop_fakes import policy


class CampaignPolicyTests(unittest.TestCase):
    def test_committed_example_is_valid_finite_and_does_not_grant_provider_authority(self):
        root = pathlib.Path(__file__).parents[1]
        record = json.loads((root / "config" / "claude_jules_campaign_policy.example.json").read_text())
        validated = validate_campaign_policy(record)
        self.assertEqual(validated["max_rounds"], 30)
        self.assertEqual(validated["max_concurrent_agents"], 1)
        self.assertIsNone(validated["dispatch_provider_budget"])

    def test_legacy_policy_builds_backward_compatible_campaign_defaults(self):
        legacy = policy(max_rounds=6)
        campaign = campaign_policy_from_legacy(legacy, "claude-auto-loop-test")
        self.assertEqual(campaign["max_rounds"], 6)
        self.assertEqual(campaign["max_concurrent_agents"], 1)
        self.assertEqual(campaign["max_transient_retries"], 2)

    def test_round_limit_is_configurable_beyond_six_without_code_change(self):
        for rounds in (3, 6, 10, 20, 30):
            with self.subTest(rounds=rounds):
                legacy = policy(max_rounds=rounds)
                self.assertEqual(validate_policy(legacy)["max_rounds"], rounds)
                self.assertEqual(campaign_policy_from_legacy(legacy, "campaign")["max_rounds"], rounds)

    def test_campaign_policy_rejects_parallel_agents_in_v1(self):
        campaign = campaign_policy_from_legacy(policy(), "campaign")
        campaign["max_concurrent_agents"] = 2
        with self.assertRaisesRegex(ValueError, "max_concurrent_agents"):
            validate_campaign_policy(campaign)

    def test_campaign_timeout_must_cover_task_timeout(self):
        campaign = campaign_policy_from_legacy(policy(), "campaign")
        campaign["campaign_timeout_seconds"] = campaign["task_timeout_seconds"] - 1
        with self.assertRaisesRegex(ValueError, "campaign_timeout_seconds"):
            validate_campaign_policy(campaign)


class BoundaryClassificationTests(unittest.TestCase):
    def test_transient_evidence_read_is_retry_safe(self):
        result = classify_boundary("UNKNOWN", "dispatch/PR evidence unverifiable: temporary network read failed")
        self.assertEqual(result.kind, TRANSIENT_UNKNOWN)
        self.assertTrue(result.retry_safe)

    def test_stale_target_is_recoverable_replan(self):
        result = classify_boundary("BLOCKED", "STALE_TARGET: target head changed")
        self.assertEqual(result.kind, RECOVERABLE_UNKNOWN)
        self.assertTrue(result.retry_safe)

    def test_no_result_timeout_is_task_scoped_blocker(self):
        result = classify_boundary("NO_RESULT_TIMEOUT", "no Jules result PR recorded by deadline")
        self.assertEqual(result.kind, TASK_BLOCKED)
        self.assertFalse(result.retry_safe)

    def test_ambiguous_mutating_write_is_never_auto_retry(self):
        result = classify_boundary("UNKNOWN", "command: create not proven by readback; do not resend")
        self.assertEqual(result.kind, HARD_UNKNOWN)
        self.assertFalse(result.retry_safe)

    def test_unclassified_unknown_fails_hard(self):
        result = classify_boundary("UNKNOWN", "durable lineage contradiction")
        self.assertEqual(result.kind, HARD_UNKNOWN)
        self.assertFalse(result.retry_safe)


if __name__ == "__main__":
    unittest.main()
