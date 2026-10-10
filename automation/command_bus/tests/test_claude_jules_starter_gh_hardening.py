"""Starter GitHub reads fail closed: pagination integrity, 403/404, proxy-safe paths, Layer 3/4 duplicate guard,
a read failure on one task never crashes the tick or starts work on an UNKNOWN state.

No real ``gh`` and no network: ``subprocess.run`` is replaced by recorded responses.
"""
from __future__ import annotations

import json
import unittest
import unittest.mock as m
from pathlib import Path
from types import SimpleNamespace

from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_gh as ghs
from automation.command_bus import claude_jules_starter_live as live
from automation.command_bus import claude_jules_task_planner as planner
from automation.command_bus.tests import starter_world as sw
from automation.command_bus.tests.test_claude_jules_loop import DEMO, LoopInvariants, labeled, world_with
from automation.command_bus.tests.test_claude_jules_starter_live import Base, authorization

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "starter_gh" / "issue_events_per_page_2.json"
PATH = "repos/x/y/issues/1/events?per_page=2"


def response(items, *, status=200, links=None, code=0, stderr=""):
    """What ``gh api --include`` prints: status line, headers, blank line, body (CRLF like the real CLI)."""
    head = [f"HTTP/2.0 {status} {'OK' if status == 200 else 'Error'}", "Content-Type: application/json"]
    if links:
        head.append("Link: " + ", ".join(
            f'<https://api.github.com/repositories/1048576/issues/1/events?per_page=2&page={p}>; rel="{rel}"'
            for rel, p in links.items()))
    return SimpleNamespace(returncode=code, stdout="\r\n".join(head) + "\r\n\r\n" + json.dumps(items),
                           stderr=stderr)


def paged(pages):
    """Responses for a list of pages, with GitHub's next/last/prev/first links."""
    out, last = [], len(pages)
    for i, items in enumerate(pages, start=1):
        links = {}
        if i < last:
            links.update(next=i + 1, last=last)
        if i > 1:
            links.update(prev=i - 1, first=1)
        out.append(response(items, links=links))
    return out


class PaginationTests(unittest.TestCase):
    def run_get(self, responses, path=PATH):
        with m.patch.object(ghs.subprocess, "run", side_effect=responses) as run:
            try:
                return ghs.gh_get(path), run
            finally:
                self.calls = [c.args[0] for c in run.call_args_list]
                self.kwargs = [c.kwargs for c in run.call_args_list]

    def test_recorded_issue_histories_are_read_completely(self):
        fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
        events, _ = self.run_get(paged(fx["issues"]["338"]))
        self.assertEqual([e["id"] for e in events], [32814810366, 32838071056, 32839285361, 32863022962])
        self.assertFalse(any(e["event"] in {"labeled", "unlabeled"} for e in events))
        events, _ = self.run_get(paged(fx["issues"]["335"]))
        self.assertEqual(len(events), 6)
        self.assertTrue(any(e["event"] == "labeled" and e["label"]["name"] == "jules" for e in events))
        # every request keeps repos/{owner}/{repo}; the numeric repositories/{id} URL of the Link is never used
        self.assertEqual(self.calls[-1][-1], PATH + "&page=3")
        for cmd in self.calls:
            self.assertEqual(cmd[:5], ["gh", "api", "--method", "GET", "--include"])
            self.assertTrue(cmd[-1].startswith("repos/x/y/"))
            self.assertNotIn("--paginate", cmd)
            self.assertNotIn("auth", cmd)                       # gh auth status is never the gate
        for kw in self.kwargs:                                  # UTF-8, never the console code page (cp932)
            self.assertEqual((kw["encoding"], kw["errors"]), ("utf-8", "replace"))

    def test_a_skipped_page_is_never_complete(self):
        pages = [response([{"id": 1}], links={"next": 3, "last": 3}), response([{"id": 3}])]
        with self.assertRaisesRegex(ghs.ReadFailed, "skip or loop"):
            self.run_get(pages)

    def test_a_repeated_page_is_never_followed(self):
        with self.assertRaisesRegex(ghs.ReadFailed, "skip or loop"):
            self.run_get([response([{"id": 1}], links={"next": 1})])

    def test_403_on_a_middle_page_is_a_failed_read_not_an_empty_history(self):
        deny = response({"message": "Resource not accessible"}, status=403, code=1,
                        stderr="gh: Resource not accessible (HTTP 403)")
        with self.assertRaises(ghs.ReadFailed) as cm:
            self.run_get([response([{"id": 1}], links={"next": 2, "last": 2}), deny])
        self.assertEqual(cm.exception.status, 403)
        self.assertNotIsInstance(cm.exception, ghs.NotFound)

    def test_404_only_on_the_first_page_is_not_found(self):
        gone = response({"message": "Not Found"}, status=404, code=1, stderr="gh: Not Found (HTTP 404)")
        with self.assertRaises(ghs.NotFound):
            self.run_get([gone])
        with self.assertRaises(ghs.ReadFailed) as cm:          # a later page vanishing is a failed read
            self.run_get([response([{"id": 1}], links={"next": 2}), gone])
        self.assertEqual(cm.exception.status, 404)

    def test_403_with_a_message_mentioning_404_is_still_403(self):
        deny = response({"message": "denied"}, status=403, code=1, stderr="gh: see docs on HTTP 404 (HTTP 403)")
        with self.assertRaises(ghs.ReadFailed) as cm:
            self.run_get([deny])
        self.assertEqual(cm.exception.status, 403)

    def test_status_only_on_stderr(self):
        with self.assertRaises(ghs.ReadFailed) as cm:
            self.run_get([SimpleNamespace(returncode=1, stdout="", stderr="gh: Forbidden (HTTP 403)")])
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(ghs.ReadFailed) as cm:
            self.run_get([SimpleNamespace(returncode=1, stdout="", stderr="error connecting to api.github.com")])
        self.assertIsNone(cm.exception.status)

    def test_exit_zero_with_a_non_200_status_is_a_failed_read(self):
        with self.assertRaises(ghs.ReadFailed):
            self.run_get([response([], status=202)])

    def test_last_page_moving_or_stopping_early_is_never_complete(self):
        with self.assertRaisesRegex(ghs.ReadFailed, "last page moved"):
            self.run_get([response([{"id": 1}], links={"next": 2, "last": 3}),
                          response([{"id": 2}], links={"next": 3, "last": 4})])
        with self.assertRaisesRegex(ghs.ReadFailed, "announced last"):
            self.run_get([response([{"id": 1}], links={"next": 2, "last": 3}), response([{"id": 2}])])

    def test_an_item_seen_twice_means_the_list_moved(self):
        with self.assertRaisesRegex(ghs.ReadFailed, "seen twice"):
            self.run_get([response([{"id": 1}, {"id": 2}], links={"next": 2}), response([{"id": 2}, {"id": 3}])])

    def test_page_cap_is_unknown(self):
        endless = [response([{"id": n}], links={"next": n + 1}) for n in range(1, ghs.MAX_PAGES + 1)]
        with self.assertRaisesRegex(ghs.ReadFailed, "more than"):
            self.run_get(endless)

    def test_unreadable_json_and_timeouts(self):
        with self.assertRaisesRegex(ghs.ReadFailed, "unreadable JSON"):
            self.run_get([SimpleNamespace(returncode=0, stdout="HTTP/2.0 200 OK\r\n\r\n{trunc", stderr="")])
        with self.assertRaises(ghs.ReadFailed):
            self.run_get([ghs.subprocess.TimeoutExpired(["gh"], 120)])

    def test_interim_status_line_uses_the_final_status(self):
        out = "HTTP/1.1 100 Continue\r\n\r\nHTTP/2.0 200 OK\r\n\r\n" + json.dumps({"n": 1})
        # the body split happens at the first blank line, so an interim block makes the body unreadable: fail closed
        with self.assertRaises(ghs.ReadFailed):
            self.run_get([SimpleNamespace(returncode=0, stdout=out, stderr="")])
        self.assertEqual(ghs._response_status("HTTP/1.1 100 Continue\nHTTP/2.0 403 Forbidden"), 403)

    def test_proxy_refused_and_absolute_paths_are_never_requested(self):
        for bad in ("repositories/1048576/issues/1/events", "/repositories/1/issues",
                    "https://api.github.com/repositories/1/issues", "search/issues?q=x"):
            with self.subTest(bad=bad), m.patch.object(ghs.subprocess, "run") as run:
                with self.assertRaises(ghs.ReadFailed):
                    ghs.gh_get(bad)
                run.assert_not_called()

    def test_link_header_parsing(self):
        head = ("HTTP/2.0 200 OK\nlink: <https://api.github.com/repositories/9/issues?per_page=100&page=2>; "
                'rel="next", <https://api.github.com/repositories/9/issues?per_page=100&page=7>; rel="last"')
        self.assertEqual(ghs.link_pages(head), {"next": 2, "last": 7})
        # per_page=100 is never read as page=100; a body line that looks like a Link header is not a header
        self.assertEqual(ghs.link_pages("HTTP/2.0 200 OK\nX-Note: per_page=100"), {})
        self.assertEqual(ghs.link_pages('HTTP/2.0 200 OK\nLink: <https://x/y?cursor=abc>; rel="next"'),
                         {"next": -1})                             # no page number: never "next is page 2"
        with self.assertRaises(ghs.ReadFailed):
            self.run_get([response([{"id": 1}], links={"next": 2}).__class__(
                returncode=0, stderr="", stdout='HTTP/2.0 200 OK\r\nLink: <https://x/y?cursor=a>; rel="next"'
                                                '\r\n\r\n[{"id": 1}]')])

    def test_non_utf8_bytes_never_crash_the_read(self):
        # errors="replace" makes undecodable bytes visible as U+FFFD instead of raising UnicodeDecodeError
        body = json.dumps([{"id": 1, "body": "caf�"}])
        events, _ = self.run_get([SimpleNamespace(returncode=0, stdout="HTTP/2.0 200 OK\r\n\r\n" + body, stderr="")])
        self.assertEqual(events[0]["body"], "caf�")


class IssueHistoryTests(unittest.TestCase):
    def test_history_404_after_the_issue_exists_is_a_failed_read(self):
        def get(path):
            if path.endswith("/issues/5"):
                return {"state": "open", "title": "t", "body": "", "labels": []}
            raise ghs.NotFound(path)
        with self.assertRaises(ghs.ReadFailed):
            ghs.read_issue(get, "o/r", 5)


class PreflightTests(unittest.TestCase):
    def test_authenticated_repo_get_decides_not_gh_auth_status(self):
        ok = ghs.repo_preflight(lambda p: {"full_name": "O/R", "private": True}, "o/r")
        self.assertTrue(ok["ok"])

        def raise_(exc):
            def get(path):
                raise exc
            return get
        cases = {"404": raise_(ghs.NotFound("repos/o/r")), "403": raise_(ghs.ReadFailed("denied", 403)),
                 "net": raise_(ghs.ReadFailed("timeout"))}
        for name, get in cases.items():
            with self.subTest(name):
                res = ghs.repo_preflight(get, "o/r")
                self.assertFalse(res["ok"])
                self.assertEqual(res["code"], ghs.REPO_ACCESS_BLOCKED)
        self.assertFalse(ghs.repo_preflight(lambda p: {"full_name": "o/r", "private": False}, "o/r")["ok"])
        self.assertFalse(ghs.repo_preflight(lambda p: {"full_name": "o/other", "private": True}, "o/r")["ok"])
        self.assertFalse(ghs.repo_preflight(lambda p: [], "o/r")["ok"])

    def test_tick_cli_stops_at_a_blocked_preflight_with_zero_writes(self):
        root = Path(__file__).resolve().parents[3]
        ev = root / "docs/evidence/claude-jules-production-starter-20261009"

        def blocked(path):
            raise ghs.ReadFailed("HTTP 403", 403)
        with m.patch.object(ghs, "gh_get", side_effect=blocked) as get, \
                m.patch("builtins.print") as out:
            code = ghs.main_tick(["--campaign", str(ev / "campaign-prd-c2.json"), "--route-declaration",
                                  str(ev / "route-declaration.json"), "--controller", "t"])
        self.assertEqual(code, 3)
        self.assertEqual(get.call_count, 1)                     # nothing else was read or written
        report = json.loads(out.call_args.args[0])
        self.assertEqual(report["outcome"], ghs.REPO_ACCESS_BLOCKED)
        self.assertEqual((report["sent"], report["prepared_writes"], report["live"]), ([], [], False))


class OutputTests(unittest.TestCase):
    def test_out_file_keeps_everything_and_stdout_is_one_ascii_line(self):
        import tempfile
        report = {"outcome": "DEFER", "reason": "日本語の理由 " + "x" * 5000}
        with tempfile.TemporaryDirectory() as d, m.patch("builtins.print") as out:
            path = Path(d) / "r.json"
            ghs._emit(report, str(path))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)
        line = out.call_args.args[0]
        self.assertNotIn("\n", line)
        line.encode("ascii")                                    # a cp932 console can always print it
        self.assertEqual(json.loads(line), report)


def task_body(campaign, signal_id, path):
    d = planner.plan_next(campaign=campaign, signals=[sw.signal(signal_id, "o1", path)], known=[])
    return planner.build_task(d.proposal, campaign=campaign, base_head=sw.MAIN, now="2026-10-10T00:00:00Z")


class DuplicateGuardTests(unittest.TestCase):
    def setUp(self):
        self.c = sw.planner_campaign("pl", [sw.objective("o1", [DEMO])])
        self.title, self.body, self.task = task_body(self.c, "s1", f"{DEMO}a.py")

    def test_layer3_issue_blocks_a_layer4_duplicate(self):
        def issue(n, **kw):
            return {"number": n, "state": "open", "title": "other", "body": "", **kw}
        self.assertIsNone(ghs.find_duplicate_issue([issue(1)], self.title, self.body))
        self.assertEqual(ghs.find_duplicate_issue([issue(2, title=self.title)], self.title, self.body)["issue"], 2)
        # a closed issue with the same title is not a duplicate by title (Layer 3's own rule) ...
        self.assertIsNone(ghs.find_duplicate_issue([issue(3, title=self.title, state="closed")], self.title,
                                                   self.body))
        # ... but the same task (correlation or fingerprint), open or closed, always is
        self.assertEqual(ghs.find_duplicate_issue([issue(4, body=self.body, state="closed")], "new title",
                                                  self.body)["match"], "same correlation_id")
        other_title, other_body, _ = task_body(self.c, "s1", f"{DEMO}a.py")
        self.assertIsNotNone(ghs.find_duplicate_issue([issue(5, body=other_body)], "t", self.body))
        self.assertIsNone(ghs.find_duplicate_issue([issue(6, title=self.title, pull_request={})], self.title,
                                                   self.body))

    def test_prepare_only_port_reports_the_duplicate(self):
        issues = [{"number": 7, "state": "open", "title": self.title, "body": ""}]
        port = ghs.GhLoopPort(lambda p: issues, repo="o/r", campaign=self.c, route_declaration={}, signals=[])
        with self.assertRaises(st.PreparedOnly):
            port.create_issue(self.title, self.body)
        self.assertEqual(port.prepared[0]["duplicate_of"]["issue"], 7)


class LiveDuplicateTests(Base):
    def test_live_create_issue_refuses_a_task_that_already_has_an_issue(self):
        c = self.c2
        task, _ = st._task_of(self.w.gh.issues[self.first]["body"])
        port = self.port(authorization(c))
        with self.assertRaisesRegex(live.LiveWriteRefused, "DUPLICATE"):
            port.create_issue("a different title", self.w.gh.issues[self.first]["body"])
        self.assertEqual(self.runner.calls, [])
        self.assertTrue(task["correlation_id"])


class TickReadFailureTests(unittest.TestCase, LoopInvariants):
    def two_prepared(self):
        sigs = [sw.signal(f"s{k}", "o1", f"{DEMO}r{k}.py") for k in (1, 2)]
        w = world_with(sigs)
        made = []
        for s in sigs:
            d = planner.plan_next(campaign=w.campaign, signals=[s], known=[])
            title, body, _ = planner.build_task(d.proposal, campaign=w.campaign, base_head=sw.MAIN,
                                                now=st._fmt(w.now))
            made.append(w.gh.create_issue(title, body))
        return w, made

    def tick(self, w):
        return loop.run_tick(w, campaign=w.campaign, controller="t", now=lambda: st._fmt(w.now))

    def test_one_unreadable_task_does_not_stop_an_independent_one(self):
        w, (a, b) = self.two_prepared()
        real = w.read_issue

        def read_issue(n):
            if n == a:
                raise loop.TransientRead("HTTP 502")
            return real(n)
        w.read_issue = read_issue
        res = self.tick(w)
        self.assertEqual(res.started, [b])
        self.assertTrue(any(d["issue"] == a and d["code"] == "READ_UNKNOWN" for d in res.defers))
        self.assertEqual(labeled(w, a), 0)
        w.read_issue = real                                     # temporary DEFER, never a permanent stop
        w.run_until_quiet()
        self.assertEqual(labeled(w, a), 1)
        self.assert_safe(w)

    def test_a_write_whose_readback_fails_stops_new_starts_this_tick(self):
        w, (a, b) = self.two_prepared()
        real, state = w.read_issue, {"wrote": False}
        real_comment = w.add_comment

        def add_comment(n, body):
            state["wrote"] = True
            return real_comment(n, body)

        def read_issue(n):
            if n == a and state["wrote"]:
                raise loop.TransientRead("HTTP 502 after the intent")
            return real(n)
        w.read_issue, w.add_comment = read_issue, add_comment
        res = self.tick(w)
        self.assertEqual(res.started, [])
        self.assertEqual(res.created, [])
        self.assertEqual(res.outcome, loop.DEFER)
        codes = {d["issue"]: d["code"] for d in res.defers}
        self.assertEqual(codes, {a: "WRITE_READBACK_UNKNOWN", b: "WRITE_READBACK_UNKNOWN"})
        self.assertEqual(labeled(w, a) + labeled(w, b), 0)      # nothing new started on an UNKNOWN state
        w.read_issue, w.add_comment = real, real_comment       # the next wake recovers from GitHub alone
        w.run_until_quiet()
        self.assertEqual(labeled(w, a) + labeled(w, b), 2)
        self.assert_safe(w)

    def test_unknown_merge_state_never_unlocks_dependent_work(self):
        w, (a, b) = self.two_prepared()
        w.run_until_quiet()                                     # both PASS, nothing merged
        issues = w.list_campaign_issues()
        w.gh.prs[w.jules_pr[a]]["merged"] = True

        def pr_merged(n):
            raise loop.TransientRead("HTTP 403")
        states = {k["issue"]: k["state"] for k in loop.task_states(issues, campaign=w.campaign, pr_merged=pr_merged)}
        self.assertEqual(states[a], planner.PASS_UNMERGED)       # never MERGED on an unreadable PR
        self.assertEqual(states[b], planner.PASS_UNMERGED)


if __name__ == "__main__":
    unittest.main()
