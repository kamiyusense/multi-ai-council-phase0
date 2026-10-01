"""Regression for the independent-review receipt binding finding."""
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
