"""Checks the Japanese how-to page for filing a Claude Loop request (task CL-497)."""
from __future__ import annotations

import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "howto" / "loop-request-ja.md"
REQUIRED = ("[claude loop]", "allowed_paths", "test_commands", "AI-Agent:", "#494")
MAX_LINES = 40


class LoopRequestHowtoDocTest(unittest.TestCase):
    def test_page_exists(self) -> None:
        self.assertTrue(DOC.is_file(), f"missing {DOC}")

    def test_page_is_short(self) -> None:
        self.assertTrue(DOC.is_file(), f"missing {DOC}")
        lines = DOC.read_text(encoding="utf-8").splitlines()
        self.assertLess(len(lines), MAX_LINES)

    def test_page_mentions_required_strings(self) -> None:
        self.assertTrue(DOC.is_file(), f"missing {DOC}")
        text = DOC.read_text(encoding="utf-8")
        for needle in REQUIRED:
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
