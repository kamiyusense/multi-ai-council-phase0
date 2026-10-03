import json
import re
import unittest
from dataclasses import replace
from pathlib import Path

from automation.command_bus.control_tower import validate_registry
from automation.command_bus.github_oidc_proof_policy_cli import SF8_AUTHORITY_PROFILE
from automation.command_bus.lane_identity_adoption import registry_digest, validate_lane_adoption_diff
from automation.command_bus.tests.pre_adoption_registry import pre_adoption

ROOT = Path(__file__).resolve().parents[3]
CAND = (ROOT / ".github/workflows/signal-sf8-authority-issuer.yml").read_text()
REG = pre_adoption(json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text()))
REC = {"schema_version": 1, "record_id": "adopt-chatgpt-semi-auto-1", "lane_loop_id": "chatgpt-semi-auto",
       "approved_by_actor_id": "20355232", "approval_ref": "github-actions:run/123",
       "approved_at": "2026-10-03T00:00:00Z", "decision": "ADOPT_DURABLE",
       "expected_registry_sha256": registry_digest(REG)}
OK = frozenset({"20355232"})


def proposed(lane="chatgpt-semi-auto"):
    p = json.loads(json.dumps(REG))
    for e in p["loops"]:
        if e["loop_id"] == lane:
            e["identity_state"] = "DURABLE"
    return p


class IssuerCandidate(unittest.TestCase):
    def test_permissions_and_triggers(self):
        self.assertIn("workflow_dispatch:", CAND)
        self.assertNotRegex(CAND, r"(?m)^\s*(push|pull_request\w*|schedule):")
        self.assertIn("contents: read", CAND)
        self.assertIn("id-token: write", CAND)
        for bad in ("contents: write", "actions: write", "attestations: write", "packages: write", "secrets."):
            self.assertNotIn(bad, CAND)
        self.assertIn("github.ref == 'refs/heads/main'", CAND)
        self.assertIn("github.event_name == 'workflow_dispatch'", CAND)
        self.assertIn("github.actor_id", CAND)
        # github.triggering_actor_id is not a documented context property (evaluates to ""),
        # so it must never gate the job; that check lives in the REST readback verifier.
        self.assertNotIn("triggering_actor_id", CAND)
        self.assertNotIn("triggering_actor", CAND)
        self.assertIn("github.run_attempt == 1", CAND)
        self.assertIn(f"OIDC_PROOF_PROFILE: {SF8_AUTHORITY_PROFILE.name}", CAND)
        for u in re.findall(r"uses: (\S+)", CAND):
            self.assertRegex(u, r"@[0-9a-f]{40}$")

    def test_single_human_allowlist_and_no_inputs(self):
        self.assertEqual(re.findall(r"fromJSON\('(\[[^']*\])'\)", CAND), ['["20355232"]'])
        self.assertNotIn("inputs:", CAND)
        self.assertNotIn("REPLACE_WITH", CAND)
        self.assertIn("github.repository == 'kamiyusense/multi-ai-council-phase0'", CAND)

    def test_checkout_and_artifact_hygiene(self):
        self.assertIn("persist-credentials: false", CAND)
        self.assertNotIn("id_token", CAND.lower().replace("id-token", ""))
        self.assertNotRegex(CAND, r"(?i)\b(jwt|ACTIONS_ID_TOKEN_REQUEST_TOKEN)\b")
        self.assertEqual(CAND.count("upload-artifact@"), 1)
        self.assertIn("oidc-proof-evidence.json", CAND)  # sanitized evidence file only
        self.assertNotRegex(CAND, r"(?m)^\s*run:.*(git (push|commit)|curl|gh )")

    def test_no_other_workflow_uses_authority_profile(self):
        for f in (ROOT / ".github/workflows").glob("*.yml"):
            if f.name != "signal-sf8-authority-issuer.yml":
                self.assertNotRegex(f.read_text(), r"OIDC_PROOF_PROFILE:\s*['\"]?sf8-authority")


class LaneAdoption(unittest.TestCase):
    def check(self, prop=None, rec=None, ok=OK, cur=None, **kw):
        return validate_lane_adoption_diff(current=cur or REG, proposed=prop or proposed(), record=rec or REC, allowed_approver_ids=ok, **kw)

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
        with self.assertRaises(ValueError): self.check(rec={**REC, "approval_ref": "issue:33#c"})  # free-text approval

    def test_stale_registry_digest(self):
        cur = json.loads(json.dumps(REG)); cur["loops"][1]["display_order"] = 25
        with self.assertRaises(ValueError): self.check(cur=cur)

    def test_duplicate_record_or_run(self):
        with self.assertRaises(ValueError): self.check(applied_record_ids=frozenset({REC["record_id"]}))
        with self.assertRaises(ValueError): self.check(approval_run_ids_in_use=frozenset({REC["approval_ref"]}))

    def test_collision_with_other_lane_and_second_adoption(self):
        p = proposed(); p["loops"][1]["loop_id"] = "chatgpt-semi-auto"
        with self.assertRaises(ValueError): self.check(prop=p)
        # recovery: re-applying after adoption fails closed (already DURABLE), never double-adopts
        after = proposed()
        rec = {**REC, "expected_registry_sha256": registry_digest(after)}
        with self.assertRaises(ValueError): self.check(cur=after, prop=after, rec=rec)

    def test_registry_unchanged_when_validation_fails(self):
        before = json.dumps(REG, sort_keys=True)
        with self.assertRaises(ValueError): self.check(ok=frozenset())
        self.assertEqual(json.dumps(REG, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
