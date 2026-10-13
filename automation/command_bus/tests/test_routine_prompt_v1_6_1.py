"""Regression checks for the reviewer v1.6.1 Jules task-ID link fix."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
EV = ROOT / "docs" / "evidence" / "claude-jules-production-starter-20261009"
OLD = EV / "routine-prompt-v1.6.CANDIDATE.txt"
NEW = EV / "routine-prompt-v1.6.1.CANDIDATE.txt"


def check_paste_safety(raw: bytes) -> bytes:
    normalized = raw.replace(b"\r\n", b"\n")
    normalized.decode("ascii")
    if b"\r" in normalized:
        raise AssertionError("Carriage return found in bytes")
    if b"\t" in normalized:
        raise AssertionError("Tab found in bytes")
    if not (normalized.endswith(b"\n") and not normalized.endswith(b"\n\n")):
        raise AssertionError("Invalid trailing newline structure")
    return normalized


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
        raw = NEW.read_bytes()
        normalized = check_paste_safety(raw)
        raw_normalized = raw.replace(b"\r\n", b"\n")
        raw_normalized.decode("ascii")
        self.assertNotIn(b"\r", raw_normalized)
        self.assertNotIn(b"\t", raw_normalized)
        self.assertTrue(raw_normalized.endswith(b"\n") and not raw_normalized.endswith(b"\n\n"))
        self.assertEqual(normalized, raw_normalized)

    def test_paste_safety_crlf_normalization_and_lone_cr_rejection(self):
        self.assertEqual(check_paste_safety(b"a\r\nb\n"), b"a\nb\n")
        with self.assertRaises(AssertionError):
            check_paste_safety(b"a\rb\n")


if __name__ == "__main__":
    unittest.main()
