from datetime import datetime, timedelta, timezone
import unittest

from automation.command_bus.reviewer import ReviewerLedger, claim_request, consume_response, make_request, submit_response

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()


class ReviewerRoleTests(unittest.TestCase):
    def setUp(self):
        self.ledger = ReviewerLedger()
        self.ledger.append_request(make_request(request_id="req-1", loop_id="loop-1", round=1, correlation_id="loop-1-round-1", expected_target_head="head-a", expires_at=EXP))

    def claim(self, generation=1, instance="reviewer-a"):
        return claim_request(self.ledger, "req-1", claim_id=f"claim-{generation}", reviewer_instance_id=instance, reviewer_generation=generation, claimed_at=NOW)

    def respond(self, **changes):
        data = dict(response_id="resp-1", reviewer_instance_id="reviewer-a", reviewer_generation=1, decision="APPROVE", evidence_refs=["ev-1"], loop_id="loop-1", round=1, correlation_id="loop-1-round-1", expected_target_head="head-a", submitted_at=NOW)
        data.update(changes)
        return submit_response(self.ledger, "req-1", **data)

    def test_request_claim_response_and_consume_without_thread_id(self):
        self.assertEqual(self.claim().status, "CLAIMED")
        self.assertEqual(self.respond().status, "ACCEPTED")
        self.assertEqual(consume_response(self.ledger, "req-1", loop_id="loop-1", round=1, correlation_id="loop-1-round-1", expected_target_head="head-a").status, "VALID")

    def test_only_one_active_claim_and_exchange_after_expiry(self):
        self.assertEqual(self.claim().status, "CLAIMED")
        self.assertEqual(self.claim(generation=2, instance="reviewer-b").status, "BLOCKED")
        self.ledger.claims[0]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
        self.assertEqual(self.claim(generation=2, instance="reviewer-b").status, "CLAIMED")
        self.assertEqual(self.respond(reviewer_instance_id="reviewer-b", reviewer_generation=2).status, "ACCEPTED")

    def test_stale_claim_wrong_correlation_and_target_head_fail_closed(self):
        self.assertEqual(self.claim().status, "CLAIMED")
        self.assertEqual(self.respond(reviewer_generation=0).status, "BLOCKED")
        self.assertEqual(self.respond(response_id="resp-2", correlation_id="wrong").status, "BLOCKED")
        self.assertEqual(self.respond(response_id="resp-3", expected_target_head="head-b").status, "BLOCKED")
        self.assertEqual(self.respond(response_id="resp-4", round=2).status, "BLOCKED")
        self.assertEqual(self.respond(response_id="resp-5", loop_id="wrong-loop").status, "BLOCKED")

    def test_expired_claim_cannot_accept_response(self):
        result = claim_request(self.ledger, "req-1", claim_id="claim-expired",
                               reviewer_instance_id="reviewer-a", reviewer_generation=1,
                               claimed_at=NOW, expires_at=(NOW - timedelta(seconds=1)).isoformat())
        self.assertEqual(result.status, "CLAIMED")
        self.assertEqual(self.respond().status, "UNKNOWN")

    def test_duplicate_response_and_receipt_replay_are_noop(self):
        self.claim(); self.assertEqual(self.respond().status, "ACCEPTED")
        self.assertEqual(self.respond().status, "NO-OP")
        self.assertEqual(consume_response(self.ledger, "req-1", loop_id="loop-1", round=1, correlation_id="loop-1-round-1", expected_target_head="head-a").status, "VALID")
        self.assertEqual(consume_response(self.ledger, "req-1", loop_id="loop-1", round=1, correlation_id="loop-1-round-1", expected_target_head="head-a").status, "NO-OP")

    def test_missing_empty_wrong_round_and_expired_response_are_unknown(self):
        self.assertEqual(consume_response(self.ledger, "req-1", loop_id="loop-1", round=1, correlation_id="loop-1-round-1", expected_target_head="head-a").status, "UNKNOWN")
        self.claim(); self.assertEqual(self.respond(decision="", evidence_refs=[]).status, "ACCEPTED")
        self.assertEqual(consume_response(self.ledger, "req-1", loop_id="loop-1", round=1, correlation_id="loop-1-round-1", expected_target_head="head-a").status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
