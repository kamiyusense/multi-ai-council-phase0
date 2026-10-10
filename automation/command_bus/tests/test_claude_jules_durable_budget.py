"""Cross-wake durable LIVE budget: the label is bounded by one GitHub ledger shared by every wake, not by
per-wake counters.  Mock GitHub, mock ledger, fake Jules; nothing real is called.

The ledger fixture is the real 9/10 slot ledger.  Fault cases A-J of the batch 26 task are marked.
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from automation.command_bus import claude_closed_loop_review as review
from automation.command_bus import claude_jules_durable_budget as db
from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_gh as ghs
from automation.command_bus import claude_jules_starter_live as live
from automation.command_bus.claude_jules_dispatch import sha256_of
from automation.command_bus.tests import budget_fixtures as bf
from automation.command_bus.tests import starter_world as sw
from automation.command_bus.tests.test_claude_jules_starter_live import (REPO, ROUTE, Api, Base, Runner,
                                                                         authorization)


def labeled(world, n):
    return sum(1 for e in world.gh.issues[n]["label_events"] if e["event"] == "labeled" and e["label"] == st.LABEL)


def label_posts(runner):
    return [c for c in runner.calls if c[0][4].endswith("/labels")]


def activation(issue=338, corr="prd-001-702497c", gen=1, head="702497c6b464a3b1ab09441b21fc6f96bd3bb2d0"):
    return {"repository": REPO, "campaign_id": "prd-c2", "issue": issue, "task_id": corr.split("-7")[0],
            "correlation_id": corr, "generation": gen, "task_sha256": "0" * 64, "expected_target_head": head,
            "route": st.ROUTE}


AUTH_ORIGIN = "auth:prd-c2:" + sha256_of("ref")[:16]


class LedgerTests(unittest.TestCase):
    def test_existing_ledger_is_9_of_10(self):
        b = bf.budget()
        self.assertEqual(b.usage(), {"used": 9, "cap": 10, "remaining": 1, "by_origin": 0})

    def test_slot_10_single_reservation_then_exhausted(self):
        store = bf.LedgerStore()
        r = bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=5, now="2026-10-10T05:00:00Z")
        self.assertEqual((r.status, r.record["slot"]), (db.ACQUIRED, 10))
        r2 = bf.budget(store).reserve(activation(issue=339, corr="prd-002-702497c"), origin=AUTH_ORIGIN,
                                      max_for_origin=5, now="2026-10-10T05:01:00Z")
        self.assertEqual(r2.status, db.EXHAUSTED)                    # slot 11 never exists under cap 10
        self.assertEqual(store.creates, [f"{bf.PREFIX}slot-10.json"])

    def test_same_activation_after_restart_is_recovered_not_a_second_slot(self):          # A, G, J
        store = bf.LedgerStore()
        first = bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t1")
        again = bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t2")
        self.assertEqual((first.status, again.status), (db.ACQUIRED, db.RECOVERED))
        self.assertEqual(again.record, first.record)
        self.assertEqual(len(store.files), 10)

    def test_identity_mismatch_is_a_collision(self):
        store = bf.LedgerStore()
        bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t")
        for other in (activation(head="1" * 40), dict(activation(), task_sha256="f" * 64)):
            with self.subTest(other=other):
                r = bf.budget(store).reserve(other, origin=AUTH_ORIGIN, max_for_origin=1, now="t")
                self.assertEqual(r.status, db.COLLISION)
        r = bf.budget(store).reserve(activation(), origin="auth:prd-c2:another", max_for_origin=1, now="t")
        self.assertEqual(r.status, db.COLLISION)
        # a new generation is a new activation: it needs a slot of its own, and none is left
        self.assertEqual(bf.budget(store).reserve(activation(gen=2), origin=AUTH_ORIGIN, max_for_origin=5,
                                                  now="t").status, db.EXHAUSTED)

    def test_per_authorization_maximum_is_durable(self):
        store = bf.LedgerStore()
        b12 = bf.budget(store, cap=12)
        self.assertEqual(b12.reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t").status, db.ACQUIRED)
        r = bf.budget(store, cap=12).reserve(activation(issue=339, corr="prd-002-702497c"), origin=AUTH_ORIGIN,
                                             max_for_origin=1, now="t")
        self.assertEqual(r.status, db.EXHAUSTED)                    # global room is left, this approval's is not

    def test_two_controllers_race_for_the_last_slot(self):                                # D, H
        store = bf.LedgerStore()
        a, b = bf.budget(store), bf.budget(store)
        results = {}
        store.before_create = lambda: results.setdefault(
            "b", b.reserve(activation(issue=339, corr="prd-002-702497c"), origin=AUTH_ORIGIN, max_for_origin=5,
                           now="t"))
        results["a"] = a.reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=5, now="t")
        self.assertEqual(results["b"].status, db.ACQUIRED)
        self.assertEqual(results["a"].status, db.EXHAUSTED)          # B's record reads back; A re-reads: 10/10
        self.assertEqual(len(store.files), 10)
        self.assertEqual(bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=5,
                                                  now="t").status, db.EXHAUSTED)

    def test_the_provable_loser_moves_to_the_next_slot(self):
        store = bf.LedgerStore()
        a, b = bf.budget(store, cap=12), bf.budget(store, cap=12)
        out = {}
        store.before_create = lambda: out.setdefault("b", b.reserve(
            activation(issue=339, corr="prd-002-702497c"), origin=AUTH_ORIGIN, max_for_origin=5, now="t"))
        out["a"] = a.reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=5, now="t")
        self.assertEqual((out["b"].record["slot"], out["a"].record["slot"]), (10, 11))
        self.assertEqual((out["a"].status, out["b"].status), (db.ACQUIRED, db.ACQUIRED))
        self.assertEqual(bf.budget(store, cap=12).usage()["used"], 11)

    def test_lost_create_response_is_decided_by_readback(self):                           # C, I
        store = bf.LedgerStore()
        store.lose_response = True
        r = bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t")
        self.assertEqual(r.status, db.ACQUIRED)
        self.assertEqual(len(store.creates), 1)                      # never re-sent

    def test_lost_readback_is_unknown_then_recovered_next_wake(self):
        store = bf.LedgerStore()
        store.hide_after_write = True
        r = bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t")
        self.assertEqual(r.status, db.UNKNOWN)
        store.hidden.clear()
        self.assertEqual(bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1,
                                                  now="t2").status, db.RECOVERED)
        self.assertEqual(len(store.creates), 1)

    def test_failed_create_is_unknown_and_not_retried(self):
        store = bf.LedgerStore()
        store.fail_before = True
        r = bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t")
        self.assertEqual(r.status, db.UNKNOWN)
        self.assertEqual(len(store.creates), 1)

    def test_unreadable_or_malformed_ledger_is_unknown(self):
        cases = {}
        s = bf.LedgerStore(); s.fail_reads = True; cases["unreadable"] = s
        s = bf.LedgerStore(); s.files[f"{bf.PREFIX}slot-03.json"] = "{not json"; cases["malformed"] = s
        s = bf.LedgerStore()
        rec = json.loads(s.files[f"{bf.PREFIX}slot-04.json"]); rec["command_id"] = "edited"
        s.files[f"{bf.PREFIX}slot-04.json"] = json.dumps(rec); cases["digest"] = s
        s = bf.LedgerStore(); del s.files[f"{bf.PREFIX}slot-05.json"]; cases["gap"] = s
        s = bf.LedgerStore(); s.files[f"{bf.PREFIX}notes.md"] = "x"; cases["stray file"] = s
        for name, store in cases.items():
            with self.subTest(name):
                r = bf.budget(store).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t")
                self.assertEqual(r.status, db.UNKNOWN)
                self.assertEqual(store.creates, [])

    def test_a_slot_written_under_a_larger_cap_is_unknown(self):
        store = bf.LedgerStore()
        bf.budget(store, cap=12).reserve(activation(), origin=AUTH_ORIGIN, max_for_origin=1, now="t")
        with self.assertRaises(db.BudgetUnknown):                    # lowering the cap never frees a slot
            bf.budget(store, cap=10).slots()

    def test_slot_creation_is_disabled_by_default(self):
        self.assertFalse(db.SLOT_CREATE_ENABLED)
        store = bf.LedgerStore()
        r = db.DurableBudget(store, bf.declaration(), repository=REPO).reserve(activation(), origin=AUTH_ORIGIN,
                                                                               max_for_origin=1, now="t")
        self.assertEqual(r.status, db.DISABLED)
        self.assertEqual(store.creates, [])

    def test_v2_declaration_decides_slot_creation(self):
        on = db.DurableBudget(bf.LedgerStore(), bf.declaration_v2(), repository=REPO)
        off = db.DurableBudget(bf.LedgerStore(), bf.declaration_v2(slot_create=False), repository=REPO)
        self.assertEqual((on.create_enabled, off.create_enabled), (True, False))
        self.assertTrue(db.validate_declaration(bf.declaration_v2(slot_create="yes"), repository=REPO))
        self.assertTrue(db.validate_declaration(bf.declaration_v2(campaign_id=""), repository=REPO))

    def test_declaration_validation(self):
        good = bf.declaration()
        self.assertEqual(db.validate_declaration(good, repository=REPO), [])
        for over in ({"cap": 0}, {"cap": True}, {"data_branch": "main"}, {"approved_by": ""}, {"repository": "x/y"},
                     {"ledger_prefix": "no-slash"}):
            with self.subTest(over=over):
                self.assertTrue(db.validate_declaration(bf.declaration(**over), repository=REPO))
        with self.assertRaises(ValueError):
            bf.budget(repository="x/y")


class LivePortBudgetTests(Base):
    """The real adapter path: per-wake port instances share only the GitHub ledger."""

    def setUp(self):
        super().setUp()
        self.ledger = bf.LedgerStore()

    def b_issue(self):
        body = self.c2["tasks"][1]["body"]
        return self.w.gh.create_issue("[PRD-C2] task B", body)

    def test_v1_authorization_can_no_longer_label(self):
        auth = authorization(self.c2)
        auth = {k: v for k, v in auth.items() if k not in {"budget_id", "max_activations"}}
        auth["profile"] = live.AUTH_PROFILE
        port = self.port(auth)
        self.assertTrue(port.live)                                   # V1 still valid for records...
        with self.assertRaisesRegex(live.LiveWriteRefused, "V1 authorization"):
            port.add_label(self.first, "jules")                      # ...but never for a start
        self.assertEqual(label_posts(self.runner), [])

    def test_no_budget_ledger_no_label(self):
        port = live.GhLiveWritePort(Api(self.w), repo=REPO, campaign=self.c2, route_declaration=ROUTE, signals=[],
                                    authorization=authorization(self.c2), runner=Runner(self.w),
                                    now=lambda: st._fmt(self.w.now))
        with self.assertRaisesRegex(live.LiveWriteRefused, "durable budget"):
            port.add_label(self.first, "jules")

    def test_cross_wake_budget_is_global_not_per_wake(self):
        """The reviewer's finding: max_labels resets every wake.  The ledger does not."""
        broad = authorization(self.c2, max_labels=2, max_activations=2)
        res = self.tick(self.port(broad))                            # wake 1: slot 10 for task A
        self.assertEqual(res.started, [self.first])
        b = self.b_issue()
        port2 = self.port(broad)                                     # wake 2: fresh counters (labels_sent = 0)
        self.assertEqual(port2.labels_sent, 0)
        with self.assertRaisesRegex(live.LiveWriteRefused, "EXHAUSTED"):
            port2.add_label(b, "jules")
        self.assertEqual(labeled(self.w, b), 0)
        self.assertEqual(len(label_posts(self.runner)), 0)
        self.assertEqual(bf.budget(self.ledger).usage()["used"], 10)

    def test_exhausted_10_of_10_sends_nothing(self):
        filler = bf.budget(self.ledger).reserve(activation(issue=900, corr="other-1"), origin="auth:x:y",
                                                max_for_origin=1, now="t")
        self.assertEqual(filler.status, db.ACQUIRED)
        res = self.tick(self.port(authorization(self.c2)))
        self.assertEqual(res.started, [])
        self.assertEqual(label_posts(self.runner), [])
        self.assertEqual(labeled(self.w, self.first), 0)

    def test_unreadable_ledger_sends_no_label(self):
        self.ledger.fail_reads = True
        res = self.tick(self.port(authorization(self.c2)))
        self.assertEqual((res.started, label_posts(self.runner)), ([], []))

    def test_pre_written_approved_slot_is_the_pilot_path_with_creation_disabled(self):
        task, _ = st._task_of(self.w.gh.issues[self.first]["body"])
        auth = authorization(self.c2)
        act = db.activation_of(task, repository=REPO, campaign_id="prd-c2", issue=self.first)
        self.ledger.files[f"{bf.PREFIX}slot-10.json"] = db.prepared_slot_record(
            act, slot=10, cap=10, origin=db.origin_of(auth), now="2026-10-10T05:00:00Z")
        guard = bf.budget(self.ledger, create_enabled=False)
        res = self.tick(self.port(auth, budget=guard))
        self.assertEqual(res.started, [self.first])
        self.assertEqual(len(label_posts(self.runner)), 1)
        self.assertEqual(self.ledger.creates, [])                     # nothing created by the adapter

    def test_creation_disabled_and_no_slot_record_means_no_label(self):
        res = self.tick(self.port(authorization(self.c2), budget=bf.budget(self.ledger, create_enabled=False)))
        self.assertEqual((res.started, label_posts(self.runner)), ([], []))
        self.assertTrue(any(r["status"] == db.DISABLED for r in self._last_port_reservations()))

    def _last_port_reservations(self):
        # rebuild with a fresh port to read what add_label recorded
        port = self.port(authorization(self.c2), budget=bf.budget(self.ledger, create_enabled=False))
        try:
            port.add_label(self.first, "jules")
        except live.LiveWriteRefused:
            pass
        return port.reservations

    def test_label_response_lost_after_it_landed(self):                                   # B, C, I
        class LandThenLose(Runner):
            def __call__(self, cmd, payload):
                proc = super().__call__(cmd, payload)
                if cmd[4].endswith("/labels"):
                    raise ghs.subprocess.TimeoutExpired(cmd, 60)
                return proc
        port = self.port(authorization(self.c2), LandThenLose(self.w))
        res = self.tick(port)
        self.assertEqual(res.started, [])
        self.assertTrue(port.ambiguous)
        self.assertEqual(labeled(self.w, self.first), 1)
        # the next wake reads back: the label is there, so no second label and no second slot
        port2 = self.port(authorization(self.c2, max_labels=3, max_activations=3))
        self.tick(port2)
        self.assertEqual(labeled(self.w, self.first), 1)
        self.assertEqual(len(label_posts(self.runner)), 0)
        self.assertEqual(bf.budget(self.ledger).usage()["used"], 10)
        with self.assertRaisesRegex(live.LiveWriteRefused, "already had"):
            port2.add_label(self.first, "jules")

    def test_label_never_landed_is_not_resent_in_the_same_wake(self):
        port = self.port(authorization(self.c2, max_labels=2), Runner(self.w, timeout_on="/labels"))
        self.tick(port)
        self.assertEqual(len(label_posts(self.runner)), 1)
        with self.assertRaisesRegex(live.LiveWriteRefused, "outcome is unknown"):
            port.add_label(self.first, "jules")
        self.assertEqual(len(label_posts(self.runner)), 1)
        self.assertEqual(bf.budget(self.ledger).usage()["used"], 10)  # the slot stays consumed

    def test_duplicate_wakes_never_label_twice(self):                                       # E
        for _ in range(3):
            self.tick(self.port(authorization(self.c2, max_labels=3, max_activations=3)))
        self.assertEqual(labeled(self.w, self.first), 1)
        self.assertEqual(bf.budget(self.ledger).usage()["used"], 10)

    def test_expired_authorization_from_a_stale_session(self):                             # F
        port = self.port(authorization(self.c2, expires_at=st._fmt(self.w.now)))
        self.assertFalse(port.live)
        self.tick(port)
        self.assertEqual((label_posts(self.runner), self.ledger.creates), ([], []))

    def test_historical_label_terminal_receipt_and_wrong_issue_are_refused(self):
        cases = {}
        w = self.w
        w.gh.add_label(self.first, "jules"); w.gh.remove_label(self.first, "jules")
        cases["historical label"] = (self.first, "already had")
        b = self.b_issue()
        task, _ = st._task_of(w.gh.issues[b]["body"])
        record = {"profile": review.RECEIPT_PROFILE, "correlation_id": task["correlation_id"], "verdict": "PASS"}
        w.gh.comment(b, f"PASS\n\n{review.RECEIPT_MARKER}\n{json.dumps(record)}\n-->")
        cases["terminal receipt"] = (b, "receipt already exists")
        for name, (n, why) in cases.items():
            with self.subTest(name):
                port = self.port(authorization(self.c2, max_activations=3))
                with self.assertRaisesRegex(live.LiveWriteRefused, why):
                    port.add_label(n, "jules")
        port = self.port(authorization(self.c2, issues=[999]))
        with self.assertRaisesRegex(live.LiveWriteRefused, "not authorized"):
            port.add_label(self.first, "jules")
        self.assertEqual(label_posts(self.runner), [])
        self.assertEqual(self.ledger.creates, [])

    def test_incomplete_history_is_refused(self):
        api = Api(self.w)

        def get(path):
            if path.endswith("/events?per_page=100"):
                raise ghs.ReadFailed("page 2 HTTP 403", 403)
            return api(path)
        port = live.GhLiveWritePort(get, repo=REPO, campaign=self.c2, route_declaration=ROUTE, signals=[],
                                    authorization=authorization(self.c2), runner=Runner(self.w),
                                    now=lambda: st._fmt(self.w.now), budget=bf.budget(self.ledger))
        with self.assertRaisesRegex(live.LiveWriteRefused, "unreadable"):
            port.add_label(self.first, "jules")
        self.assertEqual(self.ledger.creates, [])

    def test_budget_for_another_ledger_or_campaign_is_refused(self):
        port = self.port(authorization(self.c2, budget_id="other-budget"))
        with self.assertRaisesRegex(live.LiveWriteRefused, "another budget"):
            port.add_label(self.first, "jules")
        self.assertFalse(self.port(authorization(self.c2, campaign_id="prd-c9")).live)
        self.assertFalse(self.port(authorization(self.c2, max_activations=0)).live)

    def test_route_unknown_or_quota_unknown_never_reaches_the_ledger(self):
        port = live.GhLiveWritePort(Api(self.w), repo=REPO, campaign=self.c2, route_declaration={},
                                    signals=[], authorization=authorization(self.c2), runner=Runner(self.w),
                                    now=lambda: st._fmt(self.w.now), budget=bf.budget(self.ledger))
        res = self.tick(port)
        self.assertEqual((res.started, self.ledger.creates), ([], []))

    def test_main_moves_right_before_the_label(self):
        """TOCTOU: the snapshot saw the expected head, then main moved before the label."""
        task, _ = st._task_of(self.w.gh.issues[self.first]["body"])
        allowed = task["allowed_paths"][0]["path"]
        cases = {"touches the task's file": ([allowed], "changed an allowed path"),
                 "changed paths unreadable": (None, "changed paths are unknown"),
                 "unrelated file": (["docs/unrelated.md"], None)}
        for name, (changed, why) in cases.items():
            with self.subTest(name):
                self.setUp()
                port = self.port(authorization(self.c2))
                port.base_head = lambda: "b" * 40                        # fresh read: main moved
                port.base_changed_paths = lambda expected, head, c=changed: c
                if why:
                    with self.assertRaisesRegex(live.LiveWriteRefused, why):
                        port.add_label(self.first, "jules")
                    self.assertEqual((label_posts(self.runner), self.ledger.creates), ([], []))
                else:                                                     # descendant_untouched: continue
                    port.add_label(self.first, "jules")
                    self.assertEqual(len(label_posts(self.runner)), 1)

    def test_only_allowed_writes(self):
        self.tick(self.port(authorization(self.c2)))
        for cmd, payload in self.runner.calls:
            self.assertEqual(cmd[:4], ["gh", "api", "--method", "POST"])
            self.assertRegex(cmd[4], rf"^repos/{REPO}/issues/\d+/(comments|labels)$")
        self.assertEqual(self.ledger.creates, [f"{bf.PREFIX}slot-10.json"])


class TemplateAndCliTests(unittest.TestCase):
    EV = "docs/evidence/claude-jules-durable-budget-20261010/"

    def load(self, name):
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        return json.loads((root / self.EV / name).read_text(encoding="utf-8")), root

    def test_templates_are_invalid_by_construction(self):
        decl, root = self.load("live-budget-declaration.TEMPLATE.json")
        self.assertTrue(any("approved_by" in p for p in db.validate_declaration(decl, repository=REPO)))
        self.assertEqual(decl["cap"], 10)
        auth, _ = self.load("live-authorization-prd-c2-v2.TEMPLATE.json")
        c2 = json.loads((root / "docs/evidence/claude-jules-production-starter-20261009/campaign-prd-c2.json")
                        .read_text(encoding="utf-8"))
        problems = live.validate_authorization(auth, campaign=c2, now="2026-10-09T00:00:00Z")
        self.assertTrue(any("named human" in p for p in problems))
        self.assertTrue(any("usage credits" in p for p in problems))
        self.assertEqual((auth["issues"], auth["max_labels"], auth["max_activations"]), ([338], 1, 1))

    def test_tick_cli_wires_the_budget_and_creation_stays_disabled(self):
        import unittest.mock as m
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        ev = root / "docs/evidence/claude-jules-production-starter-20261009"
        decl = dict(bf.declaration())
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            dp, ap_ = Path(d) / "decl.json", Path(d) / "auth.json"
            dp.write_text(json.dumps(decl), encoding="utf-8")
            c2 = json.loads((ev / "campaign-prd-c2.json").read_text(encoding="utf-8"))
            ap_.write_text(json.dumps(authorization(c2)), encoding="utf-8")
            built = []

            class FakeGit:
                def __init__(self, repo_dir):
                    built.append(repo_dir)

            def blocked(path):
                raise ghs.ReadFailed("mock 403", 403)
            with m.patch("automation.command_bus.claude_jules_live_adapter.GitLiveClient", FakeGit), \
                    m.patch.object(ghs, "gh_get", side_effect=blocked), m.patch("builtins.print"):
                code = ghs.main_tick(["--campaign", str(ev / "campaign-prd-c2.json"), "--route-declaration",
                                      str(ev / "route-declaration.json"), "--controller", "t",
                                      "--live-authorization", str(ap_), "--budget-declaration", str(dp)])
            self.assertEqual(code, 3)             # the repository preflight stops it before any port exists
            self.assertEqual(built, [])
            seen = {}

            def fake_tick(port, **kw):
                seen["port"] = port
                return loop.TickResult(loop.DEFER, "mock")
            with m.patch("automation.command_bus.claude_jules_live_adapter.GitLiveClient", FakeGit), \
                    m.patch.object(ghs, "repo_preflight", return_value={"ok": True, "code": "OK"}), \
                    m.patch.object(loop, "run_tick", side_effect=fake_tick), m.patch("builtins.print"):
                code = ghs.main_tick(["--campaign", str(ev / "campaign-prd-c2.json"), "--route-declaration",
                                      str(ev / "route-declaration.json"), "--controller", "t",
                                      "--live-authorization", str(ap_), "--budget-declaration", str(dp)])
        self.assertEqual((code, built), (0, ["."]))
        port = seen["port"]
        self.assertIsInstance(port.budget, db.DurableBudget)
        self.assertFalse(port.budget.create_enabled)          # disabled until the reservation is proven
        self.assertEqual(port.budget.cap, 10)


class LoopContinuationTests(unittest.TestCase):
    """Every wake of the PRD-C2 loop through a NEW GhLiveWritePort; only the ledger persists."""

    def run_c2(self, *, cap, max_activations):
        import json as _json
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        c2 = _json.loads((root / "docs/evidence/claude-jules-production-starter-20261009/campaign-prd-c2.json")
                         .read_text(encoding="utf-8"))
        w = sw.LoopWorld(c2, [])
        w.main_head = c2["tasks"][0]["body"].split('"expected_target_head":"')[1][:40]
        w.main_history = [(w.main_head, [])]
        w.gh.next_number = 335
        sw.seed_predecessor(w, c2)
        w.gh.events.clear()
        ledger = bf.LedgerStore()
        auth = authorization(c2, max_labels=1, max_activations=max_activations,
                             expires_at="2099-01-01T00:00:00Z")
        ports = []

        def tick_loop(wake):
            w.controllers += 1
            port = live.GhLiveWritePort(Api(w), repo=REPO, campaign=c2, route_declaration=ROUTE, signals=[],
                                        authorization=auth, runner=Runner(w), now=lambda: st._fmt(w.now),
                                        budget=bf.budget(ledger, cap=cap))
            ports.append(port)
            try:
                res = loop.run_tick(port, campaign=c2, controller=f"routine-{w.controllers}",
                                    now=lambda: st._fmt(w.now))
            except st.PreparedOnly:
                res = SimpleNamespace(outcome="PREPARED", started=[])
            w.ticks.append(res)
        w.tick_loop = tick_loop
        w.deliver({"name": "start"})
        w.run_until_quiet()
        return w, ledger, ports

    def test_two_tasks_need_two_slots_and_stop_at_the_cap(self):
        w, ledger, ports = self.run_c2(cap=10, max_activations=2)
        starts = {n: labeled(w, n) for n in w.gh.issues if labeled(w, n) and n != 335}
        self.assertEqual(list(starts.values()), [1])                  # A only: slot 10 was the last one
        self.assertTrue(any(i["code"] == "BUDGET_EXHAUSTED" and i["human_required"] for i in w.ticks[-1].isolated))
        self.assertEqual(bf.budget(ledger).usage()["used"], 10)
        self.assertGreaterEqual(len(ports), 2)                        # separate wakes, each with fresh counters
        self.assertTrue(any(r["status"] == db.EXHAUSTED for p in ports for r in p.reservations))

    def test_two_tasks_continue_when_a_human_raised_the_cap(self):
        w, ledger, _ = self.run_c2(cap=11, max_activations=2)
        started = [n for n in w.gh.issues if labeled(w, n) and n != 335]     # #335 is the seeded predecessor
        self.assertEqual(len(started), 2)
        self.assertTrue(all(labeled(w, n) == 1 for n in started))
        self.assertEqual(bf.budget(ledger, cap=11).usage()["used"], 11)
        self.assertEqual(sum(w.jules_starts.values()), 2)


if __name__ == "__main__":
    unittest.main()
