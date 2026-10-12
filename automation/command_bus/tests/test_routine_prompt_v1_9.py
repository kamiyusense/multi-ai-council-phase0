"""Reviewer v1.9 candidate: v1.8 plus one LAYER 1 fix seen in LIVE prod-c1 on 2026-10-12.

PR #381 (task #380) carried "Fixes #365" next to "Fixes #380". #365 is the previous task issue: it still holds a
closed-loop task block but is CLOSED, so v1.8 found two task issues and stopped for five hours.  v1.9 counts only
OPEN referenced issues that hold a task block; a running task's issue is always open.
"""
from pathlib import Path
import unittest

from automation.command_bus.claude_closed_loop_protocol import linked_issue

EV = Path(__file__).resolve().parents[3] / "docs" / "evidence" / "claude-jules-production-starter-20261009"
OLD = EV / "routine-prompt-v1.8.CANDIDATE.txt"
NEW = EV / "routine-prompt-v1.9.CANDIDATE.txt"


class RoutinePromptV19Tests(unittest.TestCase):
    def setUp(self):
        self.old = OLD.read_text(encoding="utf-8").splitlines()
        self.new = NEW.read_text(encoding="utf-8").splitlines()

    def test_only_the_version_and_the_link_rule_changed(self):
        self.assertEqual(len(self.old), len(self.new))
        diffs = [i for i, (a, b) in enumerate(zip(self.old, self.new)) if a != b]
        rule = next(i for i, l in enumerate(self.old) if l.startswith('1. Find all "Fixes/Closes/Resolves #N"'))
        self.assertEqual(diffs, [0, rule])
        self.assertIn("CLAUDE_CLOSED_LOOP_REVIEWER_V1.9", self.new[0])
        self.assertIn("keep only the OPEN issues that contain exactly one", self.new[rule])
        self.assertIn("the previous, already closed task issue", self.new[rule])
        self.assertIn("Exactly one such issue must remain", self.new[rule])

    def test_paste_safety(self):
        raw = NEW.read_bytes().replace(b"\r\n", b"\n")       # a Windows checkout may add CR; the blob has none
        raw.decode("ascii")
        self.assertNotIn(b"\t", raw)
        self.assertTrue(raw.endswith(b"\n") and not raw.endswith(b"\n\n"))

    def test_pr_381_body_resolves_to_the_open_task_issue(self):
        body = ("Fixes #365\n\n- Manifest rebuild now uses .as_posix()\n\nFixes #380\n\n---\n*PR created automatically by "
                "Jules for task [2304909662256961218](https://jules.google.com/task/2304909662256961218)*")
        holds_task = {365, 380}
        is_open = {380}
        self.assertIsNone(linked_issue(body, is_task=lambda n: n in holds_task))                # v1.8: stuck
        self.assertEqual(linked_issue(body, is_task=lambda n: n in holds_task and n in is_open), 380)


if __name__ == "__main__":
    unittest.main()
