"""Reviewer v1.7 candidate: v1.6.1 plus two fixes seen in LIVE prod-c1 on 2026-10-11.

* PR #366: Jules added a stray "Fixes #358" (a merged PR) next to "Fixes #365"; v1.6.1 stopped as "not a
  closed-loop task PR".  v1.7 counts only referenced issues that hold a closed-loop task block.
* A Run now wake reviewed the pending PR to PASS but did not start the next task (LAYER 4 had already run).  v1.7
  runs LAYER 4 once more after a recovery-wake review that posted a receipt.
"""
from pathlib import Path
import unittest

from automation.command_bus.claude_closed_loop_protocol import linked_issue

ROOT = Path(__file__).resolve().parents[3]
EV = ROOT / "docs" / "evidence" / "claude-jules-production-starter-20261009"
OLD = EV / "routine-prompt-v1.6.1.CANDIDATE.txt"
NEW = EV / "routine-prompt-v1.7.CANDIDATE.txt"


class RoutinePromptV17Tests(unittest.TestCase):
    def setUp(self):
        self.old = OLD.read_text(encoding="utf-8").splitlines()
        self.new = NEW.read_text(encoding="utf-8").splitlines()

    def line(self, lines, prefix):
        found = [i for i, l in enumerate(lines) if l.startswith(prefix)]
        self.assertEqual(len(found), 1, prefix)
        return found[0]

    def test_only_the_declared_lines_changed(self):
        self.assertEqual(len(self.old), len(self.new))
        diffs = [i for i, (a, b) in enumerate(zip(self.old, self.new)) if a != b]
        expected = [0, self.line(self.old, "- Any other wake"), self.line(self.old, "1. Find all"),
                    self.line(self.old, "2. Run exactly this"), self.line(self.old, "5. Never re-run it")]
        self.assertEqual(diffs, sorted(expected))
        self.assertIn("CLAUDE_CLOSED_LOOP_REVIEWER_V1.7", self.new[0])

    def test_link_rule_keeps_only_task_issues(self):
        rule = self.new[self.line(self.new, "1. Find all")]
        self.assertIn("keep only the issues that contain exactly one `<!-- claude-closed-loop-task v1` block", rule)
        self.assertIn("Exactly one such issue must remain", rule)
        self.assertIn("never reviewed and never written to", rule)

    def test_recovery_wake_runs_layer4_at_most_twice(self):
        wake = self.new[self.line(self.new, "- Any other wake")]
        self.assertIn("if that review posted a receipt, run LAYER 4 one more time (the second and last", wake)
        self.assertIn("Never add or change a schedule or trigger yourself.", wake)
        self.assertIn("twice only in the recovery case", self.new[self.line(self.new, "2. Run exactly this")])
        self.assertIn("never retry after an error or timeout", self.new[self.line(self.new, "5. Never run it")])

    def test_paste_safety(self):
        raw = NEW.read_bytes().replace(b"\r\n", b"\n")       # a Windows checkout may add CR; the blob has none
        raw.decode("ascii")
        self.assertNotIn(b"\t", raw)
        self.assertTrue(raw.endswith(b"\n") and not raw.endswith(b"\n\n"))


class LinkedIssueV17Tests(unittest.TestCase):
    def test_pr_366_body_resolves_to_the_task_issue(self):
        body = ("Add session_id_of_pr ...\n\nFixes #358\n\nFixes #365\n\n---\n*PR created automatically by Jules for "
                "task [3777403340815424401](https://jules.google.com/task/3777403340815424401)*")
        self.assertIsNone(linked_issue(body))                              # v1.6.1 behaviour
        self.assertEqual(linked_issue(body, is_task=lambda n: n == 365), 365)

    def test_two_task_issues_or_none_stay_ambiguous(self):
        body = "Fixes #330 and Fixes #331"
        self.assertIsNone(linked_issue(body, is_task=lambda n: True))
        self.assertIsNone(linked_issue(body, is_task=lambda n: False))


if __name__ == "__main__":
    unittest.main()
