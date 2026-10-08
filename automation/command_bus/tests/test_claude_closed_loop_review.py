"""Two-layer reviewer: deterministic guard + Claude semantic review, combined by fixed precedence rules."""
from __future__ import annotations

import json
import unittest

from automation.command_bus.claude_closed_loop_protocol import CORRECTIVE_MARKER, RECEIPT_MARKER, TASK_MARKER
from automation.command_bus.claude_closed_loop_review import (
    BLOCKED, NEEDS_CORRECTION, NO_OP, NOT_A_TASK, PASS, PROCEED, TASK_BLOCKED, build_corrective, combine,
    finding_fingerprint, parse_receipt, precheck, render_receipt, validate_receipt, validate_semantic_review,
)

HEAD1, HEAD2, HEAD3 = "1" * 40, "2" * 40, "3" * 40
TREE1, TREE2 = "a" * 40, "b" * 40
SRC, TEST = "automation/command_bus/example.py", "automation/command_bus/tests/test_example.py"
TASK = {
    "profile": "CLAUDE_CLOSED_LOOP_TASK_V1", "kind": "code_change", "task_id": "grd-001",
    "loop_id": "claude-jules-github-native-001", "correlation_id": "grd-001-8fbbef9", "generation": 1,
    "expected_target_branch": "main", "expected_target_head": "8fbbef941732219e4ad43ce0d32e22922275d040",
    "allowed_paths": [{"path": SRC, "op": "MODIFY"}, {"path": TEST, "op": "MODIFY"}],
    "acceptance_criteria": ["the bug is fixed for empty input", "a regression test covers empty input"],
    "test_commands": ["python -m unittest automation.command_bus.tests.test_example"],
    "max_corrective_rounds": 2, "live_slot": 9,
    "next_task": {"title": "[next] prepared", "body": "prepared"},
}
FILES = [{"filename": SRC, "status": "modified"}, {"filename": TEST, "status": "modified"}]


def issue_body(task=TASK):
    return f"task\n\n{TASK_MARKER}\n{json.dumps(task)}\n-->\n"


def pr(head=HEAD1, body="Fixes #400", base="main"):
    return {"number": 401, "head": head, "base": base, "body": body}


def receipt(head, tree, verdict, rnd, findings=()):
    record = {"profile": "CLAUDE_CLOSED_LOOP_REVIEW_V2", "task_id": TASK["task_id"], "loop_id": TASK["loop_id"],
              "correlation_id": TASK["correlation_id"], "generation": 1, "round": rnd, "phase": "FINAL", "pr": 401,
              "pr_head_sha": head, "pr_head_tree": tree, "expected_target_head": TASK["expected_target_head"],
              "observed_base_head": TASK["expected_target_head"], "verdict": verdict,
              "decision": "ADOPT_RECORDED" if verdict == PASS else "CORRECTIVE_REQUESTED", "findings": list(findings),
              "criteria": [{"criterion": c, "met": verdict == PASS, "evidence": "diff"} for c in TASK["acceptance_criteria"]],
              "escalate_root_cause": False, "tests": {"result": "PASS"}, "live_slot": 9, "corrective_comment": None,
              "next_issue": None, "wake_event": "pull_request.opened", "reviewed_at": "2026-10-09T00:00:00Z"}
    return render_receipt(summary="review", record=record)


def corrective_comment(head):
    return f"@jules fix\n{CORRECTIVE_MARKER} {json.dumps({'correlation_id': TASK['correlation_id'], 'pr_head_sha': head, 'round': 1})} -->"


def semantic(verdict=PASS, met=(True, True), findings=(), tests="PASS", resolved=(), blocked_reason=None):
    return {"profile": "CLAUDE_SEMANTIC_REVIEW_V1", "verdict": verdict, "summary": "s",
            "criteria": [{"criterion": c, "met": m, "evidence": "read diff"} for c, m in
                         zip(TASK["acceptance_criteria"], met)],
            "findings": list(findings), "previous_findings_resolved": list(resolved),
            "tests": {"result": tests, "commands_run": TASK["test_commands"], "evidence": "log"},
            "blocked_reason": blocked_reason}


ROOT_FINDING = {"category": "root_cause_not_fixed", "severity": "major", "scope_paths": [SRC],
                "what_is_wrong": "empty input still raises IndexError", "expected_behavior": "empty input returns []",
                "reproduction": "example([])", "regression_test": "test_empty_input", "pass_condition": "returns []"}


def check(**kw):
    base = dict(pr=pr(), issue_body=issue_body(), issue_comments=[], pr_comments=[], files=FILES, head_tree=TREE1)
    base.update(kw)
    return precheck(**base)


class GuardTests(unittest.TestCase):
    def test_unrelated_pr_and_bad_metadata(self):
        self.assertEqual(check(pr=pr(body="no link")).status, NOT_A_TASK)
        self.assertEqual(check(issue_body="plain issue").status, NOT_A_TASK)
        for bad in ({"kind": "magic"}, {"acceptance_criteria": []}, {"test_commands": []},
                    {"correlation_id": "zzz"}, {"generation": 0}, {"expected_target_branch": "dev"}):
            with self.subTest(bad=bad):
                self.assertEqual(check(issue_body=issue_body(dict(TASK, **bad))).status, TASK_BLOCKED)

    def test_duplicate_opened_and_synchronize_events_are_no_op(self):
        reviewed = [receipt(HEAD1, TREE1, NEEDS_CORRECTION, 1)]
        self.assertEqual(check(issue_comments=reviewed).status, NO_OP)                      # same head again
        self.assertEqual(check(pr=pr(HEAD2), issue_comments=reviewed).status, NO_OP)          # same tree, new commit
        self.assertEqual(check(pr=pr(HEAD2), issue_comments=reviewed, head_tree=TREE2,
                               head_changes_files=False).status, NO_OP)                     # empty commit
        passed = [receipt(HEAD1, TREE1, PASS, 1)]
        self.assertEqual(check(pr=pr(HEAD3), head_tree=TREE2, issue_comments=passed).status, NO_OP)  # replay

    def test_malformed_review_record_is_never_written_over(self):
        broken = f"x\n{RECEIPT_MARKER}\n{{broken\n-->"
        result = check(issue_comments=[broken])
        self.assertEqual(result.status, NO_OP)
        self.assertIn("unreadable", result.reason)

    def test_unauthorized_second_file_is_a_guard_finding(self):
        result = check(files=FILES + [{"filename": "README.md", "status": "modified"}])
        self.assertEqual(result.status, PROCEED)
        self.assertEqual([f["scope_paths"] for f in result.guard_findings], [["README.md"]])

    def test_round_counts_previous_failures_and_carries_their_findings(self):
        result = check(pr=pr(HEAD2), head_tree=TREE2,
                       issue_comments=[receipt(HEAD1, TREE1, NEEDS_CORRECTION, 1, [ROOT_FINDING])])
        self.assertEqual((result.status, result.round, len(result.previous_findings)), (PROCEED, 2, 1))


class CombineTests(unittest.TestCase):
    def test_clean_pass(self):
        d = combine(check(), semantic())
        self.assertEqual((d.verdict, d.decision, d.writes), (PASS, "ADOPT_RECORDED", ("next_issue", "receipt")))

    def test_semantic_pass_cannot_override_a_guard_finding(self):
        pre = check(files=FILES + [{"filename": "README.md", "status": "modified"}])
        d = combine(pre, semantic())
        self.assertEqual((d.verdict, d.decision), (NEEDS_CORRECTION, "CORRECTIVE_REQUESTED"))

    def test_green_tests_with_unmet_acceptance_is_needs_correction(self):
        d = combine(check(), semantic(verdict=PASS, met=(True, False), tests="PASS"))
        self.assertEqual(d.verdict, NEEDS_CORRECTION)
        self.assertTrue(any(f["category"] == "acceptance_unmet" for f in d.findings))

    def test_failing_or_missing_tests_block_pass_for_code_change(self):
        for tests in ("FAIL", "NOT_RUN"):
            with self.subTest(tests=tests):
                self.assertEqual(combine(check(), semantic(tests=tests)).verdict, NEEDS_CORRECTION)

    def test_new_regression_introduced_during_corrective_is_caught(self):
        regression = dict(ROOT_FINDING, category="behaviour_regression", what_is_wrong="non-empty input now empty")
        pre = check(pr=pr(HEAD2), head_tree=TREE2,
                    issue_comments=[receipt(HEAD1, TREE1, NEEDS_CORRECTION, 1, [ROOT_FINDING])])
        review = semantic(verdict=NEEDS_CORRECTION, findings=[regression],
                          resolved=[{"fingerprint": finding_fingerprint(ROOT_FINDING), "resolved": True, "evidence": "ok"}])
        d = combine(pre, validate_semantic_review(review, task=TASK, previous=pre.previous_findings))
        self.assertEqual((d.verdict, d.escalate_root_cause), (NEEDS_CORRECTION, False))

    def test_previous_fail_reason_still_present_escalates_to_root_cause(self):
        pre = check(pr=pr(HEAD2), head_tree=TREE2,
                    issue_comments=[receipt(HEAD1, TREE1, NEEDS_CORRECTION, 1, [ROOT_FINDING])])
        review = semantic(verdict=NEEDS_CORRECTION, findings=[ROOT_FINDING],
                          resolved=[{"fingerprint": finding_fingerprint(ROOT_FINDING), "resolved": False,
                                     "evidence": "still raises"}])
        d = combine(pre, validate_semantic_review(review, task=TASK, previous=pre.previous_findings))
        self.assertTrue(d.escalate_root_cause)
        text = build_corrective(d, task=TASK, pr_head_sha=HEAD2)
        self.assertIn("Root-cause review requested", text)

    def test_semantic_pass_with_unresolved_previous_finding_is_not_pass(self):
        pre = check(pr=pr(HEAD2), head_tree=TREE2,
                    issue_comments=[receipt(HEAD1, TREE1, NEEDS_CORRECTION, 1, [ROOT_FINDING])])
        review = semantic(resolved=[{"fingerprint": finding_fingerprint(ROOT_FINDING), "resolved": False,
                                     "evidence": "no"}])
        self.assertEqual(combine(pre, review).verdict, NEEDS_CORRECTION)

    def test_ordinary_blocked_becomes_correction_only_real_blockers_stop(self):
        d = combine(check(), semantic(verdict=BLOCKED, met=(False, True), blocked_reason="hard to fix"))
        self.assertEqual((d.verdict, d.decision), (NEEDS_CORRECTION, "CORRECTIVE_REQUESTED"))
        d = combine(check(), semantic(verdict=BLOCKED, met=(False, True), blocked_reason="permission_missing"))
        self.assertEqual((d.verdict, d.decision, d.writes), (BLOCKED, TASK_BLOCKED, ("receipt",)))

    def test_correction_limit_isolates_the_task(self):
        fails = [receipt(h, t, NEEDS_CORRECTION, n) for n, (h, t) in enumerate(((HEAD1, TREE1), (HEAD2, TREE2)), 1)]
        pre = check(pr=pr(HEAD3), head_tree="c" * 40, issue_comments=fails)
        d = combine(pre, semantic(verdict=NEEDS_CORRECTION, met=(False, True)))
        self.assertEqual((pre.round, d.decision, d.writes), (3, TASK_BLOCKED, ("receipt",)))

    def test_crash_after_corrective_before_receipt_does_not_double_post(self):
        pre = check(pr_comments=[corrective_comment(HEAD1)])
        d = combine(pre, semantic(verdict=NEEDS_CORRECTION, met=(False, True)))
        self.assertEqual((d.decision, d.writes), ("CORRECTIVE_EXISTS", ("receipt",)))

    def test_crash_after_next_issue_before_pass_receipt_reuses_the_issue(self):
        pre = check(open_issue_titles={"[next] prepared": 777})
        d = combine(pre, semantic())
        self.assertEqual((pre.existing_next_issue, d.writes), (777, ("receipt",)))

    def test_one_blocked_task_does_not_stop_an_independent_task(self):
        blocked = check(issue_body=issue_body(dict(TASK, expected_target_branch="dev")))
        other = check(pr=pr(body="Fixes #500"))
        self.assertEqual((blocked.status, combine(other, semantic()).verdict), (TASK_BLOCKED, PASS))


class GraduationTaskTests(unittest.TestCase):
    """The prepared slot-9 task (not started) passes the guard and drives a precise corrective."""

    def setUp(self):
        from pathlib import Path
        from automation.command_bus.claude_closed_loop_protocol import _block
        body = (Path(__file__).resolve().parents[3] / "docs/evidence/claude-jules-stop-resistant-20261007"
                / "graduation-grd-001-issue-body.md").read_text(encoding="utf-8")
        self.body, self.task = body, _block(body, TASK_MARKER)[0]
        self.path = self.task["allowed_paths"][0]["path"]

    def test_task_is_valid_code_change_with_tests(self):
        pre = precheck(pr=pr(body="Fixes #600"), issue_body=self.body, issue_comments=[], pr_comments=[],
                       files=[{"filename": self.path, "status": "modified"}], head_tree=TREE1)
        self.assertEqual((pre.status, pre.round, pre.guard_findings), (PROCEED, 1, ()))
        self.assertEqual(self.task["kind"], "code_change")
        self.assertEqual(self.task["live_slot"], 9)

    def test_production_file_touched_is_a_guard_finding_even_if_tests_pass(self):
        files = [{"filename": self.path, "status": "modified"},
                 {"filename": "automation/command_bus/claude_jules_live.py", "status": "modified"}]
        pre = precheck(pr=pr(body="Fixes #600"), issue_body=self.body, issue_comments=[], pr_comments=[], files=files,
                       head_tree=TREE1)
        review = {"profile": "CLAUDE_SEMANTIC_REVIEW_V1", "verdict": PASS, "summary": "s",
                  "criteria": [{"criterion": c, "met": True, "evidence": "diff"} for c in self.task["acceptance_criteria"]],
                  "findings": [], "previous_findings_resolved": [], "tests": {"result": "PASS"}, "blocked_reason": None}
        d = combine(pre, validate_semantic_review(review, task=self.task, previous=()))
        self.assertEqual(d.verdict, NEEDS_CORRECTION)
        text = build_corrective(d, task=self.task, pr_head_sha=HEAD1)
        self.assertIn("claude_jules_live.py is changed but is not an allowed path", text)
        self.assertIn("python3 -m unittest automation.command_bus.tests.test_claude_jules_live_adapter", text)


class RecordTests(unittest.TestCase):
    def test_semantic_review_must_judge_every_criterion_and_previous_finding(self):
        with self.assertRaises(ValueError):
            validate_semantic_review(dict(semantic(), criteria=semantic()["criteria"][:1]), task=TASK, previous=())
        with self.assertRaises(ValueError):
            validate_semantic_review(semantic(), task=TASK, previous=(ROOT_FINDING,))
        bad = dict(ROOT_FINDING, category="vibes")
        with self.assertRaises(ValueError):
            validate_semantic_review(semantic(findings=[bad]), task=TASK, previous=())

    def test_receipt_is_rendered_exactly_and_parsed_strictly(self):
        comment = receipt(HEAD1, TREE1, PASS, 1)
        self.assertEqual(parse_receipt(comment)["verdict"], PASS)
        with self.assertRaises(ValueError):
            parse_receipt(comment.replace("}\n-->", "}``\n-->"))  # the live CLP-002 debris is refused for v2
        record = json.loads(comment.split(RECEIPT_MARKER)[1].split("-->")[0])
        for bad in ({"reviewed_at": "2026-10-09T12:00"}, {"reviewed_at": "around noon"}, {"verdict": "OK"},
                    {"pr_head_tree": "abc"}, {"phase": "MAYBE"}, {"criteria": [{"criterion": "x"}]}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_receipt(dict(record, **bad))

    def test_corrective_text_is_specific_scoped_and_marked(self):
        d = combine(check(), semantic(verdict=NEEDS_CORRECTION, findings=[ROOT_FINDING]))
        text = build_corrective(d, task=TASK, pr_head_sha=HEAD1)
        for needle in ("@jules", "What is wrong:", "Expected behaviour:", "How to reproduce:",
                       "Regression test to add or keep:", "Passes when:", f"Change only: {SRC}, {TEST}",
                       "do not weaken or delete existing tests", "Run before pushing:", CORRECTIVE_MARKER):
            self.assertIn(needle, text)
        self.assertTrue(text.startswith("@jules"))


if __name__ == "__main__":
    unittest.main()
