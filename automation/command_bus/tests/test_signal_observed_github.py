import unittest
from automation.command_bus.signal_observed_github import (
    map_github_workflow_run_to_observed_check,
    map_exact_head_github_run_to_observed_check,
    map_result_pr_head_to_observed_state
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

    def test_map_exact_head_valid_match(self):
        h1 = "a" * 40
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, h1, "queued", None), "VERIFYING")
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, h1, "in_progress", None), "VERIFYING")
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, h1, "completed", "success"), "PASS")
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, h1, "completed", "failure"), "FAIL")

    def test_map_exact_head_mismatch(self):
        h1 = "a" * 40
        h2 = "b" * 40
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, h2, "completed", "success"), "UNKNOWN")

    def test_map_exact_head_invalid_heads(self):
        h1 = "a" * 40
        self.assertEqual(map_exact_head_github_run_to_observed_check(None, h1, "completed", "success"), "UNKNOWN")
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, None, "completed", "success"), "UNKNOWN")
        self.assertEqual(map_exact_head_github_run_to_observed_check(123, h1, "completed", "success"), "UNKNOWN")
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, 123, "completed", "success"), "UNKNOWN")
        self.assertEqual(map_exact_head_github_run_to_observed_check("short", h1, "completed", "success"), "UNKNOWN")
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, "short", "completed", "success"), "UNKNOWN")
        self.assertEqual(map_exact_head_github_run_to_observed_check("A" * 40, "A" * 40, "completed", "success"), "UNKNOWN")

    def test_map_exact_head_unsupported_status(self):
        h1 = "a" * 40
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, h1, "completed", "cancelled"), "UNKNOWN")
        self.assertEqual(map_exact_head_github_run_to_observed_check(h1, h1, "unknown_status", None), "UNKNOWN")

    def test_map_result_pr_head_valid(self):
        h1 = "a" * 40
        self.assertEqual(map_result_pr_head_to_observed_state(h1), "PR_READY")
        self.assertEqual(map_result_pr_head_to_observed_state("1234567890abcdef1234567890abcdef12345678"), "PR_READY")

    def test_map_result_pr_head_none(self):
        self.assertEqual(map_result_pr_head_to_observed_state(None), "NO_RESULT_PR")

    def test_map_result_pr_head_invalid(self):
        self.assertEqual(map_result_pr_head_to_observed_state(""), "UNKNOWN")
        self.assertEqual(map_result_pr_head_to_observed_state("short"), "UNKNOWN")
        self.assertEqual(map_result_pr_head_to_observed_state("a" * 39), "UNKNOWN")
        self.assertEqual(map_result_pr_head_to_observed_state("a" * 41), "UNKNOWN")
        self.assertEqual(map_result_pr_head_to_observed_state("A" * 40), "UNKNOWN") # Uppercase
        self.assertEqual(map_result_pr_head_to_observed_state("g" * 40), "UNKNOWN") # Non-hex
        self.assertEqual(map_result_pr_head_to_observed_state(123), "UNKNOWN")
        self.assertEqual(map_result_pr_head_to_observed_state({}), "UNKNOWN")
