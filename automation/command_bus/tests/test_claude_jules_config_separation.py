"""Normal operating config and the one-off LIVE proof config stay separated.

The committed default policy grants nothing; the LIVE proof inputs are evidence
under ``docs/evidence`` with an authorization that has expired, and the CLI
never defaults to either file.
"""
from __future__ import annotations

import json
import os
import unittest

from automation.command_bus import claude_jules_live
from automation.command_bus.claude_jules_autoloop import validate_roadmap
from automation.command_bus.claude_jules_dispatch import live_authorization_problem, validate_policy
from automation.command_bus.claude_jules_live_budget import LOOP_A_LIVE_BUDGET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CONFIG = os.path.join(ROOT, "automation", "command_bus", "config")
PROOF = os.path.join(ROOT, "docs", "evidence", "claude-jules-autoloop-20261001", "live-proof-2026-10-02")


def load(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as handle:
        return json.load(handle)


class ConfigSeparationTests(unittest.TestCase):
    def test_normal_config_grants_nothing_and_has_no_live_files(self):
        self.assertEqual([n for n in os.listdir(CONFIG) if ".live" in n or "live-proof" in n], [])
        policy = validate_policy(load(CONFIG, "claude_jules_autoloop_policy.json"))
        self.assertEqual(policy["allowed_target_branches"], [])
        self.assertEqual(policy["allowed_lane_ids"], [])
        self.assertIsNone(policy["live_dispatch_authorization"])
        self.assertIn("no explicit human live-dispatch authorization",
                      live_authorization_problem(policy, now="2026-10-01T00:00:00+00:00", dispatches_used=0))

    def test_live_proof_inputs_are_valid_scoped_and_expired(self):
        policy = validate_policy(load(PROOF, "policy.live-proof.json"))
        auth = policy["live_dispatch_authorization"]
        self.assertEqual(policy["allowed_target_branches"], ["claude/autoloop-live-target"])
        self.assertEqual(policy["allowed_lane_ids"], ["J-GREEN"])
        self.assertEqual(auth["max_dispatches"], LOOP_A_LIVE_BUDGET)
        self.assertEqual(auth["expires_at"], "2026-10-02T15:00:00+00:00")
        self.assertEqual(live_authorization_problem(policy, now="2026-10-02T15:00:00+00:00", dispatches_used=0),
                         "live-dispatch authorization expired")
        validate_roadmap(load(PROOF, "roadmap.live-proof.json"))

    def test_budget_total_is_fixed_at_ten(self):
        self.assertEqual(LOOP_A_LIVE_BUDGET, 10)

    def test_cli_has_no_default_policy(self):
        with self.assertRaises(SystemExit):
            claude_jules_live.main(["status", "--roadmap", "x", "--origin-loop-id", "y", "--lane-id", "J-GREEN"])


if __name__ == "__main__":
    unittest.main()
