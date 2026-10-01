import unittest
from automation.command_bus.signal_observed_github import map_github_workflow_run_to_observed_check

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
