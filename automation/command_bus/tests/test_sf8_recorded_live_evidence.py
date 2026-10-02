"""Checks the sanitized evidence recorded from the one-shot SF-8 live proof (run 36981004299)."""
import hashlib
import json
import re
import unittest
from pathlib import Path

from automation.command_bus.github_oidc_proof_policy_cli import SF8_PROFILE
from automation.command_bus.oidc_workflow_execution import verify_oidc_workflow_execution

DIR = Path(__file__).parents[3] / "docs" / "evidence" / "signal-sf8"
RUN_ID = "36981004299"
SHA = "93460dee54948dc6ac3888f4142ab78cd54ce759"


def load(name):
    return json.loads((DIR / name).read_text(encoding="utf-8"))


def digest(body):
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RecordedRunReader:
    """Run fields as read back from GitHub for run 36981004299 (repository fields per REST schema)."""

    def read_run(self, run_id):
        return {
            "id": 36981004299, "path": ".github/workflows/signal-sf8-oidc-proof.yml", "head_sha": SHA,
            "head_branch": "claude/signal-sf8-oidc-runtime-integration-20261002", "event": "push",
            "run_attempt": 1, "status": "completed", "conclusion": "success",
            "repository": {"full_name": "kamiyusense/multi-ai-council-phase0"},
            "head_repository": {"full_name": "kamiyusense/multi-ai-council-phase0"},
            "actor": {"id": 20355232}, "triggering_actor": {"id": 20355232},
            "created_at": "2026-10-02T07:53:51Z", "referenced_workflows": [],
        } if run_id == RUN_ID else None


class RecordedLiveEvidenceTests(unittest.TestCase):
    def test_oidc_evidence_digest_and_exact_run_binding(self):
        evidence = load("oidc-identity-proof-36981004299.json")
        body = {k: v for k, v in evidence.items() if k != "evidence_payload_sha256"}
        self.assertEqual(digest(body), evidence["evidence_payload_sha256"])
        execution = verify_oidc_workflow_execution(
            evidence=evidence, run_reader=RecordedRunReader(), profile=SF8_PROFILE,
            expected_run_id=RUN_ID, expected_sha=SHA)
        self.assertIsNotNone(execution)
        # Same-account push run: acceptable as a workflow-identity proof only.
        self.assertEqual(execution.event, "push")

    def test_jules_get_evidence_digest_and_raw_state(self):
        evidence = load("jules-session-get-evidence-36981004299.json")
        body = {k: v for k, v in evidence.items() if k != "evidence_sha256"}
        self.assertEqual(digest(body), evidence["evidence_sha256"])
        self.assertEqual((evidence["status"], evidence["retry_count"], evidence["http_method"]), ("PASS", 0, "GET"))
        self.assertEqual(evidence["raw_state"], "COMPLETED")  # not an active-owner proof
        self.assertEqual((evidence["run_id"], evidence["exact_commit_sha"]), (RUN_ID, SHA))

    def test_no_credential_shaped_material_is_recorded(self):
        for path in DIR.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"eyJ[A-Za-z0-9_-]{10,}\.", text), path.name)
            self.assertIsNone(re.search(r"AIza[0-9A-Za-z_-]{20,}", text), path.name)
            self.assertNotIn("Authorization", text)
            self.assertNotIn("https://", text.replace("sources/github", ""))


if __name__ == "__main__":
    unittest.main()
