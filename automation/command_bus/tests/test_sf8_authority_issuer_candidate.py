import json
import re
import unittest
from dataclasses import replace
from pathlib import Path

from automation.command_bus.control_tower import validate_registry
from automation.command_bus.github_oidc_proof_policy_cli import SF8_AUTHORITY_PROFILE
from automation.command_bus.lane_identity_adoption import validate_lane_adoption_diff

ROOT = Path(__file__).resolve().parents[3]
CAND = (ROOT / "docs/candidates/signal-sf8-authority-issuer.yml.candidate").read_text()
REG = json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text())
REC = {"schema_version": 1, "lane_loop_id": "chatgpt-semi-auto", "approved_by_actor_id": "42",
       "approval_ref": "issue:33#comment", "approved_at": "2026-10-03T00:00:00Z", "decision": "ADOPT_DURABLE"}
OK = frozenset({"42"})


def proposed(lane="chatgpt-semi-auto"):
    p = json.loads(json.dumps(REG))
    for e in p["loops"]:
        if e["loop_id"] == lane:
            e["identity_state"] = "DURABLE"
    return p


class IssuerCandidate(unittest.TestCase):
    def test_inert_and_not_under_workflows(self):
        self.assertFalse((ROOT / ".github/workflows/signal-sf8-authority-issuer.yml").exists())

    def test_permissions_and_triggers(self):
        self.assertIn("workflow_dispatch:", CAND)
        self.assertNotRegex(CAND, r"(?m)^\s*(push|pull_request\w*|schedule):")
        self.assertIn("contents: read", CAND)
        self.assertIn("id-token: write", CAND)
        for bad in ("contents: write", "actions: write", "attestations: write", "packages: write", "secrets."):
            self.assertNotIn(bad, CAND)
        self.assertIn("github.ref == 'refs/heads/main'", CAND)
        self.assertIn("github.actor_id == github.triggering_actor_id", CAND)
        self.assertIn("github.run_attempt == 1", CAND)
        self.assertIn(f"OIDC_PROOF_PROFILE: {SF8_AUTHORITY_PROFILE.name}", CAND)
        for u in re.findall(r"uses: (\S+)", CAND):
            self.assertRegex(u, r"@[0-9a-f]{40}$")

    def test_actor_allowlist_is_placeholder_until_human_sets_it(self):
        self.assertIn("REPLACE_WITH_HUMAN_ACTOR_ID", CAND)


class LaneAdoption(unittest.TestCase):
    def check(self, prop=None, rec=None, ok=OK):
        return validate_lane_adoption_diff(current=REG, proposed=prop or proposed(), record=rec or REC, allowed_approver_ids=ok)

    def test_valid(self):
        self.assertEqual(self.check(), "chatgpt-semi-auto")

    def test_rejections(self):
        with self.assertRaises(ValueError): self.check(ok=frozenset({"7"}))
        with self.assertRaises(ValueError): self.check(rec={**REC, "decision": "x"})
        with self.assertRaises(ValueError): self.check(rec={**REC, "lane_loop_id": "nope"})
        with self.assertRaises(ValueError): self.check(prop=REG)  # no change
        p = proposed(); p["loops"][1]["identity_state"] = "DURABLE"
        with self.assertRaises(ValueError): self.check(prop=p)  # other lane changed
        p = proposed(); p["loops"][0]["loop_id"] = "12345"
        with self.assertRaises(ValueError): self.check(prop=p)  # id changed
        p = proposed(); p["loops"][0]["display_name"] = "Renamed"
        with self.assertRaises(ValueError): self.check(prop=p)  # extra field changed
        with self.assertRaises(ValueError): self.check(rec={**REC, "extra": 1})


if __name__ == "__main__":
    unittest.main()
