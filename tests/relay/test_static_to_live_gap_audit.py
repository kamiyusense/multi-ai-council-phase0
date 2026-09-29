import unittest
import os
import re

class TestStaticToLiveGapAudit(unittest.TestCase):
    def setUp(self):
        self.doc_path = os.path.join(os.path.dirname(__file__), '../../docs/RELAY_STATIC_TO_LIVE_GAP_AUDIT.md')
        self.blockers_path = os.path.join(os.path.dirname(__file__), '../../docs/RELAY_LIVE_BLOCKERS.md')
        self.checkpoint_path = os.path.join(os.path.dirname(__file__), '../../docs/RELAY_STATIC_CHECKPOINT.md')

        with open(self.doc_path, 'r') as f:
            self.doc_content = f.read()

        with open(self.blockers_path, 'r') as f:
            self.blockers_content = f.read()

        with open(self.checkpoint_path, 'r') as f:
            self.checkpoint_content = f.read()

        # Parse audit table
        self.table_rows = []
        table_pattern = re.compile(r'\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|')
        for match in table_pattern.findall(self.doc_content):
            if match[0] not in ('gap_id', '---'):
                self.table_rows.append(match)

    def test_common_blockers_present(self):
        common_blockers = [
            "exact finite timeout values",
            "exact minimum permission profile",
            "executed-model verification mechanism",
            "proof that the intended subscription/auth route is the route actually paying for the turn",
            "provider-specific abort/readback evidence",
            "final secret/PII/private-code fan-out patterns",
            "live filesystem/network confinement feasibility",
            "end-to-end proof that no hidden retry/fallback violates Phase 0 policy"
        ]

        for blocker in common_blockers:
            self.assertIn(blocker, self.blockers_content, f"Source blocker missing: {blocker}")
            # we check the audit also contains it or a close variation
            # handle minor variation from doc to doc
            doc_blocker = blocker.replace("that the ", "").replace(" is the route actually paying for the turn", " is actually paying for the turn").replace("that no ", "no ").replace(" Phase 0 policy", " policy").replace("  ", " ")
            self.assertIn(doc_blocker, self.doc_content, f"Audit missing blocker: {blocker}")

            # Check table structure
            found_in_table = False
            for row in self.table_rows:
                if doc_blocker in row[5]:
                    found_in_table = True
                    break
            self.assertTrue(found_in_table, f"Blocker {blocker} not found in missing_evidence column of audit table")

    def test_provider_categories_present(self):
        categories = ["OpenAI/Codex", "Claude", "Google Antigravity", "Gemini CLI"]
        for cat in categories:
            self.assertIn(cat, self.doc_content, f"Missing category {cat}")

        # check table
        table_categories = [r[1] for r in self.table_rows]
        for cat in categories:
            self.assertIn(cat, table_categories, f"Category {cat} missing from table")

    def test_required_classes_present(self):
        classes = ["EVIDENCE_REQUIRED", "HUMAN_DECISION_REQUIRED", "FINAL_HUMAN_APPROVAL", "DEFERRED_NOT_SELECTED"]
        for cls in classes:
            self.assertIn(cls, self.doc_content, f"Missing class {cls}")

        table_classes = [r[2] for r in self.table_rows]
        for cls in classes:
            self.assertIn(cls, table_classes, f"Class {cls} missing from table")

    def test_trust_sources(self):
        self.assertIn("KEEP_NOT_WIRED", self.doc_content)
        self.assertIn("OIDC candidate remains NOT_AUTHORIZED", self.doc_content)
        self.assertIn("Artifact Attestation strong candidate remains NOT_AUTHORIZED", self.doc_content)
        self.assertIn("Actions readback is transport evidence only / insufficient authenticator", self.doc_content)

        # Check table classes
        for row in self.table_rows:
            if row[0] == 'provenance_oidc':
                self.assertEqual(row[3], 'NOT_AUTHORIZED')
                self.assertEqual(row[2], 'HUMAN_DECISION_REQUIRED')
            if row[0] == 'provenance_attest':
                self.assertEqual(row[3], 'NOT_AUTHORIZED')
                self.assertEqual(row[2], 'HUMAN_DECISION_REQUIRED')

    def test_gemini_cli_deferred(self):
        self.assertIn("DEFERRED_NOT_SELECTED", self.doc_content)
        self.assertIn("Gemini CLI", self.doc_content)

        # Check table
        found = False
        for row in self.table_rows:
            if row[1] == 'Gemini CLI':
                self.assertEqual(row[2], 'DEFERRED_NOT_SELECTED')
                found = True
        self.assertTrue(found)

    def test_first_live_turn(self):
        self.assertIn("explicit human approval", self.doc_content)
        self.assertIn("FINAL_HUMAN_APPROVAL", self.doc_content)

        found = False
        for row in self.table_rows:
            if row[0] == 'first_turn':
                self.assertEqual(row[2], 'FINAL_HUMAN_APPROVAL')
                found = True
        self.assertTrue(found)

    def test_no_dangerous_resolved_wording(self):
        dangerous_phrases = [
            "real_live_ready=true",
            "execution_authorized=true",
            "provenance_verified=true",
            "dispatch_allowed=true",
            "LIVE_AUTHORIZED",
            "REAL_BLOCKERS_RESOLVED"
        ]
        for phrase in dangerous_phrases:
            self.assertNotIn(phrase, self.doc_content, f"Dangerous phrase found: {phrase}")

    def test_audit_is_checked_in_evidence_only(self):
        self.assertIn("snapshot of current checked-in canonical evidence", self.doc_content)
        self.assertIn("not fresh external provider verification", self.doc_content)

    def test_checkpoint_static_only(self):
        self.assertIn("This checkpoint is strictly PREPARED/static gap-audit status only.", self.checkpoint_content)
        self.assertIn("No real live blocker is resolved.", self.checkpoint_content)
