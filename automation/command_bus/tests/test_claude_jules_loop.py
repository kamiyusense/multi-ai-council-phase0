"""Autonomous loop: planner, merge-free continuation, typed classification, visible DEFER, recovery, endurance.

Everything runs in ``starter_world.LoopWorld``: the only wakes are pull_request events (reviewer, then a loop
tick), pull_request.closed (merged), the human's first start and an optional recovery schedule.  Issue events
wake nothing, because Routine GitHub triggers support pull_request and release only.
"""
from __future__ import annotations

import random
import unittest
from datetime import timedelta

from automation.command_bus import claude_closed_loop_review as review
from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_task_planner as planner
from automation.command_bus.tests import starter_world as sw

DEMO = "automation/command_bus/demo/"


def labeled(world, n):
    return sum(1 for e in world.gh.issues[n]["label_events"] if e["event"] == "labeled" and e["label"] == st.LABEL)


def passed(world, n):
    return any(r["verdict"] == review.PASS for r in world.receipts(n))


def merge_all_passed(world):
    return [n for n in sorted(world.gh.issues) if world.jules_pr.get(n) and not world.pr_merged(n)
            and passed(world, n)]


def tasks_by_signal(world):
    out = {}
    for n in sorted(world.gh.issues):
        t = world.task_of(n)
        meta = (t or {}).get("campaign") or {}
        if isinstance(meta, dict) and meta.get("signal_id"):
            out.setdefault(meta["signal_id"], []).append(n)
    return out


class LoopInvariants:
    def assert_safe(self, world):
        for n in world.gh.issues:
            self.assertLessEqual(labeled(world, n), 1, f"#{n} labeled twice")
            self.assertLessEqual(world.jules_starts[n], 1, f"Jules started twice for #{n}")
        for sid, issues in tasks_by_signal(world).items():
            self.assertEqual(len(issues), 1, f"signal {sid} planned more than once: {issues}")
        for n in world.gh.issues:                       # only the starter's three record kinds, the reviewer's
            for c in world.gh.issues[n]["comments"]:     # receipts, Jules' greeting and loop checkpoints
                body = c["body"]
                self.assertTrue(any(m in body for m in (st.INTENT_MARKER, st.START_RECEIPT_MARKER,
                                                        review.RECEIPT_MARKER, loop.CHECKPOINT_MARKER))
                                or c["author"] == sw.JULES, body[:80])


def world_with(signals, *, objectives=None, policy=None, **kw):
    c = sw.planner_campaign("pl", objectives or [sw.objective("o1", [DEMO])], policy=policy)
    return sw.LoopWorld(c, signals, **kw)


# ---------------------------------------------------------------- A. the work does not run out with a list
class PlannerTests(unittest.TestCase, LoopInvariants):
    def test_planner_keeps_choosing_work_without_any_prepared_list(self):
        w = world_with([sw.signal(f"s{k}", "o1", f"{DEMO}m{k}.py") for k in range(1, 8)])
        w.deliver({"name": "start"})
        w.run_until_quiet(merge_policy=merge_all_passed)
        self.assertEqual(w.ticks[-1].outcome, loop.GOAL_COMPLETE)
        self.assertEqual(sorted(tasks_by_signal(w)), [f"s{k}" for k in range(1, 8)])
        self.assert_safe(w)

    def test_new_signals_found_after_the_backlog_is_empty_are_picked_up(self):
        w = world_with([sw.signal("s1", "o1", f"{DEMO}a.py")])
        w.deliver({"name": "start"})
        w.run_until_quiet(merge_policy=merge_all_passed)
        self.assertEqual(w.ticks[-1].outcome, loop.GOAL_COMPLETE)
        w.backlog.append(sw.signal("s2", "o1", f"{DEMO}b.py", kind="missing_test"))   # e.g. a new CI failure
        w.deliver({"name": "schedule"})
        w.run_until_quiet(merge_policy=merge_all_passed)
        self.assertIn("s2", tasks_by_signal(w))
        self.assertEqual(w.ticks[-1].outcome, loop.GOAL_COMPLETE)
        self.assert_safe(w)

    def test_unreadable_signals_are_never_goal_complete(self):
        w = world_with([sw.signal("s1", "o1", f"{DEMO}a.py")])
        w.signal_failures = 99
        w.deliver({"name": "start"})
        self.assertEqual(w.ticks[-1].outcome, loop.DEFER)
        self.assertIn("could not be read", w.ticks[-1].reason)

    def test_priority_scope_evidence_and_duplicates(self):
        c = sw.planner_campaign("pp", [sw.objective("o1", [DEMO])])
        sigs = [sw.signal("docs1", "o1", f"{DEMO}d.md", kind="docs"),
                sw.signal("bug1", "o1", f"{DEMO}b.py", kind="broken"),
                sw.signal("far", "o1", "elsewhere/x.py"),
                {**sw.signal("noev", "o1", f"{DEMO}n.py"), "evidence": []},
                sw.signal("other", "o9", f"{DEMO}o.py")]
        d = planner.plan_next(campaign=c, signals=sigs, known=[])
        self.assertEqual((d.outcome, d.proposal["signal_id"]), (planner.PROPOSE, "bug1"))
        reasons = {x["signal"]: x["reason"] for x in d.skipped}
        self.assertIn("needs evidence", reasons["noev"])
        self.assertIn("outside the approved objectives", reasons["other"])
        fp = st.task_fingerprint("o1", "bug1", [f"{DEMO}b.py"])
        known = [{"task_id": "t", "fingerprint": fp, "signal_id": "bug1", "state": planner.RUNNING,
                  "paths": [f"{DEMO}b.py"]}]
        d2 = planner.plan_next(campaign=c, signals=sigs, known=known)
        self.assertEqual(d2.proposal["signal_id"], "docs1")          # bug1 is covered, never planned twice
        far = planner.propose_from_signal(sigs[2], objective=c["objectives"][0])
        self.assertIn("outside the objective scope", planner.validate_proposal(far, campaign=c, known=[]))

    def test_list_exhaustion_is_not_goal_completion(self):
        d = planner.plan_next(campaign=sw.planner_campaign("pe", [sw.objective("o1", [DEMO])]),
                              signals=[sw.signal("s1", "o1", f"{DEMO}a.py")], known=[])
        self.assertEqual(d.outcome, planner.PROPOSE)
        done = planner.plan_next(campaign=sw.planner_campaign("pe", [sw.objective("o1", [DEMO])]),
                                 signals=[sw.signal("s1", "o1", f"{DEMO}a.py")],
                                 known=[{"task_id": "x", "signal_id": "s1", "state": planner.MERGED, "paths": []}])
        self.assertEqual(done.outcome, planner.GOAL_COMPLETE)


# ---------------------------------------------------------------- B. merge-free continuation
class MergeFreeContinuationTests(unittest.TestCase, LoopInvariants):
    def test_independent_work_continues_and_dependent_work_waits_for_a_human_merge(self):
        sigs = [sw.signal("A", "o1", f"{DEMO}a.py"), sw.signal("B", "o1", f"{DEMO}b.py"),
                sw.signal("C", "o1", f"{DEMO}c.py", depends_on=["A"]),
                sw.signal("D", "o1", f"{DEMO}a.py", kind="missing_test")]     # same file as A
        w = world_with(sigs)
        w.deliver({"name": "start"})
        w.run_until_quiet()                                                 # nobody merges
        by = tasks_by_signal(w)
        self.assertTrue(passed(w, by["A"][0]) and passed(w, by["B"][0]))  # B ran although A is unmerged
        self.assertNotIn("C", by)
        self.assertNotIn("D", by)
        last = w.ticks[-1]
        self.assertEqual(last.outcome, loop.MERGE_WAIT)
        merges = [h for h in last.human_actions if h["action"] == "merge"]
        self.assertTrue(any(h["unblocks"] == "C" for h in merges) and any(h["unblocks"] == "D" for h in merges))
        # the human merges A: the merged event resumes C and D without anyone saying "continue"
        w.human_merge(by["A"][0])
        w.run_until_quiet(merge_policy=merge_all_passed)
        by = tasks_by_signal(w)
        self.assertTrue(passed(w, by["C"][0]) and passed(w, by["D"][0]))
        self.assertEqual(w.ticks[-1].outcome, loop.GOAL_COMPLETE)
        self.assert_safe(w)

    def test_manifest_dependency_is_a_merge_wait_not_a_stop(self):
        w = world_with([sw.signal("A", "o1", f"{DEMO}a.py")])
        snap = {"repository": st.DEFAULT_POLICY["repository"], "now": "2026-10-10T00:00:00Z"}
        task = sw.code_task("t-dep", path=f"{DEMO}x.py", extra={"depends_on": ["pl-a"]})
        self.assertEqual(task["depends_on"], ["pl-a"])
        del w, snap   # the starter-level check is exercised in StarterDependencyTests


class StarterDependencyTests(unittest.TestCase):
    def setUp(self):
        self.c = sw.campaign("cd", 2, extras={2: {"depends_on": ["cd-t1"]}})
        self.w = sw.World([self.c])
        self.seed, self.first = sw.seed_predecessor(self.w, self.c)

    def step2(self, states, pending=None):
        entry = self.w.entries["cd"][2]
        snap = self.w.snapshot(self.first, self.seed, "cd")
        snap["candidate"] = {**snap["candidate"], "title": entry["title"], "body": entry["body"]}
        snap["task_states"], snap["pending_merge"] = states, pending or []
        return st.next_step(snap, campaign=self.c, controller="x")

    def test_dependency_states(self):
        self.assertEqual(self.step2({"cd-t1": "PASS_UNMERGED"}).code, "MERGE_WAIT")
        self.assertTrue(self.step2({"cd-t1": "PASS_UNMERGED"}).human_required)
        self.assertEqual(self.step2({"cd-t1": "RUNNING"}).code, "DEPENDENCY_PENDING")
        self.assertEqual(self.step2({"cd-t1": "ISOLATED"}).action, st.ISOLATE)
        self.assertEqual(self.step2(None).code, "DEPENDENCY_UNKNOWN")
        # MERGED passes the dependency check (it then stops at the predecessor rule for this manifest task)
        self.assertNotIn(self.step2({"cd-t1": "MERGED"}).code, {"MERGE_WAIT", "DEPENDENCY_PENDING"})

    def test_pending_merge_on_the_same_file_waits(self):
        path = self.w.entries["cd"][1]["task"]["allowed_paths"][0]["path"]
        snap = self.w.snapshot(self.first, self.seed, "cd")
        snap["pending_merge"] = [{"task_id": "other", "paths": [path]}]
        s = st.next_step(snap, campaign=self.c, controller="x")
        self.assertEqual((s.code, s.dependency), ("PATH_CONFLICT_PENDING_MERGE", ("other",)))


# ---------------------------------------------------------------- C / D. classification by operation and risk
class ClassificationTests(unittest.TestCase):
    policy = st.make_policy()

    def cls(self, criteria=None, path=f"{DEMO}x.py", **extra):
        task = sw.code_task("t", path=path, extra=extra)
        if criteria:
            task["acceptance_criteria"] = criteria
        return st.classify_task(task, self.policy)

    def test_safe_tasks_that_mention_dangerous_words(self):
        for text in ("Add a test that the billing guard refuses metered and overage routes",
                     "Add a regression test that API keys never appear in logs or receipts",
                     "Document that automation must not merge pull requests and never force-push",
                     "The guard refuses to merge the PR when CI is red; cover it with a test",
                     "Fix the credits counter display bug in the usage report parser"):
            with self.subTest(text=text):
                self.assertIsNone(self.cls([text, "a regression test is added"]))

    def test_real_dangerous_requests(self):
        for text, op in (("Merge the pull request into main when green", "merge"),
                         ("Push directly to main after the tests pass", "default_branch_write"),
                         ("Rotate the API key used by the workflow", "api_key_change"),
                         ("Enable usage credits so the routine keeps running", "billing_change"),
                         ("Disable the provider route guard for this run", "safety_guard_disable"),
                         ("Run rm -rf build and delete the branch", "destructive_delete")):
            with self.subTest(text=text):
                code, reason, human = self.cls([text, "x"])
                self.assertEqual((code, human), ("CLASSIFICATION_MISMATCH", True))
                self.assertIn(op, reason)

    def test_declared_operations(self):
        self.assertEqual(self.cls(operations=["merge"])[:1], ("HUMAN_OPERATION",))
        self.assertEqual(self.cls(operations=["teleport"]), ("UNKNOWN_OPERATION",
                                                             "unknown operations ['teleport']: the planner must "
                                                             "classify them", False))
        self.assertIsNone(self.cls(operations=["bug_fix", "test_add"]))

    def test_loop_code_is_ordinary_development_now(self):
        for path in ("automation/command_bus/claude_jules_cli_transport.py",
                     "automation/command_bus/claude_jules_lane_proof_launcher.py",
                     "automation/command_bus/tests/test_claude_jules_dispatch_contract.py"):
            self.assertIsNone(self.cls(path=path), path)

    def test_safety_boundary_can_be_fixed_and_tested_but_not_widened(self):
        guard = "automation/command_bus/claude_jules_provider_route.py"
        self.assertIsNone(self.cls(path=guard, operations=["safety_test_add"], safety_intent="strengthen"))
        self.assertEqual(self.cls(path=guard, operations=["bug_fix"])[0], "SAFETY_BOUNDARY_TERMS")
        self.assertEqual(self.cls(path=guard, operations=["code_edit"], safety_intent="preserve")[0],
                         "SAFETY_BOUNDARY_TERMS")
        no_suite = sw.code_task("t", path=guard, extra={"operations": ["bug_fix"], "safety_intent": "preserve",
                                                        "test_commands": ["python3 -m unittest x"]})
        self.assertEqual(st.classify_task(no_suite, self.policy)[0], "SAFETY_BOUNDARY_TERMS")
        self.assertEqual(self.cls(path=guard, operations=["safety_guard_disable"])[0], "HUMAN_OPERATION")

    def test_execution_config_needs_a_human(self):
        code, _, human = self.cls(path=".github/workflows/ci.yml")
        self.assertEqual((code, human), ("PROTECTED_PATH", True))

    def test_objective_cannot_cover_execution_config(self):
        with self.assertRaises(ValueError):
            sw.planner_campaign("bad", [sw.objective("o1", [".github/"])])
        with self.assertRaises(ValueError):
            sw.planner_campaign("bad", [sw.objective("o1", [DEMO], ops=["merge"])])


# ---------------------------------------------------------------- planner-created issue identity
class PlannedIssueTests(unittest.TestCase):
    def setUp(self):
        self.w = world_with([sw.signal("s1", "o1", f"{DEMO}a.py")], recovery_wake=False)
        self.c = self.w.campaign
        d = planner.plan_next(campaign=self.c, signals=self.w.backlog, known=[])
        self.title, self.body, self.task = planner.build_task(d.proposal, campaign=self.c, base_head=sw.MAIN,
                                                               now="2026-10-10T00:00:00Z")

    def step(self, body=None, author=sw.OWNER, **snap):
        n = self.w.gh.create_issue(self.title, body or self.body, author=author)
        s = {"repository": self.c["repository"], "now": "2026-10-10T00:05:00Z",
             "candidate": self.w.gh.read_issue(n), "base_head": sw.MAIN, "base_changed_paths": [],
             "active_tasks": [], "quota": {"state": "UNKNOWN"}, "route_observation": self.w.route(),
             "known_tasks": [], "task_states": {}, "pending_merge": [], "event": {}}
        s.update(snap)
        return st.next_step(s, campaign=self.c, controller="x")

    def test_valid_planned_issue_starts(self):
        s = self.step()
        self.assertEqual(s.action, st.WRITE_INTENT)
        self.assertIn("objective", s.checks)

    def test_edited_untrusted_out_of_scope_and_duplicate(self):
        self.assertEqual(self.step(body=self.body.replace("regression test", "nothing")).code, "EDITED")
        self.assertEqual(self.step(author="mallory").code, "UNTRUSTED_AUTHOR")
        moved = self.body.replace(f"{DEMO}a.py", "elsewhere/a.py")
        self.assertIn(self.step(body=moved).code, {"EDITED", "OUT_OF_SCOPE", "METADATA"})
        fp = self.task["campaign"]["fingerprint"]
        dup = self.step(known_tasks=[{"issue": 1, "fingerprint": fp, "state": "RUNNING"}])
        self.assertEqual(dup.code, "DUPLICATE")


# ---------------------------------------------------------------- E. no silent DEFER
class DeferLedgerTests(unittest.TestCase):
    def test_defer_is_recorded_kept_and_escalated(self):
        w = world_with([sw.signal("s1", "o1", f"{DEMO}a.py")], recovery_wake=True)
        w._quota = {"state": st.QUOTA_EXHAUSTED, "reset_at": st._fmt(w.now + timedelta(days=2))}
        w.deliver({"name": "start"})
        first = w.ticks[-1]
        self.assertEqual(first.outcome, loop.DEFER)
        d = first.defers[0]
        for key in ("reason", "task_id", "code", "state", "first_seen_at", "last_checked_at", "next_check",
                    "recovery_action", "dependency", "independent_work_remaining", "human_required"):
            self.assertIn(key, d)
        self.assertEqual(d["code"], "QUOTA_EXHAUSTED")
        self.assertTrue(first.checkpoint_written)
        w.tick(30)
        w.deliver({"name": "schedule"})                      # the created task now appears in the state
        writes_before = sum(1 for c in w.gh.issues[w.control]["comments"])
        for _ in range(3):                                   # same state: no new checkpoint comment
            w.tick(30)
            w.deliver({"name": "schedule"})
        self.assertEqual(sum(1 for c in w.gh.issues[w.control]["comments"]), writes_before)
        self.assertEqual(w.ticks[-1].defers[0]["first_seen_at"], d["first_seen_at"])
        w.tick(300)                                          # older than defer_escalate_minutes, nothing else to do
        w.deliver({"name": "schedule"})
        last = w.ticks[-1]
        self.assertTrue(last.defers[0]["escalated"] and last.defers[0]["human_required"])
        self.assertTrue(any(h["action"] == "look at a long DEFER" for h in last.human_actions))
        self.assertTrue(last.checkpoint_written)
        self.assertEqual(sum(labeled(w, n) for n in w.gh.issues), 0)
        # quota resets: the next wake resumes without a human
        w._quota = {"state": st.QUOTA_OK}
        w.deliver({"name": "schedule"})
        w.run_until_quiet(merge_policy=merge_all_passed)
        self.assertEqual(w.ticks[-1].outcome, loop.GOAL_COMPLETE)


# ---------------------------------------------------------------- recovery
class LoopRecoveryTests(unittest.TestCase, LoopInvariants):
    def sigs(self, n=4):
        return [sw.signal(f"s{k}", "o1", f"{DEMO}m{k}.py") for k in range(1, n + 1)]

    def finish(self, w):
        w.run_until_quiet(merge_policy=merge_all_passed)
        self.assertEqual(w.ticks[-1].outcome, loop.GOAL_COMPLETE)
        self.assert_safe(w)

    def test_claude_dies_after_creating_the_issue(self):
        w = world_with(self.sigs())
        w.gh.inject("create", "crash_after")
        w.deliver({"name": "start"})
        self.assertEqual(w.loop_crashes, 1)
        self.finish(w)                                         # the schedule wake finds the PREPARED issue

    def test_issue_creation_response_lost_is_not_duplicated(self):
        w = world_with(self.sigs())
        w.gh.inject("create", "lost")
        w.deliver({"name": "start"})
        self.finish(w)

    def test_claude_dies_after_the_intent_and_label(self):
        w = world_with(self.sigs())
        w.gh.inject("comment", "crash_after", when=lambda i, b: st.INTENT_MARKER in b)
        w.gh.inject("label", "crash_after")
        w.deliver({"name": "start"})
        self.finish(w)

    def test_without_a_recovery_wake_a_dead_run_waits_for_a_human(self):
        w = world_with(self.sigs(), recovery_wake=False)
        w.gh.inject("create", "crash_after")
        w.deliver({"name": "start"})
        w.run()
        w.deliver({"name": "schedule"})                       # no schedule trigger: nothing happens
        self.assertEqual(sum(w.jules_starts.values()), 0)
        w.deliver({"name": "start"})                          # the human's "run now" recovers it
        w.recovery_wake = True
        self.finish(w)

    def test_lost_pr_event_is_reviewed_by_the_recovery_wake(self):
        w = world_with(self.sigs(2))
        w.deliver({"name": "start"})
        dropped = 0
        while w.gh.events:                                     # the first PR event never reaches the Routine
            e = w.gh.events.popleft()
            if e["name"] == "pull_request.opened" and not dropped:
                dropped += 1
                continue
            w.deliver(e)
        self.assertEqual(dropped, 1)
        self.assertEqual(sum(1 for n in w.gh.issues if passed(w, n)), 0)   # stuck: nobody reviewed the PR
        self.finish(w)

    def test_transient_read_failures_are_retried_then_deferred(self):
        w = world_with(self.sigs(2))
        w.read_failures = 2                                    # fewer than the retry attempts: no visible effect
        w.deliver({"name": "start"})
        self.assertEqual(w.ticks[-1].outcome, loop.CONTINUE)
        w.read_failures = 10
        w.deliver({"name": "schedule"})
        self.assertEqual(w.ticks[-1].outcome, loop.DEFER)
        w.read_failures = 0
        self.finish(w)

    def test_paid_route_stops_new_starts_only(self):
        w = world_with(self.sigs(2))
        w._route = {"transport": "carrier-rest-api-key", "auth_method": "api_key", "billing_route": "metered"}
        w.gh.create_issue("unrelated", "x")
        d = planner.plan_next(campaign=w.campaign, signals=w.backlog, known=[])
        title, body, _ = planner.build_task(d.proposal, campaign=w.campaign, base_head=sw.MAIN,
                                            now=st._fmt(w.now))
        w.gh.create_issue(title, body)
        w.deliver({"name": "start"})
        self.assertEqual(w.ticks[-1].outcome, loop.HARD_STOP_PROVIDER)
        self.assertEqual(sum(w.jules_starts.values()), 0)
        w._route = {"transport": st.ROUTE, "auth_method": "account_oauth", "billing_route": "subscription"}
        self.finish(w)

    def test_one_isolated_task_does_not_stop_the_others(self):
        sigs = self.sigs(3) + [sw.signal("human", "o1", f"{DEMO}h.py",
                                         acceptance_criteria=["Merge the pull request into main", "x"])]
        w = world_with(sigs)
        w.deliver({"name": "start"})
        w.run_until_quiet(merge_policy=merge_all_passed)
        by = tasks_by_signal(w)
        self.assertEqual(labeled(w, by["human"][0]), 0)
        self.assertTrue(all(passed(w, by[f"s{k}"][0]) for k in (1, 2, 3)))
        self.assertEqual(w.ticks[-1].outcome, loop.NO_SAFE_TASK)
        self.assertTrue(any(h.get("code") == "CLASSIFICATION_MISMATCH" for h in w.ticks[-1].human_actions))
        self.assert_safe(w)

    def test_duplicate_webhooks_and_correctives(self):
        sigs = self.sigs(6)
        w = world_with(sigs, duplicate_every=2,
                       review_script={(f"pl-{st.task_fingerprint('o1', 's3', [f'{DEMO}m3.py'])[:10]}", 1):
                                      review.NEEDS_CORRECTION})
        w.deliver({"name": "start"})
        self.finish(w)
        n3 = tasks_by_signal(w)["s3"][0]
        self.assertEqual([r["verdict"] for r in w.receipts(n3)], [review.NEEDS_CORRECTION, review.PASS])


# ---------------------------------------------------------------- the prepared two-task LIVE proof, rehearsed
class PrdC2RehearsalTests(unittest.TestCase, LoopInvariants):
    def test_prd_c2_runs_a_then_b_automatically_without_merge(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        c2 = json.loads((root / "docs/evidence/claude-jules-production-starter-20261009/campaign-prd-c2.json")
                        .read_text(encoding="utf-8"))
        w = sw.LoopWorld(c2, [], review_script={("prd-002", 1): review.NEEDS_CORRECTION})
        w.main_head = c2["tasks"][0]["body"].split('"expected_target_head":"')[1][:40]
        w.main_history = [(w.main_head, [])]
        w.gh.next_number = 335                          # the predecessor is pinned to issue #335 (GRD-001)
        seed, first = sw.seed_predecessor(w, c2)
        self.assertEqual(seed, 335)
        w.gh.events.clear()
        w.deliver({"name": "start"})                    # the human's go: the first tick starts A (#first)
        self.assertEqual(w.ticks[-1].started, [first])
        w.run_until_quiet()
        a_issue, b_issue = first, w.issue_by_correlation("prd-002-702497c")
        self.assertIsNotNone(b_issue)                   # created by the reviewer from body_ref on A's PASS
        self.assertTrue(passed(w, a_issue) and passed(w, b_issue))
        self.assertEqual([r["verdict"] for r in w.receipts(b_issue)], [review.NEEDS_CORRECTION, review.PASS])
        self.assertFalse(w.pr_merged(a_issue))          # B started while A was still unmerged
        self.assertEqual(w.ticks[-1].outcome, loop.MERGE_WAIT)
        self.assert_safe(w)
        self.assertEqual(sum(w.jules_starts.values()), 2)


# ---------------------------------------------------------------- endurance
class LoopEnduranceTests(unittest.TestCase, LoopInvariants):
    def run_endurance(self, rounds, seed):
        rng = random.Random(seed)
        objectives = [sw.objective("fix", [DEMO + "fix/"], priority=1),
                      sw.objective("tests", [DEMO + "tests/"], priority=2)]
        sigs = []
        for k in range(1, rounds + 1):
            oid = "fix" if k % 3 else "tests"
            sig = sw.signal(f"e{k}", oid, f"{DEMO}{oid}/m{k}.py",
                            kind=rng.choice(["failing_test", "known_bug", "missing_test", "todo"]))
            if k > 3 and rng.random() < 0.15:
                sig["depends_on_signals"] = [f"e{rng.randint(1, k - 1)}"]
            sigs.append(sig)
        sigs.append(sw.signal("human-op", "fix", f"{DEMO}fix/h.py",
                              acceptance_criteria=["Enable auto-merge for this repository", "x"]))
        late = sigs[rounds // 2:]
        w = world_with(sigs[:rounds // 2], objectives=objectives, duplicate_every=5)
        fps = {}
        for s in sigs:
            fps[s["signal_id"]] = f"pl-{st.task_fingerprint(s['objective_id'], s['signal_id'], s['paths'])[:10]}"
        w.review_script = {(fps[s["signal_id"]], 1): review.NEEDS_CORRECTION for s in sigs if rng.random() < 0.2}
        modes = ["lost", "timeout_unapplied", "crash_before", "crash_after"]
        injected = 0

        def inject_some():
            # faults arrive spread over time; a storm queued at once hits one issue 5 times in a row, which the
            # starter correctly isolates after max_label_attempts
            nonlocal injected
            if injected < rounds // 2 and rng.random() < 0.5:
                injected += 1
                op = rng.choice(["comment", "label", "create"])
                w.gh.inject(op, rng.choice(modes), when=None if op != "comment" else
                            (lambda i, b, k=rng.random(): k < 0.5 or st.INTENT_MARKER in b))

        w.deliver({"name": "start"})
        merges = 0

        def human(world):
            nonlocal merges
            ready = merge_all_passed(world)
            if ready and rng.random() < 0.6:
                merges += 1
                return ready[:rng.randint(1, len(ready))]
            return []

        for step in range(rounds * 6):
            if step == rounds and late:
                w.backlog.extend(late)                    # more work is discovered while the loop runs
                late = []
            if rng.random() < 0.05:
                w.read_failures = rng.randint(1, 5)
            inject_some()
            w.run()
            for n in human(w):
                w.human_merge(n)
            w.tick(rng.choice([20, 60, 90]))
            before = len(w.ticks)
            w.deliver({"name": "schedule"})
            fresh = len(w.ticks) > before                 # a crashed wake leaves no result: never judge on it
            if fresh and not late and w.ticks and w.ticks[-1].outcome in {loop.NO_SAFE_TASK, loop.GOAL_COMPLETE} \
                    and not w.gh.events and not merge_all_passed(w) and injected >= rounds // 2:
                break
        w.faults_injected = injected
        return w, merges

    def check(self, w, rounds):
        by = tasks_by_signal(w)
        done = [s for s in by if s != "human-op" and w.pr_merged(by[s][0])]
        self.assertEqual(len(done), rounds, sorted(set(f"e{k}" for k in range(1, rounds + 1)) - set(done)))
        self.assertEqual(labeled(w, by["human-op"][0]), 0)
        self.assertEqual(w.ticks[-1].outcome, loop.NO_SAFE_TASK)       # only the human-boundary task is left
        self.assertEqual(w.faults_injected, rounds // 2)
        fired = w.faults_injected - len(w.gh.faults)   # a fault injected after the last write never fires
        self.assertGreaterEqual(fired, int(0.8 * w.faults_injected))
        w.faults_fired = fired
        self.assert_safe(w)

    def test_forty_round_planner_loop_with_faults_merges_and_new_work(self):
        w, merges = self.run_endurance(40, 7)
        self.check(w, 40)
        self.assertGreater(w.loop_crashes, 0)
        self.assertGreater(merges, 1)

    def test_hundred_round_planner_loop(self):
        w, _ = self.run_endurance(100, 11)
        self.check(w, 100)


if __name__ == "__main__":
    unittest.main()
