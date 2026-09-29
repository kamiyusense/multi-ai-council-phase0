import os
import re
import unittest


class TestProvenanceTrustSourceDecisionSupport(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = os.path.join(os.path.dirname(__file__), "..", "..")
        with open(
            os.path.join(
                base,
                "docs",
                "RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md",
            ),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.doc = stream.read()
        with open(
            os.path.join(base, "docs", "RELAY_STATIC_CHECKPOINT.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.checkpoint = stream.read()

    def _matrix_rows(self) -> dict[str, str]:
        rows = {}
        for line in self.doc.splitlines():
            if not line.startswith("| "):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells and cells[0] in {
                "KEEP_NOT_WIRED",
                "GITHUB_ACTIONS_READBACK_ONLY",
                "GITHUB_OIDC_AUTHENTICATOR",
                "GITHUB_ARTIFACT_ATTESTATION",
            }:
                rows[cells[0]] = line
        return rows

    def test_exact_candidate_rows_exist_once(self) -> None:
        rows = self._matrix_rows()
        self.assertEqual(
            set(rows),
            {
                "KEEP_NOT_WIRED",
                "GITHUB_ACTIONS_READBACK_ONLY",
                "GITHUB_OIDC_AUTHENTICATOR",
                "GITHUB_ARTIFACT_ATTESTATION",
            },
        )
        for candidate in rows:
            self.assertEqual(
                sum(
                    1
                    for line in self.doc.splitlines()
                    if line.startswith(f"| {candidate} |")
                ),
                1,
            )

    def test_project_classifications_are_exactly_preserved(self) -> None:
        rows = self._matrix_rows()
        self.assertIn(
            "current safe default / no provenance advancement",
            rows["KEEP_NOT_WIRED"],
        )
        self.assertIn(
            "transport evidence only / insufficient as authenticator",
            rows["GITHUB_ACTIONS_READBACK_ONLY"],
        )
        self.assertIn(
            "candidate / NOT_AUTHORIZED",
            rows["GITHUB_OIDC_AUTHENTICATOR"],
        )
        self.assertIn(
            "strong candidate / NOT_AUTHORIZED",
            rows["GITHUB_ARTIFACT_ATTESTATION"],
        )

    def test_zero_choice_and_zero_permission_boundary_is_explicit(self) -> None:
        self.assertIn("ZERO ARCHITECTURE CHOICE / ZERO PERMISSION CHANGE", self.doc)
        self.assertIn("does not choose a trust source", self.doc)
        self.assertIn("does not add workflow permissions", self.doc)
        self.assertIn("does not request an OIDC token", self.doc)
        self.assertIn("does not create an artifact attestation", self.doc)

    def test_permission_names_are_confined_to_candidate_rows_and_explanation(self) -> None:
        rows = self._matrix_rows()
        self.assertNotIn("id-token: write", rows["KEEP_NOT_WIRED"])
        self.assertNotIn("id-token: write", rows["GITHUB_ACTIONS_READBACK_ONLY"])
        self.assertIn("id-token: write", rows["GITHUB_OIDC_AUTHENTICATOR"])
        self.assertIn("id-token: write", rows["GITHUB_ARTIFACT_ATTESTATION"])
        self.assertNotIn("attestations: write", rows["GITHUB_OIDC_AUTHENTICATOR"])
        self.assertIn(
            "attestations: write",
            rows["GITHUB_ARTIFACT_ATTESTATION"],
        )
        self.assertIn(
            "contents: read",
            rows["GITHUB_ARTIFACT_ATTESTATION"],
        )
        self.assertNotIn("id-token: write", self.checkpoint)
        self.assertNotIn("attestations: write", self.checkpoint)

    def test_oidc_and_attestation_do_not_overclaim_human_intent(self) -> None:
        rows = self._matrix_rows()
        self.assertIn(
            "does **not** by itself prove a human intentionally approved",
            rows["GITHUB_OIDC_AUTHENTICATOR"],
        )
        self.assertIn(
            "does **not** by itself prove human intent",
            rows["GITHUB_ARTIFACT_ATTESTATION"],
        )
        self.assertNotIn(
            "Independently Authenticates Execution/Human Provenance | Yes",
            self.doc,
        )

    def test_actions_readback_is_transport_evidence_only(self) -> None:
        row = self._matrix_rows()["GITHUB_ACTIONS_READBACK_ONLY"]
        self.assertIn("transport evidence only", row)
        self.assertIn("insufficient as authenticator", row)
        self.assertIn(
            "does **not** independently authenticate human intent",
            row,
        )
        self.assertIn(
            "does **not** authenticate itself",
            self.doc,
        )

    def test_attestation_verification_boundary_is_explicit(self) -> None:
        self.assertIn(
            "attestation signature/timestamps and signer identity must be verified",
            self.doc,
        )
        self.assertIn(
            "Merely retrieving an attestation record is not enough",
            self.doc,
        )

    def test_exact_remaining_human_decision_is_durable(self) -> None:
        self.assertIn("## Exact remaining human decision", self.doc)
        self.assertIn(
            "Choose whether to keep production provenance NOT_WIRED or authorize a narrowly scoped signed trust mechanism",
            self.doc,
        )
        self.assertIn(
            "separately choose OIDC vs Artifact Attestation",
            self.doc,
        )
        self.assertIn("This document does not make that choice", self.doc)

    def test_provenance_verification_remains_separate_from_execution(self) -> None:
        self.assertIn(
            "Future provenance verification must remain separate from",
            self.doc,
        )
        self.assertIn("execution authorization", self.doc)
        self.assertIn("first-live dispatch", self.doc)
        self.assertIn("provider/model execution", self.doc)
        self.assertIn(
            "first live provider turn remains a separate bounded action requiring explicit human approval",
            self.doc,
        )

    def test_no_authorized_or_wired_claims_exist(self) -> None:
        for claim in (
            "provenance_verified=true",
            "execution_authorized=true",
            "dispatch_allowed=true",
            "live_ready=true",
            "production authenticator wired",
        ):
            self.assertNotIn(claim.lower(), self.doc.lower())
            self.assertNotIn(claim.lower(), self.checkpoint.lower())

        self.assertIn("Production authenticators remain **NOT_WIRED**", self.doc)

    def test_no_real_live_blocker_claim(self) -> None:
        self.assertIn(
            "does not resolve any real live blocker",
            self.doc,
        )
        self.assertIn(
            "No synthetic fixture",
            self.doc,
        )
        self.assertIn(
            "No real live blocker is resolved",
            self.checkpoint,
        )

    def test_checkpoint_stays_prepared_static_only(self) -> None:
        self.assertIn(
            "PREPARED/static decision-support status only",
            self.checkpoint,
        )
        self.assertIn(
            "production authenticators remain NOT_WIRED",
            self.checkpoint,
        )

    def test_matrix_has_required_comparison_dimensions(self) -> None:
        header = next(
            line
            for line in self.doc.splitlines()
            if line.startswith("| Candidate |")
        )
        required = (
            "Project classification",
            "Evidence strength",
            "Independent authentication capability",
            "Documented permissions needed",
            "Repository/workflow mutation required",
            "New secret/key",
            "Offline/static testability",
            "Implementation complexity",
            "Blast radius",
            "What it still does NOT prove",
            "Explicit human authorization before implementation",
        )
        for dimension in required:
            self.assertIn(dimension, header)

    def test_no_accidental_permission_yaml_or_live_command(self) -> None:
        self.assertIsNone(
            re.search(r"(?m)^\s*permissions:\s*$", self.doc),
        )
        for forbidden in (
            "gh attestation verify ",
            "curl ",
            "ACTIONS_ID_TOKEN_REQUEST_URL",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        ):
            self.assertNotIn(forbidden, self.doc)
