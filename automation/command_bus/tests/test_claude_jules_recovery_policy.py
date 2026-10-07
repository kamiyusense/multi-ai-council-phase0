"""Reasoned bounded recovery v1 (explicit opt-in): decision table, durability, restart and no-progress detection.

Local fakes only: no network, no Jules, no LIVE.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from automation.command_bus import claude_jules_recovery_policy as rp
from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World
from automation.command_bus.tests.claude_jules_autoloop_fakes import DATA, LOOP, NOW, roadmap, task_spec

POLICY = rp.recovery_policy()


def at(seconds: int) -> str:
    return (datetime.fromisoformat(NOW) + timedelta(seconds=seconds)).isoformat()


def hist(*entries):
    """Persisted payload history: (attempt, recorded_at, reason, conditions[, reduced])."""
    out = []
    for attempt, when, cause, op, reason, cond, *rest in entries:
        decision = rp.RecoveryDecision(rp.RETRY, cause, attempt, reason,
                                       details={"reduced_scope": bool(rest and rest[0])})
        out.append(rp.decision_payload(decision, scope="a" * 64, operation=op, reason=reason, evidence_ref="x",
                                       why_meaningful="y", conditions=cond, recorded_at=when))
    return out


def decide(cause, op, reason="read failed", conditions=None, history=(), now=NOW):
    return rp.decide(POLICY, cause=cause, operation=op, reason=reason, conditions=conditions or {},
                     history=list(history), now=now)


class DecisionTableTests(unittest.TestCase):
    def test_policy_rejects_unsafe_tables(self):
        bad = dict(rp.DEFAULT_RULES)
        bad[rp.AUTHORITY] = rp.CauseRule(True, ("x",), 1, (0,), 10, "", 0, rp.STOP_CAMPAIGN)
        with self.assertRaises(ValueError):
            rp.validate_recovery_policy({"profile": rp.RECOVERY_POLICY_PROFILE, "rules": bad})
        bad = dict(rp.DEFAULT_RULES)
        bad[rp.TRANSIENT_READ] = rp.CauseRule(True, ("github-read",), 50, (0,) * 50, 10, "", 0, rp.ISOLATE_TASK)
        with self.assertRaises(ValueError):
            rp.validate_recovery_policy({"profile": rp.RECOVERY_POLICY_PROFILE, "rules": bad})
        bad = dict(rp.DEFAULT_RULES)
        bad[rp.AMBIGUOUS_WRITE] = rp.CauseRule(True, ("create-after-proven-absent",), 1, (0,), 10, "", 0,
                                               rp.STOP_CAMPAIGN)
        with self.assertRaises(ValueError):
            rp.validate_recovery_policy({"profile": rp.RECOVERY_POLICY_PROFILE, "rules": bad})
        with self.assertRaises(ValueError):
            rp.validate_recovery_policy({"profile": rp.RECOVERY_POLICY_PROFILE, "rules": {}})

    def test_never_retried_causes(self):
        for cause, expected in ((rp.AUTHORITY, rp.STOP_CAMPAIGN), (rp.BUDGET, rp.STOP_CAMPAIGN),
                                (rp.INTEGRITY, rp.STOP_CAMPAIGN), (rp.TASK_BLOCKER, rp.ISOLATE_TASK)):
            self.assertEqual(decide(cause, "anything").decision, expected, cause)

    def test_operation_must_belong_to_the_cause(self):
        self.assertEqual(decide(rp.TRANSIENT_READ, "jules-dispatch").decision, rp.STOP_CAMPAIGN)

    def test_transient_read_backoff_cap_and_deadline(self):
        op = "evidence-read"
        self.assertEqual(decide(rp.TRANSIENT_READ, op).decision, rp.RETRY)
        one = hist((1, NOW, rp.TRANSIENT_READ, op, "read failed", {}))
        waiting = decide(rp.TRANSIENT_READ, op, history=one, now=at(60))
        self.assertEqual((waiting.decision, waiting.not_before), (rp.WAIT_UNTIL, at(120)))
        self.assertEqual(decide(rp.TRANSIENT_READ, op, history=one, now=at(120)).decision, rp.RETRY)
        three = hist((1, NOW, rp.TRANSIENT_READ, op, "read failed", {}),
                     (2, at(120), rp.TRANSIENT_READ, op, "read failed", {}),
                     (3, at(720), rp.TRANSIENT_READ, op, "read failed", {}))
        exhausted = decide(rp.TRANSIENT_READ, op, history=three, now=at(800))
        self.assertEqual(exhausted.decision, rp.ISOLATE_TASK)
        self.assertIn("exhausted", exhausted.reason)
        late = decide(rp.TRANSIENT_READ, op, history=one, now=at(3601))
        self.assertEqual(late.decision, rp.ISOLATE_TASK)
        self.assertIn("deadline", late.reason)

    def test_test_rerun_needs_a_changed_environment(self):
        op = "claude-test-run"
        one = hist((1, NOW, rp.TEST_ENVIRONMENT, op, "python3 not found", {"environment_digest": "e1"}))
        same = decide(rp.TEST_ENVIRONMENT, op, "python3 not found", {"environment_digest": "e1"}, one, at(5))
        self.assertEqual(same.decision, rp.ISOLATE_TASK)
        self.assertIn("no progress", same.reason)
        changed = decide(rp.TEST_ENVIRONMENT, op, "python3 not found", {"environment_digest": "e2"}, one, at(5))
        self.assertEqual(changed.decision, rp.RETRY)

    def test_semantic_failure_same_finding_reduces_then_isolates(self):
        op = "jules-corrective"
        cond = {"findings_fingerprint": "f1"}
        one = hist((1, NOW, rp.SEMANTIC_FAILURE, op, "acceptance missing test", cond))
        reduced = decide(rp.SEMANTIC_FAILURE, op, "acceptance missing test", cond, one, at(5))
        self.assertEqual((reduced.decision, reduced.provider_budget_effect), (rp.REDUCE_SCOPE, 1))
        two = one + hist((2, at(5), rp.SEMANTIC_FAILURE, op, "acceptance missing test", cond, True))
        policy3 = rp.recovery_policy(semantic_max_attempts=3)
        again = rp.decide(policy3, cause=rp.SEMANTIC_FAILURE, operation=op, reason="acceptance missing test",
                          conditions=cond, history=two, now=at(9))
        self.assertEqual(again.decision, rp.ISOLATE_TASK)
        progress = decide(rp.SEMANTIC_FAILURE, op, "lint error", {"findings_fingerprint": "f2"}, one, at(5))
        self.assertEqual(progress.decision, rp.RETRY)

    def test_stale_target_needs_a_new_head_each_time(self):
        op = "replan"
        one = hist((1, NOW, rp.STALE_TARGET, op, "target head changed", {"canonical_head": "a" * 40}))
        self.assertEqual(decide(rp.STALE_TARGET, op, "target head changed", {"canonical_head": "a" * 40},
                                one, at(1)).decision, rp.ISOLATE_TASK)
        self.assertEqual(decide(rp.STALE_TARGET, op, "target head changed", {"canonical_head": "b" * 40},
                                one, at(1)).decision, rp.RETRY)

    def test_ambiguous_write_reconciles_first_and_retries_once_after_proven_absence(self):
        op = "create-after-proven-absent"
        self.assertEqual(decide(rp.AMBIGUOUS_WRITE, op, "write not proven").decision, rp.RECONCILE_FIRST)
        self.assertEqual(decide(rp.AMBIGUOUS_WRITE, op, "write not proven",
                                {"absence_proof": "maybe"}).decision, rp.RECONCILE_FIRST)
        self.assertEqual(decide(rp.AMBIGUOUS_WRITE, op, "write not proven",
                                {"absence_proof": True}).decision, rp.RETRY)
        one = hist((1, NOW, rp.AMBIGUOUS_WRITE, op, "write not proven", {"absence_proof": True}))
        self.assertEqual(decide(rp.AMBIGUOUS_WRITE, op, "write not proven", {"absence_proof": True},
                                one, at(1)).decision, rp.STOP_CAMPAIGN)

    def test_provider_failure_gets_one_distinct_attempt(self):
        op = "jules-new-attempt"
        first = decide(rp.PROVIDER_FAILURE, op, "provider FAILED", {"attempt_plan_digest": "p1"})
        self.assertEqual((first.decision, first.provider_budget_effect), (rp.RETRY, 1))
        one = hist((1, NOW, rp.PROVIDER_FAILURE, op, "provider FAILED", {"attempt_plan_digest": "p1"}))
        self.assertEqual(decide(rp.PROVIDER_FAILURE, op, "provider FAILED", {"attempt_plan_digest": "p2"},
                                one, at(1)).decision, rp.ISOLATE_TASK)

    def test_non_contiguous_history_is_never_a_reset(self):
        broken = hist((2, NOW, rp.TRANSIENT_READ, "evidence-read", "read failed", {}))
        self.assertEqual(decide(rp.TRANSIENT_READ, "evidence-read", history=broken).decision, rp.STOP_CAMPAIGN)

    def test_fingerprint_ignores_volatile_ids(self):
        a = rp.failure_fingerprint(rp.TRANSIENT_READ, "x", "run 123 job abcdef1234 failed")
        b = rp.failure_fingerprint(rp.TRANSIENT_READ, "x", "run 999 job 0123456789 failed")
        self.assertEqual(a, b)
        self.assertNotEqual(a, rp.failure_fingerprint(rp.TRANSIENT_READ, "x", "permission denied"))

    def test_cause_mapping_is_conservative(self):
        self.assertEqual(rp.classify_cause("TRANSIENT_UNKNOWN", "read failed"), rp.TRANSIENT_READ)
        self.assertEqual(rp.classify_cause("RECOVERABLE_UNKNOWN", "stale head"), rp.STALE_TARGET)
        self.assertEqual(rp.classify_cause("HARD_UNKNOWN", "live dispatch not granted"), rp.AUTHORITY)
        self.assertEqual(rp.classify_cause("HARD_UNKNOWN", "create not proven; do not resend"), rp.AMBIGUOUS_WRITE)
        self.assertEqual(rp.classify_cause("HARD_UNKNOWN", "digest mismatch"), rp.INTEGRITY)


class RecoveryWorld(World):
    recovery = POLICY

    def controller(self) -> ClaudeJulesAutoLoop:
        return ClaudeJulesAutoLoop(
            client=self.github, refs=self.github, policy=self.policy,
            owner_reader=LoopOwnerGitHubBackend(self.github, branch=DATA), roadmap=self.roadmap,
            facts=self.facts, origin_loop_id=LOOP, lane_id="J-BLUE", campaign_policy=self.campaign,
            recovery_policy=self.recovery)


def decisions(w):
    return [e for e in w.controller().campaign_state.events() if e["event_type"] == "RECOVERY_DECISION"]


class ControllerIntegrationTests(unittest.TestCase):
    def test_read_outage_backs_off_durably_across_restarts_then_isolates(self):
        w = RecoveryWorld(plan=roadmap(task_spec()))
        w.deliver(w.jules.run(w.step().details["command_id"]))

        def down(command_id):
            raise OSError("temporary network read failed")

        w.facts.dispatch_observation = down
        first = w.controller().run_until_boundary(now=NOW)
        # attempt 1 retries at once (backoff 0), attempt 2 must wait 120 s
        self.assertEqual([r.status for r in first], ["UNKNOWN", "UNKNOWN", "RECOVERY_BACKOFF"])
        self.assertEqual(first[-1].details["next_check_at"], at(120))
        self.assertEqual(len(decisions(w)), 1)
        # restart before the backoff ends: same WAIT, nothing written
        writes = list(w.github.writes)
        again = w.controller().run_until_boundary(now=at(60))
        self.assertEqual([r.status for r in again], ["UNKNOWN", "RECOVERY_BACKOFF"])
        self.assertEqual(w.github.writes, writes)
        later = w.controller().run_until_boundary(now=at(121))
        self.assertEqual(later[-1].status, "RECOVERY_BACKOFF")
        self.assertEqual(later[-1].details["next_check_at"], (datetime.fromisoformat(at(121)) + timedelta(seconds=600)).isoformat())
        final = w.controller().run_until_boundary(now=at(800))
        self.assertEqual(final[-1].status, "TASK_BLOCKED")
        recorded = sorted(decisions(w), key=lambda d: d["payload"]["attempt"])
        self.assertEqual([d["payload"]["attempt"] for d in recorded], [1, 2, 3, 4])
        self.assertEqual(recorded[-1]["payload"]["decision"], rp.ISOLATE_TASK)
        for d in recorded:
            self.assertEqual(d["payload"]["provider_budget_effect"], 0)
            self.assertEqual(d["payload"]["cause"], rp.TRANSIENT_READ)
            self.assertTrue(d["payload"]["why_meaningful"])
        self.assertEqual(len(w.commands()), 1)  # read recovery never dispatches

    def test_short_outage_recovers_and_finishes(self):
        w = RecoveryWorld(plan=roadmap(task_spec()))
        w.deliver(w.jules.run(w.step().details["command_id"]))
        real, calls = w.facts.dispatch_observation, []

        def flaky(command_id):
            calls.append(command_id)
            if len(calls) == 1:
                raise OSError("temporary network read failed")
            return real(command_id)

        w.facts.dispatch_observation = flaky
        results = w.controller().run_until_boundary(now=NOW)
        self.assertEqual([r.status for r in results], ["UNKNOWN", "PASS", "ADOPTED", "COMPLETE"])
        self.assertEqual(len(decisions(w)), 1)

    def test_conflicting_decisions_for_one_attempt_fail_closed(self):
        w = RecoveryWorld(plan=roadmap(task_spec()))
        w.deliver(w.jules.run(w.step().details["command_id"]))

        def down(command_id):
            raise OSError("temporary network read failed")

        w.facts.dispatch_observation = down
        w.controller().run_until_boundary(now=NOW)
        [event] = decisions(w)
        twin = rp.decision_payload(rp.RecoveryDecision(rp.RETRY, rp.TRANSIENT_READ, 1, "other"),
                                   scope=event["payload"]["scope"], operation="evidence-read", reason="other",
                                   evidence_ref="x", why_meaningful="y", conditions={}, recorded_at=at(1))
        from automation.command_bus.claude_jules_campaign_state import build_recovery_decision_event
        w.controller().campaign_state.persist(build_recovery_decision_event(campaign_id=LOOP, payload=twin))
        out = w.controller().run_until_boundary(now=at(500))
        self.assertEqual(out[-1].status, "UNKNOWN")
        self.assertIn("do not resend", out[-1].reason)


    def _corrective_world(self):
        from automation.command_bus.claude_jules_campaign import campaign_policy_from_legacy
        from automation.command_bus.tests.claude_jules_autoloop_fakes import policy
        auth = dict(policy()["live_dispatch_authorization"], max_dispatches=10)
        legacy = policy(max_rounds=10, live_dispatch_authorization=auth)
        campaign = campaign_policy_from_legacy(legacy, LOOP)
        campaign.update(max_corrective_rounds_per_task=3, max_consecutive_failures=4)
        w = RecoveryWorld(pol=legacy, plan=roadmap(task_spec("alpha-helper")), campaign=campaign)
        w.recovery = rp.recovery_policy(semantic_max_attempts=3)
        return w

    def _fail(self, w, command_id, detail):
        payload = w.jules.run(command_id)
        w.facts.review_failures[payload["pull_request"]["head"]["sha"]] = [{"category": "semantic_gap", "detail": detail}]
        w.deliver(payload)
        return w.step()

    def test_identical_finding_shrinks_scope_then_isolates_before_the_legacy_budget(self):
        w = self._corrective_world()
        command = w.step().details["command_id"]
        statuses = []
        for _ in range(3):
            self._fail(w, command, "negative case still missing")
            nxt = w.step()
            statuses.append(nxt.status)
            if nxt.status != "DISPATCHED":
                break
            command = nxt.details["command_id"]
        self.assertEqual(statuses, ["DISPATCHED", "DISPATCHED", "TASK_BLOCKED"])
        recorded = sorted((d["payload"] for d in decisions(w)), key=lambda p: p["attempt"])
        self.assertEqual([p["decision"] for p in recorded], [rp.RETRY, rp.REDUCE_SCOPE, rp.ISOLATE_TASK])
        self.assertEqual(len(w.commands()), 3)  # legacy alone would have spent a 4th dispatch
        blocked = [e for e in w.controller().campaign_state.events() if e["event_type"] == "TASK_BLOCKED"]
        self.assertIn("no progress", blocked[0]["payload"]["reason"])

    def test_changing_findings_keep_correcting_within_budget(self):
        w = self._corrective_world()
        command = w.step().details["command_id"]
        for index in range(3):
            self._fail(w, command, f"different gap {index}")
            nxt = w.step()
            self.assertEqual(nxt.status, "DISPATCHED", nxt.reason)
            command = nxt.details["command_id"]
        recorded = sorted((d["payload"] for d in decisions(w)), key=lambda p: p["attempt"])
        self.assertEqual([p["decision"] for p in recorded], [rp.RETRY] * 3)
        self.assertTrue(all(p["provider_budget_effect"] == 1 for p in recorded))


if __name__ == "__main__":
    unittest.main()
