"""Cross-lane isolation on a real git remote (a local bare repository).

Negative tests for the places where several controllers (Claude AUTO, the
ChatGPT SEMI_AUTO controller, the colour lanes) share one carrier branch and
one global Loop-number namespace.  No network, no Jules, no GitHub: the remote
is a temporary bare repository and every write goes through the production
``GitLiveClient`` (single-file commits, non-force pushes, readback).

Each test asserts what must NOT happen: a second command, a second budget
slot, a write under a stale owner, or a clobbered record of another lane.
"""
from __future__ import annotations

import json
import os
import threading
import unittest

from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_dispatch import claim_path, command_path
from automation.command_bus.claude_jules_live_adapter import GitLiveClient
from automation.command_bus.claude_jules_live_budget import LiveBudgetLedger
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend, owner_event_path
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    CARRIER, DATA, LOOP, NOW, owner_event, policy, roadmap, task_spec,
)
from automation.command_bus.tests.test_claude_jules_live_adapter import Remote, git

COMMANDS_DIR = "automation/command_bus/jules_api_requests/"


def other_lane_claim(number: int, lane: str = "J-RED") -> str:
    """A record written by another lane: opaque to Claude AUTO, must survive untouched."""
    return json.dumps({"schema_version": 3, "loop_number": number, "lane_id": lane, "note": "owned by another lane"})


class CrossLaneBase(unittest.TestCase):
    def setUp(self):
        self.remote = Remote()
        self.c = self.remote.client
        self.policy = policy()
        self.c.create(owner_event_path(LOOP, 1), json.dumps(owner_event()), "owner", DATA)

    def tearDown(self):
        self.remote.close()

    def loop(self, client=None):
        client = client or self.c
        return ClaudeJulesAutoLoop(client=client, refs=client, policy=self.policy,
                                   owner_reader=LoopOwnerGitHubBackend(client, branch=DATA),
                                   roadmap=roadmap(task_spec("alpha-helper")), facts=None,
                                   origin_loop_id=LOOP, lane_id="J-BLUE")

    def carrier_commands(self):
        return [c.path for c in self.c.list(COMMANDS_DIR, CARRIER)]

    def second_clone(self):
        return self.second_clone_named("clone-b")

    def second_clone_named(self, name):
        path = os.path.join(self.remote.root, name)
        git(self.remote.root, "clone", "-q", self.remote.bare, path)
        return GitLiveClient(path, tip_ttl_seconds=0)


class OtherLaneNumbersAreRespected(CrossLaneBase):
    def test_claude_skips_numbers_claimed_or_commanded_by_other_lanes(self):
        self.remote.outside_commit(CARRIER, "automation/command_bus/loop_id_claims/005.json", other_lane_claim(5), "red claim")
        self.remote.outside_commit(CARRIER, COMMANDS_DIR + "relay-dev-loop-007-blue-task.json", "{}", "blue command")
        self.c.invalidate()
        result = self.loop().step(now=NOW)
        self.assertEqual((result.action, result.status), ("DISPATCH", "DISPATCHED"), result.reason)
        self.assertIn("relay-dev-loop-008-", result.details["command_id"])
        # The other lanes' records are byte-for-byte what they wrote.
        self.assertEqual(self.c.get("automation/command_bus/loop_id_claims/005.json", CARRIER).text, other_lane_claim(5))
        self.assertEqual(self.c.get(COMMANDS_DIR + "relay-dev-loop-007-blue-task.json", CARRIER).text, "{}")

    def test_other_lane_wins_the_same_number_between_choice_and_claim(self):
        """The loser reads back the foreign claim, appends no command and burns no budget slot."""
        real_get, raced = self.c.get, []
        target = {"path": None}

        def racing_get(path, ref):
            if path.startswith("automation/command_bus/loop_id_claims/") and ref == CARRIER and not raced:
                raced.append(path)
                target["path"] = path
                self.remote.outside_commit(CARRIER, path, other_lane_claim(int(path.rsplit("/", 1)[-1][:-5])), "red wins race")
                return None  # our pre-read happened just before their write
            return real_get(path, ref)

        self.c.get = racing_get
        first = self.loop().step(now=NOW)
        self.c.get = real_get
        self.assertEqual(len(raced), 1, "race was not exercised")
        self.assertEqual(first.status, "BLOCKED", first.reason)
        self.assertEqual(self.carrier_commands(), [], "a command was appended despite a lost claim")
        self.assertEqual(LiveBudgetLedger(self.c, data_branch=DATA).used(), 0)
        self.assertEqual(json.loads(self.c.get(target["path"], CARRIER).text)["lane_id"], "J-RED")
        # Next step re-plans on a fresh number instead of retrying the lost one.
        second = self.loop().step(now=NOW)
        self.assertEqual(second.status, "DISPATCHED", second.reason)
        self.assertNotIn(target["path"].rsplit("/", 1)[-1][:-5], second.details["command_id"].split("-")[3])
        self.assertEqual(len(self.carrier_commands()), 1)
        self.assertEqual(LiveBudgetLedger(self.c, data_branch=DATA).used(), 1)


class StaleOwnerCannotDispatch(CrossLaneBase):
    def test_semiauto_owner_with_live_lease_fences_claude_with_zero_writes(self):
        semi = owner_event(generation=2, role="SEMI_AUTO", holder="chatgpt-controller-1",
                           event_type="HANDOFF", previous=owner_event())
        self.c.create(owner_event_path(LOOP, 2), json.dumps(semi), "chatgpt takes over", DATA)
        carrier, data = self.remote.head(CARRIER), self.remote.head(DATA)
        result = self.loop().step(now=NOW)
        self.assertEqual(result.action, "STOP", result.reason)
        self.assertNotEqual(result.status, "DISPATCHED")
        self.assertEqual((self.remote.head(CARRIER), self.remote.head(DATA)), (carrier, data))

    def test_expired_auto_lease_cannot_dispatch(self):
        other = Remote()
        self.addCleanup(other.close)
        expired = owner_event(expires_at="2026-10-01T12:30:00+00:00")  # lease ended before NOW (13:00)
        other.client.create(owner_event_path(LOOP, 1), json.dumps(expired), "expired owner", DATA)
        client = other.client
        carrier = other.head(CARRIER)
        result = ClaudeJulesAutoLoop(client=client, refs=client, policy=self.policy,
                                     owner_reader=LoopOwnerGitHubBackend(client, branch=DATA),
                                     roadmap=roadmap(task_spec("alpha-helper")), facts=None,
                                     origin_loop_id=LOOP, lane_id="J-BLUE").step(now=NOW)
        self.assertEqual(result.action, "STOP", result.reason)
        self.assertEqual(other.head(CARRIER), carrier)


class DuplicateRunsCollapseToOne(CrossLaneBase):
    def test_two_controllers_stepping_concurrently_append_one_command_and_use_one_slot(self):
        clone_b = self.second_clone()
        results, errors = [], []
        barrier = threading.Barrier(2)

        def run(client):
            try:
                barrier.wait(timeout=10)
                results.append(self.loop(client).step(now=NOW))
            except Exception as exc:  # a crash is a test failure, not a pass
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(client,)) for client in (self.c, clone_b)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.c.invalidate()
        commands = self.carrier_commands()
        self.assertLessEqual(len(commands), 1, f"duplicate commands appended: {commands}")
        self.assertLessEqual(LiveBudgetLedger(self.c, data_branch=DATA).used(), 1)
        for result in results:
            self.assertNotEqual(result.status, "DISPATCHED_TWICE")
        # Whatever raced, a later step converges on the single dispatched command, never a second one.
        converge = self.loop().step(now=NOW)
        self.c.invalidate()
        self.assertEqual(len(self.carrier_commands()), 1, converge.reason)
        self.assertEqual(LiveBudgetLedger(self.c, data_branch=DATA).used(), 1)

    def test_replayed_step_after_dispatch_does_not_resend(self):
        first = self.loop().step(now=NOW)
        self.assertEqual(first.status, "DISPATCHED", first.reason)
        before = (self.remote.head(CARRIER), self.remote.head(DATA))
        for _ in range(3):
            again = self.loop().step(now=NOW)
            self.assertEqual(again.status, "WAITING_FOR_RESULT", again.reason)
        self.assertEqual((self.remote.head(CARRIER), self.remote.head(DATA)), before)


class UnknownWritesAreNotResent(CrossLaneBase):
    def test_lost_response_after_command_write_is_recovered_by_readback_not_resend(self):
        real_create, state = self.c.create, {"lost": 0}

        def create_losing_response(path, text, message, branch):
            content = real_create(path, text, message, branch)
            if path.startswith(COMMANDS_DIR) and not state["lost"]:
                state["lost"] = 1
                raise RuntimeError("response lost after write")
            return content

        self.c.create = create_losing_response
        first = self.loop().step(now=NOW)
        self.c.create = real_create
        self.assertEqual(state["lost"], 1, "fault was not injected")
        self.assertEqual(first.status, "DISPATCHED", first.reason)
        self.assertEqual(len(self.carrier_commands()), 1)
        self.assertEqual(LiveBudgetLedger(self.c, data_branch=DATA).used(), 1)

    def test_restart_with_intent_but_no_receipt_resumes_the_same_command(self):
        loop = self.loop()
        original, hit = loop.dispatcher._create_once, []

        def crash_after_claim(path, record, branch, message, **kw):
            outcome = original(path, record, branch, message, **kw)
            if path.startswith("automation/command_bus/loop_id_claims/") and not hit:
                hit.append(path)
                raise KeyboardInterrupt("process killed after the claim write")
            return outcome

        loop.dispatcher._create_once = crash_after_claim
        with self.assertRaises(KeyboardInterrupt):
            loop.step(now=NOW)
        self.assertEqual(self.carrier_commands(), [])  # claim exists, command not yet
        resumed = self.loop().step(now=NOW)  # a brand-new process
        self.assertEqual((resumed.action, resumed.status), ("RESUME_DISPATCH", "DISPATCHED"), resumed.reason)
        self.assertEqual(len(self.carrier_commands()), 1)
        self.assertEqual(LiveBudgetLedger(self.c, data_branch=DATA).used(), 1)
        claims = [c.path for c in self.c.list("automation/command_bus/loop_id_claims/", CARRIER)]
        self.assertEqual(len(claims), 1, claims)


class BudgetCapHoldsUnderContention(CrossLaneBase):
    def test_twelve_concurrent_controllers_never_exceed_the_fixed_live_cap(self):
        """The LIVE budget is a cost safety fence: contention may refuse or defer, never overspend."""
        workers = 12
        clients = [self.c] + [self.second_clone_named(f"clone-w{i}") for i in range(1, workers)]
        outcomes, errors = [], []
        barrier = threading.Barrier(workers)

        def acquire(index, client):
            try:
                ledger = LiveBudgetLedger(client, data_branch=DATA)
                barrier.wait(timeout=30)
                outcomes.append(ledger.acquire(command_id=f"relay-dev-loop-9{index:02d}-contend",
                                               intent_sha256=f"{index:064x}", origin_loop_id=LOOP,
                                               acquired_at=NOW).status)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=acquire, args=(i, c)) for i, c in enumerate(clients)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=300)
        self.assertEqual(errors, [])
        self.c.invalidate()
        ledger = LiveBudgetLedger(self.c, data_branch=DATA)
        slots = ledger.slots()  # raises if non-contiguous, duplicated, tampered or over the cap
        self.assertLessEqual(len(slots), ledger.cap)
        acquired = outcomes.count("ACQUIRED")
        self.assertEqual(acquired, len(slots), outcomes)
        self.assertEqual(len({s["command_id"] for s in slots}), len(slots))
        self.assertTrue(all(o in {"ACQUIRED", "EXHAUSTED", "UNKNOWN"} for o in outcomes), outcomes)


if __name__ == "__main__":
    unittest.main()
