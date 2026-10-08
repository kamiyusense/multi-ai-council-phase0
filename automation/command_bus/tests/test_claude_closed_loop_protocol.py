"""GitHub-native closed-loop protocol: durability rules, checked against the live CLP-001 records."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.claude_closed_loop_protocol import (
    BUDGET_EXHAUSTED, CORRECTIVE, CORRECTIVE_EXISTS, NO_OP, NOT_A_TASK, PASS, TASK_BLOCKED, TASK_MARKER,
    _block, decide, read_with_retry, verify_live_receipt,
)

FIX = Path(__file__).parent / "fixtures" / "closed_loop"
PR = json.loads((FIX / "pr-332.json").read_text(encoding="utf-8"))
ISSUE = json.loads((FIX / "issue-331.json").read_text(encoding="utf-8"))
COMMENTS = [c["body"] for c in json.loads((FIX / "issue-331-comments.json").read_text(encoding="utf-8"))]
FILES = json.loads((FIX / "pr-332-files.json").read_text(encoding="utf-8"))
CONTENT = {"docs/closed-loop-proof/CLP-001.md": (FIX / "CLP-001.md").read_text(encoding="utf-8")}
PATH1 = "docs/closed-loop-proof/CLP-001.md"


def task_of(body):
    return _block(body, TASK_MARKER)[0]


def with_task(task, body=ISSUE["body"]):
    head, rest = body.split(TASK_MARKER, 1)
    tail = rest.split("-->", 1)[1]
    return f"{head}{TASK_MARKER}\n{json.dumps(task)}\n-->{tail}"


def two_phase_task():
    task = copy.deepcopy(task_of(ISSUE["body"]))
    final = list(task["required_lines"]) + ["- review_phase: CORRECTED"]
    task.update(first_submission_lines=final[:-1] + ["- review_phase: NEEDS_CORRECTION"], required_lines=final,
                correlation_id="clp-001-twophase", next_task=None)
    return task


def content(lines):
    return {PATH1: lines[0] + "\n\n" + "\n".join(lines[1:]) + "\n"}


class LiveRecordTests(unittest.TestCase):
    """The real Issue #331 / PR #332 state, as read from GitHub."""

    def test_first_wake_state_decides_pass_like_the_routine_did(self):
        decision = decide(pr=PR, issue_body=ISSUE["body"], issue_comments=[], pr_comments=[], files=FILES,
                          contents=CONTENT)
        self.assertEqual((decision.outcome, decision.phase, decision.round), (PASS, "FINAL", 1))
        self.assertEqual(decision.writes, ("next_issue", "receipt"))
        receipt = [r for c in COMMENTS if "claude-closed-loop-receipt v1" in c
                   for r in _block(c, "<!-- claude-closed-loop-receipt v1")][0]
        self.assertEqual(verify_live_receipt(receipt, decision, pr=PR), [])

    def test_replay_and_restart_on_the_live_state_are_no_op(self):
        # A fresh process reading today's issue (receipt present) never reviews again.
        for head in (PR["head"], "2550e2ba426710ea5da89cf4a1c9ff2b2ad2a19b"):  # opened, then Jules' empty commit
            with self.subTest(head=head):
                decision = decide(pr=dict(PR, head=head), issue_body=ISSUE["body"], issue_comments=COMMENTS,
                                  pr_comments=[], files=FILES, contents=CONTENT)
                self.assertEqual((decision.outcome, decision.writes), (NO_OP, ()))


class LiveCorrectiveRoundTests(unittest.TestCase):
    """The real CLP-002 round trip: Issue #333, PR #334 (f7444ee -> e1bf653)."""

    def setUp(self):
        load = lambda name: json.loads((FIX / name).read_text(encoding="utf-8"))
        self.pr, self.issue = load("pr-334.json"), load("issue-333.json")
        self.issue_comments = [c["body"] for c in load("issue-333-comments.json")]
        self.pr_comments = [c["body"] for c in load("pr-334-comments.json")]
        self.files = load("pr-334-files.json")
        self.path = "docs/closed-loop-proof/CLP-002.md"
        self.first = {self.path: (FIX / "CLP-002-first.md").read_text(encoding="utf-8")}
        self.fixed = {self.path: (FIX / "CLP-002-corrected.md").read_text(encoding="utf-8")}
        receipts = [c for c in self.issue_comments if "claude-closed-loop-receipt v1" in c]
        self.r1, self.r2 = receipts

    def test_live_round_one_receipt_with_trailing_debris_is_still_read_exactly(self):
        [r1] = _block(self.r1, "<!-- claude-closed-loop-receipt v1")
        self.assertEqual((r1["verdict"], r1["phase"], r1["round"]), ("FAIL", "NEEDS_CORRECTION", 1))
        with self.assertRaises(ValueError):
            _block("<!-- claude-closed-loop-receipt v1\n``{\"a\":1}\n-->", "<!-- claude-closed-loop-receipt v1")

    def test_opened_state_decides_needs_correction_and_one_corrective(self):
        pr = dict(self.pr, head=self.pr["first_head"])
        d = decide(pr=pr, issue_body=self.issue["body"], issue_comments=[], pr_comments=[], files=self.files,
                   contents=self.first)
        self.assertEqual((d.outcome, d.phase, d.round, d.writes),
                         (CORRECTIVE, "NEEDS_CORRECTION", 1, ("corrective", "receipt")))
        [r1] = _block(self.r1, "<!-- claude-closed-loop-receipt v1")
        self.assertEqual(verify_live_receipt(r1, d, pr=pr), [])

    def test_synchronize_state_decides_pass_in_round_two(self):
        d = decide(pr=self.pr, issue_body=self.issue["body"], issue_comments=[self.r1],
                   pr_comments=self.pr_comments, files=self.files, contents=self.fixed)
        self.assertEqual((d.outcome, d.phase, d.round), (PASS, "FINAL", 2))
        [r2] = _block(self.r2, "<!-- claude-closed-loop-receipt v1")
        self.assertEqual(verify_live_receipt(r2, d, pr=self.pr), [])

    def test_replaying_either_event_on_the_final_state_is_no_op(self):
        for head, contents in ((self.pr["first_head"], self.first), (self.pr["head"], self.fixed)):
            with self.subTest(head=head[:7]):
                d = decide(pr=dict(self.pr, head=head), issue_body=self.issue["body"],
                           issue_comments=self.issue_comments, pr_comments=self.pr_comments, files=self.files,
                           contents=contents)
                self.assertEqual((d.outcome, d.writes), (NO_OP, ()))

    def test_lost_receipt_after_posted_corrective_does_not_post_a_second_corrective(self):
        # Restart between the corrective and the receipt: the corrective marker on the PR is found.
        pr = dict(self.pr, head=self.pr["first_head"])
        d = decide(pr=pr, issue_body=self.issue["body"], issue_comments=[], pr_comments=self.pr_comments,
                   files=self.files, contents=self.first)
        self.assertEqual((d.outcome, d.writes), (CORRECTIVE_EXISTS, ("receipt",)))


class UnrelatedAndMalformedTests(unittest.TestCase):
    def test_unrelated_pr_writes_nothing(self):
        for body in ("Docs only. No issue link.", "Fixes #330 and Fixes #331", ""):
            with self.subTest(body=body):
                d = decide(pr=dict(PR, body=body), issue_body=ISSUE["body"], issue_comments=[], pr_comments=[],
                           files=FILES, contents=CONTENT)
                self.assertEqual((d.outcome, d.writes), (NOT_A_TASK, ()))
        d = decide(pr=PR, issue_body="a normal issue without a task block", issue_comments=[], pr_comments=[],
                   files=FILES, contents=CONTENT)
        self.assertEqual((d.outcome, d.writes), (NOT_A_TASK, ()))

    def test_bad_metadata_blocks_the_task_without_any_jules_instruction(self):
        base = task_of(ISSUE["body"])
        cases = {
            "missing loop": {k: v for k, v in base.items() if k != "loop_id"},
            "correlation mismatch": dict(base, correlation_id="clp-999-x"),
            "wrong generation type": dict(base, generation="1"),
            "generation zero": dict(base, generation=0),
            "wrong expected branch": dict(base, expected_target_branch="release"),
            "bad expected head": dict(base, expected_target_head="8fbbef9"),
            "no allowed paths": dict(base, allowed_paths=[]),
            "wrong profile": dict(base, profile="SOMETHING_ELSE"),
        }
        for name, task in cases.items():
            with self.subTest(name=name):
                d = decide(pr=PR, issue_body=with_task(task), issue_comments=[], pr_comments=[], files=FILES,
                           contents=CONTENT)
                self.assertEqual(d.outcome, TASK_BLOCKED)
                self.assertEqual(d.writes, ("receipt",))
                self.assertNotIn("corrective", d.writes)

    def test_unparseable_task_block_is_blocked(self):
        body = ISSUE["body"].split(TASK_MARKER)[0] + TASK_MARKER + "\n{not json\n-->"
        d = decide(pr=PR, issue_body=body, issue_comments=[], pr_comments=[], files=FILES, contents=CONTENT)
        self.assertEqual((d.outcome, d.writes), (TASK_BLOCKED, ("receipt",)))

    def test_broken_durable_receipt_is_never_written_over(self):
        broken = "<!-- claude-closed-loop-receipt v1\n{broken\n-->"
        d = decide(pr=PR, issue_body=ISSUE["body"], issue_comments=[broken], pr_comments=[], files=FILES,
                   contents=CONTENT)
        self.assertEqual((d.outcome, d.writes), (TASK_BLOCKED, ()))


class CorrectiveRoundTests(unittest.TestCase):
    def setUp(self):
        self.task = two_phase_task()
        self.body = with_task(self.task)

    def receipt(self, head, verdict, rnd):
        return ("x\n<!-- claude-closed-loop-receipt v1\n" + json.dumps(
            {"correlation_id": self.task["correlation_id"], "pr_head_sha": head, "verdict": verdict, "round": rnd})
            + "\n-->")

    def corrective(self, head):
        return ("@jules fix\n<!-- claude-closed-loop-corrective v1 " + json.dumps(
            {"correlation_id": self.task["correlation_id"], "pr_head_sha": head, "round": 1}) + " -->")

    def test_planned_first_submission_is_needs_correction_and_asks_once(self):
        first = content(self.task["first_submission_lines"])
        d = decide(pr=PR, issue_body=self.body, issue_comments=[], pr_comments=[], files=FILES, contents=first)
        self.assertEqual((d.outcome, d.phase, d.round), (CORRECTIVE, "NEEDS_CORRECTION", 1))
        self.assertEqual(d.writes, ("corrective", "receipt"))
        self.assertTrue(d.checks["required_lines"].startswith("FAIL"))

    def test_duplicate_corrective_for_the_same_head_is_not_posted_again(self):
        first = content(self.task["first_submission_lines"])
        d = decide(pr=PR, issue_body=self.body, issue_comments=[], pr_comments=[self.corrective(PR["head"])],
                   files=FILES, contents=first)
        self.assertEqual((d.outcome, d.writes), (CORRECTIVE_EXISTS, ("receipt",)))
        # and once the receipt exists, the same event is a NO-OP
        d = decide(pr=PR, issue_body=self.body, issue_comments=[self.receipt(PR["head"], "FAIL", 1)],
                   pr_comments=[self.corrective(PR["head"])], files=FILES, contents=first)
        self.assertEqual((d.outcome, d.writes), (NO_OP, ()))

    def test_corrected_push_passes_in_round_two_and_replay_is_no_op(self):
        fixed = content(self.task["required_lines"])
        state = dict(issue_comments=[self.receipt(PR["head"], "FAIL", 1)], pr_comments=[self.corrective(PR["head"])])
        d = decide(pr=dict(PR, head="b" * 40), issue_body=self.body, files=FILES, contents=fixed, **state)
        self.assertEqual((d.outcome, d.phase, d.round, d.writes), (PASS, "FINAL", 2, ("receipt",)))
        state["issue_comments"].append(self.receipt("b" * 40, "PASS", 2))
        for head in ("b" * 40, "c" * 40):  # the same event again, then an empty/extra commit
            d = decide(pr=dict(PR, head=head), issue_body=self.body, files=FILES, contents=fixed, **state)
            self.assertEqual((d.outcome, d.writes), (NO_OP, ()))

    def test_empty_commit_after_a_fail_is_no_op(self):
        first = content(self.task["first_submission_lines"])
        d = decide(pr=dict(PR, head="d" * 40), issue_body=self.body,
                   issue_comments=[self.receipt(PR["head"], "FAIL", 1)], pr_comments=[self.corrective(PR["head"])],
                   files=FILES, contents=first, head_changes_files=False)
        self.assertEqual((d.outcome, d.writes), (NO_OP, ()))

    def test_unexpected_wrong_content_is_a_plain_fail_not_needs_correction(self):
        wrong = content(self.task["required_lines"][:-1] + ["- review_phase: SOMETHING_ELSE"])
        d = decide(pr=PR, issue_body=self.body, issue_comments=[], pr_comments=[], files=FILES, contents=wrong)
        self.assertEqual((d.outcome, d.phase), (CORRECTIVE, "FINAL"))

    def test_corrective_budget_is_finite(self):
        first = content(self.task["first_submission_lines"])
        fails = [self.receipt(h * 40, "FAIL", n) for n, h in enumerate("ef", start=1)]
        d = decide(pr=dict(PR, head="9" * 40), issue_body=self.body, issue_comments=fails, pr_comments=[],
                   files=FILES, contents=first)
        self.assertEqual((d.outcome, d.writes), (BUDGET_EXHAUSTED, ("receipt",)))

    def test_extra_file_fails_paths(self):
        files = FILES + [{"filename": "README.md", "status": "modified"}]
        d = decide(pr=PR, issue_body=self.body, issue_comments=[], pr_comments=[], files=files,
                   contents=content(self.task["required_lines"]))
        self.assertTrue(d.checks["paths_exact"].startswith("FAIL"))
        self.assertNotEqual(d.outcome, PASS)


class StaleHeadAndIsolationTests(unittest.TestCase):
    def test_moved_main_is_recorded_not_fatal(self):
        # expected_target_head is metadata only; review proceeds against the exact PR head.
        task = dict(task_of(ISSUE["body"]), expected_target_head="0" * 40)
        d = decide(pr=PR, issue_body=with_task(task), issue_comments=[], pr_comments=[], files=FILES,
                   contents=CONTENT)
        self.assertEqual(d.outcome, PASS)

    def test_one_blocked_task_does_not_affect_another(self):
        bad = dict(task_of(ISSUE["body"]), expected_target_branch="release")
        good_pr, bad_pr = PR, dict(PR, body="Fixes #400")
        blocked = decide(pr=bad_pr, issue_body=with_task(bad), issue_comments=[], pr_comments=[], files=FILES,
                         contents=CONTENT)
        fine = decide(pr=good_pr, issue_body=ISSUE["body"], issue_comments=[], pr_comments=[], files=FILES,
                      contents=CONTENT)
        self.assertEqual((blocked.outcome, fine.outcome), (TASK_BLOCKED, PASS))


class TransientReadTests(unittest.TestCase):
    def test_read_is_retried_with_bounded_backoff(self):
        calls, sleeps = [], []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise TimeoutError("github slow")
            return "ok"
        self.assertEqual(read_with_retry(flaky, sleep=sleeps.append), "ok")
        self.assertEqual((len(calls), sleeps), (3, [5, 30]))

    def test_retries_stop_and_non_transient_errors_are_not_retried(self):
        calls = []

        def down():
            calls.append(1)
            raise OSError("down")
        with self.assertRaises(OSError):
            read_with_retry(down, sleep=lambda s: None)
        self.assertEqual(len(calls), 3)
        calls.clear()

        def bug():
            calls.append(1)
            raise KeyError("x")
        with self.assertRaises(KeyError):
            read_with_retry(bug, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
