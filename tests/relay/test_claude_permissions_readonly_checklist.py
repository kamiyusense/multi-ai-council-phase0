import os
import unittest


class TestClaudePermissionsReadonlyChecklist(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        cls.root = os.path.abspath(root)
        doc_path = os.path.join(cls.root, "docs", "RELAY_CLAUDE_PERMISSIONS_READONLY_CHECKLIST.md")
        checkpoint_path = os.path.join(cls.root, "docs", "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(doc_path):
            raise AssertionError("claude permissions readonly checklist document is missing")
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
            "provider_id",
            "gap_id",
            "static_policy_bypass_state",
            "static_session_meta_state",
            "new_session_effective_state",
            "load_session_effective_state",
            "observed_permission_mode_state",
            "bypass_absence_state",
            "readonly_inspection_state",
            "evidence_provenance_state",
            "blocker_state",
        ]
        in_table = False
        parsed: dict[str, dict[str, str]] = {}
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("| provider_id |"):
                in_table = True
                continue
            if in_table and line.startswith("| ---"):
                continue
            if in_table and not line:
                break
            if in_table and line.startswith("|"):
                parts = [p.strip() for p in line.strip("|").split("|")]
                if len(parts) >= len(headers):
                    pid = f"{parts[0]}_{parts[1]}"
                    parsed[pid] = dict(zip(headers, parts))
        return parsed

    def test_parse_exact_provider_gap_row(self) -> None:
        keys = list(self.rows.keys())
        self.assertEqual(len(keys), 1, "should have exactly 1 row")
        self.assertEqual(keys[0], "anthropic_claude_permissions")

    def test_assert_current_rows_remain_conservative_and_common_blocker_is_blocked_unknown(self) -> None:
        row = self.rows["anthropic_claude_permissions"]
        self.assertEqual(row["provider_id"], "anthropic")
        self.assertEqual(row["gap_id"], "claude_permissions")
        self.assertEqual(row["static_policy_bypass_state"], "STATIC_PREPARED")
        self.assertEqual(row["static_session_meta_state"], "STATIC_PREPARED")

        for field in [
            "new_session_effective_state",
            "load_session_effective_state",
            "observed_permission_mode_state",
            "bypass_absence_state",
            "evidence_provenance_state",
        ]:
            self.assertEqual(row[field], "EVIDENCE_REQUIRED", f"{field} should be EVIDENCE_REQUIRED")

        self.assertEqual(row["readonly_inspection_state"], "UNKNOWN")
        self.assertEqual(row["blocker_state"], "BLOCKED_UNKNOWN")

    def test_assert_explicit_distinctions(self) -> None:
        self.assertIn("ProviderPolicy `dangerous_permission_bypass=false`;", self.doc)
        self.assertIn("`claude_session_meta()` `allowDangerouslySkipPermissions=false`;", self.doc)
        self.assertIn("preflight exact `provider_meta` equality;", self.doc)
        self.assertIn("actual effective permission mode when creating a new session;", self.doc)
        self.assertIn("actual effective permission mode when loading/resuming;", self.doc)
        self.assertIn("proof that a dangerous bypass was not silently enabled elsewhere;", self.doc)
        self.assertIn("inspection event identity and evidence provenance.", self.doc)

    def test_assert_static_insufficiency(self) -> None:
        self.assertIn(
            "Static source/config values, successful preflight, or a mock/static session-meta fixture alone are insufficient to prove runtime enforcement on new/load.",
            self.doc
        )

    def test_assert_cross_provider_forbidden(self) -> None:
        self.assertIn(
            "Evidence must be Anthropic/inspection-event bound; evidence from another provider/account/inspection cannot satisfy this gap.",
            self.doc
        )

    def test_assert_no_raw_secrets(self) -> None:
        self.assertIn(
            "No raw secrets, tokens, cookies, passwords, account numbers, private profile dumps, or raw credential material belong in evidence.",
            self.doc
        )

    def test_assert_fail_closed(self) -> None:
        self.assertIn(
            "Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:",
            self.doc
        )
        for term in [
            "effective new-session permission mode",
            "effective load-session permission mode",
            "bypass absence",
            "provider/session binding",
            "evidence provenance",
        ]:
            self.assertIn(term, self.doc)

        self.assertIn(
            "Any observed true/enabled/ambiguous dangerous-permission bypass is a hard failure for proof and must not be normalized to false.",
            self.doc
        )

    def test_assert_all_conceptual_evidence_record_field_names_are_present(self) -> None:
        fields = [
            "provider_id",
            "gap_id",
            "inspection_correlation_id",
            "expected_allow_dangerously_skip_permissions",
            "observed_new_session_permission_mode",
            "observed_load_session_permission_mode",
            "observed_bypass_state",
            "evidence_source",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state",
        ]
        for field in fields:
            self.assertIn(f"`{field}`", self.doc)

    def test_assert_zero_external_evidence_acquired_and_gap_blocked(self) -> None:
        self.assertIn(
            "Zero external/read-only permission evidence is acquired by this batch.",
            self.doc
        )
        self.assertIn(
            "`claude_permissions` remains unresolved/BLOCKED_UNKNOWN.",
            self.doc
        )

    def test_assert_checkpoint_contains_the_same_prepared_unresolved_boundary(self) -> None:
        self.assertIn(
            "This checkpoint is strictly PREPARED/static claude-permissions-readonly-checklist status only.",
            self.checkpoint
        )
        self.assertIn(
            "Zero external/read-only permission evidence is acquired by this batch.",
            self.checkpoint
        )
        self.assertIn(
            "claude_permissions remains unresolved/BLOCKED_UNKNOWN.",
            self.checkpoint
        )
