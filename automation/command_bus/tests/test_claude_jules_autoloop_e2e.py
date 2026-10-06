"""STATIC/mock end-to-end proof of the Claude -> Jules -> Claude loop.

Every scenario runs against the deterministic fake world; no network, model,
Jules or GitHub call is made.  The emitted carrier request and claim are
validated with the pinned current carrier validators.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime

from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_dispatch import dispatch_receipt_path
from automation.command_bus.claude_jules_result_event import ResultEventInbox, normalize_pull_request_event
from automation.command_bus.jules_carrier_current import jules_api_request as carrier_request
from automation.command_bus.jules_carrier_current import loop_id_claim as carrier_claim
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    CARRIER, DATA, HOLDER, LOOP, NOW, REPO, TARGET, VACUOUS_TEST, FakeFacts, FakeGitHub, FakeJules,
    owner_event, policy, roadmap, seed_owner, task_spec,
)

COMMANDS = "automation/command_bus/jules_api_requests/"
CLAIMS = "automation/command_bus/loop_id_claims/"


class World:
    def __init__(self, *, pol=None, plan=None, owner=None):
        self.github = FakeGitHub()
        self.jules = FakeJules(self.github)
        self.facts = FakeFacts(self.github, self.jules)
        seed_owner(self.github, *(owner or [owner_event()]))
        self.policy = pol or policy()
        self.roadmap = plan or roadmap(task_spec("alpha-helper"),
                                       task_spec("beta-helper", "automation/command_bus/beta.py",
                                                 "automation/command_bus/tests/test_beta.py"))
        self.deliveries = 0

    def controller(self) -> ClaudeJulesAutoLoop:
        """A brand-new controller each time: proves state lives only in GitHub."""
        return ClaudeJulesAutoLoop(
            client=self.github, refs=self.github, policy=self.policy,
            owner_reader=LoopOwnerGitHubBackend(self.github, branch=DATA), roadmap=self.roadmap,
            facts=self.facts, origin_loop_id=LOOP, lane_id="J-BLUE")

    def step(self, now=NOW):
        return self.controller().step(now=now)

    def deliver(self, payload, delivery=None):
        self.deliveries += 1
        event = normalize_pull_request_event(event_name="pull_request", delivery_id=delivery or f"d-{self.deliveries}",
                                             payload=payload, expected_repo=REPO)
        assert event.status == "ACCEPTED", event.reason
        return ResultEventInbox(self.github, data_branch=DATA).record(event.record)

    def commands(self):
        return [c.path for c in self.github.list(COMMANDS, CARRIER)]

    def command(self, path):
        return json.loads(self.github.get(path, CARRIER).text)


class ClaudeJulesAutoLoopE2ETests(unittest.TestCase):
    def test_full_cycle_dispatch_result_inspect_adopt_and_next(self):
        w = World()
        first = w.step()
        self.assertEqual((first.action, first.status), ("DISPATCH", "DISPATCHED"), first.reason)
        [path] = w.commands()
        request = w.command(path)
        # Exact current carrier contract, checked by the pinned carrier validators.
        carrier_request.validate_request(request, now=datetime.fromisoformat(NOW))
        claim = json.loads(w.github.get(CLAIMS + request["command_id"].split("-")[3] + ".json", CARRIER).text)
        carrier_claim.verify_command_claim(request, claim)
        self.assertEqual(claim["lane_id"], "J-BLUE")
        self.assertFalse(any(k.startswith("origin_") for k in request))
        self.assertEqual(w.github.branches[request["work_branch"]], request["expected_target_head"])
        self.assertIn("Allowed changed paths only:", request["prompt"])
        binding = json.loads(w.github.get(
            f"automation/command_bus/evidence/claude-auto-origin-bindings/{request['command_id']}.json", DATA).text)
        self.assertEqual((binding["origin_loop_id"], binding["origin_round"], binding["command_id"]),
                         (LOOP, 1, request["command_id"]))

        self.assertEqual(w.step().action, "WAIT")
        payload = w.jules.run(request["command_id"])
        self.assertEqual(w.deliver(payload).status, "RECORDED")
        inspected = w.step()
        self.assertEqual((inspected.action, inspected.status), ("INSPECT", "PASS"), inspected.reason)
        adopted = w.step()
        self.assertEqual((adopted.action, adopted.status), ("ADOPT", "ADOPTED"), adopted.reason)
        self.assertEqual(w.github.branches[TARGET], w.jules.prs[300]["head_sha"])
        nxt = w.step()
        self.assertEqual((nxt.action, nxt.status), ("DISPATCH", "DISPATCHED"))
        second = [w.command(p) for p in w.commands() if "beta-helper" in p][0]
        self.assertEqual(second["expected_target_head"], w.jules.prs[300]["head_sha"])
        w.deliver(w.jules.run(second["command_id"]))
        self.assertEqual(w.step().status, "PASS")
        self.assertEqual(w.step().status, "ADOPTED")
        done = w.step()
        self.assertEqual((done.action, done.status), ("COMPLETE", "COMPLETE"))
        self.assertEqual(len(w.commands()), 2)
        self.assertNotIn(("ff", "main", w.github.branches[TARGET]), w.github.writes)

    def test_duplicate_and_redelivered_events_are_processed_once(self):
        w = World()
        w.step()
        command_id = w.command(w.commands()[0])["command_id"]
        payload = w.jules.run(command_id)
        self.assertEqual(w.deliver(payload, "same").status, "RECORDED")
        self.assertEqual(w.deliver(payload, "same").status, "DUPLICATE")
        self.assertEqual(w.deliver(payload, "other-delivery").status, "DUPLICATE")
        self.assertEqual(w.step().action, "INSPECT")
        self.assertEqual(w.step().status, "ADOPTED")
        w.deliver(w.jules.payload(300, "reopened"), "late")
        self.assertEqual(sum(1 for c in w.facts.calls if c.startswith("review:")), 1)

    def test_terminal_dispatch_receipt_is_never_replayed(self):
        w = World()
        w.step()
        c = w.controller()
        intent = c._intents()[0]
        again = c.dispatcher.dispatch(intent, now=NOW, dispatches_used=0)
        self.assertEqual(again.status, "NO-OP")
        self.assertEqual(len(w.commands()), 1)

    def test_target_head_mismatch_blocks_then_replans_with_fresh_snapshot(self):
        w = World()
        original = w.github.branches[TARGET]
        moved = w.github.child(original, {"x.txt": "moved"}, "concurrent change")

        def move_target(path, branch):
            if path.startswith(CLAIMS):
                w.github.branches[TARGET] = moved
            return None
        w.github.create_hook = move_target
        blocked = w.step()
        self.assertEqual(blocked.status, "BLOCKED")
        self.assertIn("STALE_TARGET", blocked.reason)
        self.assertEqual(w.commands(), [])
        w.github.create_hook = None
        retry = w.step()
        self.assertEqual(retry.status, "DISPATCHED")
        [path] = w.commands()
        self.assertEqual(w.command(path)["expected_target_head"], moved)
        self.assertEqual(len(w.github.list(CLAIMS, CARRIER)), 2)  # the first number stays reserved

    def test_stale_owner_generation_and_semiauto_owner_cannot_dispatch(self):
        first = owner_event()
        handoff = owner_event(generation=2, holder="someone-else", event_type="HANDOFF", previous=first)
        w = World(owner=[first, handoff])
        result = w.step()
        self.assertEqual(result.action, "STOP")
        self.assertIn("not owned", result.reason)
        self.assertEqual([x for x in w.github.writes if x[1] == CARRIER], [])
        semi = World(owner=[owner_event(role="SEMI_AUTO", holder="chatgpt-semiauto")])
        result = semi.step()
        self.assertIn("SEMI_AUTO", result.reason)
        self.assertEqual(semi.commands(), [])

    def test_owner_handoff_during_dispatch_blocks_before_command(self):
        w = World()
        first = owner_event()

        def handoff(path, branch):
            if path.startswith(CLAIMS):
                seed_owner(w.github, owner_event(generation=2, holder="new-holder", event_type="HANDOFF", previous=first))
            return None
        w.github.create_hook = handoff
        result = w.step()
        self.assertEqual(result.action, "STOP")
        self.assertIn("not owned", result.reason)
        self.assertEqual(w.commands(), [])

    def test_owner_renewal_keeps_loop_and_handoff_stops_adoption(self):
        first = owner_event()
        w = World()
        w.step()
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        seed_owner(w.github, owner_event(generation=2, event_type="RENEW"))
        self.assertEqual(w.step().status, "PASS")
        self.assertEqual(w.step().status, "ADOPTED")
        nxt = w.step()
        self.assertEqual(nxt.status, "DISPATCHED")
        newest = [i for i in w.controller()._intents() if i["intent_id"].endswith("a1")][-1]
        self.assertEqual(newest["origin_generation"], 2)

        lost = World()
        lost.step()
        lost.deliver(lost.jules.run(lost.command(lost.commands()[0])["command_id"]))
        lost.step()
        seed_owner(lost.github, owner_event(generation=2, holder="other", event_type="HANDOFF", previous=first))
        before = lost.github.branches[TARGET]
        result = lost.step()
        self.assertEqual(result.action, "STOP")
        self.assertEqual(lost.github.branches[TARGET], before)

    def test_owner_handoff_between_step_start_and_adoption_blocks_adoption(self):
        first = owner_event()
        w = World()
        w.step()
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        w.step()  # independent inspection recorded; adoption is the next step
        real_get = w.github.get

        def get(path, ref):
            if "claude-auto-adoption-receipts" in path:  # read after the step-start fence passed
                seed_owner(w.github, owner_event(generation=2, holder="other", event_type="HANDOFF", previous=first))
            return real_get(path, ref)
        w.github.get = get
        before = w.github.branches[TARGET]
        result = w.step()
        self.assertEqual(result.action, "STOP")
        self.assertIn("before adoption", result.reason)
        self.assertEqual(w.github.branches[TARGET], before)

    def test_expired_same_holder_owner_lease_recovers_and_continues(self):
        w = World(owner=[owner_event(expires_at="2026-10-01T12:30:00+00:00")])
        result = w.step()
        self.assertEqual((result.action, result.status), ("DISPATCH", "DISPATCHED"), result.reason)
        chain = LoopOwnerGitHubBackend(w.github, branch=DATA).read_events(LOOP)
        self.assertEqual(len(chain), 2)
        self.assertEqual((chain[-1]["event_type"], chain[-1]["owner_role"], chain[-1]["holder_id"]),
                         ("RENEW", "AUTO", HOLDER))

    def test_session_loss_mid_dispatch_resumes_without_duplicates(self):
        w = World()
        w.github.create_hook = lambda path, branch: "raise-before-write" if path.startswith(COMMANDS) else None
        lost = w.step()
        self.assertEqual(lost.status, "UNKNOWN")
        self.assertEqual(w.commands(), [])
        claims_before = len(w.github.list(CLAIMS, CARRIER))
        w.github.create_hook = None
        resumed = w.step()  # new controller instance reads only GitHub records
        self.assertEqual((resumed.action, resumed.status), ("RESUME_DISPATCH", "DISPATCHED"))
        self.assertEqual(len(w.commands()), 1)
        self.assertEqual(len(w.github.list(CLAIMS, CARRIER)), claims_before)

    def test_ambiguous_command_write_is_read_back_not_resent(self):
        w = World()
        w.github.create_hook = lambda path, branch: "raise-after-write" if path.startswith(COMMANDS) else None
        self.assertEqual(w.step().status, "DISPATCHED")
        self.assertEqual(sum(1 for x in w.github.writes if x[0] == "create" and x[2].startswith(COMMANDS)), 1)

    def test_loop_number_collision_reselects_number(self):
        w = World()

        # Simulate another controller winning the number between planning and claiming.
        original_create = w.github.create

        def racing_create(path, text, message, branch):
            if path.startswith(CLAIMS) and not any(p.startswith(CLAIMS) for (_, p) in w.github.files):
                original_create(path, json.dumps({"other": "controller"}), "foreign claim", branch)
            return original_create(path, text, message, branch)
        w.github.create = racing_create
        blocked = w.step()
        self.assertEqual(blocked.status, "BLOCKED")
        self.assertIn("choose a new Loop number", blocked.reason)
        w.github.create = original_create
        ok = w.step()
        self.assertEqual(ok.status, "DISPATCHED")
        self.assertEqual(len(w.commands()), 1)

    def test_minor_failure_gets_small_repair_then_reinspection_and_adoption(self):
        w = World()
        w.step()
        command_id = w.command(w.commands()[0])["command_id"]
        test_path = "automation/command_bus/tests/test_alpha.py"
        w.deliver(w.jules.run(command_id, changes={"automation/command_bus/alpha.py": "def helper(x):\n    return x + 1\n",
                                                    test_path: VACUOUS_TEST}))
        first = w.step()
        self.assertEqual((first.status, first.details["decision"]), ("FAIL_MINOR", "CLAUDE_SMALL_REPAIR"))
        repaired = w.step()
        self.assertEqual((repaired.action, repaired.status), ("INSPECT", "PASS"), repaired.reason)
        self.assertEqual(w.step().status, "ADOPTED")
        self.assertEqual(w.github.branches[TARGET], repaired.details["head"])
        self.assertEqual(len(w.commands()), 1)  # no Jules resend

    def test_major_failure_prepares_new_corrective_command(self):
        w = World()
        w.step()
        request = w.command(w.commands()[0])
        payload = w.jules.run(request["command_id"])
        head = payload["pull_request"]["head"]["sha"]
        w.facts.review_failures[head] = [{"category": "semantic_gap", "detail": "negative case missing"}]
        w.deliver(payload)
        self.assertEqual(w.step().details["decision"], "JULES_CORRECTIVE")
        corrective = w.step()
        self.assertEqual((corrective.action, corrective.status), ("DISPATCH", "DISPATCHED"))
        self.assertTrue(corrective.details["command_id"].endswith("alpha-helper-fix1"))
        self.assertNotEqual(corrective.details["command_id"], request["command_id"])
        fix = w.command(COMMANDS + corrective.details["command_id"] + ".json")
        self.assertIn("negative case missing", fix["prompt"])
        self.assertEqual(fix["expected_target_head"], request["expected_target_head"])
        self.assertEqual(len(w.commands()), 2)

    def test_repeated_failures_isolate_task_then_stop_only_when_dependencies_exhaust_safe_work(self):
        w = World()
        w.step()
        for _ in range(2):
            request = w.command(sorted(w.commands())[-1])
            payload = w.jules.run(request["command_id"])
            w.facts.review_failures[payload["pull_request"]["head"]["sha"]] = [
                {"category": "semantic_gap", "detail": "still wrong"}]
            w.deliver(payload)
            w.step()  # inspect
            w.step()  # corrective dispatch
        request = w.command(sorted(w.commands())[-1])
        payload = w.jules.run(request["command_id"])
        w.facts.review_failures[payload["pull_request"]["head"]["sha"]] = [{"category": "semantic_gap", "detail": "x"}]
        w.deliver(payload)
        self.assertEqual(w.step().details["decision"], "STOP_HUMAN")
        blocked = w.step()
        self.assertEqual((blocked.action, blocked.status), ("BLOCK_TASK", "TASK_BLOCKED"))
        stop = w.step()
        self.assertEqual((stop.action, stop.status), ("STOP", "TASK_BLOCKED"))
        self.assertIn("beta-helper", stop.details["remaining_tasks"])
        self.assertEqual(len(w.commands()), 3)

    def test_blocked_task_does_not_stop_independent_ready_task(self):
        plan = {
            "schema_version": 1,
            "profile": "CLAUDE_AUTO_JULES_ROADMAP_V1",
            "roadmap_id": "independent",
            "tasks": [
                {"task_spec": task_spec("alpha-helper"), "depends_on": []},
                {"task_spec": task_spec(
                    "beta-helper", "automation/command_bus/beta.py",
                    "automation/command_bus/tests/test_beta.py"), "depends_on": []},
            ],
        }
        w = World(plan=plan)
        w.step()
        for _ in range(2):
            request = w.command(sorted(w.commands())[-1])
            payload = w.jules.run(request["command_id"])
            w.facts.review_failures[payload["pull_request"]["head"]["sha"]] = [
                {"category": "semantic_gap", "detail": "still wrong"}]
            w.deliver(payload)
            w.step()
            w.step()
        request = w.command(sorted(w.commands())[-1])
        payload = w.jules.run(request["command_id"])
        w.facts.review_failures[payload["pull_request"]["head"]["sha"]] = [
            {"category": "semantic_gap", "detail": "third failure"}]
        w.deliver(payload)
        self.assertEqual(w.step().details["decision"], "STOP_HUMAN")
        results = w.controller().run_until_boundary(now=NOW, max_steps=4)
        self.assertEqual((results[0].action, results[0].status), ("BLOCK_TASK", "TASK_BLOCKED"))
        self.assertIn("DISPATCHED", [r.status for r in results])
        self.assertEqual(results[-1].status, "WAITING_FOR_RESULT")
        beta = [w.command(path) for path in w.commands() if "beta-helper" in path]
        self.assertEqual(len(beta), 1)

    def test_not_authorized_policy_writes_nothing(self):
        w = World(pol=policy(live_dispatch_authorization=None))
        result = w.step()
        self.assertEqual(result.status, "PREPARED_NOT_AUTHORIZED")
        self.assertEqual(w.github.writes, [])
        self.assertIsNotNone(result.details["intent"]["carrier_request"])

    def test_lane_not_granted_blocks_without_writes(self):
        w = World(pol=policy(allowed_lane_ids=["J-RED"]))
        result = w.step()
        self.assertEqual(result.action, "STOP")
        self.assertIn("not granted", result.reason)
        self.assertEqual([x for x in w.github.writes if x[1] == CARRIER], [])

    def test_stale_result_head_waits_for_newer_head(self):
        w = World()
        w.step()
        command_id = w.command(w.commands()[0])["command_id"]
        old = w.jules.run(command_id)
        w.deliver(old)
        w.jules.push_followup(300, {"automation/command_bus/alpha.py": "def helper(x):\n    return x + 2\n"})
        self.assertEqual(w.step().status, "WAITING_FOR_RESULT")
        w.deliver(w.jules.payload(300, "synchronize"))
        result = w.step()
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.details["head"], w.jules.prs[300]["head_sha"])

    def test_session_footer_mismatch_stops(self):
        w = World()
        w.step()
        command_id = w.command(w.commands()[0])["command_id"]
        w.deliver(w.jules.run(command_id, body_session="123"))
        result = w.step()
        self.assertEqual((result.action, result.status), ("STOP", "BLOCKED"))

    def test_target_moved_before_adoption_is_not_forced(self):
        w = World()
        w.step()
        command_id = w.command(w.commands()[0])["command_id"]
        w.deliver(w.jules.run(command_id))
        w.step()
        w.github.branches[TARGET] = w.github.child(w.github.branches[TARGET], {"y": "1"}, "other lane")
        before = w.github.branches[TARGET]
        result = w.step()
        self.assertEqual((result.action, result.status), ("STOP", "BLOCKED"))
        self.assertEqual(w.github.branches[TARGET], before)

    def test_ambiguous_fast_forward_is_resolved_by_readback(self):
        w = World()
        w.step()
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        w.step()
        w.github.ff_hook = lambda branch: "raise-after-write"
        self.assertEqual(w.step().status, "ADOPTED")
        w2 = World()
        w2.step()
        w2.deliver(w2.jules.run(w2.command(w2.commands()[0])["command_id"]))
        w2.step()
        w2.github.ff_hook = lambda branch: "raise"
        lost = w2.step()
        self.assertEqual((lost.action, lost.status), ("STOP", "UNKNOWN"))
        self.assertEqual([x for x in w2.github.writes if x[0] == "ff"], [])

    # -- PR #220 review: receipts, post-FF recovery, tampered records ---------
    def _adopted_world(self):
        w = World()
        w.step()
        command_id = w.command(w.commands()[0])["command_id"]
        w.deliver(w.jules.run(command_id))
        self.assertEqual(w.step().status, "PASS")
        self.assertEqual(w.step().status, "ADOPTED")
        return w, command_id

    def _replace(self, w, path, mutate):
        from automation.command_bus.github_backend import GitHubContent
        record = json.loads(w.github.get(path, DATA).text)
        mutate(record)
        text = json.dumps(record)
        w.github.files[(DATA, path)] = GitHubContent(path=path, text=text, sha="f" * 40)

    def test_invalid_adoption_receipt_is_not_trusted(self):
        from automation.command_bus.claude_jules_adoption import adoption_receipt_path
        cases = {
            "malformed": lambda r: r.pop("tree_after"),
            "wrong-command": lambda r: r.__setitem__("command_id", "relay-dev-loop-999-other"),
            "wrong-head": lambda r: r.__setitem__("head_after", "e" * 40),
            "wrong-intent": lambda r: r.__setitem__("intent_sha256", "0" * 64),
            "not-adopted": lambda r: r.__setitem__("state", "PENDING"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                w, command_id = self._adopted_world()
                self._replace(w, adoption_receipt_path(command_id), mutate)
                ffs = [x for x in w.github.writes if x[0] == "ff"]
                result = w.step()
                self.assertEqual((result.action, result.status), ("STOP", "UNKNOWN"), result.reason)
                self.assertEqual([x for x in w.github.writes if x[0] == "ff"], ffs)
                self.assertEqual(len(w.commands()), 1)  # never moves on to the next task

    def test_adoption_receipt_requires_canonical_to_still_contain_head(self):
        w, _ = self._adopted_world()
        w.github.branches[TARGET] = w.github.child(w.github.ancestors(w.github.branches[TARGET])[1], {"z": "1"}, "rewound")
        result = w.step()
        self.assertEqual((result.action, result.status), ("STOP", "UNKNOWN"), result.reason)
        self.assertEqual(len(w.commands()), 1)

    def test_crash_after_fast_forward_restores_receipt_without_ref_write(self):
        w = World()
        w.step()
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        w.step()
        w.github.create_hook = lambda path, branch: ("raise-before-write"
                                                     if "claude-auto-adoption-receipts" in path else None)
        crashed = w.step()
        self.assertEqual((crashed.action, crashed.status), ("STOP", "UNKNOWN"), crashed.reason)
        ffs = [x for x in w.github.writes if x[0] == "ff"]
        self.assertEqual(len(ffs), 1)
        w.github.create_hook = None
        restored = w.step()
        self.assertEqual((restored.action, restored.status), ("ADOPT", "ADOPTED"), restored.reason)
        self.assertIn("no ref write", restored.reason)
        self.assertEqual([x for x in w.github.writes if x[0] == "ff"], ffs)
        nxt = w.step()
        self.assertEqual((nxt.action, nxt.status), ("DISPATCH", "DISPATCHED"))
        self.assertEqual(len(w.commands()), 2)

    def test_canonical_at_candidate_without_lock_is_unknown(self):
        w = World()
        w.step()
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        w.step()
        # Someone else advanced the target to the candidate; no Claude lock exists.
        w.github.branches[TARGET] = w.jules.prs[300]["head_sha"]
        result = w.step()
        self.assertEqual((result.action, result.status), ("STOP", "UNKNOWN"), result.reason)
        self.assertEqual([x for x in w.github.writes if x[0] == "ff"], [])
        self.assertEqual([p for (b, p) in w.github.files if "claude-auto-adoption-receipts" in p], [])

    def test_tampered_inspection_record_stops_unknown(self):
        w = World()
        w.step()
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        w.step()
        [(_, path)] = [k for k in w.github.files if "claude-auto-inspections/" in k[1]]
        self._replace(w, path, lambda r: r.__setitem__("task_id", "other-task"))
        result = w.step()
        self.assertEqual((result.action, result.status), ("STOP", "UNKNOWN"), result.reason)
        self.assertEqual([x for x in w.github.writes if x[0] == "ff"], [])

    def test_tampered_result_event_stops_unknown(self):
        w = World()
        w.step()
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        [(_, path)] = [k for k in w.github.files if "claude-auto-result-events/" in k[1]]
        self._replace(w, path, lambda r: r.__setitem__("head_ref_session_id", "999"))
        result = w.step()
        self.assertEqual((result.action, result.status), ("STOP", "UNKNOWN"), result.reason)
        self.assertEqual(w.facts.calls, [])

    def test_fresh_pr_head_ref_or_footer_mismatch_blocks(self):
        for name, mutate in {
            "head-ref": lambda pr: pr.__setitem__("head_ref", pr["head_ref"] + "-x"),
            "footer": lambda pr: pr.__setitem__("body", "no session footer"),
        }.items():
            with self.subTest(name):
                w = World()
                w.step()
                w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
                mutate(w.jules.prs[300])
                result = w.step()
                self.assertEqual((result.action, result.status), ("STOP", "BLOCKED"), result.reason)
                self.assertEqual([x for x in w.github.writes if x[0] == "ff"], [])

    def test_max_rounds_stops_after_adoption(self):
        w = World(pol=policy(max_rounds=1))
        w.step()
        w.deliver(w.jules.run(w.command(w.commands()[0])["command_id"]))
        w.step()
        w.step()
        result = w.step()
        self.assertEqual((result.action, result.status), ("STOP", "MAX_ROUNDS"))

    def test_run_until_boundary_stops_at_wait(self):
        w = World()
        results = w.controller().run_until_boundary(now=NOW)
        self.assertEqual([r.action for r in results], ["DISPATCH", "WAIT"])
        self.assertIsNotNone(w.github.get(dispatch_receipt_path(results[0].details["command_id"]), DATA))

    def test_run_until_boundary_retries_transient_read_failure(self):
        w = World()
        w.step()
        request = w.command(w.commands()[0])
        w.deliver(w.jules.run(request["command_id"]))
        real = w.facts.dispatch_observation
        calls = 0

        def flaky(command_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary network read failed")
            return real(command_id)

        w.facts.dispatch_observation = flaky
        results = w.controller().run_until_boundary(now=NOW, max_steps=4)
        self.assertEqual(results[0].status, "UNKNOWN")
        self.assertEqual(results[0].details["boundary_class"], "TRANSIENT_UNKNOWN")
        self.assertEqual(results[1].status, "PASS")
        self.assertEqual(results[2].status, "ADOPTED")
        self.assertEqual(results[3].status, "DISPATCHED")

    def test_run_until_boundary_replans_stale_target_without_human_stop(self):
        w = World()
        original = w.github.branches[TARGET]
        moved = w.github.child(original, {"x.txt": "moved"}, "concurrent change")

        def move_target(path, branch):
            if path.startswith(CLAIMS):
                w.github.branches[TARGET] = moved
            return None

        w.github.create_hook = move_target
        results = w.controller().run_until_boundary(now=NOW, max_steps=4)
        self.assertEqual(results[0].status, "BLOCKED")
        self.assertEqual(results[0].details["boundary_class"], "RECOVERABLE_UNKNOWN")
        self.assertIn("DISPATCHED", [r.status for r in results])
        self.assertEqual(results[-1].action, "WAIT")
        self.assertEqual(results[-1].status, "WAITING_FOR_RESULT")

    def test_run_until_boundary_does_not_retry_ambiguous_mutating_write(self):
        w = World()
        w.github.create_hook = lambda path, branch: "raise-before-write" if path.startswith(COMMANDS) else None
        results = w.controller().run_until_boundary(now=NOW, max_steps=4)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "UNKNOWN")
        self.assertEqual(results[0].details["boundary_class"], "HARD_UNKNOWN")
        self.assertEqual(w.commands(), [])


if __name__ == "__main__":
    unittest.main()
