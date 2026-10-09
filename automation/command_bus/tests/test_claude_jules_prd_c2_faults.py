"""PRD-C2 (the prepared two-task LIVE proof) under every required fault, in the mock.

The chain is A start → PR A → review A → PASS A → B created → Starter → B start → PR B → review B → PASS B,
with no human step and no Merge.  The only wakes are the ones production has:

* pull_request events (reviewer, then a loop tick);
* pull_request.closed (merged);
* the human's first start;
* the recovery schedule.

The schedule is not configured yet; it is a human decision. Each scenario checks:

* no issue is labeled twice and no Jules task starts twice;
* no write outside the allowed record kinds;
* A and B both PASS without a Merge;
* with no recovery wake, the stall is visible and reported, never silent.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path

from automation.command_bus import claude_closed_loop_review as review
from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus.tests import starter_world as sw
from automation.command_bus.tests.test_claude_jules_loop import LoopInvariants, labeled, passed

ROOT = Path(__file__).resolve().parents[3]
C2_PATH = ROOT / "docs/evidence/claude-jules-production-starter-20261009/campaign-prd-c2.json"
MAIN702 = "702497c6b464a3b1ab09441b21fc6f96bd3bb2d0"


def c2(depends=False):
    manifest = json.loads(C2_PATH.read_text(encoding="utf-8"))
    if not depends:
        return manifest
    tasks = []
    for e in manifest["tasks"]:
        task = {k: v for k, v in st._task_of(e["body"])[0].items() if k not in {"campaign", "next_task", "loop_id"}}
        if task["task_id"] == "prd-002":
            task["depends_on"] = ["prd-001"]
        tasks.append({"title": e["title"], "intro": e["body"].split(st.TASK_MARKER)[0], "task": task})
    return st.build_campaign(campaign_id="prd-c2-dep", loop_id=manifest["loop_id"], tasks=tasks,
                             policy=manifest["policy"], external_predecessor={"task_id": "grd-001",
                                                                              "correlation_id": "grd-001-8fbbef9",
                                                                              "issue": 335},
                             manifest_ref={"path": "x", "ref": "y"})


def world(manifest=None, **kw):
    manifest = manifest or c2()
    w = sw.LoopWorld(manifest, [], **kw)
    w.main_head = MAIN702
    w.main_history = [(MAIN702, [])]
    w.gh.next_number = 335
    seed, first = sw.seed_predecessor(w, manifest)
    w.gh.events.clear()
    w.a_issue = first
    return w


class FaultMatrix(unittest.TestCase, LoopInvariants):
    def b_issue(self, w):
        return w.issue_by_correlation("prd-002-702497c")

    def finish(self, w, *, merges=False):
        w.run_until_quiet(merge_policy=(lambda x: []) if not merges else None)
        a, b = w.a_issue, self.b_issue(w)
        self.assertIsNotNone(b, w.log[-5:])
        self.assertTrue(passed(w, a) and passed(w, b), w.log[-6:])
        self.assertFalse(w.pr_merged(a))                    # B never needed A merged
        self.assertEqual(sum(w.jules_starts.values()), 2)
        self.assertEqual(w.ticks[-1].outcome, loop.MERGE_WAIT)
        self.assert_safe(w)
        return w

    def on_task(self, w, tid, marker=None):
        return lambda issue, body: (w.task_of(issue) or {}).get("task_id") == tid and (marker is None or marker in body)

    def start(self, w):
        w.deliver({"name": "start"})
        return w

    # -- reviewer / Routine deaths
    def test_reviewer_dies_before_reviewing_a(self):
        w = world()
        w.reviewer_crashes.add(("prd-001", "start"))
        self.finish(self.start(w))
        self.assertGreaterEqual(w.loop_crashes, 1)

    def test_restart_after_pass_receipt_before_the_tick(self):
        w = world()
        w.reviewer_crashes.add(("prd-001", "after_receipt"))
        self.finish(self.start(w))

    def test_claude_dies_after_creating_b(self):
        w = world()
        w.reviewer_crash_after_next_issue.add("prd-001")
        self.finish(self.start(w))

    # -- starter deaths and lost responses on B
    def test_starter_dies_after_b_intent(self):
        w = world()
        w.gh.inject("comment", "crash_after", when=self.on_task(w, "prd-002", st.INTENT_MARKER))
        self.finish(self.start(w))

    def test_starter_dies_before_b_label(self):
        w = world()
        w.gh.inject("label", "crash_before", when=self.on_task(w, "prd-002"))
        self.finish(self.start(w))

    def test_b_label_response_lost(self):
        w = world()
        w.gh.inject("label", "lost", when=self.on_task(w, "prd-002"))
        self.finish(self.start(w))

    def test_b_intent_response_lost(self):
        w = world()
        w.gh.inject("comment", "lost", when=self.on_task(w, "prd-002", st.INTENT_MARKER))
        self.finish(self.start(w))

    def test_b_start_receipt_response_lost(self):
        w = world()
        w.gh.inject("comment", "lost", when=self.on_task(w, "prd-002", st.START_RECEIPT_MARKER))
        self.finish(self.start(w))

    def test_restart_after_b_label(self):
        w = world()
        w.gh.inject("label", "crash_after", when=self.on_task(w, "prd-002"))
        self.finish(self.start(w))

    def test_restart_after_a_label(self):
        w = world()
        w.gh.inject("label", "crash_after", when=self.on_task(w, "prd-001"))
        self.finish(self.start(w))

    # -- events
    def test_duplicate_pr_events_and_duplicate_wakes(self):
        w = world(duplicate_every=1)
        self.start(w)
        w.deliver({"name": "start"})
        w.deliver({"name": "schedule"})
        self.finish(w)

    def test_lost_pr_event(self):
        w = world()
        self.start(w)
        dropped = False
        while w.gh.events:
            e = w.gh.events.popleft()
            if e["name"] == "pull_request.opened" and not dropped:
                dropped = True                        # dropped over the hourly cap
                continue
            w.deliver(e)
        self.assertTrue(dropped)
        self.finish(w)

    # -- GitHub outages and quota
    def test_github_read_outage(self):
        w = world()
        w.read_failures = 10
        self.start(w)
        self.assertEqual(w.ticks[-1].outcome, loop.DEFER)
        self.finish(w)

    def test_github_write_outage(self):
        w = world()
        w.gh.write_outage = True
        self.start(w)
        w.tick(60)
        w.deliver({"name": "schedule"})
        self.assertEqual(sum(w.jules_starts.values()), 0)
        w.gh.write_outage = False
        self.finish(w)

    def test_quota_exhausted_then_reset_without_any_new_pr_event(self):
        w = world()
        w._quota = {"state": st.QUOTA_EXHAUSTED, "reset_at": st._fmt(w.now + timedelta(hours=3))}
        self.start(w)
        self.assertEqual(w.ticks[-1].defers[0]["code"], "QUOTA_EXHAUSTED")
        w.tick(240)
        w._quota = {"state": st.QUOTA_OK}
        self.finish(w)                                 # only the recovery schedule can resume it

    # -- records
    def test_edited_b_issue_is_isolated_and_reported(self):
        w = world()
        w.reviewer_crash_after_next_issue.add("prd-001")
        self.start(w)
        w.run()
        b = self.b_issue(w)
        w.gh.issues[b]["body"] = w.gh.issues[b]["body"].replace("encoding", "codec")
        w.run_until_quiet()
        self.assertEqual(labeled(w, b), 0)
        last = w.ticks[-1]
        self.assertIn(last.outcome, {loop.MERGE_WAIT, loop.NO_SAFE_TASK})   # A waits for Merge; B is isolated
        self.assertTrue(any(i["code"] == "EDITED" for i in last.isolated))
        self.assertTrue(any(h.get("code") == "EDITED" for h in last.human_actions))
        self.assert_safe(w)

    def test_malformed_receipt_stops_only_with_a_visible_record(self):
        w = world()
        w.gh.comment(w.a_issue, review.RECEIPT_MARKER + "\n{broken\n-->")
        self.start(w)
        for _ in range(4):                              # the loop keeps waking; it must not write over the record
            w.run()
            w.tick(60)
            w.deliver({"name": "schedule"})
        self.assertIsNone(self.b_issue(w))             # the reviewer never writes over a broken record
        last = w.ticks[-1]
        self.assertTrue(any(d["code"] == "RECORD_UNREADABLE" and d["human_required"] for d in last.defers))
        self.assert_safe(w)

    def test_merge_dependency_waits_then_resumes_on_the_merged_event(self):
        w = world(c2(depends=True))
        self.start(w)
        for _ in range(3):
            w.run()
            w.tick(60)
            w.deliver({"name": "schedule"})
        b = w.issue_by_correlation("prd-002-702497c")
        self.assertEqual(labeled(w, b), 0)
        self.assertEqual(w.ticks[-1].outcome, loop.DEFER)
        self.assertTrue(any(d["code"] == "MERGE_WAIT" and d["human_required"] for d in w.ticks[-1].defers))
        w.human_merge(w.a_issue)                       # the human merges A; the merged event resumes B
        w.recovery_wake = False                        # proven to resume on the merged event alone
        w.run()
        self.assertTrue(passed(w, b))
        self.assertEqual(sum(w.jules_starts.values()), 2)
        self.assert_safe(w)

    # -- the recovery wake itself
    def test_no_new_pr_event_after_a_crash_needs_the_recovery_wake(self):
        for recovery in (False, True):
            with self.subTest(recovery_wake=recovery):
                w = world(recovery_wake=recovery)
                w.reviewer_crashes.add(("prd-001", "after_receipt"))
                self.start(w)
                w.run()
                for _ in range(6):
                    w.tick(60)
                    w.deliver({"name": "schedule"})
                    w.run()
                b = self.b_issue(w)
                if recovery:
                    self.assertTrue(passed(w, b))
                else:
                    self.assertEqual(labeled(w, b), 0)      # stuck: nothing wakes the loop
                    self.assertEqual(sum(w.jules_starts.values()), 1)
                self.assert_safe(w)


if __name__ == "__main__":
    unittest.main()
