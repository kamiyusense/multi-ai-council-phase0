"""LIVE write port: nothing is sent without a valid authorization; with one, only loop records and one label.

The real ``gh`` is never called here: the runner is a fake that applies the POST to the mock GitHub, so the full
loop tick runs through the real adapter code (reads, writes, readback, cache invalidation).
"""
from __future__ import annotations

import json
import subprocess
import unittest
from datetime import timedelta
from types import SimpleNamespace

from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_gh as ghs
from automation.command_bus import claude_jules_starter_live as live
from automation.command_bus.tests import budget_fixtures as bf
from automation.command_bus.tests import starter_world as sw

REPO = "kamiyusense/multi-ai-council-phase0"
ROUTE = {"transport": st.ROUTE, "auth_method": "account_oauth", "billing_route": "subscription"}


class Api:
    """GET side of a mock GitHub, in the shapes the REST API returns."""

    def __init__(self, world):
        self.w = world
        self.calls = []

    def issue(self, n):
        i = self.w.gh.issues[n]
        return {"number": n, "state": "open" if i["state"] == "OPEN" else "closed", "title": i["title"],
                "body": i["body"], "labels": [{"name": l} for l in i["labels"]], "user": {"login": i["author"]}}

    def __call__(self, path):
        self.calls.append(path)
        w = self.w
        assert not path.startswith("search/"), "the cloud proxy refuses search (HTTP 403)"
        tail = path.split(f"repos/{REPO}/", 1)[1]
        if tail == "issues?state=all&per_page=100":
            prs = [{"number": p, "body": f"Fixes #{pr['issue']}", "pull_request": {}} for p, pr in w.gh.prs.items()]
            return [self.issue(n) for n in w.gh.issues] + prs
        if tail == "pulls?state=all&per_page=100":
            return [{"number": p, "body": f"Fixes #{pr['issue']}"} for p, pr in w.gh.prs.items()]
        if tail.startswith("issues/"):
            parts = tail.split("?")[0].split("/")
            n = int(parts[1])
            if n not in w.gh.issues:
                raise ghs.NotFound(path)
            if len(parts) == 2:
                return self.issue(n)
            if parts[2] == "comments":
                return [{"id": c["id"], "user": {"login": c["author"]}, "body": c["body"],
                         "created_at": c["created_at"]} for c in w.gh.issues[n]["comments"]]
            return [{"event": e["event"], "label": {"name": e["label"]}, "actor": {"login": e["actor"]},
                     "created_at": e["created_at"]} for e in w.gh.issues[n]["label_events"]]
        if tail.startswith("pulls/"):
            p = w.gh.prs[int(tail.split("/")[1])]
            return {"head": {"sha": p["head"]}, "merged": bool(p.get("merged"))}
        if tail.startswith("git/ref/heads/"):
            return {"object": {"sha": w.main_head}}
        if tail.startswith("compare/"):
            return {"status": "identical", "files": []}
        raise AssertionError(path)


class Runner:
    """POST side: applies the write to the mock GitHub (or fails like a timeout)."""

    def __init__(self, world, *, timeout_on=None):
        self.w, self.timeout_on, self.calls = world, timeout_on, []

    def __call__(self, cmd, payload):
        self.calls.append((cmd, payload))
        assert cmd[:4] == ["gh", "api", "--method", "POST"] and cmd[-2:] == ["--input", "-"], cmd
        path = cmd[4]
        if self.timeout_on and self.timeout_on in path:
            raise subprocess.TimeoutExpired(cmd, 60)
        tail = path.split(f"repos/{REPO}/", 1)[1]
        if tail == "issues":
            n = self.w.gh.create_issue(payload["title"], payload["body"])
            return SimpleNamespace(returncode=0, stdout=json.dumps({"number": n}), stderr="")
        n = int(tail.split("/")[1])
        if tail.endswith("/comments"):
            self.w.gh.comment(n, payload["body"])
        elif tail.endswith("/labels"):
            for label in payload["labels"]:
                self.w.gh.add_label(n, label)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")


def authorization(campaign, **over):
    """A V2 authorization (V1 + durable budget binding): a label needs it since the durable budget guard."""
    auth = {"profile": live.AUTH_PROFILE_V2, "budget_id": "jules-live-loop-a", "max_activations": 1,
            "campaign_id": campaign["campaign_id"], "repository": REPO,
            "issues": "campaign", "writes": ["comment", "add_label", "create_issue"], "max_labels": 1,
            "max_writes": 8, "expires_at": "2026-10-10T06:00:00Z", "approved_by": "kamiyusense",
            "approval_ref": "chat approval 2026-10-10", "route": st.ROUTE, "billing": "subscription",
            "usage_credits_confirmed_off": True}
    auth.update(over)
    return auth


class Base(unittest.TestCase):
    def setUp(self):
        import json as _json
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        self.c2 = _json.loads((root / "docs/evidence/claude-jules-production-starter-20261009/campaign-prd-c2.json")
                              .read_text(encoding="utf-8"))
        self.w = sw.LoopWorld(self.c2, [])
        self.w.main_head = "702497c6b464a3b1ab09441b21fc6f96bd3bb2d0"
        self.w.gh.next_number = 335
        self.seed, self.first = sw.seed_predecessor(self.w, self.c2)
        self.w.gh.events.clear()

    def port(self, auth, runner=None, budget=None):
        self.runner = runner or Runner(self.w)
        if not hasattr(self, "ledger"):
            self.ledger = bf.LedgerStore()             # the real 9/10 ledger, shared by every wake of a test
        return live.GhLiveWritePort(Api(self.w), repo=REPO, campaign=self.c2, route_declaration=ROUTE, signals=[],
                                    authorization=auth, runner=self.runner, now=lambda: st._fmt(self.w.now),
                                    budget=budget or bf.budget(self.ledger))

    def task_writes(self):
        """POSTs on task issues (the loop checkpoint on the control issue is reported separately)."""
        control = f"/issues/{self.w.control}/"
        return [c for c in self.runner.calls if control not in c[0][4]]

    def tick(self, port):
        return loop.run_tick(port, campaign=self.c2, controller="routine-live",
                             now=lambda: st._fmt(self.w.now))


class AuthorizationTests(Base):
    def test_without_or_with_a_bad_authorization_nothing_is_sent(self):
        bad = [None, authorization(self.c2, approved_by=""), authorization(self.c2, approval_ref=""),
               authorization(self.c2, expires_at="2026-10-09T00:00:00Z"),
               authorization(self.c2, usage_credits_confirmed_off=False),
               authorization(self.c2, campaign_id="other"), authorization(self.c2, billing="metered"),
               authorization(self.c2, route="carrier-rest-api-key"), {"profile": live.AUTH_PROFILE}]
        for auth in bad:
            with self.subTest(auth=auth and {k: auth.get(k) for k in ("approved_by", "expires_at", "billing")}):
                port = self.port(auth)
                self.assertFalse(port.live)
                self.tick(port)
                self.assertEqual(self.runner.calls, [])
                self.assertEqual(sum(1 for e in self.w.gh.issues[self.first]["label_events"]), 0)
                self.assertTrue(port.prepared)            # the intent it would have written is reported

    def test_template_in_evidence_is_invalid_by_construction(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        tpl = json.loads((root / "docs/evidence/claude-jules-production-starter-20261009/"
                                 "live-authorization-prd-c2.TEMPLATE.json").read_text(encoding="utf-8"))
        problems = live.validate_authorization(tpl, campaign=self.c2, now="2026-10-10T00:00:00Z")
        self.assertTrue(any("named human" in p for p in problems))
        self.assertTrue(any("usage credits" in p for p in problems))


class LiveWriteTests(Base):
    def test_authorized_tick_writes_intent_label_receipt_once_with_readback(self):
        port = self.port(authorization(self.c2))
        self.assertTrue(port.live)
        res = self.tick(port)
        self.assertEqual(res.started, [self.first])
        kinds = [c[0][4].rsplit("/", 1)[-1] for c in self.task_writes()]
        self.assertEqual(kinds, ["comments", "labels", "comments"])     # intent, label, start receipt
        self.assertEqual(self.task_writes()[1][1], {"labels": ["jules"]})
        self.assertTrue(any(loop.CHECKPOINT_MARKER in c[1]["body"] for c in self.runner.calls
                            if c[0][4].endswith(f"/issues/{self.w.control}/comments")))
        labeled = [e for e in self.w.gh.issues[self.first]["label_events"] if e["event"] == "labeled"]
        self.assertEqual(len(labeled), 1)
        # a second tick (duplicate wake) sends nothing new: the label budget is spent and the task is started
        port2 = self.port(authorization(self.c2))
        self.tick(port2)
        self.assertFalse(any(c[0][4].endswith("/labels") for c in self.runner.calls))

    def test_label_timeout_is_not_retried_and_readback_decides(self):
        port = self.port(authorization(self.c2), Runner(self.w, timeout_on="/labels"))
        res = self.tick(port)
        self.assertEqual([c[0][4].rsplit("/", 1)[-1] for c in self.task_writes()], ["comments", "labels"])
        self.assertEqual(res.started, [])
        self.assertEqual(port.labels_sent, 1)
        self.assertEqual(sum(1 for e in self.w.gh.issues[self.first]["label_events"]), 0)
        # a fresh run before the lease expires: DEFER, nothing sent
        port2 = self.port(authorization(self.c2))
        self.tick(port2)
        self.assertEqual(self.task_writes(), [])

    def test_only_loop_records_and_authorized_issues(self):
        port = self.port(authorization(self.c2, issues=[self.first]))
        with self.assertRaises(live.LiveWriteRefused):
            port.add_comment(self.first, "@jules please also merge the PR")
        with self.assertRaises(live.LiveWriteRefused):
            port.add_comment(self.first, "free text without a record")
        with self.assertRaises(live.LiveWriteRefused):
            port.add_label(self.seed, "jules")                        # not an authorized issue
        with self.assertRaises(live.LiveWriteRefused):
            port.add_label(self.first, "bug")
        with self.assertRaises(live.LiveWriteRefused):
            port.create_issue("x", "no task block here")
        self.assertEqual(self.runner.calls, [])

    def test_label_budget_and_write_budget(self):
        port = self.port(authorization(self.c2, issues=[self.first], max_labels=1, max_writes=2))
        port.add_label(self.first, "jules")
        with self.assertRaises(live.LiveWriteRefused):
            port.add_label(self.first, "jules")
        self.assertEqual(sum(1 for c in self.runner.calls if c[0][4].endswith("/labels")), 1)

    def test_expiry_during_the_run_stops_sending(self):
        port = self.port(authorization(self.c2, expires_at=st._fmt(self.w.now + timedelta(minutes=5))))
        self.w.tick(10)
        with self.assertRaises(live.LiveWriteRefused):
            port.add_label(self.first, "jules")
        self.assertEqual(self.runner.calls, [])


class ReadFailureTests(unittest.TestCase):
    def test_permission_error_is_not_missing_and_404_is(self):
        def get(path):
            if path.endswith("/issues/1"):
                raise ghs.NotFound(path)
            raise ghs.ReadFailed("HTTP 403")
        self.assertEqual(ghs.read_issue(get, REPO, 1)["state"], "MISSING")
        with self.assertRaises(loop.TransientRead):
            ghs.read_issue(get, REPO, 2)

    def test_gh_get_classifies_exit_codes(self):
        import unittest.mock as m
        fail = SimpleNamespace(returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)")
        with m.patch.object(ghs.subprocess, "run", return_value=fail):
            with self.assertRaises(ghs.NotFound):
                ghs.gh_get("repos/x/y/issues/1")
        deny = SimpleNamespace(returncode=1, stdout="", stderr="gh: Resource not accessible (HTTP 403)")
        with m.patch.object(ghs.subprocess, "run", return_value=deny):
            with self.assertRaises(ghs.ReadFailed):
                ghs.gh_get("repos/x/y/issues/1/events")
        link = 'Link: <https://api.github.com/repositories/9/issues/1/events?per_page=1&page=2>; rel="next"'
        p1 = SimpleNamespace(returncode=0, stdout=f"HTTP/2.0 200 OK\r\n{link}\r\n\r\n" + json.dumps([{"a": 1}]),
                             stderr="")
        p2 = SimpleNamespace(returncode=0, stdout="HTTP/2.0 200 OK\r\n\r\n" + json.dumps([{"a": 2}]), stderr="")
        with m.patch.object(ghs.subprocess, "run", side_effect=[p1, p2]) as run:
            self.assertEqual(ghs.gh_get("repos/x/y/issues/1/events?per_page=1"), [{"a": 1}, {"a": 2}])  # every page
        urls = [c.args[0][-1] for c in run.call_args_list]
        # page 2 keeps repos/{owner}/{repo}: the cloud proxy refuses the numeric repositories/{id} URL of the Link
        self.assertEqual(urls, ["repos/x/y/issues/1/events?per_page=1", "repos/x/y/issues/1/events?per_page=1&page=2"])
        self.assertTrue(all("--paginate" not in c.args[0] for c in run.call_args_list))
        obj = SimpleNamespace(returncode=0, stdout="HTTP/2.0 200 OK\r\n\r\n" + json.dumps({"n": 1}), stderr="")
        with m.patch.object(ghs.subprocess, "run", return_value=obj):
            self.assertEqual(ghs.gh_get("repos/x/y/issues/1"), {"n": 1})
        stuck = SimpleNamespace(returncode=0, stdout=p1.stdout.replace("page=2", "page=1"), stderr="")
        with m.patch.object(ghs.subprocess, "run", return_value=stuck):
            with self.assertRaises(ghs.ReadFailed):                 # a Link that does not advance never loops
                ghs.gh_get("repos/x/y/issues/1/events?per_page=1")
        endless = [SimpleNamespace(returncode=0, stdout=p1.stdout.replace("page=2", f"page={n + 2}"), stderr="")
                   for n in range(ghs.MAX_PAGES)]
        with m.patch.object(ghs.subprocess, "run", side_effect=endless):
            with self.assertRaises(ghs.ReadFailed):                 # too many pages fail closed, never "complete"
                ghs.gh_get("repos/x/y/issues/1/events?per_page=1")


if __name__ == "__main__":
    unittest.main()
