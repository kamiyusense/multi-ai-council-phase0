"""Production Starter: start conditions, negative cases, crash / restart / duplicate / response-loss recovery."""
from __future__ import annotations

import json
import unittest
from datetime import timedelta

from automation.command_bus import claude_closed_loop_review as review
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus.tests import starter_world as sw


def labeled_events(world, n):
    return sum(1 for e in world.gh.issues[n]["label_events"] if e["event"] == "labeled" and e["label"] == st.LABEL)


class Base(unittest.TestCase):
    def make(self, n=2, *, policy=None, extras=None, seed=True):
        self.c = sw.campaign("ca", n, policy=policy, extras=extras)
        self.w = sw.World([self.c])
        if seed:
            self.seed, self.first = sw.seed_predecessor(self.w, self.c)
            self.w.gh.events.clear()
        return self.w

    def step(self, n=None, controller="ctl-x", **snap_overrides):
        n = n or self.first
        snap = self.w.snapshot(n, getattr(self, "seed", None), "ca")
        snap.update(snap_overrides)
        return st.next_step(snap, campaign=self.c, controller=controller)

    def assert_not_started(self, n=None, action=None):
        n = n or self.first
        self.assertEqual(labeled_events(self.w, n), 0)
        if action:
            self.assertEqual(self.step(n).action, action)


class StartSequenceTests(Base):
    def test_full_sequence_intent_label_receipt_then_noop(self):
        self.make()
        res = self.w.run_controller(self.first)
        self.assertEqual([s.action for s in res.steps],
                         [st.WRITE_INTENT, st.WRITE_LABEL, st.WRITE_START_RECEIPT, st.NO_OP])
        self.assertEqual(labeled_events(self.w, self.first), 1)
        intents, receipts = st.starter_records(self.w.gh.issues[self.first]["comments"], {sw.OWNER})
        self.assertEqual(len(intents), 1)
        self.assertEqual(receipts[0]["outcome"], "STARTED")
        self.assertEqual(receipts[0]["task_sha256"], self.w.entries["ca"][1]["task_sha256"])
        self.assertEqual(intents[0]["predecessor_pr_head"], sw.sha("seed"))

    def test_all_checks_are_named_before_any_write(self):
        self.make()
        s = self.step()
        self.assertEqual(s.action, st.WRITE_INTENT)
        self.assertEqual(s.checks, ("policy", "manifest", "route", "task_identity", "task_policy", "not_started",
                                    "dependencies", "predecessor_pass", "base", "capacity"))

    def test_replay_after_start_is_noop_and_never_relabels(self):
        self.make()
        self.w.run_controller(self.first)
        for k in range(5):
            res = self.w.run_controller(self.first, controller=f"replay-{k}")
            self.assertEqual(res.steps[-1].action, st.NO_OP)
        self.assertEqual(labeled_events(self.w, self.first), 1)

    def test_issue_opened_before_receipt_defers_then_receipt_event_starts(self):
        self.make()
        comments = self.w.gh.issues[self.seed]["comments"]
        receipt = comments.pop()                        # the reviewer created the issue, the receipt is not there yet
        self.w.starter_wake({"name": "issues.opened", "issue": self.first})
        self.assertEqual(self.w.starter_results[-1].steps[-1].action, st.DEFER)
        comments.append(receipt)
        self.w.starter_wake({"name": "issue_comment.created", "issue": self.seed, "author": sw.OWNER,
                             "body": receipt["body"]})
        self.assertEqual(labeled_events(self.w, self.first), 1)


class NegativeTests(Base):
    """None of these may start a Jules task."""

    def _receipt(self, **changes):
        pred = self.w.gh.issues[self.seed]
        body = pred["comments"][-1]["body"]
        rec = review.parse_receipt(body)
        rec.update(changes)
        pred["comments"][-1]["body"] = review.render_receipt(summary="edited", record=rec)

    def test_no_pass_receipt(self):
        self.make()
        self.w.gh.issues[self.seed]["comments"].clear()
        self.assert_not_started(action=st.DEFER)

    def test_malformed_receipt(self):
        self.make()
        self.w.gh.issues[self.seed]["comments"][-1]["body"] += "\n" + review.RECEIPT_MARKER + "\n{broken\n-->"
        self.assert_not_started(action=st.NO_OP)

    def test_fail_predecessor_waits(self):
        self.make()
        self._receipt(verdict=review.NEEDS_CORRECTION, decision="CORRECTIVE_REQUESTED", next_issue=None)
        self.assert_not_started(action=st.DEFER)

    def test_blocked_predecessor(self):
        self.make()
        self._receipt(verdict=review.BLOCKED, decision="TASK_BLOCKED", next_issue=None)
        self.assert_not_started(action=st.BLOCKED)

    def test_receipt_naming_another_issue(self):
        self.make()
        self._receipt(next_issue=self.first + 50)
        self.assert_not_started(action=st.BLOCKED)

    def test_duplicate_pass_receipt(self):
        self.make()
        pred = self.w.gh.issues[self.seed]
        pred["comments"].append({**pred["comments"][-1], "id": 99999})
        self.assert_not_started(action=st.BLOCKED)

    def test_forged_receipt_by_untrusted_author_is_ignored(self):
        self.make()
        for c in self.w.gh.issues[self.seed]["comments"]:
            c["author"] = "someone-else"
        self.assert_not_started(action=st.DEFER)

    def test_wrong_correlation(self):
        self.make()
        pred = self.w.gh.issues[self.seed]
        pred["body"] = pred["body"].replace("ca-seed-aaaaaaa", "ca-seed-bbbbbbb")
        self.assert_not_started(action=st.BLOCKED)

    def test_predecessor_head_changed_after_pass(self):
        self.make()
        self.w.gh.prs[self.w.jules_pr[self.seed]]["head"] = "f" * 40
        self.assert_not_started(action=st.BLOCKED)

    def test_stale_generation_wake(self):
        self.make()
        self.assertEqual(self.step(event={"generation": 7}).action, st.NO_OP)
        self.assert_not_started()

    def test_wrong_repository(self):
        self.make()
        self.assertEqual(self.step(repository="someone/else").action, st.BLOCKED)

    def test_already_labeled_outside_the_starter(self):
        self.make()
        self.w.gh.add_label(self.first, st.LABEL)
        self.assertEqual(self.step().action, st.BLOCKED)
        self.assertEqual(labeled_events(self.w, self.first), 1)  # the human's, not a second one

    def test_closed_issue(self):
        self.make()
        self.w.gh.issues[self.first]["state"] = "CLOSED"
        self.assert_not_started(action=st.BLOCKED)

    def test_deleted_issue(self):
        self.make()
        del self.w.gh.issues[self.first]
        snap = self.w.snapshot(self.first, self.seed, "ca")
        self.assertEqual(st.next_step(snap, campaign=self.c, controller="x").action, st.BLOCKED)

    def test_edited_task_identity(self):
        self.make()
        issue = self.w.gh.issues[self.first]
        issue["body"] = issue["body"].replace("behaviour fixed", "behaviour changed")
        self.assert_not_started(action=st.BLOCKED)
        self.assertIn("edited after preparation", self.step().reason)

    def test_edited_title(self):
        self.make()
        self.w.gh.issues[self.first]["title"] += " (edited)"
        self.assert_not_started(action=st.BLOCKED)

    def test_unauthorized_task_type(self):
        self.make(policy=st.make_policy(allowed_task_kinds=["proof"]))
        self.assert_not_started(action=st.BLOCKED)

    def _boundary(self, text):
        self.make(extras={1: {"acceptance_criteria": [text, "a regression test is added"]}})
        self.assert_not_started(action=st.ISOLATE)
        s = self.step()
        self.assertEqual((s.code, s.human_required), ("CLASSIFICATION_MISMATCH", True))

    def test_destructive_request(self):
        self._boundary("Run rm -rf on the build directory and delete the branch afterwards")

    def test_merge_request(self):
        self._boundary("Merge the pull request into main when green")

    def test_default_branch_write_request(self):
        self._boundary("Push directly to main")

    def test_billing_or_key_request(self):
        self._boundary("Rotate the API key used by the workflow")

    def test_protected_path(self):
        self.make(extras={1: {"allowed_paths": [{"path": ".github/workflows/x.yml", "op": "MODIFY"}]}})
        self.assert_not_started(action=st.BLOCKED)

    def test_other_route_requested_by_task(self):
        self.make(extras={1: {"route": "carrier-rest"}})
        self.assert_not_started(action=st.BLOCKED)

    def test_api_key_route_observed_is_hard_stop(self):
        self.make()
        s = self.step(route_observation={"transport": "carrier-rest-api-key", "auth_method": "api_key",
                                         "billing_route": "unknown"})
        self.assertEqual((s.action, s.scope, s.code), (st.HARD_STOP, "provider_execution", "PAID_ROUTE"))

    def test_metered_route_observed_is_hard_stop(self):
        self.make()
        s = self.step(route_observation={"transport": st.ROUTE, "auth_method": "account_oauth",
                                         "billing_route": "metered"})
        self.assertEqual(s.action, st.HARD_STOP)

    def test_unknown_route_defers(self):
        self.make()
        self.assertEqual(self.step(route_observation={}).action, st.DEFER)
        self.assertEqual(self.step(route_observation={"transport": "something-new", "auth_method": "account_oauth",
                                                      "billing_route": "subscription"}).action, st.DEFER)

    def test_policy_with_fallback_is_hard_stop(self):
        for bad in ({"allow_api_fallback": True}, {"allow_metered_fallback": True}, {"billing": "metered"},
                    {"route": "carrier-rest"}):
            with self.subTest(bad=bad):
                self.make()
                self.c["policy"].update(bad)
                self.assertEqual(self.step().action, st.HARD_STOP)

    def test_base_moved_over_an_allowed_path_is_stale(self):
        self.make()
        path = self.w.entries["ca"][1]["task"]["allowed_paths"][0]["path"]
        self.assertEqual(self.step(base_head="b" * 40, base_changed_paths=[path]).action, st.BLOCKED)
        self.assertEqual(self.step(base_head="b" * 40, base_changed_paths=None).action, st.DEFER)
        self.assertEqual(self.step(base_head="b" * 40, base_changed_paths=["README.md"]).action, st.WRITE_INTENT)
        self.assertEqual(self.step(base_head="not-a-sha").action, st.DEFER)

    def test_exact_base_policy(self):
        self.make(policy=st.make_policy(base_policy="exact"))
        self.assertEqual(self.step(base_head="b" * 40, base_changed_paths=[]).action, st.BLOCKED)

    def test_unrelated_issue_is_ignored(self):
        self.make()
        n = self.w.gh.create_issue("random bug", "Something is broken.")
        snap = self.w.snapshot(n, None, "ca")
        self.assertEqual(st.next_step(snap, campaign=self.c, controller="x").action, st.IGNORE)

    def test_task_without_starter_metadata_needs_a_human(self):
        self.make()
        task = sw.code_task("plain", path="docs/p.md")
        n = self.w.gh.create_issue("plain", st.render_task_issue(task, "plain task"))
        snap = self.w.snapshot(n, self.seed, "ca")
        self.assertEqual(st.next_step(snap, campaign=self.c, controller="x").action, st.BLOCKED)

    def test_corrupt_starter_record_means_no_write(self):
        self.make()
        self.w.gh.comment(self.first, st.INTENT_MARKER + "\n{\"profile\": \"x\"}\n-->")
        self.assert_not_started(action=st.NO_OP)

    def test_unread_comments_or_label_history_means_unknown(self):
        self.make()
        for key in ("comments", "label_events", "labels"):
            with self.subTest(key=key):
                snap = self.w.snapshot(self.first, self.seed, "ca")
                snap["candidate"].pop(key)
                self.assertEqual(st.next_step(snap, campaign=self.c, controller="x").action, st.DEFER)

    def test_corrupt_manifest_is_hard_stop(self):
        self.make()
        self.c["tasks"][0]["task_sha256"] = "0" * 64
        self.assertEqual(self.step().action, st.HARD_STOP)

    def test_label_removed_after_start_is_never_readded(self):
        self.make()
        self.w.run_controller(self.first)
        # a human removes the label and deletes the start receipt comment
        self.w.gh.remove_label(self.first, st.LABEL)
        comments = self.w.gh.issues[self.first]["comments"]
        comments[:] = [c for c in comments if st.START_RECEIPT_MARKER not in c["body"]]
        self.assertEqual(self.step().action, st.BLOCKED)
        self.assertEqual(labeled_events(self.w, self.first), 1)


class CapacityAndQuotaTests(Base):
    def test_concurrency_limit_defers(self):
        self.make()
        s = self.step(active_tasks=[{"issue": 1, "correlation_id": "other"}])
        self.assertEqual((s.action, s.scope), (st.DEFER, "global"))

    def test_confirmed_quota_exhaustion_defers_until_reset(self):
        self.make()
        reset = st._fmt(self.w.now + timedelta(hours=2))
        s = self.step(quota={"state": st.QUOTA_EXHAUSTED, "reset_at": reset})
        self.assertEqual((s.action, s.retry_after), (st.DEFER, reset))
        later = st._fmt(self.w.now + timedelta(hours=3))
        self.assertEqual(self.step(quota={"state": st.QUOTA_EXHAUSTED, "reset_at": reset}, now=later).action,
                         st.WRITE_INTENT)
        self.assertEqual(self.step(quota={"state": st.QUOTA_EXHAUSTED}).action, st.DEFER)

    def test_unknown_quota_follows_policy_and_never_stops_the_campaign(self):
        self.make()
        self.assertEqual(self.step(quota={"state": st.QUOTA_UNKNOWN}).action, st.WRITE_INTENT)
        self.make(policy=st.make_policy(on_quota_unknown="defer"))
        s = self.step(quota={"state": st.QUOTA_UNKNOWN})
        self.assertEqual(s.action, st.DEFER)
        self.assertNotEqual(s.action, st.HARD_STOP)

    def test_campaign_round_limit(self):
        self.make(policy=st.make_policy(max_campaign_rounds=1))
        self.assertEqual(self.step().action, st.WRITE_INTENT)  # seq 1 is within the limit
        c2 = sw.campaign("cb", 3, policy=st.make_policy(max_campaign_rounds=1))
        entry = st.validate_campaign(c2)[2]
        snap = {**self.w.snapshot(self.first, None, "ca")}
        snap["candidate"] = {**snap["candidate"], "title": entry["title"], "body": entry["body"]}
        self.assertNotEqual(st.next_step(snap, campaign=c2, controller="x").action, st.WRITE_INTENT)

    def test_policy_values_are_configurable_and_validated(self):
        self.assertEqual(st.validate_policy(st.make_policy(max_concurrent_tasks=3, intent_lease_minutes=5,
                                                           max_campaign_rounds=50)), [])
        for bad in ({"max_concurrent_tasks": 0}, {"max_label_attempts": True}, {"max_campaign_rounds": 0},
                    {"on_quota_unknown": "stop"}, {"trusted_writers": []}):
            with self.subTest(bad=bad):
                self.assertTrue(st.validate_policy(st.make_policy(**bad)))


class RecoveryTests(Base):
    def run_until_started(self, max_runs=12, step_minutes=20):
        for k in range(max_runs):
            self.w.run_controller(self.first, controller=f"restart-{k}")
            _, receipts = st.starter_records(self.w.gh.issues[self.first]["comments"], {sw.OWNER})
            if receipts:
                return k
            self.w.tick(step_minutes)
        self.fail("never started")

    def check_once(self):
        self.assertEqual(labeled_events(self.w, self.first), 1)
        _, receipts = st.starter_records(self.w.gh.issues[self.first]["comments"], {sw.OWNER})
        self.assertGreaterEqual(len(receipts), 1)

    def test_crash_before_intent(self):
        self.make()
        self.w.gh.inject("comment", "crash_before", issue=self.first)
        self.assertIsNone(self.w.run_controller(self.first))
        self.assertEqual(self.run_until_started(), 0)
        self.check_once()

    def test_crash_after_intent_waits_for_lease_then_takes_over(self):
        self.make()
        self.w.gh.inject("comment", "crash_after", issue=self.first)
        self.assertIsNone(self.w.run_controller(self.first))
        res = self.w.run_controller(self.first, controller="fresh")
        self.assertEqual(res.steps[-1].action, st.DEFER)            # owner may still be alive
        self.assertEqual(labeled_events(self.w, self.first), 0)
        self.w.tick(20)
        res = self.w.run_controller(self.first, controller="fresh2")
        self.assertEqual([s.action for s in res.steps][:2], [st.WRITE_INTENT, st.WRITE_LABEL])
        intents, _ = st.starter_records(self.w.gh.issues[self.first]["comments"], {sw.OWNER})
        self.assertEqual([i["attempt"] for i in intents], [1, 2])
        self.check_once()

    def test_intent_response_lost(self):
        self.make()
        self.w.gh.inject("comment", "lost", issue=self.first)
        res = self.w.run_controller(self.first)
        self.assertEqual(res.stopped, st.DEFER)
        self.run_until_started()
        self.check_once()

    def test_label_write_response_lost_is_recovered_by_readback(self):
        self.make()
        self.w.gh.inject("label", "lost", issue=self.first)
        res = self.w.run_controller(self.first)
        self.assertEqual(res.writes[-1], (st.WRITE_LABEL + "?", self.first))
        res = self.w.run_controller(self.first, controller="restart")
        self.assertEqual(res.steps[0].action, st.WRITE_START_RECEIPT)  # label seen: no second label write
        self.check_once()

    def test_label_timeout_unapplied_is_retried_only_after_lease_as_a_new_attempt(self):
        self.make()
        self.w.gh.inject("label", "timeout_unapplied", issue=self.first)
        self.w.run_controller(self.first)
        self.assertEqual(labeled_events(self.w, self.first), 0)
        self.assertEqual(self.w.run_controller(self.first, controller="r1").steps[-1].action, st.DEFER)
        self.run_until_started()
        self.check_once()

    def test_restart_just_before_label(self):
        self.make()
        self.w.gh.inject("label", "crash_before", issue=self.first)
        self.assertIsNone(self.w.run_controller(self.first))
        self.run_until_started()
        self.check_once()

    def test_crash_after_label_before_receipt(self):
        self.make()
        self.w.gh.inject("label", "crash_after", issue=self.first)
        self.assertIsNone(self.w.run_controller(self.first))
        res = self.w.run_controller(self.first, controller="fresh")
        self.assertEqual(res.steps[0].action, st.WRITE_START_RECEIPT)
        self.check_once()

    def test_repeated_invisible_labels_back_off_and_escalate_but_never_drop_the_task(self):
        self.make(policy=st.make_policy(max_label_attempts=2))
        for _ in range(3):
            self.w.gh.inject("label", "timeout_unapplied", issue=self.first)
        seen = []
        for k in range(30):
            self.w.run_controller(self.first, controller=f"r{k}")
            seen.append(self.step())
            self.w.tick(10)
        unhealthy = [s for s in seen if s.code == "WRITE_PATH_UNHEALTHY"]
        self.assertTrue(unhealthy and all(s.action == st.DEFER and s.human_required for s in unhealthy))
        self.assertEqual(labeled_events(self.w, self.first), 1)            # started once the path recovered
        intents, receipts = st.starter_records(self.w.gh.issues[self.first]["comments"], {sw.OWNER})
        self.assertEqual([i["attempt"] for i in intents], [1, 2, 3, 4])    # backoff: no intent spam
        self.assertEqual(len(receipts), 1)

    def test_two_controllers_racing_one_wins(self):
        self.make()
        a = self.step(controller="A")
        b = self.step(controller="B")
        self.w.gh.comment(self.first, a.body)
        self.w.gh.comment(self.first, b.body)
        snap = self.w.snapshot(self.first, None, "ca")
        sa = st.next_step(snap, campaign=self.c, controller="A", session_nonces=frozenset({a.nonce}))
        sb = st.next_step(snap, campaign=self.c, controller="B", session_nonces=frozenset({b.nonce}))
        self.assertEqual((sa.action, sb.action), (st.WRITE_LABEL, st.DEFER))

    def test_stale_controller_after_takeover_cannot_double_start(self):
        self.make()
        a = self.step(controller="A")
        self.w.gh.comment(self.first, a.body)
        stale_snapshot = self.w.snapshot(self.first, None, "ca")   # A reads, then pauses
        self.w.tick(30)
        self.w.run_controller(self.first, controller="B")         # B takes over and starts
        self.check_once()
        # A wakes up with its old view: its decision would be WRITE_LABEL ...
        sa = st.next_step(stale_snapshot, campaign=self.c, controller="A", session_nonces=frozenset({a.nonce}))
        self.assertEqual(sa.action, st.WRITE_LABEL)
        self.w.gh.starter_label(self.first, st.LABEL)              # ... and the write lands on a labeled issue
        self.assertEqual(labeled_events(self.w, self.first), 1)    # no second labeled event, no second task
        res = self.w.run_controller(self.first, controller="A")    # a fresh read stops it
        self.assertEqual(res.steps[-1].action, st.NO_OP)

    def test_duplicate_events_after_restart(self):
        self.make()
        self.w.gh.inject("label", "crash_after", issue=self.first)
        self.w.run_controller(self.first)
        receipt_event = {"name": "issue_comment.created", "issue": self.seed, "author": sw.OWNER,
                         "body": self.w.gh.issues[self.seed]["comments"][-1]["body"]}
        for _ in range(4):
            self.w.starter_wake(receipt_event)
            self.w.starter_wake({"name": "issues.opened", "issue": self.first})
        self.check_once()

    def test_issue_edited_after_intent(self):
        self.make()
        a = self.step(controller="A")
        self.w.gh.comment(self.first, a.body)
        issue = self.w.gh.issues[self.first]
        issue["body"] = issue["body"].replace("regression test added", "no test")
        snap = self.w.snapshot(self.first, None, "ca")
        self.assertEqual(st.next_step(snap, campaign=self.c, controller="A",
                                      session_nonces=frozenset({a.nonce})).action, st.BLOCKED)
        self.assertEqual(labeled_events(self.w, self.first), 0)


class WakeTests(unittest.TestCase):
    def test_wake_routing(self):
        body = review.RECEIPT_MARKER + "\n" + json.dumps({"verdict": "PASS", "next_issue": 12}) + "\n-->"
        self.assertEqual(st.wake_targets({"name": "issues.opened", "issue": 3}, trusted=["o"]), [{"issue": 3}])
        self.assertEqual(st.wake_targets({"name": "issue_comment.created", "issue": 5, "author": "o", "body": body},
                                         trusted=["o"]), [{"issue": 12, "predecessor": 5}])
        self.assertEqual(st.wake_targets({"name": "issue_comment.created", "issue": 5, "author": "x", "body": body},
                                         trusted=["o"]), [])
        fail = body.replace("PASS", "NEEDS_CORRECTION")
        self.assertEqual(st.wake_targets({"name": "issue_comment.created", "issue": 5, "author": "o", "body": fail},
                                         trusted=["o"]), [])
        self.assertEqual(st.wake_targets({"name": "pull_request.opened", "pr": 9}, trusted=["o"]), [])
        self.assertEqual(st.wake_targets({"name": "issues.labeled", "issue": 3, "label": "bug"}, trusted=["o"]), [])
        self.assertEqual(st.wake_targets({"name": "schedule"}, trusted=["o"]), [{"issue": "ALL_OPEN_CANDIDATES"}])
        broken = review.RECEIPT_MARKER + "\n{oops\n-->"
        self.assertEqual(st.wake_targets({"name": "issue_comment.created", "issue": 5, "author": "o",
                                          "body": broken}, trusted=["o"]), [])


class RecordAndManifestTests(unittest.TestCase):
    def test_records_round_trip_and_reject_extra_keys(self):
        c = sw.campaign("cr", 2)
        self.assertEqual(len(st.validate_campaign(c)), 2)
        with self.assertRaises(ValueError):
            st.render_intent({"profile": st.INTENT_PROFILE})

    def test_manifest_next_task_is_a_pinned_reference_not_a_nested_body(self):
        c = sw.campaign("cn", 3)
        entries = st.validate_campaign(c)
        ref = entries[1]["task"]["next_task"]["body_ref"]
        self.assertEqual((ref["seq"], ref["task_sha256"]), (2, entries[2]["task_sha256"]))
        self.assertNotIn("next_task", entries[3]["task"])
        self.assertEqual(entries[2]["task"]["campaign"]["predecessor"]["correlation_id"],
                         entries[1]["task"]["correlation_id"])
        self.assertEqual(entries[1]["body"].count(st.TASK_MARKER), 1)

    def test_render_next_returns_the_pinned_body_or_refuses(self):
        c = sw.campaign("cv", 3)
        entries = st.validate_campaign(c)
        ref = entries[1]["task"]["next_task"]["body_ref"]
        out = st.render_next(c, seq=ref["seq"], expected_sha256=ref["task_sha256"])
        self.assertEqual(out, {"title": entries[2]["title"], "body": entries[2]["body"]})
        with self.assertRaises(ValueError):
            st.render_next(c, seq=2, expected_sha256="0" * 64)
        with self.assertRaises(ValueError):
            st.render_next(c, seq=9, expected_sha256=ref["task_sha256"])

    def test_cli_step_and_validate(self):
        import contextlib
        import io
        import os
        import tempfile
        w = sw.World([sw.campaign("cl", 2)])
        seed, first = sw.seed_predecessor(w, w.campaigns["cl"])
        with tempfile.TemporaryDirectory() as d:
            cp, sp = os.path.join(d, "c.json"), os.path.join(d, "s.json")
            with open(cp, "w", encoding="utf-8") as fh:
                json.dump(w.campaigns["cl"], fh)
            with open(sp, "w", encoding="utf-8") as fh:
                json.dump(w.snapshot(first, None, "cl"), fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(st.main(["step", "--campaign", cp, "--snapshot", sp, "--controller", "cli"]), 0)
            first_step = json.loads(out.getvalue())
            self.assertEqual(first_step["action"], st.WRITE_INTENT)
            w.gh.comment(first, first_step["body"])
            with open(sp, "w", encoding="utf-8") as fh:
                json.dump(w.snapshot(first, None, "cl"), fh)
            for extra, expected in (([], st.DEFER), (["--session-nonce", first_step["nonce"]], st.WRITE_LABEL),
                                    (["--session-nonce", first_step["nonce"], "--label-written-nonce",
                                      first_step["nonce"]], st.DEFER)):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    st.main(["step", "--campaign", cp, "--snapshot", sp, "--controller", "cli", *extra])
                self.assertEqual(json.loads(out.getvalue())["action"], expected, extra)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(st.main(["validate-campaign", "--campaign", cp]), 0)
            self.assertEqual(json.loads(out.getvalue())["tasks"], 2)


if __name__ == "__main__":
    unittest.main()
