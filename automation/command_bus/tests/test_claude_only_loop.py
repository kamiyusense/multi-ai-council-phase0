import json
import unittest
from pathlib import Path

from automation.command_bus import claude_only_loop as cl
from automation.command_bus.claude_closed_loop_protocol import RECEIPT_MARKER
from automation.command_bus.claude_closed_loop_review import render_receipt, validate_task_v2

ROOT = Path(__file__).resolve().parents[3]
POLICY = cl.load_policy(json.loads((ROOT / "docs/claude-loop/active/policy.json").read_text(encoding="utf-8")))
NOW = "2026-11-01T03:00:00Z"
BASE = "a" * 40
HEAD1, HEAD2 = "b" * 40, "c" * 40

REQUEST = """Requested by Grok.

goal: Add a short how-to page for the loop.
allowed_paths:
- docs/howto/loop.md (ADD)
- automation/command_bus/tests/test_howto_loop.py (ADD)
acceptance:
- the page explains how to file a request
- a new test checks the page exists
test_commands:
- python3 -m unittest automation.command_bus.tests.test_howto_loop

AI-Agent: grok
"""


def issue(n, body=REQUEST, *, title="[claude loop] add how-to", author="kamiyusense", state="OPEN", comments=()):
    return {"number": n, "title": title, "author": author, "state": state, "body": body, "labels": [],
            "comments": [dict(c) for c in comments]}


def comment(body, *, author="kamiyusense", at="2026-11-01T01:00:00Z", app="claude"):
    return {"author": author, "app": app, "body": body, "created_at": at}


def accepted(n, *, at="2026-11-01T01:00:00Z", base=BASE):
    req, problems = cl.request_problems(issue(n), POLICY)
    assert not problems, problems
    task = cl.build_task(n, req, base_head=base, policy=POLICY)
    return task, comment(cl.render_accept(n, task, now=at), at=at)


def pr(n, number, head, *, state="open", updated="2026-11-01T02:00:00Z"):
    return {"number": number, "state": state, "head": {"ref": f"claude/loop-{n}", "sha": head}, "updated_at": updated}


def receipt(task, *, pr_number, head, round_, verdict, decision, at="2026-11-01T02:30:00Z"):
    record = {"profile": "CLAUDE_CLOSED_LOOP_REVIEW_V2", "task_id": task["task_id"], "loop_id": task["loop_id"],
              "correlation_id": task["correlation_id"], "generation": 1, "round": round_, "phase": "FINAL",
              "pr": pr_number, "pr_head_sha": head, "pr_head_tree": "d" * 40,
              "expected_target_head": task["expected_target_head"], "observed_base_head": BASE, "verdict": verdict,
              "decision": decision, "criteria": [], "escalate_root_cause": False,
              "findings": [] if verdict == "PASS" else [{"category": "acceptance_unmet", "severity": "major",
                                                         "what_is_wrong": "page missing a section"}],
              "tests": {"result": "PASS"}, "live_slot": 0, "corrective_comment": None, "next_issue": None,
              "wake_event": "pull_request", "reviewed_at": at}
    return comment(render_receipt(summary="review", record=record), at=at)


CONTROL = {"number": 494, "state": "OPEN", "labels": [], "comments": [], "body": ""}


class PolicyTest(unittest.TestCase):
    def test_policy_file_is_valid_and_points_at_control_issue(self):
        self.assertEqual(POLICY["control_issue"], 494)
        self.assertEqual(POLICY["loop_id"], "claude-claude-auto")

    def test_every_loop_a_safety_boundary_and_execution_path_is_forbidden(self):
        campaign = json.loads((ROOT / "docs/claude-jules-loop/active/campaign.json").read_text(encoding="utf-8"))
        classes = campaign["policy"]["path_classes"]
        for path in classes["safety_boundary"] + classes["execution_config"]:
            probe = path + "x.py" if path.endswith("/") else path
            self.assertIsNotNone(cl.path_problem(probe, "MODIFY", POLICY), path)
            self.assertIsNotNone(cl.path_problem(probe, "ADD", POLICY), path)

    def test_loop_cannot_edit_itself_or_its_policy(self):
        for path in ("automation/command_bus/claude_only_loop.py", "docs/claude-loop/active/policy.json",
                     "automation/command_bus/tests/test_claude_only_loop.py"):
            self.assertIsNotNone(cl.path_problem(path, "ADD", POLICY), path)

    def test_loop_cannot_change_test_loading_prompts_lanes_or_safety_docs(self):
        for path in ("tests/conftest.py", "automation/command_bus/tests/conftest.py", "sitecustomize.py",
                     "usercustomize.py", "src/extra.pth", "tests/__init__.py", "tests/relay/__init__.py",
                     "automation/command_bus/tests/__init__.py",
                     "docs/claude-loop/worker-routine-prompt-v1.txt", "docs/claude-loop/reviewer-routine-prompt-v1.txt",
                     "docs/claude-loop/README.md", "automation/command_bus/config/lane_catalog_v4.json",
                     "HANDOVER_CURRENT.md", "docs/ARCHITECTURE.md", "docs/PHASE0_IMPLEMENTATION_SPEC.md",
                     "docs/PHASE0_IMPLEMENTATION_CHECKLIST.md", "docs/DEVELOPMENT_WORKFLOW.md",
                     "docs/CHAT_WORK_AUTONOMY_RULES.md", "docs/AUTONOMOUS_DEVELOPMENT_LOOP_NORTH_STAR.md",
                     "docs/USER_COPY_TEXT_FORMAT.md", "docs/RELAY_TOWER_DIRECTION_V4.md",
                     "docs/SYMPHONY_MVP_CHARTER.md"):
            for op in ("ADD", "MODIFY"):
                self.assertIsNotNone(cl.path_problem(path, op, POLICY), (path, op))
        self.assertIsNone(cl.path_problem("src/council/__init__.py", "ADD", POLICY))

    def test_full_suite_is_the_known_green_commands(self):
        # Both pass on main; a suite that is red on main would block every task.
        self.assertEqual(POLICY["full_suite"], [
            "python3 -m unittest discover -s automation/command_bus/tests -t .",
            "PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests"])

    def test_invalid_policy_is_refused(self):
        bad = dict(POLICY, branch_prefix="loop-")
        with self.assertRaises(cl.PolicyError):
            cl.load_policy(bad)
        bad = json.loads(json.dumps(POLICY))
        bad["forbidden"]["existing_tests_read_only"] = False
        with self.assertRaises(cl.PolicyError):
            cl.load_policy(bad)


class RequestTest(unittest.TestCase):
    def test_list_form(self):
        req, problems = cl.request_problems(issue(1), POLICY)
        self.assertEqual(problems, [])
        self.assertEqual([p["op"] for p in req["allowed_paths"]], ["ADD", "ADD"])
        self.assertEqual(len(req["acceptance"]), 2)
        self.assertEqual(req["test_commands"], ["python3 -m unittest automation.command_bus.tests.test_howto_loop"])

    def test_inline_contractor_form(self):
        body = ("goal: Create docs/x/HELLO.md with two lines.\nallowed_paths: docs/x/HELLO.md (ADD)\n"
                "acceptance: the file exists with exactly those two lines\ntest_commands: test -f docs/x/HELLO.md\n\n"
                "AI-Agent: grok")
        req, problems = cl.request_problems(issue(2, body), POLICY)
        self.assertEqual(problems, [])
        self.assertEqual(req["allowed_paths"], [{"path": "docs/x/HELLO.md", "op": "ADD"}])

    def test_refusals(self):
        cases = {
            "unsigned": (REQUEST.replace("AI-Agent: grok", ""), {}),
            "stranger": (REQUEST, {"author": "someone"}),
            "no prefix": (REQUEST, {"title": "add how-to"}),
            "delete": (REQUEST.replace("docs/howto/loop.md (ADD)", "docs/old.md (DELETE)"), {}),
            "workflow": (REQUEST.replace("docs/howto/loop.md (ADD)", ".github/workflows/x.yml (ADD)"), {}),
            "existing test": (REQUEST.replace("test_howto_loop.py (ADD)", "test_howto_loop.py (MODIFY)"), {}),
            "traversal": (REQUEST.replace("docs/howto/loop.md", "docs/../AGENTS.md"), {}),
            "research": (REQUEST + "\nmode: research\n", {}),
            "no tests": (REQUEST.replace("test_commands:\n- python3 -m unittest "
                                         "automation.command_bus.tests.test_howto_loop\n", ""), {}),
            "too many": (REQUEST.replace("- docs/howto/loop.md (ADD)\n", "".join(
                f"- docs/howto/p{i}.md (ADD)\n" for i in range(11))), {}),
        }
        for name, (body, extra) in cases.items():
            _, problems = cl.request_problems(issue(3, body, **extra), POLICY)
            self.assertTrue(problems, name)

    def test_new_test_file_may_be_added(self):
        self.assertIsNone(cl.path_problem("automation/command_bus/tests/test_new_thing.py", "ADD", POLICY))
        self.assertIsNotNone(cl.path_problem("automation/command_bus/tests/test_new_thing.py", "MODIFY", POLICY))

    def test_task_is_a_valid_code_change_task_with_the_full_suite(self):
        task, _ = accepted(7)
        self.assertIsNone(validate_task_v2(task, pr_base="main"))
        self.assertEqual(task["task_id"], "CL-7")
        self.assertEqual(task["work_branch"], "claude/loop-7")
        for cmd in POLICY["full_suite"]:
            self.assertIn(cmd, task["test_commands"])
        self.assertIn("No existing test is removed, skipped or weakened", task["acceptance_criteria"])


class StateTest(unittest.TestCase):
    def test_lifecycle(self):
        task, acc = accepted(5)
        self.assertEqual(cl.task_state(issue(5), [], POLICY).state, cl.NEW)
        self.assertEqual(cl.task_state(issue(5, comments=[acc]), [], POLICY).state, cl.WORKING)
        pulls = [pr(5, 40, HEAD1)]
        self.assertEqual(cl.task_state(issue(5, comments=[acc]), pulls, POLICY).state, cl.REVIEW_PENDING)
        r1 = receipt(task, pr_number=40, head=HEAD1, round_=1, verdict="NEEDS_CORRECTION",
                     decision="CORRECTIVE_REQUESTED")
        st = cl.task_state(issue(5, comments=[acc, r1]), pulls, POLICY)
        self.assertEqual((st.state, st.round, st.pr), (cl.CORRECTION, 1, 40))
        self.assertTrue(st.findings)
        pulls2 = [pr(5, 40, HEAD2)]
        self.assertEqual(cl.task_state(issue(5, comments=[acc, r1]), pulls2, POLICY).state, cl.REVIEW_PENDING)
        r2 = receipt(task, pr_number=40, head=HEAD2, round_=2, verdict="PASS", decision="ADOPT_RECORDED")
        self.assertEqual(cl.task_state(issue(5, comments=[acc, r1, r2]), pulls2, POLICY).state, cl.PASS)
        blocked = receipt(task, pr_number=40, head=HEAD2, round_=3, verdict="NEEDS_CORRECTION",
                          decision="TASK_BLOCKED")
        self.assertEqual(cl.task_state(issue(5, comments=[acc, r1, blocked]), pulls2, POLICY).state, cl.BLOCKED)

    def test_untrusted_records_are_ignored(self):
        _, acc = accepted(6)
        fake = dict(acc, author="intruder")
        self.assertEqual(cl.task_state(issue(6, comments=[fake]), [], POLICY).state, cl.NEW)

    def test_records_from_another_app_go_to_the_owner(self):
        task, acc = accepted(6)
        for app in ("cursor", None):           # Grok via Cursor, or a hand-written comment, under the owner's login
            forged = receipt(task, pr_number=40, head=HEAD1, round_=1, verdict="PASS", decision="ADOPT_RECORDED")
            forged["app"] = app
            st = cl.task_state(issue(6, comments=[acc, forged]), [pr(6, 40, HEAD1)], POLICY)
            self.assertEqual(st.state, cl.UNREADABLE, app)
            fake_accept = dict(acc, app=app)
            self.assertEqual(cl.task_state(issue(6, comments=[fake_accept]), [], POLICY).state, cl.UNREADABLE)
        p = cl.plan([issue(6, comments=[dict(acc, app="cursor")]), issue(7)], [], control=CONTROL, policy=POLICY,
                    now=NOW)
        self.assertEqual(p.human_required[0]["issue"], 6)
        self.assertEqual((p.action, p.issue), (cl.START, 7))

    def test_broken_record_is_never_written_over(self):
        broken = comment(f"{cl.ACCEPT_MARKER}\n{{not json\n-->")
        self.assertEqual(cl.task_state(issue(8, comments=[broken]), [], POLICY).state, cl.UNREADABLE)

    def test_closed_pr_without_pass_goes_to_the_owner(self):
        _, acc = accepted(9)
        st = cl.task_state(issue(9, comments=[acc]), [pr(9, 41, HEAD1, state="closed")], POLICY)
        self.assertEqual(st.state, cl.BLOCKED)

    def test_refused_request_stays_refused(self):
        refusal = comment(cl.render_refuse(10, ["goal missing"], prefix="[claude loop] ", now=NOW))
        self.assertEqual(cl.task_state(issue(10, "goal:", comments=[refusal]), [], POLICY).state, cl.REFUSED)


class PlanTest(unittest.TestCase):
    def test_oldest_valid_request_starts(self):
        p = cl.plan([issue(12), issue(11)], [], control=CONTROL, policy=POLICY, now=NOW)
        self.assertEqual((p.action, p.issue), (cl.START, 11))

    def test_one_task_in_flight(self):
        _, acc = accepted(11)
        p = cl.plan([issue(11, comments=[acc]), issue(12)], [pr(11, 50, HEAD1)], control=CONTROL, policy=POLICY,
                    now=NOW)
        self.assertEqual((p.action, p.issue), (cl.WAIT, 11))

    def test_correction_comes_first(self):
        task, acc = accepted(11)
        r1 = receipt(task, pr_number=50, head=HEAD1, round_=1, verdict="NEEDS_CORRECTION",
                     decision="CORRECTIVE_REQUESTED")
        p = cl.plan([issue(11, comments=[acc, r1]), issue(12)], [pr(11, 50, HEAD1)], control=CONTROL,
                    policy=POLICY, now=NOW)
        self.assertEqual((p.action, p.issue, p.pr, p.round), (cl.CORRECT, 11, 50, 1))

    def test_pass_frees_the_queue(self):
        task, acc = accepted(11)
        ok = receipt(task, pr_number=50, head=HEAD1, round_=1, verdict="PASS", decision="ADOPT_RECORDED")
        p = cl.plan([issue(11, comments=[acc, ok]), issue(12)], [pr(11, 50, HEAD1)], control=CONTROL,
                    policy=POLICY, now=NOW)
        self.assertEqual((p.action, p.issue), (cl.START, 12))

    def test_daily_cap(self):
        done = []
        for n in range(20, 30):
            task, acc = accepted(n, at="2026-11-01T00:10:00Z")
            done.append(issue(n, comments=[acc, receipt(task, pr_number=n + 100, head=HEAD1, round_=1,
                                                        verdict="PASS", decision="ADOPT_RECORDED")]))
        p = cl.plan(done + [issue(40)], [], control=CONTROL, policy=POLICY, now=NOW)
        self.assertEqual(p.action, cl.WAIT)
        self.assertIn("daily cap", p.reason)
        p = cl.plan(done + [issue(40)], [], control=CONTROL, policy=POLICY, now="2026-11-02T00:01:00Z")
        self.assertEqual((p.action, p.issue), (cl.START, 40))

    def test_stop_switch_and_expiry(self):
        for control, now in ((dict(CONTROL, state="CLOSED"), NOW), (dict(CONTROL, labels=["loop-stop"]), NOW),
                             (None, NOW), (CONTROL, "2027-01-01T00:00:00Z")):
            p = cl.plan([issue(11)], [], control=control, policy=POLICY, now=now)
            self.assertEqual(p.action, cl.STOPPED)

    def test_invalid_requests_are_refused_once_and_do_not_block(self):
        p = cl.plan([issue(11, author="someone"), issue(12)], [], control=CONTROL, policy=POLICY, now=NOW)
        self.assertEqual([r["issue"] for r in p.refuse], [11])
        self.assertEqual((p.action, p.issue), (cl.START, 12))

    def test_stalled_worker_is_reported(self):
        _, acc = accepted(11, at="2026-11-01T00:00:00Z")
        p = cl.plan([issue(11, comments=[acc])], [], control=CONTROL, policy=POLICY, now=NOW)
        self.assertEqual(p.action, cl.WAIT)
        self.assertEqual(p.human_required[0]["issue"], 11)

    def test_requests_need_the_title_prefix(self):
        p = cl.plan([issue(11, title="unrelated issue")], [], control=CONTROL, policy=POLICY, now=NOW)
        self.assertEqual(p.action, cl.IDLE)


class CheckpointTest(unittest.TestCase):
    def test_written_on_change_and_heartbeat_only(self):
        p = cl.plan([issue(11)], [], control=CONTROL, policy=POLICY, now=NOW)
        rec = cl.checkpoint_record(p, policy=POLICY, now=NOW)
        self.assertTrue(cl.checkpoint_due(rec, None, policy=POLICY))
        self.assertFalse(cl.checkpoint_due(dict(rec, at="2026-11-01T04:00:00Z"), rec, policy=POLICY))
        self.assertTrue(cl.checkpoint_due(dict(rec, at="2026-11-02T03:00:00Z"), rec, policy=POLICY))
        self.assertIn(cl.CHECKPOINT_MARKER, cl.render_checkpoint(rec))


class FakeGitHub(cl.GitHub):
    def __init__(self, issues, pulls=(), *, post_lands=True, control=None):
        self.policy, self.repo = POLICY, POLICY["repository"]
        self.issues = {i["number"]: i for i in issues}
        self.pulls, self.control = list(pulls), control or dict(CONTROL)
        self.post_lands, self.posts = post_lands, []

    def read_issue(self, n):
        if n == POLICY["control_issue"]:
            return self.control
        return json.loads(json.dumps(self.issues[n]))

    def snapshot(self):
        return [self.read_issue(n) for n in sorted(self.issues)], self.pulls, self.control

    def base_head(self):
        return BASE

    def comment(self, n, body):
        self.posts.append((n, body))
        if self.post_lands:
            target = self.control if n == POLICY["control_issue"] else self.issues[n]
            target["comments"].append(comment(body, at=NOW))
        return 0 if self.post_lands else 1


class CommandTest(unittest.TestCase):
    def test_accept_once(self):
        gh = FakeGitHub([issue(11)])
        code, out = cl.cmd_accept(gh, 11, now=NOW)
        self.assertEqual((code, out["result"]), (cl.EXIT_OK, "ACCEPTED"))
        code, out = cl.cmd_accept(gh, 11, now=NOW)
        self.assertEqual(code, cl.EXIT_REFUSED)
        self.assertEqual(len(gh.posts), 1)

    def test_accept_only_what_the_plan_starts(self):
        gh = FakeGitHub([issue(11), issue(12)])
        code, _ = cl.cmd_accept(gh, 12, now=NOW)
        self.assertEqual(code, cl.EXIT_REFUSED)
        self.assertEqual(gh.posts, [])

    def test_unknown_outcome_is_not_resent(self):
        gh = FakeGitHub([issue(11)], post_lands=False)
        code, out = cl.cmd_accept(gh, 11, now=NOW)
        self.assertEqual((code, out["result"]), (cl.EXIT_UNKNOWN, "UNKNOWN"))
        self.assertEqual(len(gh.posts), 1)

    def test_refuse_once(self):
        gh = FakeGitHub([issue(11, author="someone")])
        code, out = cl.cmd_refuse(gh, 11, now=NOW)
        self.assertEqual((code, out["result"]), (cl.EXIT_OK, "REFUSAL_POSTED"))
        code, _ = cl.cmd_refuse(gh, 11, now=NOW)
        self.assertEqual(code, cl.EXIT_REFUSED)
        self.assertEqual(len(gh.posts), 1)

    def test_checkpoint_only_when_changed(self):
        gh = FakeGitHub([issue(11)])
        self.assertEqual(cl.cmd_checkpoint(gh, now=NOW)[1]["result"], "WRITTEN")
        self.assertEqual(cl.cmd_checkpoint(gh, now=NOW)[1]["result"], "NOT_DUE")
        stopped = FakeGitHub([issue(11)], control=dict(CONTROL, state="CLOSED"))
        self.assertEqual(cl.cmd_checkpoint(stopped, now=NOW)[1]["result"], "NOT_DUE")

    def test_show_gives_the_reviewer_only_trusted_records(self):
        task, acc = accepted(11)
        r1 = receipt(task, pr_number=50, head=HEAD1, round_=1, verdict="NEEDS_CORRECTION",
                     decision="CORRECTIVE_REQUESTED")
        gh = FakeGitHub([issue(11, comments=[acc, r1])], [pr(11, 50, HEAD1)])
        code, out = cl.cmd_show(gh, 11)
        self.assertEqual((code, out["state"], out["task"]["task_id"], len(out["receipts"])),
                         (cl.EXIT_OK, cl.CORRECTION, "CL-11", 1))

    def test_receipt_marker_is_the_loop_a_marker(self):
        self.assertEqual(RECEIPT_MARKER, "<!-- claude-closed-loop-receipt v1")


class RoutinePromptTest(unittest.TestCase):
    WORKER = (ROOT / "docs/claude-loop/worker-routine-prompt-v1.txt").read_bytes().decode("utf-8")
    REVIEWER = (ROOT / "docs/claude-loop/reviewer-routine-prompt-v1.txt").read_bytes().decode("utf-8")

    def test_paste_safe(self):
        for text in (self.WORKER, self.REVIEWER):
            self.assertNotIn("\r", text)
            self.assertNotIn("\t", text)
            self.assertNotIn("```", text)

    def test_prompts_use_the_module_and_policy(self):
        for text in (self.WORKER, self.REVIEWER):
            self.assertIn("python3 -m automation.command_bus.claude_only_loop", text)
            self.assertIn("docs/claude-loop/active/policy.json", text)
            self.assertIn("claude/loop-", text)
            self.assertIn("Never merge", text)
            self.assertNotIn("@jules", text)
        for cmd in ("next", "accept", "refuse"):
            self.assertIn(f"claude_only_loop {cmd} --policy", self.WORKER)
        self.assertIn("claude_only_loop checkpoint --policy", self.REVIEWER)

    def test_reviewer_writes_receipts_the_module_reads(self):
        self.assertIn(RECEIPT_MARKER, self.REVIEWER)
        self.assertIn("CLAUDE_CLOSED_LOOP_REVIEW_V2", self.REVIEWER)
        for text in (self.WORKER, self.REVIEWER):
            self.assertIn("claude_only_loop show --policy", text)       # records only through the app-checked reader
        self.assertIn("RECORD_UNREADABLE", self.REVIEWER)
        for decision in ("ADOPT_RECORDED", "CORRECTIVE_REQUESTED", "TASK_BLOCKED"):
            self.assertIn(decision, self.REVIEWER)
        self.assertIn("Never comment on a PR", self.REVIEWER)

    def test_worker_keeps_the_hard_limits(self):
        for phrase in ("Never modify an existing test file", "never force push", "Never start Jules",
                       "do not install anything", "Fixes #N", "not a draft"):
            self.assertIn(phrase, self.WORKER)


if __name__ == "__main__":
    unittest.main()
