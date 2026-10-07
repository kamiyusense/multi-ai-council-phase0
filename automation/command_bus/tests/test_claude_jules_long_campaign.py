"""Long STATIC mock campaign (20 tasks, up to 30 rounds) with fault injection and a restart on every wake.

Production gate vs. scheduler: the real Loop A cap (10 dispatches) is tested by
``test_production_cap_is_back_after_the_simulator`` and the existing campaign
continuation tests.  The long run uses ``static_dispatch_simulator`` so the
scheduler can be exercised past 10 simulated dispatches without loosening the
production gate.  No network, no Jules, no LIVE.

Expected outcome per task, fixed BEFORE running (the test asserts this table):

======== ======================================================= =========== ==========
task     injected fault                                          dispatches  final
======== ======================================================= =========== ==========
long-03  semantic failure once, corrective fixes it              2           ADOPTED
long-06  dispatch-observation read fails once (bounded recovery) 1           ADOPTED
long-08  test evidence missing once (append-only reinspection)   1           ADOPTED
long-10  no result; provider RUNNING, later verified SETTLED     1           TASK_BLOCKED
long-11  depends on long-10                                      0           never ready
long-13  canonical target moves after PASS (replan)              2           ADOPTED
long-15  every delivery duplicated, plus a late old delivery     1           ADOPTED
long-17  identical finding three times (no-progress detection)   3           TASK_BLOCKED
long-19  dispatch receipt write lands but its response is lost   1           ADOPTED
others   none                                                    1 each (11) ADOPTED
======== ======================================================= =========== ==========

Total: 23 provider dispatches, 17 tasks adopted, blocked = {long-10, long-17};
the campaign ends at the genuine dependency boundary (TASK_BLOCKED with long-11
remaining), never at a round, step or retry limit.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from automation.command_bus import claude_jules_recovery_policy as rp
from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_campaign import campaign_policy_from_legacy
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend
from automation.command_bus.tests.claude_jules_autoloop_fakes import DATA, LOOP, NOW, TARGET, policy, roadmap, task_spec
from automation.command_bus.tests.claude_jules_static_simulator import simulation_authorization, static_dispatch_simulator
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World

TASKS = [f"long-{n:02d}" for n in range(1, 21)]
EXPECTED_DISPATCHES = {t: 1 for t in TASKS}
EXPECTED_DISPATCHES.update({"long-03": 2, "long-11": 0, "long-13": 2, "long-17": 3})
EXPECTED_BLOCKED = {"long-10", "long-17"}
EXPECTED_ADOPTED = set(TASKS) - EXPECTED_BLOCKED - {"long-11"}


def spec(task_id):
    name = task_id.replace("-", "_")
    return task_spec(task_id, f"automation/command_bus/{name}.py", f"automation/command_bus/tests/test_{name}.py")


class LongWorld(World):
    def controller(self) -> ClaudeJulesAutoLoop:
        return ClaudeJulesAutoLoop(
            client=self.github, refs=self.github, policy=self.policy,
            owner_reader=LoopOwnerGitHubBackend(self.github, branch=DATA), roadmap=self.roadmap,
            facts=self.facts, origin_loop_id=LOOP, lane_id="J-BLUE", campaign_policy=self.campaign,
            recovery_policy=rp.recovery_policy(semantic_max_attempts=3))


def build_world(max_rounds=30, budget=30):
    auth = simulation_authorization(policy()["live_dispatch_authorization"])
    legacy = policy(max_rounds=max_rounds, live_dispatch_authorization=auth)
    campaign = campaign_policy_from_legacy(legacy, LOOP)
    campaign.update(max_rounds=max_rounds, max_corrective_rounds_per_task=3, max_consecutive_failures=4,
                    task_timeout_seconds=300, campaign_timeout_seconds=6 * 3600, dispatch_provider_budget=budget)
    plan = roadmap(*[spec(t) for t in TASKS])
    for entry in plan["tasks"]:
        entry["depends_on"] = ["long-10"] if entry["task_spec"]["task_id"] == "long-11" else []
    return LongWorld(pol=legacy, plan=plan, campaign=campaign)


def family(task_id):
    return task_id.split("-fix")[0]


class LongCampaignTests(unittest.TestCase):
    def run_campaign(self, w):
        now = NOW
        faults = {"obs": False, "tests": False, "moved": False, "receipt": False, "running": False}
        real_obs, real_tests, real_create = w.facts.dispatch_observation, w.facts.run_tests, w.github.create
        real_timeout = w.facts.timeout_reconciliation
        dispatched: dict[str, int] = {}
        statuses: list[str] = []
        late_payload = {}

        def obs(command_id):
            if "long-06" in command_id and not faults["obs"]:
                faults["obs"] = True
                raise OSError("temporary network read failed")
            return real_obs(command_id)

        def tests(head):
            intent = w.controller()._intents()[-1]
            if intent["task_id"] == "long-08" and not faults["tests"]:
                faults["tests"] = True
                return None
            evidence = real_tests(head)
            if intent["task_id"] == "long-13" and not faults["moved"]:
                faults["moved"] = True
                old = w.github.branches[TARGET]
                w.github.branches[TARGET] = w.github.child(old, {"parallel.txt": "keep\n"}, "parallel writer")
            return evidence

        def create(path, text, message, branch):
            real_create(path, text, message, branch)
            if "claude-auto-dispatch-receipts/" in path and "long-19" in path and not faults["receipt"]:
                faults["receipt"] = True
                raise TimeoutError("response lost after the receipt landed")

        def timeout(intent):
            if not faults["running"]:
                faults["running"] = True
                return dict(real_timeout(intent), status="RUNNING")
            return real_timeout(intent)

        w.facts.dispatch_observation, w.facts.run_tests, w.github.create = obs, tests, create
        w.facts.timeout_reconciliation = timeout
        for wake in range(80):
            results = w.controller().run_until_boundary(now=now, max_steps=20)  # fresh controller = restart
            statuses.extend(r.status for r in results)
            for r in results:
                if r.status == "DISPATCHED":
                    task = family(w.controller()._intents()[-1]["task_id"])
                    dispatched[task] = dispatched.get(task, 0) + 1
            last = results[-1]
            if last.action == "STOP":
                self.final_now = now
                return statuses, dispatched, last
            now = (datetime.fromisoformat(now) + timedelta(seconds=10)).isoformat()
            if last.status != "WAITING_FOR_RESULT":
                continue
            intent = w.controller()._intents()[-1]
            task = family(intent["task_id"])
            if task == "long-10":
                now = (datetime.fromisoformat(now) + timedelta(seconds=301)).isoformat()
                continue
            payload = w.jules.run(intent["carrier_request"]["command_id"])
            head = payload["pull_request"]["head"]["sha"]
            if task == "long-03" and intent["task_id"] == "long-03":
                w.facts.review_failures[head] = [{"category": "semantic_gap", "detail": "gap A"}]
            if task == "long-17":
                w.facts.review_failures[head] = [{"category": "semantic_gap", "detail": "same gap"}]
            w.deliver(payload)
            if task == "long-15":
                w.deliver(payload, delivery=f"dup-{wake}")
                late_payload["long-15"] = payload
            if task == "long-16" and "long-15" in late_payload:
                w.deliver(late_payload.pop("long-15"), delivery="late-old-long-15")
        self.fail("campaign did not reach a boundary within 80 wakes")

    def test_twenty_task_campaign_converges_to_the_predefined_outcome(self):
        w = build_world()
        with static_dispatch_simulator(cap=30):
            statuses, dispatched, last = self.run_campaign(w)
            controller = w.controller()
            self.assertEqual(last.status, "TASK_BLOCKED", last.reason)
            self.assertEqual({t: dispatched.get(t, 0) for t in TASKS}, EXPECTED_DISPATCHES)
            self.assertEqual(len(w.commands()), sum(EXPECTED_DISPATCHES.values()))
            self.assertEqual(controller.campaign_state.blocked_tasks(), EXPECTED_BLOCKED)
            self.assertEqual(statuses.count("ADOPTED"), len(EXPECTED_ADOPTED))
            for marker in ("REPLANNED", "AWAITING_TIMEOUT_RECONCILIATION", "UNKNOWN", "FAIL_MAJOR"):
                self.assertIn(marker, statuses)
            final_files = w.github.commits[w.github.branches[TARGET]]["files"]
            for task in EXPECTED_ADOPTED:
                self.assertIn(f"automation/command_bus/{task.replace('-', '_')}.py", final_files, task)
            for task in EXPECTED_BLOCKED | {"long-11"}:
                self.assertNotIn(f"automation/command_bus/{task.replace('-', '_')}.py", final_files, task)
            self.assertIn("parallel.txt", final_files)  # the parallel writer's work survived
            # budget conservation: one slot per dispatched command, contiguous, never more than the campaign used
            slots = controller.dispatcher.budget.slots()
            self.assertEqual(len(slots), len(w.commands()))
            self.assertEqual(len({s["command_id"] for s in slots}), len(slots))
            # at most one provider active at any time: every dispatch waited for its predecessor's outcome
            self.assertEqual(max(i["origin_round"] for i in controller._intents()), len(w.commands()))
            # a final duplicate wake writes nothing and dispatches nothing
            before = list(w.github.writes)
            again = w.controller().run_until_boundary(now=self.final_now)
            self.assertEqual(again[-1].status, "TASK_BLOCKED")
            self.assertEqual(w.github.writes, before)

    def test_round_limit_is_a_real_stop_not_a_silent_success(self):
        w = build_world(max_rounds=10, budget=30)
        with static_dispatch_simulator(cap=30):
            statuses, dispatched, last = self.run_campaign(w)
        self.assertNotEqual(last.status, "COMPLETE")
        self.assertEqual(len(w.commands()), 10)
        self.assertLessEqual(max(i["origin_round"] for i in w.controller()._intents()), 10)

    def test_campaign_provider_budget_stops_before_the_round_limit(self):
        w = build_world(max_rounds=30, budget=12)
        with static_dispatch_simulator(cap=30):
            statuses, dispatched, last = self.run_campaign(w)
        self.assertEqual(last.status, "PREPARED_NOT_AUTHORIZED")
        self.assertEqual(len(w.commands()), 12)

    def test_production_cap_is_back_after_the_simulator(self):
        w = build_world()
        with static_dispatch_simulator(cap=30):
            pass
        ledger = w.controller().dispatcher.budget
        for index in range(10):
            ledger.acquire(command_id=f"relay-dev-loop-{900 + index}-used", intent_sha256="a" * 64,
                           origin_loop_id=LOOP, acquired_at=NOW)
        self.assertEqual(w.step().status, "PREPARED_NOT_AUTHORIZED")  # the fixed 10-slot ledger is back
        self.assertEqual(w.commands(), [])
        real = World()
        with static_dispatch_simulator(cap=30):
            self.assertEqual(real.step().status, "PREPARED_NOT_AUTHORIZED")  # a real authorization is not simulated
        self.assertEqual(real.commands(), [])

if __name__ == "__main__":
    unittest.main()
