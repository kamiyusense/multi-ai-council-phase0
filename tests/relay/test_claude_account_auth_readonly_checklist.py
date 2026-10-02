import os
import unittest


class TestClaudeAccountAuthReadonlyChecklist(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        cls.root = os.path.abspath(root)
        doc_path = os.path.join(cls.root, "docs", "RELAY_CLAUDE_ACCOUNT_AUTH_READONLY_CHECKLIST.md")
        checkpoint_path = os.path.join(cls.root, "docs", "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(doc_path):
            raise AssertionError("claude account auth readonly checklist document is missing")
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
            "static_expected_auth_kind_state",
            "static_hide_auth_guard_state",
            "observed_authenticated_identity_state",
            "observed_credential_kind_state",
            "observed_subscription_route_state",
            "api_key_absence_state",
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
        self.assertEqual(keys[0], "anthropic_claude_account_auth")

    def test_assert_current_rows_remain_conservative_and_common_blocker_is_blocked_unknown(self) -> None:
        row = self.rows["anthropic_claude_account_auth"]
        self.assertEqual(row["provider_id"], "anthropic")
        self.assertEqual(row["gap_id"], "claude_account_auth")
        self.assertEqual(row["static_expected_auth_kind_state"], "STATIC_PREPARED")
        self.assertEqual(row["static_hide_auth_guard_state"], "STATIC_PREPARED")

        for field in [
            "observed_authenticated_identity_state",
            "observed_credential_kind_state",
            "observed_subscription_route_state",
            "api_key_absence_state",
            "evidence_provenance_state",
        ]:
            self.assertEqual(row[field], "EVIDENCE_REQUIRED", f"{field} should be EVIDENCE_REQUIRED")

        self.assertEqual(row["readonly_inspection_state"], "UNKNOWN")
        self.assertEqual(row["blocker_state"], "BLOCKED_UNKNOWN")

    def test_assert_static_guard_insufficiency(self) -> None:
        self.assertIn(
            "Checked-in static config/profile/default values, a successful login/account label, or repository-only absence of API-key material are individually insufficient to prove the actual account/subscription route.",
            self.doc
        )

    def test_assert_hide_claude_auth_is_incompatible(self) -> None:
        self.assertIn(
            "`--hide-claude-auth` is incompatible with the intended claude.ai subscription route and must not be used as a proof shortcut.",
            self.doc
        )

    def test_assert_cross_provider_forbidden(self) -> None:
        self.assertIn(
            "Evidence must be Anthropic/inspection-event bound; evidence from OpenAI, Google, another account, or another inspection cannot satisfy this gap.",
            self.doc
        )

    def test_assert_no_raw_secrets(self) -> None:
        self.assertIn(
            "No raw secrets, tokens, cookies, passwords, account numbers, billing identifiers, payment instrument data, or full private profile dumps belong in evidence.",
            self.doc
        )

    def test_assert_fail_closed(self) -> None:
        self.assertIn(
            "Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:",
            self.doc
        )
        for term in [
            "observed auth kind",
            "observed identity class",
            "credential mechanism",
            "hide-claude-auth state",
            "API-key route absence",
            "subscription route ownership",
            "evidence provenance",
            "exact provider/inspection binding",
        ]:
            self.assertIn(term, self.doc)

    def test_assert_all_conceptual_evidence_record_field_names_are_present(self) -> None:
        fields = [
            "provider_id",
            "gap_id",
            "inspection_correlation_id",
            "intended_auth_kind",
            "observed_auth_kind",
            "observed_identity_class",
            "hide_claude_auth_observation",
            "api_key_route_state",
            "subscription_route_observation",
            "evidence_source",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state",
        ]
        for field in fields:
            self.assertIn(f"`{field}`", self.doc)

    def test_assert_zero_external_evidence_acquired_and_gap_blocked(self) -> None:
        self.assertIn(
            "Zero external/read-only account evidence is acquired by this batch.",
            self.doc
        )
        self.assertIn(
            "`claude_account_auth` remains unresolved/BLOCKED_UNKNOWN.",
            self.doc
        )

    def test_assert_checkpoint_contains_the_same_prepared_unresolved_boundary(self) -> None:
        self.assertIn(
            "This checkpoint is strictly PREPARED/static claude-account-auth-readonly-checklist status only.",
            self.checkpoint
        )
        self.assertIn(
            "Zero external/read-only account or billing evidence is acquired by this batch.",
            self.checkpoint
        )
        self.assertIn(
            "claude_account_auth remains unresolved/BLOCKED_UNKNOWN.",
            self.checkpoint
        )
        self.assertIn(
            "No real live blocker is resolved.",
            self.checkpoint
        )
