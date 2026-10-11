"""Tests for automation.command_bus.claude_jules_api_session_link (objective o2-jules-api-requests)."""
from __future__ import annotations

import unittest

from automation.command_bus.claude_jules_api_session_link import session_id_of_pr


class TestSessionIdOfPr(unittest.TestCase):
    def test_none_or_empty_input(self) -> None:
        self.assertIsNone(session_id_of_pr(None))
        self.assertIsNone(session_id_of_pr(""))
        self.assertIsNone(session_id_of_pr("   \n\t "))

    def test_valid_single_task_link(self) -> None:
        body = "https://jules.google.com/task/4724323400892625017"
        self.assertEqual(session_id_of_pr(body), "4724323400892625017")

    def test_pr_body_footer(self) -> None:
        body = (
            "Added docs/closed-loop-proof/CLP-001.md\n\n"
            "Fixes #331\n\n"
            "---\n"
            "*PR created automatically by Jules for task "
            "[5876000902096140896](https://jules.google.com/task/5876000902096140896) "
            "started by @kamiyusense*"
        )
        self.assertEqual(session_id_of_pr(body), "5876000902096140896")

    def test_repeated_same_session_id(self) -> None:
        body = (
            "Link 1: https://jules.google.com/task/12345\n"
            "Link 2: [12345](https://jules.google.com/task/12345)"
        )
        self.assertEqual(session_id_of_pr(body), "12345")

    def test_multiple_different_session_ids(self) -> None:
        body = (
            "https://jules.google.com/task/12345 "
            "https://jules.google.com/task/67890"
        )
        self.assertIsNone(session_id_of_pr(body))

    def test_non_digit_session_id(self) -> None:
        self.assertIsNone(session_id_of_pr("https://jules.google.com/task/abc"))
        self.assertIsNone(session_id_of_pr("https://jules.google.com/task/123a"))

    def test_non_https_url(self) -> None:
        self.assertIsNone(session_id_of_pr("http://jules.google.com/task/12345"))

    def test_other_host_url(self) -> None:
        self.assertIsNone(session_id_of_pr("https://example.com/task/12345"))
        self.assertIsNone(session_id_of_pr("https://jules.google.org/task/12345"))

    def test_no_task_link(self) -> None:
        self.assertIsNone(session_id_of_pr("Fixes #352"))
        self.assertIsNone(session_id_of_pr("https://github.com/kamiyusense/multi-ai-council-phase0"))

    def test_subpath_or_query_param(self) -> None:
        self.assertIsNone(session_id_of_pr("https://jules.google.com/task/12345/subpath"))
        self.assertIsNone(session_id_of_pr("https://jules.google.com/task/12345?foo=bar"))


if __name__ == "__main__":
    unittest.main()
