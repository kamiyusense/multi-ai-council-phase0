"""Regression checks for the reviewer v1.6.1 Jules task-ID link fix."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
EV = ROOT / "docs" / "evidence" / "claude-jules-production-starter-20261009"
OLD = EV / "routine-prompt-v1.6.CANDIDATE.txt"
NEW = EV / "routine-prompt-v1.6.1.CANDIDATE.txt"


class RoutinePromptV161Tests(unittest.TestCase):
    def setUp(self):
        self.old = OLD.read_text(encoding="utf-8")
        self.new = NEW.read_text(encoding="utf-8")

    def test_only_version_and_layer1_link_rule_changed(self):
        old_lines = self.old.splitlines()
        new_lines = self.new.splitlines()
        self.assertEqual(len(old_lines), len(new_lines))
        diffs = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
        rule = next(i for i, line in enumerate(old_lines)
                    if line.startswith('1. Find exactly one "Fixes/Closes/Resolves #N"'))
        self.assertEqual(diffs, [0, rule])
        self.assertIn("CLAUDE_CLOSED_LOOP_REVIEWER_V1.6.1", new_lines[0])
        self.assertIn("https://jules.google.com/task/N", new_lines[rule])
        self.assertIn("not a repository issue link; ignore it", new_lines[rule])
        self.assertIn("exactly one issue #N must remain", new_lines[rule])

    def test_paste_safety(self):
        raw = NEW.read_bytes().replace(b"\r\n", b"\n")       # a Windows checkout may add CR; the blob has none
        raw.decode("ascii")
        self.assertNotIn(b"\r", raw)
        self.assertNotIn(b"\t", raw)
        self.assertTrue(raw.endswith(b"\n") and not raw.endswith(b"\n\n"))


if __name__ == "__main__":
    unittest.main()
