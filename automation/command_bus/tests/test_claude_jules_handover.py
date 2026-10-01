"""SEMI_AUTO (ChatGPT) <-> AUTO (Claude) handover of one Jules stream (mock)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta

from automation.command_bus.claude_jules_handover import (
    SEMIAUTO_HOLDER, StreamActivity, append_decision, decide_handback, decide_reclaim, decide_takeover,
    observe_stream,
)
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    CARRIER, DATA, HOLDER, LOOP, REPO, TARGET, owner_event, policy, roadmap, task_spec,
)
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World

T0 = datetime.fromisoformat("2026-10-01T09:00:00+00:00")


def at(hours: float) -> str:
    return (T0 + timedelta(hours=hours)).isoformat()


def semiauto_acquire(expires_hours: float = 1) -> dict:
    event = owner_event(role="SEMI_AUTO", holder=SEMIAUTO_HOLDER, expires_at=at(expires_hours))
    event["claimed_at"] = at(0)
    return event


def gpt_claim(n: int, hours: float, lane: str = "J-BLUE", target: str = TARGET) -> dict:
    return {"lane_id": lane, "target_branch": target, "command_id": f"relay-dev-loop-{n:03d}-gpt-task",
            "claimed_at": at(hours)}


def pr(updated_hours: float, state: str = "open") -> dict:
    return {"state": state, "updated_at": at(updated_hours), "merged_at": None}


class StreamObservationTests(unittest.TestCase):
    def test_in_flight_and_last_activity(self):
        claims = [gpt_claim(50, 0), gpt_claim(51, 1), gpt_claim(52, 1, lane="J-RED")]
        activity = observe_stream(lane_id="J-BLUE", target_branch=TARGET, claims=claims,
                                  result_prs={"relay-dev-loop-050-gpt-task": [pr(0.5, "closed")]}, owner_chain=[], now=at(2))
        # 050 already has a settled result PR; 051 has no PR yet and is younger than the result deadline: Jules may still run.
        self.assertEqual(activity.in_flight, ("relay-dev-loop-051-gpt-task",))
        self.assertEqual(activity.last_activity_at, at(1))
        moving = observe_stream(lane_id="J-BLUE", target_branch=TARGET, claims=claims[:1],
                                result_prs={"relay-dev-loop-050-gpt-task": [pr(0.5)]}, owner_chain=[], now=at(2))
        self.assertEqual(moving.in_flight, ("relay-dev-loop-050-gpt-task",))  # open PR changed < 2h ago
        self.assertNotIn("relay-dev-loop-052-gpt-task", activity.commands)  # other lane is not this stream
        later = observe_stream(lane_id="J-BLUE", target_branch=TARGET, claims=claims,
                               result_prs={"relay-dev-loop-050-gpt-task": [pr(0.5)],
                                           "relay-dev-loop-051-gpt-task": [pr(1.5)]}, owner_chain=[], now=at(4))
        self.assertEqual((later.in_flight, later.last_activity_at), ((), at(1.5)))
        with self.assertRaises(ValueError):
            observe_stream(lane_id="J-BLUE", target_branch=TARGET, claims=[gpt_claim(53, 9)], result_prs={},
                           owner_chain=[], now=at(4))


class TakeoverDecisionTests(unittest.TestCase):
    def decide(self, chain, activity, now, holder=HOLDER):
        return decide_takeover(owner_chain=chain, activity=activity, auto_holder=holder, loop_id=LOOP,
                               expected_repo=REPO, expected_pr=999, target_head="a" * 40, now=now)

    def test_time_alone_never_takes_ownership(self):
        idle = StreamActivity(at(0), (), ("c",))
        self.assertEqual(self.decide([semiauto_acquire(expires_hours=8)], idle, at(5)).status, "BLOCKED")  # valid lease
        busy = StreamActivity(at(0), ("relay-dev-loop-051-gpt-task",), ("c",))
        self.assertEqual(self.decide([semiauto_acquire()], busy, at(5)).status, "BLOCKED")  # Jules in flight
        recent = StreamActivity(at(4), (), ("c",))
        self.assertEqual(self.decide([semiauto_acquire()], recent, at(5)).status, "BLOCKED")  # not stalled 2h
        self.assertEqual(self.decide([semiauto_acquire()], StreamActivity(None, (), ()), at(5)).status, "UNKNOWN")

    def test_eligible_takeover_is_a_fenced_handoff(self):
        decision = self.decide([semiauto_acquire()], StreamActivity(at(0), (), ("c",)), at(3))
        self.assertEqual(decision.status, "ELIGIBLE", decision.reason)
        event = decision.event
        self.assertEqual((event["event_type"], event["owner_role"], event["generation"], event["previous_owner_role"]),
                         ("HANDOFF", "AUTO", 2, "SEMI_AUTO"))
        legacy = self.decide([], StreamActivity(at(0), (), ("c",)), at(3))  # ChatGPT never wrote an owner
        self.assertEqual((legacy.status, legacy.event["event_type"]), ("ELIGIBLE", "ACQUIRE"))

    def test_never_two_auto_controllers_and_closed_chains_stay_closed(self):
        auto = self.decide([semiauto_acquire()], StreamActivity(at(0), (), ()), at(3)).event
        self.assertEqual(self.decide([semiauto_acquire(), auto], StreamActivity(at(0), (), ()), at(9),
                                     holder="claude-other").status, "BLOCKED")
        released = dict(semiauto_acquire(), event_type="RELEASE")
        self.assertIn(self.decide([released], StreamActivity(at(0), (), ()), at(3)).status, {"BLOCKED", "UNKNOWN"})

    def test_handback_only_at_a_boundary_and_reclaim_only_after_expiry(self):
        auto = self.decide([semiauto_acquire()], StreamActivity(at(0), (), ()), at(3)).event
        chain = [semiauto_acquire(), auto]
        busy = decide_handback(owner_chain=chain, auto_holder=HOLDER, outstanding_dispatches=1,
                               target_head="b" * 40, now=at(4))
        self.assertEqual(busy.status, "BLOCKED")
        self.assertEqual(decide_handback(owner_chain=chain, auto_holder="claude-other", outstanding_dispatches=0,
                                         target_head="b" * 40, now=at(4)).status, "BLOCKED")
        back = decide_handback(owner_chain=chain, auto_holder=HOLDER, outstanding_dispatches=0,
                               target_head="b" * 40, now=at(4))
        self.assertEqual((back.status, back.event["owner_role"], back.event["holder_id"]),
                         ("ELIGIBLE", "SEMI_AUTO", SEMIAUTO_HOLDER))
        self.assertEqual(decide_reclaim(owner_chain=chain, semiauto_holder=SEMIAUTO_HOLDER,
                                        target_head="b" * 40, now=at(4)).status, "BLOCKED")  # AUTO lease valid
        reclaim = decide_reclaim(owner_chain=chain, semiauto_holder=SEMIAUTO_HOLDER, target_head="b" * 40, now=at(7))
        self.assertEqual((reclaim.status, reclaim.event["generation"]), ("ELIGIBLE", 3))


class HandoverEndToEndTests(unittest.TestCase):
    """ChatGPT stalls -> Claude takes over -> one full task -> hands back -> ChatGPT owns again."""

    def world(self):
        # Claude's lane is whatever the stream uses; it is not a Claude-only lane.
        w = World(owner=[semiauto_acquire()], plan=roadmap(task_spec("alpha-helper")))
        w.policy = policy(live_dispatch_authorization=dict(policy()["live_dispatch_authorization"],
                                                           expires_at=at(48)))
        backend = LoopOwnerGitHubBackend(w.github, branch=DATA)
        return w, backend

    def chain(self, w):
        prefix = f"automation/command_bus/loop_owner_events/{LOOP}/"
        return [json.loads(c.text) for c in w.github.list(prefix, DATA)]

    def takeover(self, w, backend, now, holder=HOLDER):
        activity = observe_stream(lane_id="J-BLUE", target_branch=TARGET,
                                  claims=[gpt_claim(40, 0)], result_prs={"relay-dev-loop-040-gpt-task": [pr(0.2, "closed")]},
                                  owner_chain=self.chain(w), now=now)
        decision = decide_takeover(owner_chain=self.chain(w), activity=activity, auto_holder=holder, loop_id=LOOP,
                                   expected_repo=REPO, expected_pr=999, target_head=w.github.branches[TARGET], now=now)
        return append_decision(backend, decision)

    def test_semiauto_auto_semiauto_round_trip(self):
        w, backend = self.world()
        # While ChatGPT owns the stream, Claude never dispatches.
        self.assertEqual(w.step(now=at(0.5)).action, "STOP")
        self.assertEqual(w.commands(), [])
        taken = self.takeover(w, backend, at(3))
        self.assertEqual(taken.status, "APPENDED", taken.reason)
        # A second Claude racing for the same generation loses (create-only generation path).
        stale = append_decision(backend, decide_takeover(
            owner_chain=self.chain(w)[:1], activity=StreamActivity(at(0), (), ()), auto_holder="claude-other",
            loop_id=LOOP, expected_repo=REPO, expected_pr=999, target_head="a" * 40, now=at(3)))
        self.assertEqual(stale.status, "BLOCKED")

        first = w.step(now=at(3))
        self.assertEqual((first.action, first.status), ("DISPATCH", "DISPATCHED"), first.reason)
        # Handback is refused while the Claude dispatch is outstanding.
        busy = decide_handback(owner_chain=self.chain(w), auto_holder=HOLDER, outstanding_dispatches=1,
                               target_head=w.github.branches[TARGET], now=at(3.1))
        self.assertEqual(busy.status, "BLOCKED")
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        self.assertEqual(w.step(now=at(3.2)).status, "PASS")
        self.assertEqual(w.step(now=at(3.3)).status, "ADOPTED")
        back = append_decision(backend, decide_handback(owner_chain=self.chain(w), auto_holder=HOLDER,
                                                        outstanding_dispatches=0,
                                                        target_head=w.github.branches[TARGET], now=at(3.4)))
        self.assertEqual(back.status, "APPENDED", back.reason)
        after = w.step(now=at(3.5))
        self.assertEqual((after.action, after.status), ("STOP", "BLOCKED"))
        self.assertIn("SEMI_AUTO", after.reason)
        self.assertEqual(len(w.commands()), 1)  # nothing dispatched after the handback
        self.assertEqual([e["owner_role"] for e in self.chain(w)], ["SEMI_AUTO", "AUTO", "SEMI_AUTO"])

    def test_claude_session_loss_while_owning_then_semiauto_reclaims_after_expiry(self):
        w, backend = self.world()
        self.takeover(w, backend, at(3))
        w.step(now=at(3))  # dispatched, then the Claude environment disappears
        self.assertEqual(decide_reclaim(owner_chain=self.chain(w), semiauto_holder=SEMIAUTO_HOLDER,
                                        target_head=w.github.branches[TARGET], now=at(4)).status, "BLOCKED")
        reclaimed = append_decision(backend, decide_reclaim(owner_chain=self.chain(w), semiauto_holder=SEMIAUTO_HOLDER,
                                                            target_head=w.github.branches[TARGET], now=at(6.5)))
        self.assertEqual(reclaimed.status, "APPENDED")
        # A late Claude session with the old generation can no longer act.
        late = w.step(now=at(6.6))
        self.assertEqual((late.action, late.status), ("STOP", "BLOCKED"))
        self.assertEqual(len(w.commands()), 1)

    def test_takeover_blocked_while_chatgpt_jules_task_in_flight(self):
        w, backend = self.world()
        activity = observe_stream(lane_id="J-BLUE", target_branch=TARGET, claims=[gpt_claim(41, 2)], result_prs={},
                                  owner_chain=self.chain(w), now=at(4.5))
        decision = append_decision(backend, decide_takeover(
            owner_chain=self.chain(w), activity=activity, auto_holder=HOLDER, loop_id=LOOP, expected_repo=REPO,
            expected_pr=999, target_head=w.github.branches[TARGET], now=at(4.5)))
        self.assertEqual(decision.status, "BLOCKED")
        self.assertEqual(len(self.chain(w)), 1)


if __name__ == "__main__":
    unittest.main()
