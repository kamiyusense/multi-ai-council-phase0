from __future__ import annotations

import unittest

from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_campaign import (
    CAMPAIGN_PROFILE,
    legacy_campaign_policy,
    validate_campaign_envelope,
    validate_campaign_policy,
)
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    DATA, LOOP, NOW, policy, roadmap, task_spec,
)
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World


def campaign(*, max_rounds: int = 6, dispatch_budget: int | None = 6, **overrides):
    value = {
        "schema_version": 1,
        "profile": CAMPAIGN_PROFILE,
        "campaign_id": LOOP,
        "max_rounds": max_rounds,
        "max_corrective_rounds_per_task": 2,
        "max_transient_retries": 0,
        "max_consecutive_failures": 1,
        "max_concurrent_agents": 1,
        "idle_check_interval_seconds": 300,
        "task_timeout_seconds": 21600,
        "campaign_timeout_seconds": 86400,
        "dispatch_budget": dispatch_budget,
        "subscription_only": True,
    }
    value.update(overrides)
    return value


class CampaignPolicyTests(unittest.TestCase):
    def test_legacy_projection_preserves_current_six_round_default(self):
        projected = legacy_campaign_policy(policy(), campaign_id=LOOP)
        self.assertEqual(projected["max_rounds"], 6)
        self.assertEqual(projected["max_transient_retries"], 0)
        self.assertEqual(projected["max_concurrent_agents"], 1)
        self.assertTrue(projected["subscription_only"])

    def test_configurable_round_counts_include_longer_campaigns(self):
        for rounds in (3, 6, 10, 20, 30):
            with self.subTest(rounds=rounds):
                value = campaign(max_rounds=rounds, dispatch_budget=None)
                self.assertEqual(validate_campaign_policy(value)["max_rounds"], rounds)

    def test_campaign_cannot_expand_dispatch_envelope(self):
        with self.assertRaisesRegex(ValueError, "exceeds dispatch policy envelope"):
            validate_campaign_envelope(campaign(max_rounds=10, dispatch_budget=6), policy(max_rounds=6))

    def test_v1_rejects_parallel_agents_and_usage_based_fallback(self):
        with self.assertRaisesRegex(ValueError, "max_concurrent_agents=1"):
            validate_campaign_policy(campaign(max_concurrent_agents=2))
        with self.assertRaisesRegex(ValueError, "subscription_only=true"):
            validate_campaign_policy(campaign(subscription_only=False))

    def test_timeout_relationships_are_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "shorter than task_timeout"):
            validate_campaign_policy(campaign(idle_check_interval_seconds=600, task_timeout_seconds=600))
        with self.assertRaisesRegex(ValueError, ">= task_timeout"):
            validate_campaign_policy(campaign(task_timeout_seconds=3600, campaign_timeout_seconds=1800))

    def test_controller_rejects_campaign_identity_mismatch(self):
        w = World()
        wrong = campaign(campaign_id="another-campaign")
        with self.assertRaisesRegex(ValueError, "campaign_id must match origin_loop_id"):
            CampaignRoundIntegrationTests.controller(w, wrong)


class CampaignRoundIntegrationTests(unittest.TestCase):
    @staticmethod
    def controller(w: World, campaign_policy: dict) -> ClaudeJulesAutoLoop:
        return ClaudeJulesAutoLoop(
            client=w.github,
            refs=w.github,
            policy=w.policy,
            owner_reader=LoopOwnerGitHubBackend(w.github, branch=DATA),
            roadmap=w.roadmap,
            facts=w.facts,
            origin_loop_id=LOOP,
            lane_id="J-BLUE",
            campaign_policy=campaign_policy,
        )

    def step(self, w: World, campaign_policy: dict):
        return self.controller(w, campaign_policy).step(now=NOW)

    def test_seven_task_campaign_is_not_architecturally_capped_at_six(self):
        specs = [task_spec(f"task-{n}", f"automation/command_bus/task_{n}.py",
                           f"automation/command_bus/tests/test_task_{n}.py") for n in range(1, 8)]
        base = policy()
        auth = dict(base["live_dispatch_authorization"], max_dispatches=10)
        w = World(pol=policy(max_rounds=10, live_dispatch_authorization=auth), plan=roadmap(*specs))
        camp = campaign(max_rounds=10, dispatch_budget=10)

        for _ in specs:
            dispatched = self.step(w, camp)
            self.assertEqual((dispatched.action, dispatched.status), ("DISPATCH", "DISPATCHED"), dispatched.reason)
            command_id = dispatched.details["command_id"]
            w.deliver(w.jules.run(command_id))
            inspected = self.step(w, camp)
            self.assertEqual(inspected.status, "PASS", inspected.reason)
            adopted = self.step(w, camp)
            self.assertEqual(adopted.status, "ADOPTED", adopted.reason)

        done = self.step(w, camp)
        self.assertEqual((done.action, done.status), ("COMPLETE", "COMPLETE"))
        self.assertEqual(len(w.commands()), 7)

    def test_campaign_limit_may_narrow_a_larger_dispatch_envelope(self):
        specs = [task_spec(f"task-{n}", f"automation/command_bus/task_{n}.py",
                           f"automation/command_bus/tests/test_task_{n}.py") for n in range(1, 5)]
        base = policy()
        auth = dict(base["live_dispatch_authorization"], max_dispatches=10)
        w = World(pol=policy(max_rounds=10, live_dispatch_authorization=auth), plan=roadmap(*specs))
        camp = campaign(max_rounds=3, dispatch_budget=3)

        for _ in range(3):
            dispatched = self.step(w, camp)
            w.deliver(w.jules.run(dispatched.details["command_id"]))
            self.assertEqual(self.step(w, camp).status, "PASS")
            self.assertEqual(self.step(w, camp).status, "ADOPTED")

        stopped = self.step(w, camp)
        self.assertEqual((stopped.action, stopped.status), ("STOP", "MAX_ROUNDS"))
        self.assertEqual(len(w.commands()), 3)

    def test_campaign_dispatch_budget_narrows_live_authorization(self):
        specs = [task_spec(f"budget-task-{n}", f"automation/command_bus/budget_task_{n}.py",
                           f"automation/command_bus/tests/test_budget_task_{n}.py") for n in range(1, 4)]
        base = policy()
        auth = dict(base["live_dispatch_authorization"], max_dispatches=6)
        w = World(pol=policy(max_rounds=6, live_dispatch_authorization=auth), plan=roadmap(*specs))
        camp = campaign(max_rounds=6, dispatch_budget=2)

        for _ in range(2):
            dispatched = self.step(w, camp)
            self.assertEqual(dispatched.status, "DISPATCHED", dispatched.reason)
            w.deliver(w.jules.run(dispatched.details["command_id"]))
            self.assertEqual(self.step(w, camp).status, "PASS")
            self.assertEqual(self.step(w, camp).status, "ADOPTED")

        stopped = self.step(w, camp)
        self.assertEqual((stopped.action, stopped.status), ("STOP", "CAMPAIGN_DISPATCH_BUDGET"))
        self.assertEqual(len(w.commands()), 2)


if __name__ == "__main__":
    unittest.main()
