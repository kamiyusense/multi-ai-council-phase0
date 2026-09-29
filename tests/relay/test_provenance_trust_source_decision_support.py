import unittest
import os

class TestProvenanceTrustSourceDecisionSupport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc_path = os.path.join("docs", "RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md")
        cls.checkpoint_path = os.path.join("docs", "RELAY_STATIC_CHECKPOINT.md")

        with open(cls.doc_path, 'r', encoding='utf-8') as f:
            cls.doc_content = f.read()

        with open(cls.checkpoint_path, 'r', encoding='utf-8') as f:
            cls.checkpoint_content = f.read()

    def test_candidates_and_classifications_present(self):
        # 9. Assert durable presence of every candidate row/classification
        self.assertIn("KEEP_NOT_WIRED", self.doc_content)
        self.assertIn("current safe default", self.doc_content)
        self.assertIn("no provenance advancement", self.doc_content)

        self.assertIn("GITHUB_ACTIONS_READBACK_ONLY", self.doc_content)
        self.assertIn("transport evidence only", self.doc_content)
        self.assertIn("insufficient as authenticator", self.doc_content)

        self.assertIn("GITHUB_OIDC_AUTHENTICATOR", self.doc_content)
        self.assertIn("candidate / NOT_AUTHORIZED", self.doc_content)

        self.assertIn("GITHUB_ARTIFACT_ATTESTATION", self.doc_content)
        self.assertIn("strong candidate / NOT_AUTHORIZED", self.doc_content)

    def test_zero_choice_boundary(self):
        # 9. Assert the zero-choice/zero-permission boundary
        self.assertIn("ZERO ARCHITECTURE CHOICE", self.doc_content)
        self.assertIn("ZERO PERMISSION CHANGE", self.doc_content)

    def test_permissions_isolated(self):
        # 10. Assert id-token: write only in OIDC/Attestation, attestations: write only in Artifact Attestation
        lines = self.doc_content.split('\n')
        for line in lines:
            if "id-token: write" in line:
                self.assertTrue("GITHUB_OIDC_AUTHENTICATOR" in line or "GITHUB_ARTIFACT_ATTESTATION" in line or "OIDC" in line or "Attestation" in line or "Documented Permissions Needed" in line, f"Found id-token: write outside allowed context: {line}")
            if "attestations: write" in line:
                self.assertTrue("GITHUB_ARTIFACT_ATTESTATION" in line or "Artifact Attestation" in line or "Documented Permissions Needed" in line, f"Found attestations: write outside allowed context: {line}")

        # Make sure they are actually there
        self.assertIn("id-token: write", self.doc_content)
        self.assertIn("attestations: write", self.doc_content)

        # Verify they don't appear in RELAY_STATIC_CHECKPOINT.md
        self.assertNotIn("id-token: write", self.checkpoint_content)
        self.assertNotIn("attestations: write", self.checkpoint_content)

    def test_no_false_provenance_claims(self):
        # 11. Assert no language claims provenance_verified=true, etc.
        false_claims = [
            "provenance_verified=true",
            "execution_authorized=true",
            "dispatch_allowed=true",
            "live_ready=true",
            "production authenticator wired"
        ]

        lower_doc = self.doc_content.lower()
        lower_check = self.checkpoint_content.lower()
        for claim in false_claims:
            # Need to be careful because 'provenance_verified=false' might exist
            self.assertNotIn(claim.lower(), lower_doc)
            self.assertNotIn(claim.lower(), lower_check)

    def test_actions_readback_classification(self):
        # 12. Assert GitHub Actions readback is explicitly classified as transport evidence only / insufficient independent authenticator
        self.assertIn("transport evidence only", self.doc_content)
        self.assertIn("insufficient as authenticator", self.doc_content)

    def test_provenance_verification_remains_separate(self):
        # 13. Assert future provenance verification remains separate from provider execution
        self.assertIn("keep provenance verification separate from execution authorization", self.doc_content)
        self.assertIn("first-live dispatch", self.doc_content)

    def test_no_real_blocker_resolved(self):
        # 14. Assert docs explicitly say no real live blocker is resolved
        self.assertIn("No real live blocker is resolved by this matrix or any synthetic fixtures", self.doc_content)

    def test_checkpoint_status(self):
        # 16. Update RELAY_STATIC_CHECKPOINT.md with PREPARED/static decision-support status only.
        self.assertIn("PREPARED/static decision-support status only", self.checkpoint_content)
