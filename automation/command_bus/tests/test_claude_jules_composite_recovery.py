"""Composite STATIC recovery: timeout + blocked dependency + stale HEAD + restart + late evidence in one campaign.

Local fakes only (no network, no Jules, no LIVE). Every step uses a brand-new controller, so all state is restored from
the fake GitHub records.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from automation.command_bus.claude_jules_campaign import campaign_policy_from_legacy
from automation.command_bus.claude_jules_live import wake_resume
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World
from automation.command_bus.tests.claude_jules_autoloop_fakes import LOOP, NOW, TARGET, policy, roadmap, task_spec


def plan_with_dependency():
    plan = roadmap(task_spec("alpha-helper"),
                   task_spec("beta-helper", "automation/command_bus/beta.py", "automation/command_bus/tests/test_beta.py"),
                   task_spec("gamma-helper", "automation/command_bus/gamma.py", "automation/command_bus/tests/test_gamma.py"))
    plan["tasks"][2]["depends_on"] = []  # gamma is independent; beta keeps its default dependency on alpha
    return plan


def at(seconds: int) -> str:
    return (datetime.fromisoformat(NOW) + timedelta(seconds=seconds)).isoformat()


class CompositeRecoveryTests(unittest.TestCase):
    def test_timeout_blocked_dependency_stale_head_and_restart_converge_without_extra_dispatch(self):
        auth = dict(policy()["live_dispatch_authorization"], max_dispatches=10)
        campaign = campaign_policy_from_legacy(policy(live_dispatch_authorization=auth), LOOP)
        campaign.update(max_rounds=10, task_timeout_seconds=30, campaign_timeout_seconds=3600)
        w = World(plan=plan_with_dependency(), campaign=campaign, pol=policy(live_dispatch_authorization=auth))
        alpha = w.step().details["command_id"]

        # 1. alpha times out while the provider is still running: wait, never overlap another provider.
        real = w.facts.timeout_reconciliation
        w.facts.timeout_reconciliation = lambda intent: dict(real(intent), status="RUNNING")
        waiting = w.controller().run_until_boundary(now=at(31))
        self.assertEqual(waiting[-1].status, "AWAITING_TIMEOUT_RECONCILIATION")
        self.assertEqual(len(w.commands()), 1)

        # 2. provider settles with no result: alpha is isolated, dependent beta is skipped, gamma continues.
        w.facts.timeout_reconciliation = real
        moved_on = w.controller().run_until_boundary(now=at(32))
        self.assertEqual([r.status for r in moved_on], ["TASK_BLOCKED", "DISPATCHED", "WAITING_FOR_RESULT"])
        gamma = moved_on[1].details["command_id"]
        self.assertIn("gamma-helper", gamma)
        self.assertEqual(w.controller().campaign_state.blocked_tasks(), {"alpha-helper"})

        # 3. gamma's result passes, then the canonical target moves before adoption: replan, keep old PASS.
        w.deliver(w.jules.run(gamma))
        self.assertEqual(w.controller().step(now=at(40)).status, "PASS")
        moved = w.github.child(w.github.branches[TARGET], {"parallel.txt": "keep\n"}, "canonical forward")
        w.github.branches[TARGET] = moved
        replanned = w.controller().run_until_boundary(now=at(41))
        self.assertEqual([r.status for r in replanned], ["REPLANNED", "DISPATCHED", "WAITING_FOR_RESULT"])
        gamma2 = replanned[1].details["command_id"]
        self.assertNotEqual(gamma2, gamma)

        # 4. restart with a duplicate wake before the new result: nothing is written twice.
        writes = list(w.github.writes)
        idle = wake_resume(loop=w.controller(), git=w.github, rest=None, policy=w.policy, origin_loop_id=LOOP,
                           now=at(42), poller=lambda **kw: [])
        self.assertEqual([s["status"] for s in idle["steps"]], ["WAITING_FOR_RESULT"])
        self.assertEqual(w.github.writes, writes)

        # 5. late evidence for the stale gamma head arrives again: it must not be adopted over the fresh one.
        stale_pr = next(n for n, pr in w.jules.prs.items() if pr["base_ref"].endswith(gamma))
        self.assertEqual(w.deliver(w.jules.payload(stale_pr, "synchronize"), delivery="late-duplicate").status, "DUPLICATE")
        w.deliver(w.jules.run(gamma2))
        done = w.controller().run_until_boundary(now=at(50))
        statuses = [r.status for r in done]
        self.assertIn("ADOPTED", statuses)
        self.assertEqual(statuses[-1], "TASK_BLOCKED")  # only blocked alpha and its dependent remain
        final = w.github.branches[TARGET]
        self.assertIn("parallel.txt", w.github.commits[final]["files"])
        self.assertIn("automation/command_bus/gamma.py", w.github.commits[final]["files"])
        self.assertNotIn("automation/command_bus/beta.py", w.github.commits[final]["files"])

        # 6. exactly three provider dispatches in total (alpha, gamma, fresh gamma); the slot of alpha stays used.
        self.assertEqual(len(w.commands()), 3)
        again = w.controller().run_until_boundary(now=at(60))
        self.assertEqual([r.status for r in again], ["TASK_BLOCKED"])
        self.assertEqual(len(w.commands()), 3)


if __name__ == "__main__":
    unittest.main()
