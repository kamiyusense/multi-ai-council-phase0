from datetime import datetime, timedelta, timezone
import json
import unittest

from automation.command_bus.reviewer import (
    ReviewerLedger, claim_request, consume_response, make_request,
    request_review, submit_response,
)
from automation.command_bus.state_machine import StateMachine

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()


def loop_state(**changes):
    value = {"schema_version": 1, "loop_id": "loop-1", "state": "RUNNING",
             "round": 0, "max_rounds": 6, "expires_at": EXP,
             "stop_requested": False, "last_command_id": None,
             "last_receipt_id": None, "expected_target": "work",
             "retry_policy": 0}
    value.update(changes)
    return value


class ReviewerRoleTests(unittest.TestCase):
    def setUp(self):
        self.ledger = ReviewerLedger()
        self.ledger.append_request(make_request(
            request_id="req-1", loop_id="loop-1", round=1,
            correlation_id="loop-1-round-1", expected_target_head="head-a",
            expires_at=EXP))

    def claim(self, generation=1, instance="reviewer-a", expires_at=None, at=NOW, state=None):
        return claim_request(self.ledger, "req-1", claim_id=f"claim-{generation}",
                             reviewer_instance_id=instance, reviewer_generation=generation,
                             claimed_at=at, expires_at=expires_at, state=state)

    def respond(self, state=None, **changes):
        data = dict(response_id="resp-1", reviewer_instance_id="reviewer-a",
                    reviewer_generation=1, decision="APPROVE", evidence_refs=["ev-1"],
                    loop_id="loop-1", round=1, correlation_id="loop-1-round-1",
                    expected_target_head="head-a", submitted_at=NOW)
        data.update(changes)
        return submit_response(self.ledger, "req-1", state=state, **data)

    def consume(self, ledger=None, state=None, now=NOW):
        return consume_response(ledger or self.ledger, "req-1", loop_id="loop-1",
                                round=1, correlation_id="loop-1-round-1",
                                expected_target_head="head-a", now=now, state=state)

    def test_request_claim_response_and_consume_without_thread_id(self):
        self.assertEqual(self.claim().status, "CLAIMED")
        self.assertEqual(self.respond().status, "ACCEPTED")
        self.assertEqual(self.consume().status, "VALID")

    def test_only_one_active_claim_and_exchange_after_expiry(self):
        old_expiry = (NOW + timedelta(seconds=1)).isoformat()
        self.assertEqual(self.claim(expires_at=old_expiry).status, "CLAIMED")
        self.assertEqual(self.claim(generation=2, instance="reviewer-b").status, "BLOCKED")
        self.assertEqual(self.claim(generation=2, instance="reviewer-b",
                                    at=NOW + timedelta(seconds=2)).status, "CLAIMED")
        self.assertEqual(submit_response(
            self.ledger, "req-1", response_id="resp-2",
            reviewer_instance_id="reviewer-b", reviewer_generation=2,
            decision="APPROVE", evidence_refs=["ev-2"], loop_id="loop-1", round=1,
            correlation_id="loop-1-round-1", expected_target_head="head-a",
            submitted_at=NOW + timedelta(seconds=2)).status, "ACCEPTED")

    def test_stale_claim_wrong_correlation_and_target_head_fail_closed(self):
        self.assertEqual(self.claim().status, "CLAIMED")
        self.assertEqual(self.respond(reviewer_generation=0).status, "BLOCKED")
        self.assertEqual(self.respond(response_id="resp-2", correlation_id="wrong").status, "BLOCKED")
        self.assertEqual(self.respond(response_id="resp-3", expected_target_head="head-b").status, "BLOCKED")
        self.assertEqual(self.respond(response_id="resp-4", round=2).status, "BLOCKED")
        self.assertEqual(self.respond(response_id="resp-5", loop_id="wrong-loop").status, "BLOCKED")

    def test_already_expired_claim_rejected_at_claim_time(self):
        result = self.claim(expires_at=(NOW - timedelta(seconds=1)).isoformat())
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("claim expires", result.reason)
        self.assertEqual(self.ledger.claims, [])

    def test_claim_cannot_outlive_request(self):
        request_expiry = datetime.fromisoformat(EXP) + timedelta(seconds=1)
        result = self.claim(expires_at=request_expiry.isoformat())
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("after review request", result.reason)

    def test_request_expiry_blocks_submit(self):
        self.assertEqual(self.claim().status, "CLAIMED")
        result = self.respond(submitted_at=NOW + timedelta(hours=2))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("expired", result.reason)

    def test_duplicate_response_and_receipt_replay_are_noop(self):
        self.claim(); self.assertEqual(self.respond().status, "ACCEPTED")
        self.assertEqual(self.respond().status, "NO-OP")
        self.assertEqual(self.consume().status, "VALID")
        self.assertEqual(self.consume().status, "NO-OP")

    def test_missing_empty_and_malformed_response_are_unknown_without_crash(self):
        self.assertEqual(self.consume().status, "UNKNOWN")
        self.claim(); self.assertEqual(self.respond(decision="", evidence_refs=[]).status, "ACCEPTED")
        self.assertEqual(self.consume().status, "UNKNOWN")
        self.ledger.responses[0]["decision"] = {"not": "a string"}
        self.assertEqual(self.consume().status, "UNKNOWN")
        self.ledger.responses[0]["decision"] = "APPROVE"
        self.ledger.responses[0]["evidence_refs"] = ["ok", 7]
        self.assertEqual(self.consume().status, "UNKNOWN")
        self.ledger.responses[0]["round"] = "1"
        self.assertEqual(self.consume().status, "UNKNOWN")

    def test_stop_max6_and_global_expiry_gates(self):
        stopped = loop_state(stop_requested=True, state="HALTED")
        stopped_request = make_request(
            request_id="stop", loop_id="loop-1", round=1,
            correlation_id="loop-1-round-1", expected_target_head="head-a",
            expires_at=EXP)
        self.assertEqual(request_review(self.ledger, stopped_request, state=stopped, now=NOW).status, "BLOCKED")
        self.assertEqual(self.claim(state=stopped).status, "BLOCKED")
        self.assertEqual(self.respond(state=stopped).status, "BLOCKED")
        self.assertEqual(self.consume(state=stopped).status, "BLOCKED")
        maxed = loop_state(round=6)
        maxed_request = make_request(
            request_id="maxed", loop_id="loop-1", round=7,
            correlation_id="loop-1-round-7", expected_target_head="head-a",
            expires_at=EXP)
        self.assertEqual(request_review(self.ledger, maxed_request, state=maxed, now=NOW).status, "BLOCKED")
        self.assertEqual(self.claim(state=maxed).status, "BLOCKED")
        expired = loop_state(expires_at=(NOW - timedelta(seconds=1)).isoformat())
        self.assertEqual(self.consume(state=expired).status, "BLOCKED")
        self.assertEqual(expired["state"], "EXPIRED")

    def test_fresh_session_recovery_without_thread_id(self):
        state = loop_state()
        self.assertEqual(request_review(ReviewerLedger(), make_request(
            request_id="unused", loop_id="loop-1", round=1,
            correlation_id="loop-1-round-1", expected_target_head="head-a",
            expires_at=EXP), state=state, now=NOW).status, "REQUESTED")
        self.claim(); self.respond()
        serialized = json.dumps({"records": self.ledger.export_records(), "state": state})
        durable = json.loads(serialized)
        fresh = ReviewerLedger.from_records(durable["records"])
        fresh_state = durable["state"]
        self.assertEqual(self.consume(ledger=fresh, state=fresh_state).status, "VALID")

    def test_reviewer_replacement_after_recovery(self):
        self.assertEqual(self.claim(expires_at=(NOW + timedelta(seconds=1)).isoformat()).status, "CLAIMED")
        durable = json.loads(json.dumps({"records": self.ledger.export_records(), "state": loop_state()}))
        fresh = ReviewerLedger.from_records(durable["records"])
        replacement_at = NOW + timedelta(seconds=2)
        self.assertEqual(claim_request(
            fresh, "req-1", claim_id="claim-2", reviewer_instance_id="reviewer-b",
            reviewer_generation=2, claimed_at=replacement_at,
            state=durable["state"]).status, "CLAIMED")
        stale = claim_request(
            fresh, "req-1", claim_id="claim-stale", reviewer_instance_id="reviewer-a",
            reviewer_generation=1, claimed_at=replacement_at,
            state=durable["state"])
        self.assertEqual(stale.status, "BLOCKED")
        result = submit_response(
            fresh, "req-1", response_id="resp-2", reviewer_instance_id="reviewer-b",
            reviewer_generation=2, decision="APPROVE", evidence_refs=["ev-2"],
            loop_id="loop-1", round=1, correlation_id="loop-1-round-1",
            expected_target_head="head-a", submitted_at=replacement_at,
            state=durable["state"])
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(self.consume(ledger=fresh, state=durable["state"], now=replacement_at).status, "VALID")


if __name__ == "__main__":
    unittest.main()
