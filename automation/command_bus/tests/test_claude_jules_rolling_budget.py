"""Rolling 24-hour start limit (owner decision 2026-10-12): at most N Jules starts in any 24 hours.

Jules' own daily task limit is a rolling 24 hours (100 on Google AI Pro), so the loop stops itself a little below
it, counted from the budget slots' own ``acquired_at``.  A full window is temporary: no intent is written, nothing
is escalated to a human, and the start resumes by itself once the oldest start in the window is 24 hours old.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from automation.command_bus import claude_jules_durable_budget as db
from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus.tests import budget_fixtures as bf

ROOT = Path(__file__).resolve().parents[3]


def v3(limit=3, **over):
    return bf.declaration_v2(profile=db.DECLARATION_PROFILE_V3, cap=9999, rolling_24h_limit=limit, **over)


def activation(n):
    return {"repository": "kamiyusense/multi-ai-council-phase0", "campaign_id": "prod-test", "issue": n,
            "task_id": f"t{n}", "correlation_id": f"t{n}-abc1234", "generation": 1, "task_sha256": "0" * 64,
            "expected_target_head": "a" * 40, "route": st.ROUTE}


class RollingLimitTests(unittest.TestCase):
    def setUp(self):
        self.store = bf.LedgerStore(real_slots=0)
        self.budget = db.DurableBudget(self.store, v3(), repository="kamiyusense/multi-ai-council-phase0")

    def take(self, n, now):
        return self.budget.reserve(activation(n), origin="o", max_for_origin=9999, now=now)

    def test_the_window_fills_and_frees_by_itself(self):
        for n, at in ((1, "2026-10-12T00:00:00Z"), (2, "2026-10-12T01:00:00Z"), (3, "2026-10-12T02:00:00Z")):
            self.assertEqual(self.take(n, at).status, db.ACQUIRED)
        full = self.take(4, "2026-10-12T10:00:00Z")
        self.assertEqual((full.status, full.retry_after), (db.RATE_LIMITED, "2026-10-13T00:00:00Z"))
        self.assertEqual(self.budget.rate_limited_until("2026-10-12T10:00:00Z"), "2026-10-13T00:00:00Z")
        self.assertIsNone(self.budget.rate_limited_until("2026-10-13T00:00:01Z"))
        self.assertEqual(self.take(4, "2026-10-13T00:00:01Z").status, db.ACQUIRED)   # slot 1 left the window
        self.assertEqual(self.take(5, "2026-10-13T00:30:00Z").status, db.RATE_LIMITED)

    def test_a_restarted_activation_is_recovered_even_when_the_window_is_full(self):
        for n in (1, 2, 3):
            self.take(n, f"2026-10-12T0{n}:00:00Z")
        self.assertEqual(self.take(3, "2026-10-12T05:00:00Z").status, db.RECOVERED)

    def test_declaration_rules(self):
        repo = "kamiyusense/multi-ai-council-phase0"
        self.assertEqual(db.validate_declaration(v3(80), repository=repo), [])
        for bad in (0, 10000, True, "80"):
            self.assertTrue(db.validate_declaration(v3(bad), repository=repo))
        no_limit = db.DurableBudget(self.store, bf.declaration_v2(), repository=repo)
        self.assertIsNone(no_limit.rate_limited_until("2026-10-12T00:00:00Z"))

    def test_active_files_carry_the_owner_decision(self):
        active = ROOT / "docs" / "claude-jules-loop" / "active"
        decl = json.loads((active / "budget-declaration.json").read_text(encoding="utf-8"))
        auth = json.loads((active / "authorization.json").read_text(encoding="utf-8"))
        self.assertEqual(db.validate_declaration(decl, repository=decl["repository"]), [])
        self.assertEqual((decl["profile"], decl["rolling_24h_limit"], decl["cap"]),
                         (db.DECLARATION_PROFILE_V3, 80, 9999))
        self.assertEqual((auth["max_activations"], auth["expires_at"]), (9999, "2027-01-12T07:00:00Z"))


class FullWindowPort:
    """Enough of a port for one tick: a prepared task exists and the window is full."""

    def __init__(self):
        self.writes = []

    def start_rate_limited_until(self):
        return "2026-10-13T00:00:00Z"

    def list_campaign_issues(self):
        return []

    def read_control_issue(self):
        return None

    def base_head(self):
        return "a" * 40

    def pr_merged(self, n):
        return False

    def add_comment(self, n, body):
        self.writes.append(("comment", n))


class LoopTests(unittest.TestCase):
    def test_full_window_writes_no_intent_plans_nothing_and_needs_no_human(self):
        campaign = {"campaign_id": "c", "control_issue": None, "tasks": [], "objectives": [],
                    "policy": st.make_policy()}
        port = FullWindowPort()
        res = loop.run_tick(port, campaign=campaign, controller="t", now=lambda: "2026-10-12T10:00:00Z")
        self.assertEqual(res.outcome, loop.DEFER)
        self.assertEqual(res.defers[0]["code"], "RATE_LIMITED")
        self.assertEqual(res.defers[0]["next_check"], "2026-10-13T00:00:00Z")
        self.assertFalse(res.defers[0]["human_required"])
        self.assertFalse(res.human_actions)
        self.assertEqual(port.writes, [])

    def test_a_long_full_window_is_not_escalated_before_it_should_have_freed(self):
        campaign = {"campaign_id": "c", "control_issue": None, "tasks": [], "objectives": [],
                    "policy": st.make_policy()}
        res = loop.run_tick(FullWindowPort(), campaign=campaign, controller="t", now=lambda: "2026-10-12T23:00:00Z")
        self.assertFalse(res.defers[0]["escalated"])


if __name__ == "__main__":
    unittest.main()
