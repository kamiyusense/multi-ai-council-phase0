"""Production MVP rehearsal: one human approval, then the loop runs task after task by itself.

Every wake is a NEW ``GhLiveWritePort`` (fresh per-wake counters) over a mock GitHub, with a production-style V2
budget (its own ledger, slot creation enabled by the declaration) and a campaign-wide V2 authorization.  The
planner picks each next task from the signals; the simulated Reviewer (PASS / corrective) and Jules (PR, fix)
drive it.  Faults: a corrective round, a process killed right after a label, transient GitHub read failures,
duplicated webhooks, one task that must be isolated, a stale controller coming back, a session that ends, a
confirmed subscription-usage exhaustion (WAIT, then resume), and the human's stop switch.

Nothing real is called: no GitHub, no Jules, no model.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from types import SimpleNamespace

from automation.command_bus import claude_closed_loop_review as review
from automation.command_bus import claude_jules_durable_budget as db
from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_gh as ghs
from automation.command_bus import claude_jules_starter_live as live
from automation.command_bus.tests import budget_fixtures as bf
from automation.command_bus.tests import starter_world as sw
from automation.command_bus.tests.test_claude_jules_starter_live import REPO, ROUTE, Api, Runner

DEMO = "automation/command_bus/demo/"


def labeled(world, n):
    return sum(1 for e in world.gh.issues[n]["label_events"] if e["event"] == "labeled" and e["label"] == st.LABEL)


def passed(world, n):
    return any(r["verdict"] == review.PASS for r in world.receipts(n))


class Harness:
    """A LoopWorld whose every tick runs through the real LIVE adapter, budget and planner."""

    def __init__(self, signals, *, review_script=None, duplicate_every=0, cap=50):
        self.campaign = sw.planner_campaign("prod-test", [sw.objective("o1", [DEMO])])
        self.w = sw.LoopWorld(self.campaign, signals, review_script=review_script, duplicate_every=duplicate_every)
        self.ledger = bf.LedgerStore(real_slots=0)
        self.decl = bf.declaration_v2(cap=cap)
        self.auth = {"profile": live.AUTH_PROFILE_V2, "campaign_id": "prod-test", "repository": REPO,
                     "budget_id": self.decl["budget_id"], "issues": "campaign",
                     "writes": ["comment", "add_label", "create_issue"], "max_labels": 1, "max_activations": cap,
                     "max_writes": 12, "expires_at": "2099-01-01T00:00:00Z", "approved_by": "test-human",
                     "approval_ref": "campaign approval", "route": st.ROUTE, "billing": "subscription",
                     "usage_credits_confirmed_off": True}
        self.ports, self.crash_after_label, self.read_faults, self.quota = [], 0, 0, None
        self.w.tick_loop = self.tick_loop

    def api(self):
        base = Api(self.w)

        def get(path):
            if self.read_faults:
                self.read_faults -= 1
                raise ghs.ReadFailed("HTTP 502 (injected)", 502)
            if self.quota and path.endswith(f"/issues/{self.w.control}/comments?per_page=100"):
                return base(path) + [self.quota]
            return base(path)
        return get

    def runner(self):
        h = self

        class Killing(Runner):
            def __call__(self, cmd, payload):
                proc = super().__call__(cmd, payload)
                if cmd[4].endswith("/labels") and h.crash_after_label:
                    h.crash_after_label -= 1
                    raise sw.Crash("process killed right after the label landed")
                return proc
        return Killing(self.w)

    def port(self):
        return live.GhLiveWritePort(self.api(), repo=REPO, campaign=self.campaign, route_declaration=ROUTE,
                                    signals=[dict(s) for s in self.w.backlog], authorization=self.auth,
                                    runner=self.runner(), now=lambda: st._fmt(self.w.now),
                                    budget=db.DurableBudget(self.ledger, self.decl, repository=REPO))

    def tick_loop(self, wake):
        self.w.controllers += 1
        port = self.port()
        self.ports.append(port)
        try:
            res = loop.run_tick(port, campaign=self.campaign, controller=f"routine-{self.w.controllers}",
                                now=lambda: st._fmt(self.w.now))
        except sw.Crash as exc:
            self.w.loop_crashes += 1
            self.w.log.append(f"tick crashed: {exc}")
            return
        except loop.TransientRead:
            res = loop.TickResult(loop.DEFER, "read failed")
        except st.PreparedOnly:
            res = SimpleNamespace(outcome="PREPARED", started=[], isolated=[], defers=[])
        self.w.ticks.append(res)

    def task_issues(self):
        return [n for n in sorted(self.w.gh.issues) if n != self.w.control and self.w.task_of(n)]

    def assert_invariants(self, tc):
        for n in self.w.gh.issues:
            tc.assertLessEqual(labeled(self.w, n), 1, f"#{n} labeled twice")
            tc.assertLessEqual(self.w.jules_starts[n], 1, f"Jules started twice for #{n}")
        slots = db.DurableBudget(self.ledger, self.decl, repository=REPO).slots()
        started = [n for n in self.task_issues() if labeled(self.w, n)]
        tc.assertEqual(len(slots), len(started), "every start has exactly one durable slot")
        tc.assertEqual(sorted(int(s["command_id"].rsplit("#", 1)[1]) for s in slots), started)


class AutonomousMvpTests(unittest.TestCase):
    def signals(self):
        sigs = [sw.signal(f"s{k}", "o1", f"{DEMO}mvp{k}.py") for k in range(1, 5)]
        sigs.append(sw.signal("needs-human", "o1", f"{DEMO}human.py",
                              acceptance_criteria=["Merge the pull request into main", "x"]))
        return sigs

    def test_three_plus_tasks_run_back_to_back_through_faults(self):
        fp1 = st.task_fingerprint("o1", "s1", [f"{DEMO}mvp1.py"])
        h = Harness(self.signals(), duplicate_every=3,
                    review_script={(f"prod-test-{fp1[:10]}", 1): review.NEEDS_CORRECTION})
        h.crash_after_label = 1                 # the first start: the process dies right after the label
        h.w.deliver({"name": "start"})          # the human's ONE go; nothing else is approved after this
        h.read_faults = 5                       # GitHub flakes during the next wakes
        stale = h.port()                        # a controller that will come back late
        h.w.run_until_quiet()
        done = [n for n in h.task_issues() if passed(h.w, n)]
        self.assertGreaterEqual(len(done), 3, h.w.log[-12:])
        by_signal = {h.w.task_of(n)["campaign"]["signal_id"]: n for n in h.task_issues()}
        self.assertTrue({"s1", "s2", "s3"} <= {s for s, n in by_signal.items() if passed(h.w, n)})
        self.assertEqual([r["verdict"] for r in h.w.receipts(by_signal["s1"])],
                         [review.NEEDS_CORRECTION, review.PASS])          # corrective, fix, PASS
        self.assertGreaterEqual(h.w.loop_crashes, 1)
        self.assertEqual(h.read_faults, 0)                                  # every injected read failure fired
        self.assertNotIn("needs-human", {s for s, n in by_signal.items() if labeled(h.w, n)})
        self.assertIn(h.w.ticks[-1].outcome, {loop.MERGE_WAIT, loop.NO_SAFE_TASK})
        h.assert_invariants(self)
        # the stale controller comes back: it starts nothing that already ran and wastes no slot
        before = len(db.DurableBudget(h.ledger, h.decl, repository=REPO).slots())
        loop.run_tick(stale, campaign=h.campaign, controller="stale", now=lambda: st._fmt(h.w.now))
        self.assertEqual(len(db.DurableBudget(h.ledger, h.decl, repository=REPO).slots()), before)
        h.assert_invariants(self)
        self.assertGreater(len(h.ports), 4)                                # many independent wakes
        self.assertTrue(all(p.authorization["approval_ref"] == "campaign approval" for p in h.ports))
        isolated = [i for t in h.w.ticks if hasattr(t, "isolated") for i in t.isolated]
        self.assertTrue(any(i["code"] == "CLASSIFICATION_MISMATCH" for i in isolated))   # BLOCKED: only that task

    def test_session_end_mid_campaign_resumes_from_github_only(self):
        h = Harness(self.signals()[:3])
        h.w.deliver({"name": "start"})
        with self.assertRaises(AssertionError):  # the session ends after 4 events; in-memory state is dropped
            h.w.run(max_events=4)
        h2 = Harness.__new__(Harness)
        h2.__dict__.update(h.__dict__)          # same GitHub + ledger, new controller objects only
        h2.ports, h2.crash_after_label, h2.read_faults = [], 0, 0
        h2.w.tick_loop = h2.tick_loop
        h2.w.run_until_quiet()
        self.assertEqual(sum(1 for n in h2.task_issues() if passed(h2.w, n)), 3)
        h2.assert_invariants(self)

    def test_budget_cap_stops_new_starts_visibly_and_raising_it_resumes(self):
        h = Harness(self.signals()[:4], cap=2)
        h.w.deliver({"name": "start"})
        h.w.run_until_quiet()
        self.assertEqual(sum(1 for n in h.task_issues() if labeled(h.w, n)), 2)
        self.assertTrue(any(i["code"] == "BUDGET_EXHAUSTED" for t in h.w.ticks[-3:] for i in t.isolated))
        h.assert_invariants(self)
        h.decl = bf.declaration_v2(cap=10)       # a human approves a bigger budget: the same loop continues
        h.auth["max_activations"] = 10
        h.w.deliver({"name": "schedule"})
        h.w.run_until_quiet()
        self.assertEqual(sum(1 for n in h.task_issues() if passed(h.w, n)), 4)
        h.assert_invariants(self)

    def test_subscription_usage_exhausted_waits_then_resumes(self):
        h = Harness(self.signals()[:3])
        h.quota = {"id": 10 ** 9, "user": {"login": "kamiyusense"}, "created_at": st._fmt(h.w.now),
                   "body": "Jules reported its usage limit.\n\n" + ghs.QUOTA_MARKER + "\n" + json.dumps(
                       {"profile": ghs.QUOTA_PROFILE, "state": st.QUOTA_EXHAUSTED,
                        "reset_at": st._fmt(h.w.now + timedelta(hours=5)), "evidence": "provider message"}) + "\n-->"}
        h.w.deliver({"name": "start"})
        h.w.run(max_events=50)
        self.assertEqual(sum(1 for n in h.task_issues() if labeled(h.w, n)), 0)      # WAIT, not a stop
        self.assertTrue(any(d["code"] == "QUOTA_EXHAUSTED" for d in h.w.ticks[-1].defers))
        self.assertNotIn(h.w.ticks[-1].outcome, {loop.HARD_STOP_PROVIDER, loop.GOAL_COMPLETE})
        h.w.tick(6 * 60)                          # the usage window resets
        h.w.deliver({"name": "schedule"})
        h.w.run_until_quiet()
        self.assertEqual(sum(1 for n in h.task_issues() if passed(h.w, n)), 3)
        self.assertEqual(h.auth["route"], st.ROUTE)                              # never an API-key route
        h.assert_invariants(self)

    def test_human_stop_switch_from_a_phone(self):
        h = Harness(self.signals()[:3])
        h.w.gh.issues[h.w.control]["labels"].append("loop-stop")
        h.w.deliver({"name": "start"})
        h.w.run(max_events=50)
        self.assertEqual(sum(1 for n in h.task_issues() if labeled(h.w, n)), 0)
        self.assertEqual(h.ledger.creates, [])
        h.w.gh.issues[h.w.control]["labels"].remove("loop-stop")
        h.w.deliver({"name": "start"})
        h.w.run_until_quiet()
        self.assertEqual(sum(1 for n in h.task_issues() if passed(h.w, n)), 3)
        h.assert_invariants(self)


class ProductionTemplateTests(unittest.TestCase):
    """The long-running templates: invalid as committed, valid after ONE human approval fills them in."""

    def load(self):
        from pathlib import Path
        d = Path(__file__).resolve().parents[3] / "docs/evidence/claude-jules-production-mvp-20261010"
        return [json.loads((d / f"prod-{n}.TEMPLATE.json").read_text(encoding="utf-8"))
                for n in ("budget-declaration", "authorization", "campaign")]

    def test_invalid_as_committed(self):
        decl, auth, camp = self.load()
        self.assertTrue(db.validate_declaration(decl, repository=REPO))
        with self.assertRaises(ValueError):
            st.validate_campaign(camp)
        self.assertTrue(live.validate_authorization(auth, campaign=camp, now="2026-10-11T00:00:00Z"))

    def test_one_approval_makes_a_long_running_campaign(self):
        decl, auth, camp = self.load()
        decl.update(approved_by="human", approval_ref="chat 2026-10-11")
        auth.update(approved_by="human", approval_ref="chat 2026-10-11", usage_credits_confirmed_off=True)
        camp["objectives"][0].update(approved_by="human", approved_at="2026-10-11T00:00:00Z")
        st.validate_campaign(camp)
        self.assertEqual(db.validate_declaration(decl, repository=REPO), [])
        self.assertEqual(live.validate_authorization(auth, campaign=camp, now="2026-10-11T00:00:00Z"), [])
        budget = db.DurableBudget(bf.LedgerStore(real_slots=9), decl, repository=REPO)
        self.assertTrue(budget.create_enabled)                    # no per-task human step
        self.assertEqual(budget.usage()["used"], 0)               # its own ledger: the 9/10 proof ledger is apart
        self.assertNotEqual(decl["ledger_prefix"], bf.PREFIX)
        self.assertEqual((auth["issues"], auth["budget_id"], decl["campaign_id"]), ("campaign", decl["budget_id"],
                                                                                    camp["campaign_id"]))
        self.assertGreaterEqual(auth["max_activations"], 10)
        self.assertGreater(st._ts(auth["expires_at"]) - st._ts("2026-10-11T00:00:00Z"), timedelta(days=7))
        self.assertEqual((auth["route"], auth["billing"]), (st.ROUTE, "subscription"))
        self.assertFalse(camp["policy"]["allow_api_fallback"] or camp["policy"]["allow_metered_fallback"])


class SignalSourceTests(unittest.TestCase):
    def test_signals_live_on_github_issues(self):
        sig = sw.signal("gh1", "o1", f"{DEMO}gh.py")
        issues = [{"number": 7, "state": "open", "user": {"login": "kamiyusense"},
                   "body": f"work\n\n{ghs.SIGNAL_MARKER}\n{json.dumps(sig)}\n-->"},
                  {"number": 8, "state": "closed", "user": {"login": "kamiyusense"},
                   "body": f"{ghs.SIGNAL_MARKER}\n{json.dumps(dict(sig, signal_id='gh2'))}\n-->"},
                  {"number": 9, "state": "open", "user": {"login": "stranger"},
                   "body": f"{ghs.SIGNAL_MARKER}\n{json.dumps(dict(sig, signal_id='evil'))}\n-->"}]
        got = ghs.signals_from_issues(issues, {"kamiyusense"})
        self.assertEqual([(s["signal_id"], s.get("resolved", False)) for s in got], [("gh1", False), ("gh2", True)])
        port = ghs.GhLoopPort(lambda p: issues, repo=REPO, campaign=sw.planner_campaign(
            "c", [sw.objective("o1", [DEMO])]), route_declaration=ROUTE, signals=None)
        self.assertEqual([s["signal_id"] for s in port.signals()], ["gh1", "gh2"])


if __name__ == "__main__":
    unittest.main()
