from __future__ import annotations

import json
import unittest

from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_recovery import HARD_UNKNOWN, TASK_BLOCKED
from automation.command_bus.claude_jules_task_block import (
    TaskBlockStore, block_path, validate_task_block,
)
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    DATA, LOOP, NOW, FakeGitHub, roadmap, seed_owner, task_spec, owner_event,
)
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World


def independent_roadmap():
    a = task_spec("task-a", "automation/command_bus/task_a.py",
                  "automation/command_bus/tests/test_task_a.py")
    c = task_spec("task-c", "automation/command_bus/task_c.py",
                  "automation/command_bus/tests/test_task_c.py")
    b = task_spec("task-b", "automation/command_bus/task_b.py",
                  "automation/command_bus/tests/test_task_b.py")
    return {
        "schema_version": 1,
        "profile": "CLAUDE_AUTO_JULES_ROADMAP_V1",
        "roadmap_id": "blocker-isolation",
        "tasks": [
            {"task_spec": a, "depends_on": []},
            {"task_spec": c, "depends_on": ["task-a"]},
            {"task_spec": b, "depends_on": []},
        ],
    }


def dummy_block(store: TaskBlockStore, task_id: str, command_id: str = "relay-dev-loop-777-block"):
    intent = {
        "task_id": task_id,
        "origin_round": 1,
        "intent_sha256": "1" * 64,
        "carrier_request": {"command_id": command_id},
    }
    inspection = {
        "command_id": command_id,
        "intent_sha256": "1" * 64,
        "decision": "STOP_HUMAN",
        "inspection_sha256": "2" * 64,
        "reason": "safe corrective path exhausted",
    }
    return store.persist(intent=intent, inspection=inspection, blocked_at=NOW)


class TaskBlockStoreTests(unittest.TestCase):
    def test_task_block_is_create_only_digest_bound_and_recoverable(self):
        github = FakeGitHub()
        seed_owner(github, owner_event())
        store = TaskBlockStore(github, data_branch=DATA, origin_loop_id=LOOP)
        first = dummy_block(store, "task-a")
        self.assertEqual(first.status, "CREATED")
        self.assertEqual(first.record["classification"], TASK_BLOCKED)
        self.assertEqual(validate_task_block(first.record), first.record)
        self.assertEqual(github.get(block_path(LOOP, "task-a"), DATA).text,
                         json.dumps(first.record, sort_keys=True, separators=(",", ":")))

        again = dummy_block(store, "task-a", "relay-dev-loop-778-later")
        self.assertEqual(again.status, "RECOVERED")
        self.assertEqual(again.record, first.record)
        self.assertEqual(len(store.list_all()), 1)

    def test_tampered_block_record_is_hard_invalid(self):
        github = FakeGitHub()
        seed_owner(github, owner_event())
        store = TaskBlockStore(github, data_branch=DATA, origin_loop_id=LOOP)
        record = dummy_block(store, "task-a").record
        tampered = dict(record, reason="rewritten")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            validate_task_block(tampered)

    def test_non_terminal_inspection_cannot_be_isolated(self):
        github = FakeGitHub()
        seed_owner(github, owner_event())
        store = TaskBlockStore(github, data_branch=DATA, origin_loop_id=LOOP)
        intent = {
            "task_id": "task-a", "origin_round": 1, "intent_sha256": "1" * 64,
            "carrier_request": {"command_id": "relay-dev-loop-777-block"},
        }
        inspection = {
            "command_id": "relay-dev-loop-777-block", "intent_sha256": "1" * 64,
            "decision": "JULES_CORRECTIVE", "inspection_sha256": "2" * 64,
            "reason": "still safely correctable",
        }
        result = store.persist(intent=intent, inspection=inspection, blocked_at=NOW)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(store.list_all(), [])


class RoadmapIsolationTests(unittest.TestCase):
    def controller(self, w: World):
        return ClaudeJulesAutoLoop(
            client=w.github, refs=w.github, policy=w.policy,
            owner_reader=LoopOwnerGitHubBackend(w.github, branch=DATA),
            roadmap=w.roadmap, facts=w.facts, origin_loop_id=LOOP, lane_id="J-BLUE",
        )

    def test_blocked_dependency_does_not_hide_later_independent_ready_task(self):
        w = World(plan=independent_roadmap())
        store = TaskBlockStore(w.github, data_branch=DATA, origin_loop_id=LOOP)
        self.assertEqual(dummy_block(store, "task-a").status, "CREATED")

        position = self.controller(w)._roadmap_position()
        self.assertEqual(position["state"], "READY")
        self.assertEqual(position["spec"]["task_id"], "task-b")
        self.assertEqual(position["blocked"], ["task-a"])
        self.assertEqual(position["dependency_blocked"], {"task-c": ["task-a"]})

    def test_no_ready_independent_task_becomes_human_required_not_complete(self):
        w = World(plan=independent_roadmap())
        store = TaskBlockStore(w.github, data_branch=DATA, origin_loop_id=LOOP)
        dummy_block(store, "task-a")
        dummy_block(store, "task-b", "relay-dev-loop-778-block")

        result = self.controller(w).step(now=NOW)
        self.assertEqual((result.action, result.status), ("STOP", "HUMAN_REQUIRED"))
        self.assertEqual(result.details["blocked"], ["task-a", "task-b"])
        self.assertIn("task-c", result.details["remaining"])

    def test_three_failed_candidates_isolate_a_then_b_continues(self):
        w = World(plan=independent_roadmap())

        # Round 1: task A fails materially.
        first = self.controller(w).step(now=NOW)
        self.assertEqual((first.action, first.status), ("DISPATCH", "DISPATCHED"))
        payload = w.jules.run(first.details["command_id"])
        head = w.jules.prs[300]["head_sha"]
        w.facts.review_failures[head] = [{"category": "semantic_gap", "detail": "A still wrong"}]
        w.deliver(payload)
        failed1 = self.controller(w).step(now=NOW)
        self.assertEqual((failed1.action, failed1.status, failed1.details["decision"]),
                         ("INSPECT", "FAIL_MAJOR", "JULES_CORRECTIVE"))

        # Round 2: first corrective fails, but remains autonomously correctable.
        fix1 = self.controller(w).step(now=NOW)
        self.assertEqual((fix1.action, fix1.status), ("DISPATCH", "DISPATCHED"))
        payload = w.jules.run(fix1.details["command_id"])
        head = w.jules.prs[301]["head_sha"]
        w.facts.review_failures[head] = [{"category": "semantic_gap", "detail": "A fix1 wrong"}]
        w.deliver(payload)
        failed2 = self.controller(w).step(now=NOW)
        self.assertEqual((failed2.action, failed2.status, failed2.details["decision"]),
                         ("INSPECT", "FAIL_MAJOR", "JULES_CORRECTIVE_REDUCED"))

        # Round 3: second corrective exhausts the existing inspection policy.
        fix2 = self.controller(w).step(now=NOW)
        self.assertEqual((fix2.action, fix2.status), ("DISPATCH", "DISPATCHED"))
        payload = w.jules.run(fix2.details["command_id"])
        head = w.jules.prs[302]["head_sha"]
        w.facts.review_failures[head] = [{"category": "semantic_gap", "detail": "A fix2 wrong"}]
        w.deliver(payload)
        failed3 = self.controller(w).step(now=NOW)
        self.assertEqual((failed3.action, failed3.status, failed3.details["decision"]),
                         ("INSPECT", "FAIL_MAJOR", "STOP_HUMAN"))

        # Fresh controller persists TASK_BLOCKED for A and immediately skips
        # dependency-blocked C to dispatch independent B. No human hop occurs.
        next_safe = self.controller(w).step(now=NOW)
        self.assertEqual((next_safe.action, next_safe.status), ("DISPATCH", "DISPATCHED"), next_safe.reason)
        command = w.command(w.commands()[-1])
        self.assertEqual(command["prompt"].find("task-b") >= 0, True)
        blocks = TaskBlockStore(w.github, data_branch=DATA, origin_loop_id=LOOP).list_all()
        self.assertEqual([(b["task_family"], b["classification"]) for b in blocks],
                         [("task-a", TASK_BLOCKED)])

        # B succeeds and is adopted. C still depends on blocked A, so only then
        # is the campaign allowed to require human input.
        w.deliver(w.jules.run(next_safe.details["command_id"]))
        self.assertEqual(self.controller(w).step(now=NOW).status, "PASS")
        self.assertEqual(self.controller(w).step(now=NOW).status, "ADOPTED")
        terminal = self.controller(w).step(now=NOW)
        self.assertEqual((terminal.action, terminal.status), ("STOP", "HUMAN_REQUIRED"))
        self.assertEqual(terminal.details["blocked"], ["task-a"])
        self.assertEqual(terminal.details["dependency_blocked"], {"task-c": ["task-a"]})

    def test_corrupt_block_ledger_fails_closed(self):
        w = World(plan=independent_roadmap())
        path = block_path(LOOP, "task-a")
        w.github.create(path, json.dumps({"bad": True}), "corrupt block", DATA)
        result = self.controller(w).step(now=NOW)
        self.assertEqual((result.action, result.status), ("STOP", HARD_UNKNOWN))
        self.assertIn("roadmap position unverifiable", result.reason)

    def test_completion_at_exact_round_limit_reports_complete(self):
        one = roadmap(task_spec("only-task"))
        w = World(plan=one)
        w.policy = dict(w.policy, max_rounds=1)
        w.policy["live_dispatch_authorization"] = dict(
            w.policy["live_dispatch_authorization"], max_dispatches=1,
        )
        first = self.controller(w).step(now=NOW)
        w.deliver(w.jules.run(first.details["command_id"]))
        self.assertEqual(self.controller(w).step(now=NOW).status, "PASS")
        self.assertEqual(self.controller(w).step(now=NOW).status, "ADOPTED")
        done = self.controller(w).step(now=NOW)
        self.assertEqual((done.action, done.status), ("COMPLETE", "COMPLETE"))


if __name__ == "__main__":
    unittest.main()
