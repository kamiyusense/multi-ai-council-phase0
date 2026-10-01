import os
import unittest

from src.providers.policy import CLAUDE_POLICY, claude_session_meta
from src.providers.preflight import validate_provider_static
from src.relay.envelope import validate_payload, validate_timeout


class TestStaticEvidencePreparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        cls.root = os.path.abspath(root)
        doc_path = os.path.join(cls.root, "docs", "RELAY_STATIC_EVIDENCE_PREPARATION.md")
        checkpoint_path = os.path.join(cls.root, "docs", "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(doc_path):
            raise AssertionError("static evidence preparation document is missing")
        if not os.path.isfile(checkpoint_path):
            raise AssertionError("static checkpoint document is missing")
        with open(doc_path, "r", encoding="utf-8") as stream:
            cls.doc = stream.read()
        with open(checkpoint_path, "r", encoding="utf-8") as stream:
            cls.checkpoint = stream.read()
        cls.rows = cls._parse_table(cls.doc)

    @staticmethod
    def _parse_table(content: str) -> dict[str, dict[str, str]]:
        headers = [
            "gap_id",
            "preparation_status",
            "evidence_refs",
            "observed_static_controls",
            "still_missing",
            "blocker_state",
        ]
        lines = content.splitlines()
        header_index = None
        for index, line in enumerate(lines):
            if line.startswith("| gap_id |"):
                actual = [cell.strip() for cell in line.strip("|").split("|")]
                if actual != headers:
                    raise AssertionError(f"unexpected table headers: {actual}")
                header_index = index
                break
        if header_index is None:
            raise AssertionError("evidence table header is missing")

        rows = {}
        for line in lines[header_index + 2 :]:
            if not line.startswith("| "):
                break
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != len(headers):
                raise AssertionError(f"malformed evidence row: {line}")
            row = dict(zip(headers, cells))
            gap_id = row["gap_id"]
            if gap_id in rows:
                raise AssertionError(f"duplicate gap row: {gap_id}")
            rows[gap_id] = row
        return rows

    def test_exact_three_gap_rows_and_fail_closed_states(self) -> None:
        self.assertEqual(
            set(self.rows),
            {"common_timeout", "common_min_permissions", "common_sensitive_fanout"},
        )
        expected_status = {
            "common_timeout": "PARTIAL_STATIC_EVIDENCE",
            "common_min_permissions": "PARTIAL_STATIC_EVIDENCE",
            "common_sensitive_fanout": "MISSING_STATIC_EVIDENCE",
        }
        for gap_id, status in expected_status.items():
            with self.subTest(gap_id=gap_id):
                self.assertEqual(self.rows[gap_id]["preparation_status"], status)
                self.assertEqual(self.rows[gap_id]["blocker_state"], "BLOCKED_UNKNOWN")

    def test_every_non_none_evidence_ref_resolves_to_repository_bytes(self) -> None:
        for gap_id, row in self.rows.items():
            refs = row["evidence_refs"]
            if refs == "NONE":
                continue
            for ref in refs.split("<br>"):
                with self.subTest(gap_id=gap_id, ref=ref):
                    path, separator, anchor = ref.partition("::")
                    self.assertEqual(separator, "::")
                    self.assertTrue(path)
                    self.assertTrue(anchor)
                    self.assertFalse(os.path.isabs(path))
                    self.assertNotIn("..", path.split("/"))
                    target = os.path.join(self.root, path)
                    self.assertTrue(os.path.isfile(target), path)
                    with open(target, "r", encoding="utf-8") as stream:
                        source = stream.read()
                    self.assertIn(anchor.replace("\\|", "|"), source)

    def test_common_timeout_has_real_static_evidence_but_stays_unresolved(self) -> None:
        row = self.rows["common_timeout"]
        self.assertNotEqual(row["evidence_refs"], "NONE")
        self.assertIn("provider-specific exact finite timeout values", row["still_missing"])
        self.assertIn("real provider processes enforce", row["still_missing"])

        validate_timeout(None)
        validate_timeout(1)
        for value in (True, False, 0, -1, 1.5, "30"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_timeout(value)

    def test_min_permission_evidence_is_partial_and_claude_specific(self) -> None:
        row = self.rows["common_min_permissions"]
        self.assertIn("whole-path minimum permission profile", row["still_missing"])
        self.assertFalse(CLAUDE_POLICY.dangerous_permission_bypass)
        self.assertFalse(
            claude_session_meta()["claudeCode"]["options"][
                "allowDangerouslySkipPermissions"
            ]
        )

        result = validate_provider_static(
            provider_id="anthropic",
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "dangerous_permission_bypass": True,
                "hide_claude_auth": False,
            },
            provider_meta=claude_session_meta(),
        )
        self.assertEqual(result["static_configuration_status"], "UNKNOWN")
        self.assertIn("dangerous_permission_bypass", result["reasons"][0])

    def test_generic_payload_override_validation_is_not_sensitive_fanout_proof(self) -> None:
        row = self.rows["common_sensitive_fanout"]
        self.assertEqual(row["evidence_refs"], "NONE")
        self.assertIn("not treated as evidence", row["observed_static_controls"])
        self.assertIn("secret/PII/private-code", row["still_missing"])

        # A synthetic key named "secret" is not one of the control-plane
        # override keys rejected by validate_payload. This directly prevents
        # treating generic override validation as a sensitive-data filter.
        validate_payload({"secret": "synthetic"})
        with self.assertRaises(ValueError):
            validate_payload({"billing": "synthetic"})

    def test_document_never_claims_live_resolution_or_authorization(self) -> None:
        for forbidden in (
            "execution_authorized=true",
            "dispatch_allowed=true",
            "live_ready=true",
            "LIVE_AUTHORIZED",
            "READY_FOR_LIVE",
            "REAL_BLOCKERS_RESOLVED",
        ):
            self.assertNotIn(forbidden, self.doc)

        for phrase in (
            "zero external/read-only/live evidence acquisition",
            "Static evidence preparation != real blocker resolved",
            "Every audited blocker remains `BLOCKED_UNKNOWN`",
            "No provider/model turn is authorized",
            "first real provider/model turn remains separately human-approved",
        ):
            self.assertIn(phrase, " ".join(self.doc.split()))

    def test_checkpoint_preserves_prepared_static_boundary(self) -> None:
        section = self.checkpoint.split(
            "## Static Evidence Preparation Checkpoint",
            1,
        )[1]
        for phrase in (
            "PREPARED/static evidence-preparation-audit status only",
            "No real live blocker is resolved",
            "First live provider turn remains unauthorized",
        ):
            self.assertIn(phrase, section)
