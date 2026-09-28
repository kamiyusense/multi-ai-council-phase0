from __future__ import annotations

import copy
import unittest

from automation.command_bus.runtime_transition_jules import prepare_jules_evidence
from automation.command_bus.tests.test_loop_owner import first_event


class JulesStaticAdapterTests(unittest.TestCase):
    def setUp(self):
        self.event = first_event()
        self.receipt = {
            "retry_count": 0, "fallback_used": False,
            "evidence_refs": ["workflow-run:123", "jules-session:abc", "result-commit:" + "a" * 40],
        }
        self.publication = {
            "repository": self.event["expected_repo"], "pr_number": self.event["expected_pr"],
            "resulting_commit": self.event["expected_target_head"], "result_tree": "b" * 40,
            "tests_passed": True, "compileall_passed": True, "diff_check_passed": True,
        }

    def prepare(self):
        return prepare_jules_evidence(
            self.event, jules_receipt=self.receipt, publication=self.publication,
            observed_at="2026-09-27T09:30:00+00:00", provider_readback="provider:jules-123",
        )

    def test_prepares_only_canonical_evidence_without_owner_inference(self):
        document = self.prepare()
        self.assertEqual(document["external_refs"], self.receipt["evidence_refs"])
        self.assertEqual(document["expected_target_head"], self.event["expected_target_head"])
        self.assertEqual(document["test_results"][0]["status"], "PASS")

    def test_mismatched_publication_and_unsafe_receipt_rejected(self):
        self.publication["resulting_commit"] = "c" * 40
        with self.assertRaises(ValueError):
            self.prepare()
        self.publication["resulting_commit"] = self.event["expected_target_head"]
        self.receipt["retry_count"] = 1
        with self.assertRaises(ValueError):
            self.prepare()
        self.receipt["retry_count"] = 0
        self.receipt["evidence_refs"] = ["https://secret.example/token"]
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
