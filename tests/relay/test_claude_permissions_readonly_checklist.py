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
            if not line or not line.startswith("|"):
                continue
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if not parts:
                continue
            if parts[0] == "provider_id":
                in_table = True
                continue
            if in_table and parts[0].startswith("---"):
                continue
            if in_table and len(parts) == len(headers):
                parsed_row = {headers[i]: parts[i] for i in range(len(headers))}
                row_key = f"{parsed_row['provider_id']}:{parsed_row['gap_id']}"
                parsed[row_key] = parsed_row
        return parsed

    def test_exactly_one_anthropic_row(self):
        """Assert exactly one anthropic/claude_permissions row exists and is parsed correctly."""
        self.assertEqual(len(self.rows), 1)
        self.assertIn("anthropic:claude_permissions", self.rows)
        row = self.rows["anthropic:claude_permissions"]
        self.assertEqual(row["provider_id"], "anthropic")
        self.assertEqual(row["gap_id"], "claude_permissions")

    def test_conservative_vocabulary(self):
        """Assert conservative current-state vocabulary and values are used."""
        row = self.rows["anthropic:claude_permissions"]
        self.assertEqual(row["static_policy_bypass_state"], "STATIC_PREPARED")
        self.assertEqual(row["static_session_meta_state"], "STATIC_PREPARED")
        self.assertEqual(row["new_session_effective_state"], "EVIDENCE_REQUIRED")
        self.assertEqual(row["load_session_effective_state"], "EVIDENCE_REQUIRED")
        self.assertEqual(row["observed_permission_mode_state"], "EVIDENCE_REQUIRED")
        self.assertEqual(row["bypass_absence_state"], "EVIDENCE_REQUIRED")
        self.assertEqual(row["readonly_inspection_state"], "UNKNOWN")
        self.assertEqual(row["evidence_provenance_state"], "EVIDENCE_REQUIRED")
        self.assertEqual(row["blocker_state"], "BLOCKED_UNKNOWN")

    def test_static_vs_runtime_distinctions(self):
        """Assert the static-vs-runtime distinctions are present."""
        self.assertIn("explicitly distinguishes between:", self.doc)
        self.assertIn("ProviderPolicy `dangerous_permission_bypass=false`", self.doc)
        self.assertIn("`claude_session_meta()` `allowDangerouslySkipPermissions=false`", self.doc)
        self.assertIn("preflight exact `provider_meta` equality", self.doc)
        self.assertIn("actual effective permission mode on a new session", self.doc)
        self.assertIn("actual effective permission mode on a load/resume session", self.doc)
        self.assertIn("proof that dangerous bypass was not silently enabled elsewhere", self.doc)
        self.assertIn("inspection event identity and evidence provenance", self.doc)

    def test_static_preflight_cannot_satisfy_runtime(self):
        """Assert static preflight/meta cannot satisfy runtime new/load fields."""
        self.assertIn(
            "Checked-in static config/source values, a successful preflight, and mock/static session-meta alone are individually insufficient to prove actual runtime enforcement.",
            self.doc,
        )

    def test_conceptual_evidence_fields(self):
        """Assert all conceptual evidence field names are present."""
        fields = [
            "`provider_id`",
            "`gap_id`",
            "`inspection_correlation_id`",
            "`expected_allow_dangerously_skip_permissions`",
            "`observed_new_session_permission_mode`",
            "`observed_load_session_permission_mode`",
            "`observed_bypass_state`",
            "`evidence_source`",
            "`evidence_locator_or_hash`",
            "`captured_at`",
            "`verification_state`",
        ]
        for field in fields:
            self.assertIn(field, self.doc)

    def test_forbidden_raw_sensitive_data(self):
        """Assert forbidden raw sensitive data semantics."""
        self.assertIn("No raw secrets, tokens, cookies, passwords, account numbers", self.doc)
        self.assertIn("private profile dumps, or raw credential material belong in evidence.", self.doc)

    def test_cross_provider_evidence_fails(self):
        """Assert cross-provider/cross-inspection evidence cannot satisfy the gap."""
        self.assertIn(
            "Evidence must be Anthropic/inspection-event bound; evidence from cross-provider, another account, or another inspection cannot satisfy this gap.",
            self.doc,
        )

    def test_unknown_states_fail_closed(self):
        """Assert unknown new/load states fail closed."""
        self.assertIn(
            "Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:",
            self.doc,
        )
        self.assertIn("new/load effective permission mode", self.doc)
        self.assertIn("bypass absence", self.doc)
        self.assertIn("provider/session binding", self.doc)
        self.assertIn("evidence provenance", self.doc)

    def test_bypass_fails_closed(self):
        """Assert true/enabled/ambiguous bypass fails closed."""
        self.assertIn(
            "Any observed true/enabled/ambiguous dangerous-permission bypass is a hard proof failure and must not be normalized to false.",
            self.doc,
        )

    def test_zero_external_evidence(self):
        """Assert zero external evidence and unresolved/BLOCKED_UNKNOWN."""
        self.assertIn("Zero external/read-only permission evidence is acquired by this batch.", self.doc)
        self.assertIn("`claude_permissions` remains unresolved/BLOCKED_UNKNOWN.", self.doc)

        self.assertIn(
            "If proof would require changing permissions/settings/auth, starting a provider/model turn, reading a raw secret, or widening access, that proof method is forbidden in this batch.",
            self.doc,
        )

    def test_checkpoint_preserves_boundary(self):
        """Assert checkpoint preserves the same boundary."""
        self.assertIn("## Claude Permissions Read-Only Checklist Static Checkpoint", self.checkpoint)
        self.assertIn("Implemented static claude-permissions-readonly-checklist document.", self.checkpoint)
        self.assertIn("This checkpoint is strictly PREPARED/static claude-permissions-readonly-checklist status only.", self.checkpoint)
        self.assertIn("Zero external/read-only permission evidence is acquired by this batch.", self.checkpoint)
        self.assertIn("claude_permissions remains unresolved/BLOCKED_UNKNOWN.", self.checkpoint)
        self.assertIn("No real live blocker is resolved.", self.checkpoint)
