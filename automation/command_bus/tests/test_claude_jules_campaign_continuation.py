"""Campaign integration regressions: all providers/GitHub are local fakes."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from dataclasses import replace

from automation.command_bus.claude_jules_campaign import (
    MAX_CAMPAIGN_ROUNDS, campaign_policy_from_legacy, classify_boundary, validate_campaign_policy,
)
from automation.command_bus.claude_jules_campaign_state import build_recovery_event
from automation.command_bus.claude_jules_dispatch import canonical_json, dispatch_receipt_path
from automation.command_bus.claude_jules_live import outstanding_dispatches, wake_resume
from automation.command_bus.claude_loop import BackendMode, validate_machine_gate
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import COMMANDS, World
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    DATA, LOOP, NOW, TARGET, policy, roadmap, task_spec,
)


def independent_plan():
    plan = roadmap(task_spec("alpha-helper"), task_spec("beta-helper", "automation/command_bus/beta.py",
                                                       "automation/command_bus/tests/test_beta.py"))
    plan["tasks"][1]["depends_on"] = []
    return plan


class CampaignContinuationTests(unittest.TestCase):
    def test_deferred_default_is_stable_across_duplicate_wake_and_conflicting_proposal(self):
        w = World()
        proposal = dict(decision_id="layout-1", question="Choose reversible local layout",
                        options=["current", "later"], reason="No correctness dependency",
                        selected_safe_default="current", reversibility="reversible",
                        affected_scope="local cache", reconsider_condition="measured need")
        first = w.controller().defer_decision(**proposal, now=NOW)
        before = list(w.github.writes)
        duplicate = w.controller().defer_decision(**proposal, now="2026-10-01T13:01:00+00:00")
        self.assertEqual((first.status, duplicate.status), ("DEFERRED", "DEFERRED"))
        conflict = w.controller().defer_decision(**dict(proposal, selected_safe_default="later"), now=NOW)
        self.assertEqual(conflict.status, "UNKNOWN")
        self.assertEqual(w.github.writes, before)
        self.assertEqual(w.step().status, "DISPATCHED")

    def test_common_machine_gate_accepts_explicit_limits_but_keeps_legacy_default(self):
        common = dict(mode=BackendMode.JULES_BACKEND.value, loop_id=LOOP,
                      expected_target_head="h", observed_target_head="h",
                      expected_target_tree="t", observed_target_tree="t")
        self.assertEqual(validate_machine_gate(**common, round=7, max_rounds=6).status, "BLOCKED")
        self.assertEqual(validate_machine_gate(**common, round=7, max_rounds=30).status, "BLOCKED")
        for limit in (3, 6, 10, 20, 30, MAX_CAMPAIGN_ROUNDS):
            campaign = campaign_policy_from_legacy(policy(), LOOP)
            campaign["max_rounds"] = limit
            with self.subTest(limit=limit):
                self.assertEqual(validate_machine_gate(**common, round=limit, max_rounds=limit,
                                                       campaign_policy=campaign).status, "PASS")
                self.assertEqual(validate_machine_gate(**common, round=limit + 1, max_rounds=limit,
                                                       campaign_policy=campaign).status, "BLOCKED")
                self.assertEqual(validate_machine_gate(**common, round=1, max_rounds=limit,
                                                       campaign_policy=campaign, live_model_requested=True).status, "BLOCKED")
                self.assertEqual(validate_machine_gate(**common, round=1, max_rounds=limit + 1,
                                                       campaign_policy=campaign).status, "BLOCKED")

    def test_campaign_policy_rejects_boolean_and_unbounded_configuration(self):
        for field, bad in (("schema_version", True), ("max_concurrent_agents", True),
                           ("max_rounds", True), ("max_rounds", None),
                           ("max_rounds", MAX_CAMPAIGN_ROUNDS + 1), ("campaign_id", "../escape")):
            campaign = campaign_policy_from_legacy(policy(), LOOP)
            campaign[field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                validate_campaign_policy(campaign)

    def test_long_campaign_round_propagates_through_every_prepare_contract(self):
        for limit in (3, 6, 10, 20, 30, MAX_CAMPAIGN_ROUNDS):
            campaign = campaign_policy_from_legacy(policy(), LOOP)
            campaign["max_rounds"] = limit
            w = World(campaign=campaign)
            controller = w.controller()
            intent = controller._build_intent(
                task_spec(), now=NOW, round_number=limit, attempt=1, generation=1,
                head=w.github.branches[TARGET], tree=w.github.get_commit_tree(w.github.branches[TARGET]),
            )
            self.assertEqual(intent["origin_round"], limit)
            self.assertEqual(intent["origin_binding"]["origin_round"], limit)
            self.assertEqual(controller.dispatcher.policy["max_rounds"], limit)
            self.assertEqual(intent["carrier_request"]["retry"], 0)
            self.assertEqual(w.github.writes, [])

    def test_evidence_start_failure_recovers_in_same_batch_without_new_dispatch(self):
        w = World(plan=roadmap(task_spec()))
        first = w.step()
        w.deliver(w.jules.run(first.details["command_id"]))
        real = w.facts.run_tests
        calls = 0

        def unavailable(head):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("test process temporarily failed to start")
            return real(head)

        w.facts.run_tests = unavailable
        results = w.controller().run_until_boundary(now=NOW)
        self.assertEqual([r.status for r in results], ["UNKNOWN", "PASS", "ADOPTED", "COMPLETE"])
        events = w.controller().campaign_state.events()
        self.assertEqual(sum(e["event_type"] == "RECOVERY_ATTEMPT" for e in events), 1)
        self.assertEqual(len(w.commands()), 1)

    def test_read_recovery_budget_does_not_reset_on_new_controller(self):
        campaign = campaign_policy_from_legacy(policy(), LOOP)
        campaign["max_transient_retries"] = 1
        w = World(campaign=campaign)
        first = w.step()
        w.deliver(w.jules.run(first.details["command_id"]))
        real = w.facts.dispatch_observation

        def unavailable(command):
            raise OSError("temporary network read failed")

        w.facts.dispatch_observation = unavailable
        one = w.controller().run_until_boundary(now=NOW)
        self.assertEqual(len(one), 2)  # initial acquisition plus one bounded recovery
        self.assertTrue(one[-1].details["recovery_budget_exhausted"])
        two = w.controller().run_until_boundary(now=NOW)
        self.assertEqual(len(two), 1)
        self.assertTrue(two[-1].details["recovery_budget_exhausted"])
        w.facts.dispatch_observation = real
        three = w.controller().run_until_boundary(now=NOW)
        self.assertIn("PASS", [r.status for r in three])
        self.assertEqual(len(w.commands()), 2)

    def test_conflicting_recovery_counters_cannot_reset_retry_budget(self):
        w = World()
        state = w.controller().campaign_state
        for attempt in (1, 3):
            event = build_recovery_event(campaign_id=LOOP, scope="a" * 64, attempt=attempt,
                                         reason="read failed", boundary_class="TRANSIENT_UNKNOWN", recorded_at=NOW)
            self.assertEqual(state.persist(event), "CREATED")
        with self.assertRaisesRegex(ValueError, "non-contiguous"):
            state.recovery_attempts("a" * 64)

    def test_corrupted_records_and_ambiguous_writes_stay_non_retryable(self):
        for reason in ("durable intent records unverifiable: digest mismatch; network read failed",
                       "adoption receipt invalid: evidence unavailable", "owner chain invalid: network",
                       "command create not proven; do not resend"):
            result = classify_boundary("UNKNOWN", reason)
            self.assertFalse(result.retry_safe)
            self.assertEqual(result.kind, "HARD_UNKNOWN")

    def test_reinspection_chain_order_wins_over_clock_skew(self):
        w = World(plan=roadmap(task_spec()))
        first = w.step()
        command = first.details["command_id"]
        w.deliver(w.jules.run(command))
        real = w.facts.run_tests
        w.facts.run_tests = lambda head: None
        self.assertEqual(w.step().status, "UNKNOWN")
        w.facts.run_tests = real
        earlier = (datetime.fromisoformat(NOW) - timedelta(seconds=1)).isoformat()
        self.assertEqual(w.step(now=earlier).status, "PASS")
        self.assertEqual(w.step().status, "ADOPTED")
        self.assertEqual(w.step().status, "COMPLETE")
        self.assertEqual(len(w.controller().reinspections.all_versions(w.controller().inspections.list_all()[0])), 2)

    def test_unknown_old_head_then_newer_result_does_not_overwrite_history(self):
        w = World(plan=roadmap(task_spec()))
        command = w.step().details["command_id"]
        payload = w.jules.run(command)
        old_head = payload["pull_request"]["head"]["sha"]
        w.deliver(payload)
        real = w.facts.run_tests
        w.facts.run_tests = lambda head: None
        self.assertEqual(w.step().status, "UNKNOWN")
        newer = w.jules.push_followup(300, {"automation/command_bus/alpha.py": "VALUE = 43\n"})
        w.deliver(newer)
        w.deliver(payload, "late-old-head")
        w.facts.run_tests = real
        results = w.controller().run_until_boundary(now=NOW)
        self.assertEqual([r.status for r in results], ["PASS", "ADOPTED", "COMPLETE"])
        self.assertEqual(w.controller().inspections.get(command, old_head)["verdict"], "UNKNOWN")
        self.assertEqual(w.github.branches[TARGET], newer["pull_request"]["head"]["sha"])

    def test_stale_adoption_replans_and_finishes_same_batch_when_mock_result_arrives(self):
        w = World(plan=roadmap(task_spec()))
        command = w.step().details["command_id"]
        w.deliver(w.jules.run(command))
        self.assertEqual(w.step().status, "PASS")
        old = w.controller().inspections.list_all()[0]
        new_base = w.github.child(w.github.branches[TARGET], {"parallel.txt": "preserve me\n"}, "forward")
        w.github.branches[TARGET] = new_base
        results = w.controller().run_until_boundary(now=NOW)
        self.assertEqual([r.status for r in results], ["REPLANNED", "DISPATCHED", "WAITING_FOR_RESULT"])
        new_command = results[1].details["command_id"]
        self.assertNotEqual(new_command, command)
        w.deliver(w.jules.run(new_command))
        done = w.controller().run_until_boundary(now=NOW)
        self.assertEqual([r.status for r in done], ["PASS", "ADOPTED", "COMPLETE"])
        self.assertEqual(w.controller().inspections.get(command, old["candidate_head"]), old)
        self.assertIn("parallel.txt", w.github.commits[w.github.branches[TARGET]]["files"])

    def test_stale_replan_restores_fresh_head_again_after_restart(self):
        w = World(plan=roadmap(task_spec()))
        w.deliver(w.jules.run(w.step().details["command_id"]))
        w.step()
        first_move = w.github.child(w.github.branches[TARGET], {"one.txt": "1"}, "move1")
        w.github.branches[TARGET] = first_move
        self.assertEqual(w.step().status, "REPLANNED")
        second_move = w.github.child(first_move, {"two.txt": "2"}, "move2")
        w.github.branches[TARGET] = second_move
        dispatched = w.step()
        request = w.command(COMMANDS + dispatched.details["command_id"] + ".json")
        self.assertEqual(request["expected_target_head"], second_move)

    def test_rewritten_canonical_history_is_not_replanned(self):
        w = World(plan=roadmap(task_spec()))
        w.deliver(w.jules.run(w.step().details["command_id"]))
        w.step()
        # Fake canonical reset to an unrelated root: no trusted forward path.
        unrelated = w.github.child(w.github.branches[TARGET], {"x.txt": "x"}, "unrelated")
        w.github.commits[unrelated]["parent"] = None
        w.github.branches[TARGET] = unrelated
        result = w.step()
        self.assertEqual((result.action, result.status), ("STOP", "UNKNOWN"))
        self.assertEqual(len(w.commands()), 1)

    def test_consumed_budget_slot_is_counted_without_dispatch_receipt(self):
        campaign = campaign_policy_from_legacy(policy(), LOOP)
        campaign["dispatch_provider_budget"] = 1
        w = World(campaign=campaign)
        command = w.step().details["command_id"]
        receipt = json.loads(w.github.get(dispatch_receipt_path(command), DATA).text)
        receipt["state"] = "BLOCKED"
        receipt["reason"] = "STALE_TARGET: result was not sent"
        old = w.github.files[(DATA, dispatch_receipt_path(command))]
        w.github.files[(DATA, old.path)] = replace(old, text=canonical_json(receipt))
        result = w.step()
        self.assertEqual(result.status, "PREPARED_NOT_AUTHORIZED")
        self.assertEqual(w.controller()._campaign_dispatches_used(), 1)
        self.assertEqual(len(w.commands()), 1)

    def test_time_is_refreshed_between_controller_steps(self):
        campaign = campaign_policy_from_legacy(policy(), LOOP)
        campaign["task_timeout_seconds"] = 3600
        campaign["campaign_timeout_seconds"] = 3600
        w = World(plan=roadmap(task_spec()), campaign=campaign)
        w.deliver(w.jules.run(w.step().details["command_id"]))
        moments = iter([NOW, (datetime.fromisoformat(NOW) + timedelta(seconds=3601)).isoformat()])
        results = w.controller().run_until_boundary(now=NOW, clock=lambda: next(moments))
        self.assertEqual(results[0].status, "PASS")
        self.assertEqual(results[1].action, "STOP")
        self.assertEqual(results[1].status, "CAMPAIGN_TIMEOUT")
        self.assertNotEqual(w.github.branches[TARGET], w.controller().inspections.list_all()[0]["candidate_head"])

    def test_step_budget_is_a_resumable_yield_not_a_campaign_terminal(self):
        w = World(plan=roadmap(task_spec()))
        result = w.controller().run_until_boundary(now=NOW, max_steps=1)[0]
        self.assertTrue(result.details["continuation_required"])
        self.assertEqual(w.step().status, "WAITING_FOR_RESULT")
        for invalid in (True, 0, 101, 1.5):
            with self.assertRaises(ValueError):
                w.controller().run_until_boundary(now=NOW, max_steps=invalid)

    def test_duplicate_wake_at_complete_does_not_write_or_dispatch_again(self):
        w = World(plan=roadmap(task_spec()))
        w.deliver(w.jules.run(w.step().details["command_id"]))
        one = wake_resume(loop=w.controller(), git=w.github, rest=None, policy=w.policy,
                          origin_loop_id=LOOP, now=NOW, poller=lambda **kwargs: [])
        self.assertEqual(one["steps"][-1]["status"], "COMPLETE")
        writes = list(w.github.writes)
        two = wake_resume(loop=w.controller(), git=w.github, rest=None, policy=w.policy,
                          origin_loop_id=LOOP, now=NOW, poller=lambda **kwargs: [])
        self.assertEqual([s["status"] for s in two["steps"]], ["COMPLETE"])
        self.assertEqual(w.github.writes, writes)

    def test_poll_failure_does_not_discard_already_durable_result(self):
        w = World(plan=roadmap(task_spec()))
        w.deliver(w.jules.run(w.step().details["command_id"]))
        calls = []

        def unavailable(**kwargs):
            calls.append("poll")
            raise OSError("temporary GitHub read failed")

        result = wake_resume(loop=w.controller(), git=w.github, rest=None, policy=w.policy,
                             origin_loop_id=LOOP, now=NOW, poller=unavailable)
        self.assertIn("UNKNOWN", result["poll_error"])
        self.assertEqual(result["steps"][-1]["status"], "COMPLETE")
        self.assertEqual(calls, ["poll"])

    def test_poll_does_not_trust_an_adoption_receipt_by_existence(self):
        w = World()
        command = w.step().details["command_id"]
        path = f"automation/command_bus/evidence/claude-auto-adoption-receipts/{command}.json"
        w.github.create(path, "{}", "tampered fixture", DATA)
        with self.assertRaisesRegex(ValueError, "unverifiable adoption"):
            outstanding_dispatches(w.github, w.policy, LOOP)

    def test_verified_success_is_not_classified_as_an_ambiguous_write(self):
        for status, reason in (("ADOPTED", "fast-forward written and read back"),
                               ("PASS", "all independent checks passed"),
                               ("REPLANNED", "stale candidate preserved")):
            self.assertIsNone(classify_boundary(status, reason))

    def test_config_is_durable_and_restart_cannot_silently_reset_it(self):
        campaign = campaign_policy_from_legacy(policy(), LOOP)
        w = World(campaign=campaign)
        self.assertEqual(w.step().status, "DISPATCHED")
        writes = list(w.github.writes)
        self.assertEqual(w.step().status, "WAITING_FOR_RESULT")
        self.assertEqual(w.github.writes, writes)
        w.campaign = dict(campaign, max_transient_retries=20)
        mismatch = w.step()
        self.assertEqual(mismatch.status, "UNKNOWN")
        self.assertIn("configuration mismatch", mismatch.reason)
        self.assertEqual(w.github.writes, writes)

    def test_explicit_config_without_dispatch_authority_does_not_write(self):
        legacy = policy(live_dispatch_authorization=None)
        campaign = campaign_policy_from_legacy(legacy, LOOP)
        campaign["max_rounds"] = 30
        w = World(pol=legacy, campaign=campaign)
        self.assertEqual(w.step().status, "PREPARED_NOT_AUTHORIZED")
        self.assertEqual(w.github.writes, [])

    def test_live_dispatch_cap_is_not_expanded_by_a_long_campaign(self):
        campaign = campaign_policy_from_legacy(policy(), LOOP)
        campaign["max_rounds"] = 30
        w = World(campaign=campaign)
        self.assertEqual(w.controller().dispatcher.policy["live_dispatch_authorization"]["max_dispatches"], 6)
        for index in range(6):
            # A separate settled record for the same logical stream consumes
            # the local provider cap even if the engine is configured for 30.
            ledger = w.controller().dispatcher.budget
            ledger.acquire(command_id=f"relay-dev-loop-{800 + index}-used", intent_sha256="a" * 64,
                           origin_loop_id=LOOP, acquired_at=NOW)
        w.campaign["dispatch_provider_budget"] = 6
        result = w.step()
        self.assertEqual(result.status, "PREPARED_NOT_AUTHORIZED")
        self.assertEqual(w.commands(), [])

    def test_timeout_with_running_or_unverified_provider_does_not_overlap_dispatch(self):
        for status in ("RUNNING", "UNKNOWN"):
            campaign = campaign_policy_from_legacy(policy(), LOOP)
            campaign["task_timeout_seconds"] = 30
            campaign["campaign_timeout_seconds"] = 600
            w = World(plan=independent_plan(), campaign=campaign)
            first = w.step()
            real = w.facts.timeout_reconciliation
            w.facts.timeout_reconciliation = lambda intent: dict(real(intent), status=status)
            late = (datetime.fromisoformat(NOW) + timedelta(seconds=31)).isoformat()
            results = w.controller().run_until_boundary(now=late)
            self.assertEqual(results[-1].status, "AWAITING_TIMEOUT_RECONCILIATION")
            self.assertEqual(len(w.commands()), 1)
            self.assertEqual(w.controller().campaign_state.blocked_tasks(), set())
            w.facts.timeout_reconciliation = real
            resumed = w.controller().run_until_boundary(now=late)
            self.assertEqual([r.status for r in resumed], ["TASK_BLOCKED", "DISPATCHED", "WAITING_FOR_RESULT"])
            self.assertNotEqual(resumed[1].details["command_id"], first.details["command_id"])

    def test_timeout_reconciliation_recovers_a_lost_event_before_blocking_task(self):
        campaign = campaign_policy_from_legacy(policy(), LOOP)
        campaign["task_timeout_seconds"] = 30
        campaign["campaign_timeout_seconds"] = 600
        w = World(plan=roadmap(task_spec()), campaign=campaign)
        command = w.step().details["command_id"]
        payload = w.jules.run(command)  # result exists but its event was lost
        from automation.command_bus.claude_jules_result_event import normalize_pull_request_event
        event = normalize_pull_request_event(event_name="pull_request", delivery_id="timeout-readback",
                                             payload=payload, expected_repo=w.policy["target_repo"]).record
        real = w.facts.timeout_reconciliation
        w.facts.timeout_reconciliation = lambda intent: dict(real(intent), result_events=[event])
        late = (datetime.fromisoformat(NOW) + timedelta(seconds=31)).isoformat()
        results = w.controller().run_until_boundary(now=late)
        self.assertEqual([r.status for r in results], ["PASS", "ADOPTED", "COMPLETE"])
        self.assertEqual(w.controller().campaign_state.blocked_tasks(), set())
        self.assertEqual(len(w.commands()), 1)

    def test_malformed_timeout_settlement_cannot_authorize_new_dispatch(self):
        campaign = campaign_policy_from_legacy(policy(), LOOP)
        campaign["task_timeout_seconds"] = 30
        campaign["campaign_timeout_seconds"] = 600
        w = World(plan=independent_plan(), campaign=campaign)
        w.step()
        real = w.facts.timeout_reconciliation
        w.facts.timeout_reconciliation = lambda intent: dict(real(intent), command_id="wrong-command")
        result = w.step(now=(datetime.fromisoformat(NOW) + timedelta(seconds=31)).isoformat())
        self.assertEqual((result.action, result.status), ("STOP", "UNKNOWN"))
        self.assertEqual(len(w.commands()), 1)

    def test_mixed_campaign_continues_seven_rounds_across_restarts(self):
        auth = dict(policy()["live_dispatch_authorization"], max_dispatches=10)
        legacy = policy(live_dispatch_authorization=auth)
        campaign = campaign_policy_from_legacy(legacy, LOOP)
        campaign.update(max_rounds=10, task_timeout_seconds=30, campaign_timeout_seconds=600)
        specs = [task_spec(name, f"automation/command_bus/{name.replace('-', '_')}.py",
                           f"automation/command_bus/tests/test_{name.replace('-', '_')}.py")
                 for name in ("pass-first", "correct-me", "lost-evidence", "timeout-only", "last-independent")]
        plan = roadmap(*specs)
        for entry in plan["tasks"]:
            entry["depends_on"] = []
        w = World(pol=legacy, plan=plan, campaign=campaign)
        statuses = []
        now = NOW
        real_tests = w.facts.run_tests
        faults = {"lost_head": None, "missing": False, "moved": False}

        def tests(head):
            if head == faults["lost_head"] and not faults["missing"]:
                faults["missing"] = True
                return None
            evidence = real_tests(head)
            if head == faults["lost_head"] and not faults["moved"]:
                faults["moved"] = True
                old = w.github.branches[TARGET]
                w.github.branches[TARGET] = w.github.child(old, {"parallel.txt": "preserved"}, "mid-campaign")
            return evidence

        w.facts.run_tests = tests
        for _ in range(12):
            # Each wake reconstructs a new controller solely from durable data.
            results = w.controller().run_until_boundary(now=now)
            statuses.extend(r.status for r in results)
            if results[-1].action == "STOP":
                self.assertEqual(results[-1].status, "TASK_BLOCKED")
                break
            self.assertEqual(results[-1].status, "WAITING_FOR_RESULT")
            intent = w.controller()._intents()[-1]
            task = intent["task_id"]
            if task == "timeout-only":
                now = (datetime.fromisoformat(now) + timedelta(seconds=31)).isoformat()
                continue
            payload = w.jules.run(intent["carrier_request"]["command_id"])
            if task == "lost-evidence" and faults["lost_head"] is None:
                faults["lost_head"] = payload["pull_request"]["head"]["sha"]
            if task == "correct-me":
                w.facts.review_failures[payload["pull_request"]["head"]["sha"]] = [
                    {"category": "semantic_gap", "detail": "missing negative case"}]
            w.deliver(payload)
            w.deliver(payload, "duplicate-" + task)
        else:
            self.fail("mixed campaign did not reach its genuine dependency boundary")
        self.assertEqual(len(w.commands()), 7)
        self.assertEqual(w.controller()._intents()[-1]["origin_round"], 7)
        self.assertEqual(w.controller().campaign_state.blocked_tasks(), {"timeout-only"})
        self.assertIn("REPLANNED", statuses)
        self.assertIn("UNKNOWN", statuses)
        self.assertIn("FAIL_MAJOR", statuses)
        self.assertEqual(statuses.count("ADOPTED"), 4)
        self.assertTrue(any(r["verdict"] == "UNKNOWN" for r in w.controller().inspections.list_all()))
        self.assertIn("parallel.txt", w.github.commits[w.github.branches[TARGET]]["files"])
        before = list(w.github.writes)
        self.assertEqual(w.controller().run_until_boundary(now=now)[-1].status, "TASK_BLOCKED")
        self.assertEqual(w.github.writes, before)


if __name__ == "__main__":
    unittest.main()
