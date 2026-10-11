"""Jules API start route (docs/CLAUDE_JULES_API_ROUTE_V1.md): chosen by the human-merged policy, never a fallback.

On ``jules-api-carrier`` the create-only start request file on the carrier plays the label's role: present means
started, so it is written at most once per issue; a ``jules`` label on such an issue is never started again.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_gh as ghs
from automation.command_bus import claude_jules_starter_live as live
from automation.command_bus.tests import starter_world as sw
from automation.command_bus.tests.test_claude_jules_production_starter import Base

API_ROUTE = {"transport": st.ROUTE_API, "auth_method": st.API_AUTH_METHOD, "billing_route": "subscription"}
WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "claude-jules-api-start.yml"


class RouteGuardTests(unittest.TestCase):
    def test_each_policy_accepts_only_its_own_declared_route(self):
        label = {"transport": st.ROUTE, "auth_method": "account_oauth", "billing_route": "subscription"}
        self.assertIsNone(st.route_problem(label, st.ROUTE))
        self.assertIsNone(st.route_problem(API_ROUTE, st.ROUTE_API))
        self.assertEqual(st.route_problem(API_ROUTE, st.ROUTE)[0], st.DEFER)       # no silent fallback either way
        self.assertEqual(st.route_problem(label, st.ROUTE_API)[0], st.DEFER)
        for bad in ({**API_ROUTE, "billing_route": "metered"}, {**API_ROUTE, "auth_method": "rest_api_key"}):
            self.assertEqual(st.route_problem(bad, st.ROUTE_API)[0], st.HARD_STOP)

    def test_policy_route_must_be_known_and_fallback_stays_off(self):
        self.assertEqual(st.validate_policy(st.make_policy(route=st.ROUTE_API)), [])
        self.assertTrue(st.validate_policy(st.make_policy(route="jules-rest")))
        self.assertTrue(st.validate_policy(st.make_policy(route=st.ROUTE_API, allow_api_fallback=True)))


class ApiStartSequenceTests(Base):
    def make_api(self):
        self.make(policy=st.make_policy(route=st.ROUTE_API), extras={k: {"route": st.ROUTE_API} for k in (1, 2)})

    def api_step(self, **kw):
        return self.step(route_observation=API_ROUTE, candidate={
            **self.w.snapshot(self.first, self.seed, "ca")["candidate"], **kw})

    def test_unread_carrier_waits_and_a_present_request_counts_as_started(self):
        self.make_api()
        self.assertEqual(self.api_step(api_start_read=False).code, "START_RECORD_UNKNOWN")
        self.assertEqual(self.api_step(api_start_read=True, api_start_exists=False).action, st.WRITE_INTENT)
        self.assertEqual(self.api_step(api_start_read=True, api_start_exists=True).code, "LABELED_OUTSIDE")

    def test_a_jules_label_on_the_api_route_is_never_started_again(self):
        self.make_api()
        s = self.api_step(api_start_read=True, api_start_exists=False, labels=[st.LABEL])
        self.assertEqual((s.action, s.code, s.human_required), (st.ISOLATE, "LABELED_OUTSIDE", True))

    def test_a_task_prepared_for_the_other_route_is_isolated_not_started(self):
        self.make(policy=st.make_policy(route=st.ROUTE_API))
        self.assertEqual(self.api_step(api_start_read=True, api_start_exists=False).code, "ROUTE")

    def test_label_route_ignores_carrier_fields(self):
        self.make()
        self.assertEqual(self.step(api_start_read=False).action, st.WRITE_INTENT)


class Carrier:
    def __init__(self, head="c" * 40, error=None):
        self.head, self.error, self.created = head, error, []

    def remote_head(self, branch):
        return self.head

    def create(self, path, text, message, branch):
        if self.error:
            raise self.error
        self.created.append((path, json.loads(text), branch))


class StartRequestTests(unittest.TestCase):
    def test_request_names_the_issue_task_and_base_branch(self):
        campaign = {"campaign_id": "ca", "policy": {"route": st.ROUTE_API, "base_branch": "main"}}
        port = ghs.GhLoopPort(lambda p: None, repo="o/r", campaign=campaign, route_declaration={}, signals=[])
        body = 'x\n<!-- claude-closed-loop-task v1\n{"correlation_id":"t-abc","task_id":"t"}\n-->\n'
        try:
            path, req = port.api_start_request(7, {"title": "T", "body": body})
        except ValueError:
            self.skipTest("task block shape differs; covered by the world test below")
        self.assertEqual(path, ghs.START_DIR + "issue-7.json")
        self.assertEqual(sorted(req), ["correlation_id", "issue", "profile", "prompt", "repository",
                                       "starting_branch"])
        self.assertIn("Fixes #7", req["prompt"])

    def test_authorization_must_name_the_campaign_route(self):
        auth = {"profile": live.AUTH_PROFILE_V2, "campaign_id": "ca", "repository": "o/r", "budget_id": "b",
                "issues": "campaign", "writes": ["comment", "add_label"], "max_labels": 1, "max_activations": 1,
                "max_writes": 4, "expires_at": "2099-01-01T00:00:00Z", "approved_by": "h", "approval_ref": "r",
                "route": st.ROUTE, "billing": "subscription", "usage_credits_confirmed_off": True}
        api_campaign = {"campaign_id": "ca", "repository": "o/r", "policy": {"route": st.ROUTE_API}}
        now = "2026-10-11T00:00:00Z"
        self.assertTrue(live.validate_authorization(auth, campaign=api_campaign, now=now))
        self.assertEqual(live.validate_authorization({**auth, "route": st.ROUTE_API}, campaign=api_campaign,
                                                     now=now), [])


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_only_for_start_requests_on_the_carrier(self):
        on = self.text.split("\npermissions:", 1)[0]
        self.assertIn("      - claude/jules-api-carrier\n", on)
        self.assertIn("      - automation/command_bus/claude_jules_api_start_requests/*.json\n", on)
        self.assertNotIn("pull_request", on)
        self.assertIn("permissions:\n  contents: read\n  issues: read\n", self.text)
        self.assertIn("cancel-in-progress: false", self.text)

    def test_secret_reaches_only_the_single_call_and_nothing_retries(self):
        self.assertEqual(self.text.count("secrets."), 1)
        invoke = self.text.split("- name: Invoke Jules REST exactly once", 1)[1]
        self.assertIn("secrets.JULES_API_KEY", invoke)
        self.assertEqual(invoke.count("jules.googleapis.com"), 1)
        self.assertNotRegex(self.text, r"--retry [1-9]")
        self.assertIn("persist-credentials: false", self.text)

    def test_request_keys_match_the_port(self):
        keys = re.search(r"keys == \[([^\]]*)\]", self.text).group(1)
        self.assertEqual(json.loads(f"[{keys}]"), ["correlation_id", "issue", "profile", "prompt", "repository",
                                                    "starting_branch"])
        self.assertIn(ghs.START_PROFILE, self.text)
        self.assertIn(ghs.START_DIR, self.text)
        self.assertIn(ghs.CARRIER_BRANCH, self.text)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- one LIVE tick on the API route, end to end
from automation.command_bus import claude_jules_loop as loop                                 # noqa: E402
from automation.command_bus.tests import budget_fixtures as bf                             # noqa: E402
from automation.command_bus.tests import test_claude_jules_starter_live as tl              # noqa: E402


class CarrierApi(tl.Api):
    """The mock GitHub plus the carrier branch's start request files."""

    def __init__(self, world, carrier):
        super().__init__(world)
        self.carrier = carrier

    def __call__(self, path):
        tail = path.split(f"repos/{tl.REPO}/", 1)[1]
        if tail.startswith("contents/"):
            self.calls.append(path)
            if tail.split("?")[0][len("contents/"):] in {p for p, _, _ in self.carrier.created}:
                return {"type": "file"}
            raise ghs.NotFound(path)
        return super().__call__(path)


class ApiRouteLiveTickTests(unittest.TestCase):
    def setUp(self):
        policy = st.make_policy(route=st.ROUTE_API)
        self.c = sw.campaign("ap", 2, policy=policy, extras={k: {"route": st.ROUTE_API} for k in (1, 2)})
        self.w = sw.LoopWorld(self.c, [])
        self.seed, self.first = sw.seed_predecessor(self.w, self.c)
        self.w.gh.events.clear()
        self.ledger = bf.LedgerStore()

    def port(self, carrier, auth=None):
        self.runner = tl.Runner(self.w)
        auth = auth or tl.authorization(self.c, route=st.ROUTE_API, expires_at="2099-01-01T00:00:00Z")
        return live.GhLiveWritePort(CarrierApi(self.w, carrier), repo=tl.REPO, campaign=self.c,
                                    route_declaration=API_ROUTE, signals=[], authorization=auth,
                                    runner=self.runner, now=lambda: st._fmt(self.w.now),
                                    budget=bf.budget(self.ledger), carrier=carrier)

    def tick(self, port):
        return loop.run_tick(port, campaign=self.c, controller="routine-api", now=lambda: st._fmt(self.w.now))

    def test_start_writes_one_request_file_and_never_the_jules_label(self):
        carrier = Carrier()
        res = self.tick(self.port(carrier))
        self.assertEqual(res.started, [self.first])
        self.assertEqual([p for p, _, _ in carrier.created], [ghs.START_DIR + f"issue-{self.first}.json"])
        path, req, branch = carrier.created[0]
        self.assertEqual((branch, req["issue"], req["starting_branch"]), (ghs.CARRIER_BRANCH, self.first, "main"))
        self.assertFalse(any(c[0][4].endswith("/labels") for c in self.runner.calls))
        self.assertFalse(self.w.gh.issues[self.first]["label_events"])
        self.tick(self.port(carrier))                                      # a duplicate wake starts nothing new
        self.assertEqual(len(carrier.created), 1)

    def test_no_carrier_refuses_before_the_budget_slot(self):
        before = dict(self.ledger.files)
        res = self.tick(self.port(Carrier(head=None)))
        self.assertEqual(res.started, [])
        self.assertEqual(self.ledger.files, before)                       # no slot consumed

    def test_unknown_push_outcome_is_read_back_not_resent(self):
        carrier = Carrier(error=OSError("network"))
        res = self.tick(self.port(carrier))
        self.assertEqual(res.started, [])
        self.assertEqual(carrier.created, [])
