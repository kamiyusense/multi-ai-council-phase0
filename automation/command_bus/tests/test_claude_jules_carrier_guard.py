"""Shared-carrier quiet guard, new-stream acquire and AUTO lease renewal.

Real bare git remote (see ``test_claude_jules_live_adapter``); REST reads are
stubbed.  The guard keeps Claude's claim/command writes out of the window in
which another controller's carrier run is unfinished or just pushed, so the
carrier workflow's single concurrency group never cancels anyone's pending run.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_dispatch import DispatchResult, claim_path, command_path
from automation.command_bus.claude_jules_handover import StreamActivity, decide_renew, decide_takeover
from automation.command_bus.claude_jules_live import CarrierQuietGuard, cancelled_carrier_runs, handover
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend, owner_event_path
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    CARRIER, DATA, LOOP, NOW, REPO, owner_event, policy, roadmap, task_spec,
)
from automation.command_bus.tests.test_claude_jules_live_adapter import Remote, StubRest


class GuardRest(StubRest):
    def __init__(self):
        super().__init__()
        self.active: list[dict] = []
        self.recent: list[dict] = []
        self.fail = False

    def active_workflow_runs(self, workflow):
        if self.fail:
            raise RuntimeError("HTTP 502")
        return list(self.active)

    def recent_workflow_runs(self, workflow, per_page=30):
        return list(self.recent)


class Switch:
    """A guard whose verdict the test flips."""

    def __init__(self, status="PASS"):
        self.status, self.calls = status, 0

    def __call__(self):
        self.calls += 1
        return DispatchResult(self.status, "CARRIER_BUSY: test" if self.status == "WAIT" else "quiet")


class CarrierQuietGuardTests(unittest.TestCase):
    def setUp(self):
        self.remote = Remote()
        self.rest = GuardRest()
        tip_time = datetime.fromisoformat(self.remote.client.commit_time(self.remote.head(CARRIER)))
        self.later = lambda minutes: (lambda: tip_time + timedelta(minutes=minutes))

    def tearDown(self):
        self.remote.close()

    def guard(self, minutes):
        return CarrierQuietGuard(git=self.remote.client, rest=self.rest, carrier_branch=CARRIER,
                                 clock=self.later(minutes))()

    def test_quiet_busy_recent_and_unreadable(self):
        self.assertEqual(self.guard(10).status, "PASS")
        recent = self.guard(2)
        self.assertEqual(recent.status, "WAIT")
        self.assertIn("CARRIER_BUSY", recent.reason)
        self.rest.active = [{"id": 9001, "status": "in_progress"}]
        busy = self.guard(60)
        self.assertEqual(busy.status, "WAIT")
        self.assertIn("9001", busy.reason)
        self.rest.fail = True
        self.assertEqual(self.guard(60).status, "UNKNOWN")

    def test_cancelled_runs_are_reported_since_a_time(self):
        self.rest.recent = [
            {"id": 1, "head_sha": "a", "created_at": "2026-10-01T10:00:00Z", "conclusion": "cancelled"},
            {"id": 2, "head_sha": "b", "created_at": "2026-10-01T12:00:00Z", "conclusion": "cancelled"},
            {"id": 3, "head_sha": "c", "created_at": "2026-10-01T12:05:00Z", "conclusion": "success"},
        ]
        found = cancelled_carrier_runs(self.rest, since="2026-10-01T11:00:00+00:00")
        self.assertEqual([r["id"] for r in found], [2])


class GuardedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.remote = Remote()
        self.c = self.remote.client
        self.policy = policy()
        self.c.create(owner_event_path(LOOP, 1), json.dumps(owner_event()), "owner", DATA)

    def tearDown(self):
        self.remote.close()

    def loop(self, guard):
        return ClaudeJulesAutoLoop(client=self.c, refs=self.c, policy=self.policy,
                                   owner_reader=LoopOwnerGitHubBackend(self.c, branch=DATA),
                                   roadmap=roadmap(task_spec("alpha-helper")), facts=None,
                                   origin_loop_id=LOOP, lane_id="J-BLUE", carrier_guard=guard)

    def test_busy_carrier_waits_with_nothing_written(self):
        carrier, data = self.remote.head(CARRIER), self.remote.head(DATA)
        result = self.loop(Switch("WAIT")).step(now=NOW)
        self.assertEqual((result.action, result.status), ("WAIT", "CARRIER_BUSY"), result.reason)
        self.assertEqual((self.remote.head(CARRIER), self.remote.head(DATA)), (carrier, data))

    def test_carrier_turning_busy_mid_dispatch_resumes_the_same_intent(self):
        guard = Switch("PASS")
        loop = self.loop(guard)
        dispatcher = loop.dispatcher
        original = dispatcher._create_once
        flipped: list[str] = []

        def create_then_busy(path, record, branch, message, **kw):
            outcome = original(path, record, branch, message, **kw)
            if "dispatch-intents" in path and not flipped:
                flipped.append(path)
                guard.status = "WAIT"  # another controller pushed right after our intent write
            return outcome

        dispatcher._create_once = create_then_busy
        carrier = self.remote.head(CARRIER)
        first = loop.step(now=NOW)
        self.assertEqual((first.action, first.status), ("WAIT", "CARRIER_BUSY"), first.reason)
        self.assertEqual(self.remote.head(CARRIER), carrier)  # no claim, no command
        command_id = first.details["command_id"]
        guard.status = "PASS"
        second = loop.step(now=NOW)
        self.assertEqual((second.action, second.status), ("RESUME_DISPATCH", "DISPATCHED"), second.reason)
        self.assertEqual(second.details["command_id"], command_id)
        self.assertIsNotNone(self.c.get(command_path(command_id), CARRIER))
        loop_id = json.loads(self.c.get(command_path(command_id), CARRIER).text)["command_id"].split("-")[3]
        self.assertIsNotNone(self.c.get(claim_path(loop_id), CARRIER))

    def test_guard_failure_is_unknown_not_pass(self):
        def broken():
            raise RuntimeError("boom")
        result = self.loop(broken).step(now=NOW)
        self.assertEqual((result.action, result.status), ("STOP", "UNKNOWN"), result.reason)


class NewStreamAndRenewTests(unittest.TestCase):
    def test_new_stream_acquire_only_when_never_owned_or_commanded(self):
        kwargs = dict(auto_holder="claude-auto-controller-1", loop_id=LOOP, expected_repo=REPO,
                      expected_pr=999, target_head="a" * 40, now=NOW)
        empty = StreamActivity(None, (), ())
        fresh = decide_takeover(owner_chain=[], activity=empty, **kwargs)
        self.assertEqual((fresh.status, fresh.event["event_type"], fresh.event["owner_role"]),
                         ("ELIGIBLE", "ACQUIRE", "AUTO"))
        commanded = StreamActivity(None, (), ("relay-dev-loop-040-x",))
        self.assertEqual(decide_takeover(owner_chain=[], activity=commanded, **kwargs).status, "UNKNOWN")
        busy = StreamActivity(None, ("relay-dev-loop-040-x",), ("relay-dev-loop-040-x",))
        self.assertEqual(decide_takeover(owner_chain=[], activity=busy, **kwargs).status, "BLOCKED")

    def test_renew_rules(self):
        auto = owner_event()  # live AUTO lease held by the fake policy holder
        holder = auto["holder_id"]
        ok = decide_renew(owner_chain=[auto], auto_holder=holder, outstanding_dispatches=1,
                          half_written_intents=0, target_head="b" * 40, now=NOW)
        self.assertEqual((ok.status, ok.event["event_type"], ok.event["generation"]), ("ELIGIBLE", "RENEW", 2))
        half = decide_renew(owner_chain=[auto], auto_holder=holder, outstanding_dispatches=0,
                            half_written_intents=1, target_head="b" * 40, now=NOW)
        self.assertEqual(half.status, "BLOCKED")
        other = decide_renew(owner_chain=[auto], auto_holder="someone-else", outstanding_dispatches=0,
                             half_written_intents=0, target_head="b" * 40, now=NOW)
        self.assertEqual(other.status, "BLOCKED")
        expired = decide_renew(owner_chain=[auto], auto_holder=holder, outstanding_dispatches=0,
                               half_written_intents=0, target_head="b" * 40, now=auto["expires_at"])
        self.assertEqual(expired.status, "BLOCKED")


class LiveNewStreamTests(unittest.TestCase):
    """Isolated test target: acquire, dispatch, renew, hand back - on real git."""

    def setUp(self):
        self.remote = Remote()
        self.c = self.remote.client
        self.rest = GuardRest()
        self.policy = policy(allowed_lane_ids=["J-GREEN"],
                             live_dispatch_authorization=dict(policy()["live_dispatch_authorization"],
                                                              expires_at="2026-10-03T00:00:00+00:00"))

    def tearDown(self):
        self.remote.close()

    def act(self, action, now, write=True):
        return handover(action, git=self.c, rest=self.rest, policy=self.policy, origin_loop_id=LOOP,
                        lane_id="J-GREEN", now=now, write=write)

    def test_acquire_dispatch_renew_handback(self):
        acquired = self.act("takeover", NOW)
        self.assertEqual(acquired["status"], "APPENDED", acquired)
        self.assertEqual(self.act("takeover", NOW)["status"], "BLOCKED")  # never two AUTO controllers
        loop = ClaudeJulesAutoLoop(client=self.c, refs=self.c, policy=self.policy,
                                   owner_reader=LoopOwnerGitHubBackend(self.c, branch=DATA),
                                   roadmap=roadmap(task_spec("alpha-helper")), facts=None,
                                   origin_loop_id=LOOP, lane_id="J-GREEN", carrier_guard=Switch("PASS"))
        self.assertEqual(loop.step(now=NOW).status, "DISPATCHED")
        later = (datetime.fromisoformat(NOW) + timedelta(hours=2)).isoformat()
        renewed = self.act("renew", later)
        self.assertEqual(renewed["status"], "APPENDED", renewed)
        self.assertEqual(self.act("handback", later)["status"], "BLOCKED")  # dispatch outstanding
        events = [json.loads(c.text) for c in self.c.list(f"automation/command_bus/loop_owner_events/{LOOP}/", DATA)]
        self.assertEqual([e["event_type"] for e in events], ["ACQUIRE", "RENEW"])
        self.assertGreater(datetime.fromisoformat(events[-1]["expires_at"]),
                           datetime.fromisoformat(events[0]["expires_at"]))


if __name__ == "__main__":
    unittest.main()
