import unittest
from automation.command_bus.signal_observed_github import (
    map_github_workflow_run_to_observed_check,
    bind_exact_pr_head_to_observed_check
)

class TestSignalObservedGithub(unittest.TestCase):
    def test_positive_mappings(self):
        self.assertEqual(map_github_workflow_run_to_observed_check("queued", None), "VERIFYING")
        self.assertEqual(map_github_workflow_run_to_observed_check("in_progress", None), "VERIFYING")
        self.assertEqual(map_github_workflow_run_to_observed_check("completed", "success"), "PASS")
        self.assertEqual(map_github_workflow_run_to_observed_check("completed", "failure"), "FAIL")

    def test_unknown_completed_conclusions(self):
        self.assertEqual(map_github_workflow_run_to_observed_check("completed", "cancelled"), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check("completed", "skipped"), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check("completed", None), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check("completed", 123), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check("completed", ""), "UNKNOWN")

    def test_unsupported_status(self):
        self.assertEqual(map_github_workflow_run_to_observed_check(None, None), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check("", None), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check("QUEUED", None), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check(123, None), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check("unknown_status", None), "UNKNOWN")

    def test_nonterminal_with_conclusion(self):
        self.assertEqual(map_github_workflow_run_to_observed_check("queued", "success"), "UNKNOWN")
        self.assertEqual(map_github_workflow_run_to_observed_check("in_progress", "failure"), "UNKNOWN")

class TestBindExactPrHead(unittest.TestCase):
    def setUp(self):
        self.valid_sha = "7e8af2d0a4c5b90594eb788e015d72db1ccd86ac"
        self.invalid_case_sha = "7E8AF2D0A4C5B90594EB788E015D72DB1CCD86AC"
        self.invalid_len_sha = "7e8af2d0a4c5"
        self.other_sha = "7e8af2d0a4c5b90594eb788e015d72db1ccd86ad"

    def test_exact_valid_sha_and_states(self):
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, self.valid_sha, "PASS"), "PASS")
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, self.valid_sha, "FAIL"), "FAIL")
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, self.valid_sha, "VERIFYING"), "VERIFYING")
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, self.valid_sha, "UNKNOWN"), "UNKNOWN")

    def test_mismatched_valid_shas(self):
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, self.other_sha, "PASS"), "UNKNOWN")

    def test_missing_malformed_shas(self):
        self.assertEqual(bind_exact_pr_head_to_observed_check(None, self.valid_sha, "PASS"), "UNKNOWN")
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, None, "PASS"), "UNKNOWN")
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.invalid_len_sha, self.invalid_len_sha, "PASS"), "UNKNOWN")
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.invalid_case_sha, self.invalid_case_sha, "PASS"), "UNKNOWN")
        self.assertEqual(bind_exact_pr_head_to_observed_check(12345, 12345, "PASS"), "UNKNOWN")

    def test_unsupported_check_state(self):
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, self.valid_sha, "BOGUS"), "UNKNOWN")
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, self.valid_sha, None), "UNKNOWN")
        self.assertEqual(bind_exact_pr_head_to_observed_check(self.valid_sha, self.valid_sha, 123), "UNKNOWN")
