"""Mock end-to-end: Jules -> PR -> reviewer -> (corrective) -> PASS -> next issue -> Production Starter -> label ...

No model and no network: ``starter_world`` simulates GitHub, Jules and the reviewer Routine (with the real
reviewer code).  Every scenario checks the one invariant that matters: **no issue ever gets a second
``labeled jules`` event, so no task ever becomes two Jules tasks**.
"""
from __future__ import annotations

import random
import unittest
from datetime import timedelta

from automation.command_bus import claude_closed_loop_review as review
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus.tests import starter_world as sw


def labeled(world, n):
    return sum(1 for e in world.gh.issues[n]["label_events"] if e["event"] == "labeled" and e["label"] == st.LABEL)


def campaign_issues(world, cid):
    out = {}
    for n in sorted(world.gh.issues):
        t = world.task_of(n)
        meta = (t or {}).get("campaign")
        if isinstance(meta, dict) and meta.get("campaign_id") == cid:
            out[meta["seq"]] = n
    return out


class Invariants:
    def assert_never_double_started(self, world):
        for n in world.gh.issues:
            self.assertLessEqual(labeled(world, n), 1, f"issue #{n} labeled twice")
            self.assertLessEqual(world.jules_starts[n], 1, f"Jules started twice for #{n}")

    def passes(self, world, cid):
        issues = campaign_issues(world, cid)
        return {seq: n for seq, n in issues.items()
                if any(r["verdict"] == review.PASS for r in world.receipts(n))}


class MultiRoundE2ETests(unittest.TestCase, Invariants):
    def test_twelve_rounds_with_corrective_restarts_duplicates_and_blocked_isolation(self):
        a = sw.campaign("ca", 12)
        b = sw.campaign("cb", 3, extras={2: {"acceptance_criteria": [
            "Merge the pull request into main when it is green", "a regression test is added"]}})
        world = sw.World([a, b], review_script={("ca-t4", 1): review.NEEDS_CORRECTION,
                                                ("ca-t9", 1): review.NEEDS_CORRECTION},
                         duplicate_every=3)
        gh = world.gh

        def task_issue(task_id):
            return lambda issue, body: task_id in (gh.issues.get(issue, {}).get("title", "") + body) or \
                (world.task_of(issue) or {}).get("task_id") == task_id

        # faults spread over the campaign (each fires once)
        gh.inject("comment", "crash_after", when=task_issue("ca-t3"))        # crash right after the intent
        gh.inject("label", "lost", when=task_issue("ca-t5"))                 # label applied, response lost
        gh.inject("label", "timeout_unapplied", when=task_issue("ca-t7"))   # label not applied, timeout
        gh.inject("label", "crash_after", when=task_issue("ca-t8"))         # label applied, crash before receipt
        world.reviewer_crash_after_next_issue.add("ca-t10")                  # reviewer dies after creating #next

        sw.seed_predecessor(world, a)
        sw.seed_predecessor(world, b)
        world.run()
        world.settle()
        # duplicate PASS event replay and a stale controller on every started issue
        for n in list(gh.issues):
            for c in list(gh.issues[n]["comments"]):
                if review.RECEIPT_MARKER in c["body"]:
                    world.starter_wake({"name": "issue_comment.created", "issue": n, "author": sw.OWNER,
                                        "body": c["body"]})
            if st.LABEL in gh.issues[n]["labels"] and world.campaign_for(n):
                res = world.run_controller(n, controller="stale-old-controller")
                self.assertIn(res.steps[-1].action, {st.NO_OP, st.BLOCKED})
        world.run()

        # the reviewer crash left t11's issue without a receipt; the PR event is redelivered (as GitHub retries)
        t10 = campaign_issues(world, "ca").get(10)
        self.assertIsNotNone(t10)
        self.assertFalse(any(r["verdict"] == review.PASS for r in world.receipts(t10)))
        world.deliver({"name": "pull_request.synchronize", "pr": world.jules_pr[t10]})
        world.run()
        world.settle()

        passed = self.passes(world, "ca")
        self.assertEqual(sorted(passed), list(range(1, 13)))
        self.assert_never_double_started(world)

        # campaign B: t1 passed, t2 is a human-boundary task -> isolated, t3 never prepared
        b_issues = campaign_issues(world, "cb")
        self.assertIn(1, self.passes(world, "cb"))
        self.assertEqual(labeled(world, b_issues[2]), 0)
        self.assertNotIn(3, b_issues)
        snap = world.snapshot(b_issues[2], None, "cb")
        self.assertEqual(st.next_step(snap, campaign=b, controller="x").action, st.BLOCKED)

        # corrective rounds really happened through @jules
        t4 = campaign_issues(world, "ca")[4]
        self.assertEqual([r["verdict"] for r in world.receipts(t4)], [review.NEEDS_CORRECTION, review.PASS])
        pr4 = gh.prs[world.jules_pr[t4]]
        self.assertTrue(any(c["body"].startswith("@jules") for c in pr4["comments"]))
        # the takeover after the intent crash used attempt 2; the unapplied label too
        for seq in (3, 7):
            intents, _ = st.starter_records(gh.issues[campaign_issues(world, "ca")[seq]]["comments"], {sw.OWNER})
            self.assertEqual([i["attempt"] for i in intents], [1, 2], seq)
        self.assertGreaterEqual(sum(len(world.receipts(n)) for n in gh.issues), 15)
        self.assertEqual(gh.faults, [])                       # every injected fault really fired
        self.assertTrue(any("crashed" in line for line in world.log))

    def test_quota_exhaustion_pauses_and_reset_resumes(self):
        a = sw.campaign("cq", 4)
        world = sw.World([a])
        sw.seed_predecessor(world, a)
        world.run()
        self.assertEqual(sorted(self.passes(world, "cq")), [1, 2, 3, 4])
        # a new campaign while quota is exhausted
        c = sw.campaign("cr", 3)
        world2 = sw.World([c])
        reset = world2.now + timedelta(hours=5)
        world2.quota = {"state": st.QUOTA_EXHAUSTED, "reset_at": st._fmt(reset), "evidence": "Jules usage limit"}
        sw.seed_predecessor(world2, c)
        world2.settle(rounds=3, minutes=30)
        self.assertEqual(self.passes(world2, "cr"), {})
        self.assertTrue(all(labeled(world2, n) == 0 for n in campaign_issues(world2, "cr").values()))
        world2.now = reset + timedelta(minutes=1)
        world2.deliver({"name": "schedule"})
        world2.run()
        self.assertEqual(sorted(self.passes(world2, "cr")), [1, 2, 3])
        self.assert_never_double_started(world2)

    def test_two_independent_campaigns_share_one_concurrency_slot(self):
        a, b = sw.campaign("cx", 5), sw.campaign("cy", 5)
        world = sw.World([a, b])
        sw.seed_predecessor(world, a)
        sw.seed_predecessor(world, b)
        max_active = 0
        while world.step_one():
            max_active = max(max_active, len(world.active_tasks()))
        world.settle()
        self.assertEqual(max_active, 1)            # never two campaign tasks running at once (seeds are terminal)
        self.assertEqual(sorted(self.passes(world, "cx")), [1, 2, 3, 4, 5])
        self.assertEqual(sorted(self.passes(world, "cy")), [1, 2, 3, 4, 5])
        self.assert_never_double_started(world)

    def test_budget_exhausted_task_is_isolated(self):
        a = sw.campaign("cz", 3)
        world = sw.World([a], review_script={("cz-t2", r): review.NEEDS_CORRECTION for r in range(1, 6)})
        sw.seed_predecessor(world, a)
        world.run()
        world.settle()
        issues = campaign_issues(world, "cz")
        self.assertEqual(world.receipts(issues[2])[-1]["decision"], "TASK_BLOCKED")
        self.assertNotIn(3, issues)                # its successor is never prepared or started
        self.assert_never_double_started(world)


class EnduranceTests(unittest.TestCase, Invariants):
    def test_forty_round_campaign_under_random_faults(self):
        rng = random.Random(20261009)
        a = sw.campaign("ce", 40)
        script = {(f"ce-t{k}", 1): review.NEEDS_CORRECTION for k in range(1, 41) if rng.random() < 0.25}
        world = sw.World([a], review_script=script, duplicate_every=4)
        modes = ["lost", "timeout_unapplied", "crash_before", "crash_after"]
        for k in rng.sample(range(1, 41), 30):          # one fault per task (two on one task exhaust attempts)
            op = rng.choice(["comment", "label"])
            world.gh.inject(op, rng.choice(modes),
                            when=lambda issue, body, tid=f"ce-t{k}": (world.task_of(issue) or {}).get("task_id") == tid)
        sw.seed_predecessor(world, a)
        for _ in range(60):
            world.run(schedule_every=7)
            world.tick(20)
            world.deliver({"name": "schedule"})
            if len(self.passes(world, "ce")) == 40:
                break
        self.assertEqual(sorted(self.passes(world, "ce")), list(range(1, 41)))
        self.assertEqual(world.gh.faults, [])
        self.assert_never_double_started(world)
        corrected = [int(tid.rsplit("-t", 1)[1]) for (tid, _r) in script]
        for k in corrected:
            n = campaign_issues(world, "ce")[k]
            self.assertEqual(world.receipts(n)[0]["verdict"], review.NEEDS_CORRECTION)


if __name__ == "__main__":
    unittest.main()
