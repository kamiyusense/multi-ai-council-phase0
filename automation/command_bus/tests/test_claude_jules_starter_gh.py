"""Starter GitHub adapter: snapshot shape from fake GETs; writes are prepared as data and never sent."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_gh as ghs
from automation.command_bus.tests import starter_world as sw

REPO = "kamiyusense/multi-ai-council-phase0"
ROUTE = {"transport": st.ROUTE, "auth_method": "account_oauth", "billing_route": "subscription"}


def api_issue(world, n):
    i = world.gh.issues[n]
    return {"state": "open" if i["state"] == "OPEN" else "closed", "title": i["title"], "body": i["body"],
            "labels": [{"name": l} for l in i["labels"]], "number": n}


class FakeApi:
    def __init__(self, world):
        self.world = world
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)
        w = self.world
        tail = path.split(f"repos/{REPO}/", 1)[1]
        if tail.startswith("issues?labels="):
            return [api_issue(w, n) for n, i in w.gh.issues.items() if st.LABEL in i["labels"]]
        if tail.startswith("issues/"):
            parts = tail.split("?")[0].split("/")
            n = int(parts[1])
            if len(parts) == 2:
                return api_issue(w, n)
            if parts[2] == "comments":
                return [{"id": c["id"], "user": {"login": c["author"]}, "body": c["body"],
                         "created_at": c["created_at"]} for c in w.gh.issues[n]["comments"]]
            return [{"event": e["event"], "label": {"name": e["label"]}, "actor": {"login": e["actor"]},
                     "created_at": e["created_at"]} for e in w.gh.issues[n]["label_events"]]
        if tail.startswith("pulls/"):
            return {"head": {"sha": w.gh.prs[int(tail.split("/")[1])]["head"]}}
        if tail.startswith("git/ref/heads/"):
            return {"object": {"sha": w.main_head}}
        raise AssertionError(path)


class AdapterTests(unittest.TestCase):
    def test_snapshot_from_gets_leads_to_the_same_step_as_the_world(self):
        c = sw.campaign("cg", 2)
        w = sw.World([c])
        seed, first = sw.seed_predecessor(w, c)
        api = FakeApi(w)
        snap = ghs.read_snapshot(api, repo=REPO, campaign=c, issue=first, predecessor=seed, route_declaration=ROUTE,
                                 now=st._fmt(w.now))
        step = st.next_step(snap, campaign=c, controller="local")
        self.assertEqual(step.action, st.WRITE_INTENT)
        self.assertEqual(snap["predecessor"]["pr_head"], sw.sha("seed"))
        self.assertEqual(snap["active_tasks"], [])          # the seed is labeled but terminal (PASS)
        prepared = ghs.prepare(step, REPO)
        self.assertEqual(prepared["command"][:4], ["gh", "api", "--method", "POST"])
        self.assertEqual(prepared["body"], step.body)
        self.assertTrue(all("POST" not in p for p in api.calls))

    def test_label_write_is_prepared_never_sent(self):
        step = st.Step(st.WRITE_LABEL, "x", 338, nonce="n")
        self.assertEqual(ghs.prepare(step, REPO)["command"][-1], "labels[]=jules")
        self.assertIsNone(ghs.prepare(st.Step(st.DEFER, "x", 338), REPO))

    def test_module_only_runs_get_requests(self):
        tree = ast.parse(Path(ghs.__file__).read_text(encoding="utf-8"))
        runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "run"]
        self.assertEqual(len(runs), 1)                       # the single subprocess.run in gh_get
        self.assertIn("\"--method\", \"GET\"", Path(ghs.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
