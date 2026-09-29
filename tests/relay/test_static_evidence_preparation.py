import unittest
import re
import pathlib

class TestStaticEvidencePreparation(unittest.TestCase):
    def setUp(self):
        self.doc_path = pathlib.Path("docs/RELAY_STATIC_EVIDENCE_PREPARATION.md")
        self.assertTrue(self.doc_path.exists())
        self.content = self.doc_path.read_text(encoding="utf-8")

        self.checkpoint_path = pathlib.Path("docs/RELAY_STATIC_CHECKPOINT.md")
        self.assertTrue(self.checkpoint_path.exists())
        self.checkpoint_content = self.checkpoint_path.read_text(encoding="utf-8")

        # Parse markdown table
        self.rows = []
        lines = self.content.splitlines()
        for line in lines:
            line = line.strip()
            if line.startswith("|") and "gap_id" not in line and "---" not in line:
                cols = [col.strip() for col in line.split("|")[1:-1]]
                if len(cols) == 6:
                    self.rows.append({
                        "gap_id": cols[0],
                        "preparation_status": cols[1],
                        "evidence_refs": cols[2],
                        "observed_static_controls": cols[3],
                        "still_missing": cols[4],
                        "blocker_state": cols[5],
                    })

    def test_exactly_three_primary_gap_rows(self):
        self.assertEqual(len(self.rows), 3, "Must have exactly 3 primary gap rows")
        expected_gaps = {"common_timeout", "common_min_permissions", "common_sensitive_fanout"}
        actual_gaps = {row["gap_id"] for row in self.rows}
        self.assertEqual(expected_gaps, actual_gaps)

    def test_preparation_status_and_blocker_state(self):
        allowed_statuses = {"MISSING_STATIC_EVIDENCE", "PARTIAL_STATIC_EVIDENCE", "STATIC_CONTROL_OBSERVED"}
        for row in self.rows:
            self.assertIn(row["preparation_status"], allowed_statuses)
            self.assertEqual(row["blocker_state"], "BLOCKED_UNKNOWN")

    def test_evidence_refs_parsing_and_verification(self):
        root = pathlib.Path(".")
        for row in self.rows:
            if row["preparation_status"] == "MISSING_STATIC_EVIDENCE":
                self.assertEqual(row["evidence_refs"], "NONE")

            if row["evidence_refs"] != "NONE":
                refs = row["evidence_refs"].split("<br>")
                for ref in refs:
                    if not ref:
                        continue
                    parts = ref.split("::", 1)
                    self.assertEqual(len(parts), 2, f"Invalid evidence ref format: {ref}")
                    path_str, anchor = parts

                    self.assertFalse(path_str.startswith("/"))
                    self.assertNotIn("..", path_str)

                    target_path = root / path_str
                    self.assertTrue(target_path.exists(), f"Path does not exist: {path_str}")

                    self.assertTrue(anchor, "Literal anchor must be non-empty")
                    target_content = target_path.read_text(encoding="utf-8")
                    self.assertIn(anchor, target_content, f"Anchor '{anchor}' not found in {path_str}")

    def test_common_timeout_rules(self):
        timeout_row = next((r for r in self.rows if r["gap_id"] == "common_timeout"), None)
        self.assertIsNotNone(timeout_row)
        if timeout_row["preparation_status"] == "STATIC_CONTROL_OBSERVED":
            self.assertNotEqual(timeout_row["evidence_refs"], "NONE", "Cannot be OBSERVED without evidence")

    def test_common_min_permissions_rules(self):
        min_perms_row = next((r for r in self.rows if r["gap_id"] == "common_min_permissions"), None)
        self.assertIsNotNone(min_perms_row)
        self.assertIn("not proven merely from ProviderPolicy", min_perms_row["still_missing"])

    def test_common_sensitive_fanout_rules(self):
        fanout_row = next((r for r in self.rows if r["gap_id"] == "common_sensitive_fanout"), None)
        self.assertIsNotNone(fanout_row)
        self.assertNotIn("generic schema validation", fanout_row["observed_static_controls"].lower())

    def test_no_dangerous_result_wording(self):
        dangerous_words = [
            "RESOLVED", "VERIFIED", "READY_FOR_LIVE", "LIVE_AUTHORIZED",
            "execution_authorized=true", "dispatch_allowed=true", "live_ready=true"
        ]
        for row in self.rows:
            for val in row.values():
                for word in dangerous_words:
                    self.assertNotIn(word, val)

    def test_checkpoint_wording(self):
        self.assertIn("PREPARED/static evidence-preparation-audit status", self.checkpoint_content)
        self.assertIn("No real live blocker is resolved", self.checkpoint_content)
        self.assertIn("First live provider turn remains unauthorized", self.checkpoint_content)
