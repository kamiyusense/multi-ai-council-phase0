"""Regression for the independent-review receipt binding finding."""
import json
import unittest
from . import test_blue_work_reconcile_prepare as fixtures


class ReceiptBindingRegression(unittest.TestCase):
    setUp = fixtures.BlueReconciliationTests.setUp
    prepare = fixtures.BlueReconciliationTests.prepare
    command = fixtures.BlueReconciliationTests.command
    review = fixtures.BlueReconciliationTests.review
    body = staticmethod(fixtures.BlueReconciliationTests.body)
    receipt = fixtures.BlueReconciliationTests.receipt
    assess = fixtures.BlueReconciliationTests.assess

    def test_receipt_same_id_wrong_pr_blocks_worker(self):
        self.assertEqual(self.assess(comments=[self.receipt(target_pr=999)]).status, "UNKNOWN")

    def test_receipt_same_id_wrong_branch_blocks_worker(self):
        self.assertEqual(self.assess(comments=[self.receipt(target_branch="unrelated")]).status, "UNKNOWN")

    def test_receipt_same_id_wrong_head_blocks_worker(self):
        self.assertEqual(self.assess(comments=[self.receipt(target_head_before="b" * 40)]).status, "UNKNOWN")

    def test_receipt_same_id_wrong_generation_blocks_worker(self):
        self.assertEqual(self.assess(comments=[self.receipt(worker_generation=2)]).status, "UNKNOWN")

    def test_result_receipt_claiming_target_write_blocks_worker(self):
        self.assertEqual(self.assess(comments=[self.receipt(target_head_after="b" * 40)]).status, "UNKNOWN")

    def test_receipt_without_submitted_command_blocks_worker(self):
        self.assertEqual(self.assess(reviews=[], comments=[self.receipt()]).status, "UNKNOWN")

    def test_receipt_same_id_wrong_pr_blocks_adapter(self):
        self.assertEqual(self.prepare(comments=[self.receipt(target_pr=999)]).status, "UNKNOWN")

    def test_receipt_same_id_wrong_generation_blocks_adapter(self):
        self.assertEqual(self.prepare(comments=[self.receipt(worker_generation=2)]).status, "UNKNOWN")

    def test_duplicate_terminal_receipts_are_uncertainty(self):
        self.assertEqual(self.assess(comments=[self.receipt(), self.receipt()]).status, "UNKNOWN")
        self.assertEqual(self.prepare(comments=[self.receipt(), self.receipt()]).status, "UNKNOWN")

    def test_terminal_receipt_requires_verification_evidence(self):
        for value in (None, [], "claimed PASS", [""], ["  "], [None], [1]):
            with self.subTest(value=value):
                row = self.receipt(verification=value)
                self.assertEqual(self.assess(comments=[row]).status, "UNKNOWN")
                self.assertEqual(self.prepare(reviews=[self.review()], comments=[row]).status, "UNKNOWN")

    def test_terminal_receipt_missing_verification_is_not_replay_authority(self):
        row = self.receipt()
        payload = json.loads(row["body"].split("\n", 1)[1])
        del payload["verification"]
        row["body"] = "[CW_BLUE_RECEIPT_V1]\n" + json.dumps(payload)
        self.assertEqual(self.assess(comments=[row]).status, "UNKNOWN")

    def test_terminal_receipt_optional_capability_boundary_is_typed(self):
        for value in ({}, [], False, 1):
            with self.subTest(value=value):
                self.assertEqual(self.assess(comments=[self.receipt(capability_boundary=value)]).status, "UNKNOWN")
