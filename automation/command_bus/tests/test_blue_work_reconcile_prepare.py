import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from automation.command_bus.blue_jules_result_event import EventLineage
from automation.command_bus.blue_work_wake_prepare import CarrierSnapshot
from automation.command_bus.blue_work_reconcile_prepare import (
    PREFIX, RECEIPT_PREFIX, assess_blue_review, prepare_reconciled_wake,
    prepare_result_review_request,
)
from automation.command_bus.reviewer import ReviewerLedger, validate_review_request

FIXTURE = Path(__file__).parent / "fixtures/blue_work_reconcile/input.json"


class BlueReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.inputs = json.loads(FIXTURE.read_text())
        self.now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)

    def prepare(self, **changes):
        inputs = copy.deepcopy(self.inputs)
        inputs.update(changes)
        inputs["lineage"] = EventLineage(**inputs["lineage"])
        inputs["protocol"] = CarrierSnapshot(**inputs["protocol"])
        return prepare_reconciled_wake(**inputs, now=self.now)

    def command(self):
        return json.loads(self.prepare().review_body.split("\n", 1)[1])

    def review(self, command=None):
        return {"id": 42, "state": "COMMENTED", "body": self.body(command or self.command())}

    @staticmethod
    def body(command):
        return PREFIX + "\n" + json.dumps(command)

    def receipt(self, **changes):
        command = self.command()
        r = {"protocol_version": 1, "command_id": command["command_id"], "worker_generation": 1,
             "status": "PASS", "target_repository": command["target_repository"],
             "target_pr": command["target_pr"], "target_branch": command["target_branch"],
             "target_head_before": command["expected_target_head"],
             "target_head_after": command["expected_target_head"], "terminal": True,
             "verification": ["fixture only"]}
        r.update(changes)
        return {"id": 77, "body": RECEIPT_PREFIX + "\n" + json.dumps(r)}

    def assess(self, command=None, **changes):
        c = command or self.command()
        args = dict(body=self.body(c), active_generation=1, fixed_generation=1,
                    current_target={k: c.get(k) for k in ("target_repository", "target_pr", "target_branch", "expected_target_head")},
                    reviews=[self.review(c)], comments=[], records_complete=True, now=self.now)
        args.update(changes)
        return assess_blue_review(**args)

    def test_round_trip_uses_result_head_branch_and_current_generation(self):
        plan = self.prepare()
        self.assertEqual(plan.status, "PREPARED")
        self.assertEqual(plan.carrier_pr, 167)
        command = self.command()
        self.assertEqual(command["target_branch"], "jules-result/fixture")
        self.assertNotEqual(command["target_branch"], self.inputs["lineage"]["work_branch"])
        self.assertEqual(self.assess(command).purpose, "JULES_RESULT_REVIEW")
        self.assertEqual(self.assess(command).status, "VALIDATED")
        self.assertEqual(self.prepare(reviews=[self.review()], comments=[self.receipt()]).status, "NO_OP")
        self.assertEqual(self.assess(comments=[self.receipt()]).status, "NO_OP")

    def test_existing_review_deduplicates_even_when_expired(self):
        c = self.command()
        c["expires_at"] = "2026-09-01T12:00:00Z"
        self.assertEqual(self.prepare(reviews=[self.review(c)]).status, "NO_OP")

    def test_all_terminal_statuses_prevent_replay(self):
        for status in ("PASS", "FAIL", "BLOCKED", "UNKNOWN", "STALE", "NO_OP"):
            with self.subTest(status=status):
                self.assertEqual(self.prepare(reviews=[self.review()], comments=[self.receipt(status=status)]).status, "NO_OP")

    def test_chat_command_and_result_request_share_prefix_without_rewriting_chat_task(self):
        c = self.command()
        c.update(command_id="blue-chat-fixture", task="Inspect docs only.", allowed_paths=["docs/example.md"])
        before = copy.deepcopy(c)
        self.assertEqual(self.assess(c).purpose, "CHAT_REQUEST")
        self.assertEqual(self.assess(c).status, "VALIDATED")
        self.assertEqual(c, before)
        self.assertEqual(self.prepare(reviews=[self.review(c)]).status, "PREPARED")

    def test_different_lane_receipt_and_command_do_not_route_to_blue(self):
        self.assertEqual(self.assess(body="[CW_GREEN_V1]\n{}").status, "NO_OP")
        self.assertEqual(self.prepare(comments=[{"body": "[CW_GREEN_RECEIPT_V1]\n{}"}]).status, "PREPARED")

    def test_delayed_event_with_moved_head_is_stale(self):
        pr = copy.deepcopy(self.inputs["result_pr"])
        pr["head"]["sha"] = "b" * 40
        self.assertEqual(self.prepare(result_pr=pr).status, "STALE")

    def test_new_head_has_new_logical_identity(self):
        event = copy.deepcopy(self.inputs["event"])
        pr = copy.deepcopy(self.inputs["result_pr"])
        event["action"] = "synchronize"
        event["pull_request"]["head"]["sha"] = pr["head"]["sha"] = "b" * 40
        plan = self.prepare(event=event, result_pr=pr, reviews=[self.review()])
        self.assertEqual(plan.status, "PREPARED")
        self.assertNotEqual(plan.command_id, self.prepare().command_id)

    def test_carrier_head_change_is_allowed_and_not_compared_to_result_head(self):
        carrier = copy.deepcopy(self.inputs["carrier_pr"])
        carrier["head"]["sha"] = "f" * 40
        self.assertEqual(self.prepare(carrier_pr=carrier).review_body, self.prepare().review_body)

    def test_incomplete_paginated_readback_blocks_preparation_and_worker(self):
        for complete in (False, None, "true", 1):
            with self.subTest(complete=complete):
                self.assertEqual(self.prepare(records_complete=complete).status, "UNKNOWN")
                self.assertEqual(self.assess(records_complete=complete).status, "UNKNOWN")

    def test_unreadable_and_malformed_records_fail_closed(self):
        for reviews, comments in ((None, []), ([], None), ([None], []),
                                  ([{"body": PREFIX + "\n{}", "id": 1, "state": "COMMENTED"}], []),
                                  ([], [{"body": RECEIPT_PREFIX + "\n{}"}])):
            with self.subTest(reviews=reviews, comments=comments):
                self.assertEqual(self.prepare(reviews=reviews, comments=comments).status, "UNKNOWN")

    def test_duplicate_json_keys_are_rejected(self):
        self.assertEqual(self.assess(body=PREFIX + '\n{"command_id":"one","command_id":"two"}').status, "UNKNOWN")

    def test_pending_or_approval_review_is_not_a_command(self):
        for state in ("PENDING", "APPROVED", "CHANGES_REQUESTED", None):
            r = self.review()
            r["state"] = state
            self.assertEqual(self.prepare(reviews=[r]).status, "UNKNOWN")

    def test_carrier_state_protocol_fences(self):
        for key, value in (("active_generation", True), ("active_generation", 0),
                           ("active_generation", 2), ("carrier_pr", 166),
                           ("carrier_branch", "other"), ("lane", "red"), ("schema_version", True)):
            with self.subTest(key=key):
                s = dict(self.inputs["worker_state"])
                s[key] = value
                self.assertEqual(self.prepare(worker_state=s).status, "UNKNOWN")

    def test_generation_cutover_prepares_new_generation_only_with_matching_protocol(self):
        state = dict(self.inputs["worker_state"], active_generation=2)
        protocol = dict(self.inputs["protocol"], worker_generation=2)
        plan = self.prepare(worker_state=state, protocol=protocol)
        self.assertEqual(json.loads(plan.review_body.split("\n", 1)[1])["worker_generation"], 2)

    def test_stale_worker_silent_noop_precedes_unreadable_command(self):
        self.assertEqual(self.assess(body=None, fixed_generation=2, comments=None).status, "NO_OP")

    def test_stale_command_generation(self):
        c = self.command()
        c["worker_generation"] = 2
        self.assertEqual(self.assess(c).status, "STALE")

    def test_expired_equal_naive_time_cases(self):
        for expiry in ("2026-10-01T12:00:00Z", "2026-09-01T12:00:00Z"):
            self.assertEqual(self.prepare(expires_at=expiry).status, "UNKNOWN")
            c = self.command()
            c["expires_at"] = expiry
            self.assertEqual(self.assess(c).status, "STALE")
        self.assertEqual(self.assess(now=self.now.replace(tzinfo=None)).status, "UNKNOWN")

    def test_reserved_result_contract_cannot_turn_into_write_or_dispatch(self):
        for key, value in (("task", "Start Jules now"), ("allowed_paths", ["automation/*"]),
                           ("verification", ["Skip verification"]), ("command_id", "blue-jules-result-bad"),
                           ("target_pr", 99), ("expected_target_head", "b" * 40)):
            with self.subTest(key=key):
                c = self.command()
                c[key] = value
                self.assertEqual(self.assess(c).status, "UNKNOWN")

    def test_missing_command_fields_and_unsafe_policies(self):
        c = self.command()
        for key in c:
            bad = dict(c)
            del bad[key]
            self.assertEqual(self.assess(bad).status, "UNKNOWN", key)
        for key, value in (("protocol_version", True), ("retry", False), ("retry", 1),
                           ("fallback", "enabled"), ("live_provider_or_model_allowed", True),
                           ("worker_generation", True), ("target_pr", True)):
            bad = dict(c)
            bad[key] = value
            self.assertEqual(self.assess(bad).status, "UNKNOWN", key)

    def test_result_pr_fork_closed_identity_and_lineage_checks(self):
        for mutate in (lambda p: p.update(state="closed"), lambda p: p.update(merged=True),
                       lambda p: p.update(number=167), lambda p: p.update(number=True),
                       lambda p: p["base"].update(sha="b" * 40),
                       lambda p: p["head"]["repo"].update(full_name="fork/repo")):
            p = copy.deepcopy(self.inputs["result_pr"])
            mutate(p)
            self.assertEqual(self.prepare(result_pr=p).status, "UNKNOWN")

    def test_invalid_carrier_closed_missing_label_and_repo(self):
        for mutate in (lambda p: p.update(state="closed"), lambda p: p.update(merged=True),
                       lambda p: p.update(labels=[]), lambda p: p["head"]["repo"].update(full_name="other/repo")):
            p = copy.deepcopy(self.inputs["carrier_pr"])
            mutate(p)
            self.assertEqual(self.prepare(carrier_pr=p).status, "UNKNOWN")

    def test_unsafe_result_branch_and_missing_head(self):
        for branch in ("main", "master", "../x", "refs/heads/x", "x\ny", ""):
            p = copy.deepcopy(self.inputs["result_pr"])
            p["head"]["ref"] = branch
            self.assertEqual(self.prepare(result_pr=p).status, "UNKNOWN")

    def test_malformed_receipt_is_unknown_never_success(self):
        for changes in ({"terminal": False}, {"status": "COMPLETE"}, {"target_pr": True},
                        {"worker_generation": True}, {"target_head_after": None}):
            self.assertEqual(self.assess(comments=[self.receipt(**changes)]).status, "UNKNOWN")

    def test_receipt_must_match_submitted_command_and_reserved_read_only_head(self):
        command = self.command()
        tampering = (
            {"target_repository": "other/repo"},
            {"target_pr": command["target_pr"] + 1},
            {"target_branch": "another/result-branch"},
            {"target_head_before": "b" * 40},
            {"target_head_after": "b" * 40},
            {"worker_generation": 2},
            {"protocol_version": 2},
        )
        for changes in tampering:
            with self.subTest(changes=changes):
                receipt = self.receipt(**changes)
                self.assertEqual(self.prepare(reviews=[self.review(command)], comments=[receipt]).status, "UNKNOWN")
                self.assertEqual(self.assess(command, comments=[receipt]).status, "UNKNOWN")

    def test_terminal_receipt_without_submitted_command_or_with_duplicate_is_unknown(self):
        receipt = self.receipt()
        self.assertEqual(self.prepare(comments=[receipt]).status, "UNKNOWN")
        self.assertEqual(self.assess(reviews=[], comments=[receipt]).status, "UNKNOWN")
        self.assertEqual(self.assess(comments=[receipt, receipt]).status, "UNKNOWN")

    def test_changed_worker_target_is_stale_and_wrong_identity_is_unknown(self):
        target = {k: self.command()[k] for k in ("target_repository", "target_pr", "target_branch", "expected_target_head")}
        target["expected_target_head"] = "b" * 40
        self.assertEqual(self.assess(current_target=target).status, "STALE")
        target["target_pr"] = 99
        self.assertEqual(self.assess(current_target=target).status, "UNKNOWN")

    def test_reconciliation_deterministic_and_does_not_mutate_snapshots(self):
        before = copy.deepcopy(self.inputs)
        self.assertEqual(self.prepare(), self.prepare())
        self.assertEqual(self.inputs, before)

    def test_prepare_existing_durable_review_contract_without_jules_command(self):
        request = prepare_result_review_request(self.prepare(), target_tree="d" * 40,
                                                evidence_refs=["fixture://diff", "fixture://tests"],
                                                expires_at=self.inputs["expires_at"], now=self.now)
        validate_review_request(request)
        ledger = ReviewerLedger()
        ledger.append_request(request)
        self.assertEqual(len(ledger.requests), 1)
        self.assertEqual(request["expected_target_head"], "a" * 40)
        self.assertEqual(request["expected_target_tree"], "d" * 40)
        self.assertEqual(request["retry"], 0)
        self.assertNotIn("work_branch", request)

    def test_review_requires_exact_tree_evidence_and_bounded_expiry(self):
        for tree, refs, expiry in (("bad", ["x"], self.inputs["expires_at"]),
                                   ("d" * 40, [], self.inputs["expires_at"]),
                                   ("d" * 40, ["x"], "2026-10-01T14:00:00Z")):
            with self.assertRaises(ValueError):
                prepare_result_review_request(self.prepare(), target_tree=tree, evidence_refs=refs, expires_at=expiry, now=self.now)

    def test_missing_conflicting_or_duplicate_command_readback_blocks_worker(self):
        c = self.command()
        conflict = dict(c, expires_at="2026-10-01T12:30:00Z")
        for reviews in ([], [self.review(conflict)], [self.review(c), self.review(c)]):
            self.assertEqual(self.assess(c, reviews=reviews).status, "UNKNOWN")

    def test_legacy_unrelated_smoke_identity_does_not_grant_generation_or_block_new_work(self):
        old = self.command()
        old.update(command_id="blue-fixed-carrier-smoke-001-20260930", task="Read-only old smoke.")
        del old["worker_generation"]
        old_receipt = self.receipt()["body"].split("\n", 1)[1]
        old_receipt = json.loads(old_receipt)
        old_receipt["command_id"] = old["command_id"]
        del old_receipt["worker_generation"]
        comments = [{"body": RECEIPT_PREFIX + "\n" + json.dumps(old_receipt)}]
        self.assertEqual(self.prepare(reviews=[self.review(old)], comments=comments).status, "PREPARED")
        self.assertEqual(self.assess(reviews=[self.review(), self.review(old)], comments=comments).status, "VALIDATED")
        self.assertEqual(self.assess(old, comments=comments).status, "UNKNOWN")

    def test_chat_paths_do_not_escape_repository(self):
        c = self.command()
        c.update(command_id="blue-chat-fixture", task="Inspect docs.")
        for path in ("../secret", "/tmp/file", "./path", "a\\b"):
            c["allowed_paths"] = [path]
            self.assertEqual(self.assess(c).status, "UNKNOWN")

    def test_review_request_rejects_forged_plan_and_expired_preparation(self):
        for plan in (replace(self.prepare(), command_id="other"), replace(self.prepare(), carrier_pr=None)):
            with self.assertRaises(ValueError):
                prepare_result_review_request(plan, target_tree="d" * 40, evidence_refs=["x"],
                                              expires_at=self.inputs["expires_at"], now=self.now)
        with self.assertRaises(ValueError):
            prepare_result_review_request(self.prepare(), target_tree="d" * 40, evidence_refs=["x"],
                                          expires_at=self.now.isoformat(), now=self.now)


if __name__ == "__main__":
    unittest.main()
