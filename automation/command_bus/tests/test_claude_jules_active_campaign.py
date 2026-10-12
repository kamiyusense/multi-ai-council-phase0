"""The ACTIVE campaign files (docs/claude-jules-loop/active/) are consistent, in-lane and subscription-only.

Skipped while no campaign is active.  Static checks plus a mock run of the real files; no GitHub, no Jules.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path

from automation.command_bus import claude_jules_durable_budget as db
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_live as live
from automation.command_bus.tests import budget_fixtures as bf
from automation.command_bus.tests.test_claude_jules_autonomous_mvp import Harness, labeled, passed

ROOT = Path(__file__).resolve().parents[3]
ACTIVE = ROOT / "docs/claude-jules-loop/active"
EV = ROOT / "docs/evidence/claude-jules-production-mvp-20261010"
LANE = ("automation/command_bus/claude_jules_", "automation/command_bus/tests/test_claude_jules_")


def load(name):
    return json.loads((ACTIVE / name).read_text(encoding="utf-8"))


@unittest.skipUnless((ACTIVE / "campaign.json").exists(), "no active campaign")
class ActiveCampaignTests(unittest.TestCase):
    def setUp(self):
        self.camp, self.auth, self.decl = load("campaign.json"), load("authorization.json"), load("budget-declaration.json")

    def test_files_validate_and_agree(self):
        st.validate_campaign(self.camp)
        self.assertEqual(db.validate_declaration(self.decl, repository=self.camp["repository"]), [])
        now = st._fmt(st._ts(self.auth["expires_at"]) - timedelta(days=1))
        self.assertEqual(live.validate_authorization(self.auth, campaign=self.camp, now=now), [])
        self.assertEqual(self.camp["campaign_id"], self.auth["campaign_id"])
        self.assertEqual(self.camp["campaign_id"], self.decl["campaign_id"])
        self.assertEqual(self.auth["budget_id"], self.decl["budget_id"])
        self.assertEqual(self.camp["repository"], self.auth["repository"])

    def test_lane_scope_and_control_issue(self):
        self.assertEqual(self.camp["control_issue"], 346)
        for o in self.camp["objectives"]:
            for prefix in o["scope_prefixes"]:
                self.assertTrue(prefix.startswith(LANE), prefix)
        self.assertEqual(self.camp["policy"]["max_concurrent_tasks"], 1)

    def test_subscription_only(self):
        p = self.camp["policy"]
        self.assertEqual((p["route"], p["billing"]), (st.ROUTE, "subscription"))
        self.assertFalse(p["allow_api_fallback"] or p["allow_metered_fallback"])
        self.assertEqual((self.auth["route"], self.auth["billing"]), (st.ROUTE, "subscription"))
        self.assertIs(self.auth["usage_credits_confirmed_off"], True)

    def test_budget_is_its_own_ledger_and_within_the_template(self):
        tpl = json.loads((EV / "prod-budget-declaration.TEMPLATE.json").read_text(encoding="utf-8"))
        if "rolling_24h_limit" in self.decl:
            # owner decision 2026-10-12: no total cap, a rolling 24-hour limit below Jules' own (100 on AI Pro)
            self.assertLess(self.decl["rolling_24h_limit"], 100)
        else:
            self.assertLessEqual(self.decl["cap"], tpl["cap"])
        self.assertLessEqual(self.auth["max_activations"], self.decl["cap"])
        self.assertNotEqual(self.decl["ledger_prefix"], bf.PREFIX)                   # never the 9/10 proof ledger
        self.assertIn(self.decl["budget_id"], self.decl["ledger_prefix"])
        self.assertIs(self.decl["slot_create"], True)

    def test_the_real_files_run_in_the_mock_and_stop_on_loop_stop(self):
        backlog = json.loads((EV / "initial-backlog.json").read_text(encoding="utf-8"))
        camp = json.loads(json.dumps(self.camp))
        h = Harness(backlog["signals"], campaign=camp, cap=self.decl["cap"])
        h.w.gh.issues[h.w.control]["labels"].append("loop-stop")
        h.w.deliver({"name": "start"})
        try:
            h.w.run(max_events=50)
        except AssertionError:
            pass
        self.assertEqual(sum(1 for n in h.task_issues() if labeled(h.w, n)), 0)
        h.w.gh.issues[h.w.control]["labels"].remove("loop-stop")
        h.w.deliver({"name": "start"})
        h.w.run_until_quiet()
        self.assertEqual(sum(1 for n in h.task_issues() if passed(h.w, n)), len(backlog["signals"]))
        h.assert_invariants(self)


if __name__ == "__main__":
    unittest.main()
