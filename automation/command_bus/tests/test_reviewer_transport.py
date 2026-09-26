from datetime import datetime, timedelta, timezone
import unittest

from automation.command_bus.reviewer import (
    DURABLE_REVIEW_V2,
    ReviewerLedger,
    claim_request,
    consume_response,
    make_request_v2,
    submit_response,
)
from automation.command_bus.reviewer_transport import (
    MockReviewerTransport,
    ReviewWakeCoordinator,
    build_review_wake,
)

NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()
HEAD = "a" * 40
TREE = "b" * 40
LOOP = "hybrid-review-001"
REQ = "req-001"
REF = f"automation/command_bus/review_requests/{LOOP}/{REQ}.json"


def request(**changes):
    values = dict(
        request_id=REQ,
        loop_id=LOOP,
        round=1,
        correlation_id=f"{LOOP}-round-1",
        expected_target_head=HEAD,
        expected_target_tree=TREE,
        reviewer_role="semantic-reviewer",
        review_kind="RELAY_SAFETY_DIFF",
        evidence_refs=["evidence://relay-receipt"],
        allowed_decisions=["APPROVE", "CHANGES_REQUIRED", "UNKNOWN"],
        expires_at=EXP,
    )
    values.update(changes)
    return make_request_v2(**values)


class ReviewerTransportTests(unittest.TestCase):
    def test_supported_static_routes_share_same_durable_wake_contract(self):
        req = request()
        wake = build_review_wake(req, REF)
        self.assertEqual(wake["expected_target_head"], HEAD)
        self.assertEqual(wake["expected_target_tree"], TREE)
        self.assertEqual(wake["response_channel"], "GITHUB_DURABLE_ONLY")
        self.assertFalse(wake["parse_browser_output"])
        for route in ("browser", "direct", "manual", "scheduled"):
            transport = MockReviewerTransport(route)
            result = ReviewWakeCoordinator().dispatch(
                req, request_ref=REF, transport=transport
            )
            self.assertEqual(result.status, "SIMULATED")
            self.assertFalse(result.evidence["external_send_attempted"])
            self.assertFalse(result.evidence["live_model_started"])
            self.assertFalse(result.evidence["browser_ui_parsed"])
            self.assertTrue(result.evidence["durable_response_required"])
            self.assertEqual(len(transport.sent), 1)

    def test_wake_has_no_chat_thread_or_browser_session_correctness_identity(self):
        wake = build_review_wake(request(), REF)
        serialized = repr(wake).lower()
        self.assertNotIn("thread_id", serialized)
        self.assertNotIn("conversation_id", serialized)
        self.assertNotIn("browser_session_id", serialized)
        self.assertNotIn("chat_id", serialized)

    def test_v2_request_rejects_extra_session_identity(self):
        req = request()
        req["thread_id"] = "must-not-be-correctness"
        ledger = ReviewerLedger()
        with self.assertRaisesRegex(ValueError, "session identity"):
            ledger.append_request(req)

    def test_duplicate_wake_is_blocked_without_second_send(self):
        req = request()
        transport = MockReviewerTransport("browser")
        coordinator = ReviewWakeCoordinator()
        first = coordinator.dispatch(req, request_ref=REF, transport=transport)
        second = coordinator.dispatch(req, request_ref=REF, transport=transport)
        self.assertEqual(first.status, "SIMULATED")
        self.assertEqual(second.status, "BLOCKED")
        self.assertFalse(second.evidence["second_send_attempted"])
        self.assertEqual(len(transport.sent), 1)

    def test_live_capable_transport_is_blocked_in_static_p1(self):
        class LiveTransport:
            route = "browser"
            live_transport = True

            def __init__(self):
                self.sent = []

            def send(self, wake):
                self.sent.append(wake)
                raise AssertionError("live transport must not be called")

        transport = LiveTransport()
        result = ReviewWakeCoordinator().dispatch(
            request(), request_ref=REF, transport=transport
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertFalse(result.evidence["external_send_attempted"])
        self.assertEqual(transport.sent, [])

    def test_transport_exception_is_unknown_and_never_retried(self):
        class BrokenTransport:
            route = "browser"
            live_transport = False

            def __init__(self):
                self.calls = 0

            def send(self, wake):
                self.calls += 1
                raise RuntimeError("ambiguous browser failure")

        transport = BrokenTransport()
        coordinator = ReviewWakeCoordinator()
        first = coordinator.dispatch(request(), request_ref=REF, transport=transport)
        second = coordinator.dispatch(request(), request_ref=REF, transport=transport)
        self.assertEqual(first.status, "UNKNOWN")
        self.assertEqual(first.evidence["retry_count"], 0)
        self.assertEqual(first.evidence["external_send_attempted"], "UNKNOWN")
        self.assertEqual(second.status, "BLOCKED")
        self.assertEqual(transport.calls, 1)

    def test_bad_durable_request_ref_fails_closed_before_transport(self):
        transport = MockReviewerTransport("browser")
        result = ReviewWakeCoordinator().dispatch(
            request(),
            request_ref="automation/command_bus/review_requests/wrong/req.json",
            transport=transport,
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(transport.sent, [])

    def test_transport_revalidates_malformed_durable_request_before_send(self):
        malformed = request()
        malformed["retry"] = 1
        transport = MockReviewerTransport("browser")
        result = ReviewWakeCoordinator().dispatch(
            malformed, request_ref=REF, transport=transport
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.evidence["retry_count"], 0)
        self.assertEqual(transport.sent, [])

    def test_v2_happy_path_requires_tree_and_structured_response(self):
        ledger = ReviewerLedger()
        req = request()
        ledger.append_request(req)
        claim = claim_request(
            ledger, REQ, claim_id="claim-001",
            reviewer_instance_id="sol-reviewer",
            reviewer_generation=1,
            role="semantic-reviewer",
            capability="semantic-review",
            claimed_at=NOW,
        )
        self.assertEqual(claim.status, "CLAIMED")
        response = submit_response(
            ledger, REQ,
            response_id="resp-001",
            reviewer_instance_id="sol-reviewer",
            reviewer_generation=1,
            decision="APPROVE",
            evidence_refs=["evidence://relay-receipt", "evidence://diff"],
            loop_id=LOOP,
            round=1,
            correlation_id=f"{LOOP}-round-1",
            expected_target_head=HEAD,
            expected_target_tree=TREE,
            rationale_summary="Static Relay diff preserves the declared safety invariants.",
            next_command_proposal={"action": "STATIC_VALIDATE_COMMAND_BUS"},
            model_route_evidence={
                "route": "browser",
                "live_route_proven": False,
                "response_source": "GITHUB_DURABLE_ONLY",
            },
            submitted_at=NOW,
        )
        self.assertEqual(response.status, "ACCEPTED")
        consumed = consume_response(
            ledger, REQ,
            loop_id=LOOP,
            round=1,
            correlation_id=f"{LOOP}-round-1",
            expected_target_head=HEAD,
            expected_target_tree=TREE,
            now=NOW,
        )
        self.assertEqual(consumed.status, "VALID")
        receipt = ledger.receipts[0]
        self.assertEqual(receipt["review_profile"], DURABLE_REVIEW_V2)
        self.assertEqual(receipt["expected_target_tree"], TREE)

    def test_wrong_target_tree_is_rejected(self):
        ledger = ReviewerLedger()
        ledger.append_request(request())
        claim_request(
            ledger, REQ, claim_id="claim-001",
            reviewer_instance_id="sol-reviewer",
            reviewer_generation=1,
            role="semantic-reviewer",
            claimed_at=NOW,
        )
        result = submit_response(
            ledger, REQ,
            response_id="resp-001",
            reviewer_instance_id="sol-reviewer",
            reviewer_generation=1,
            decision="APPROVE",
            evidence_refs=["evidence://diff"],
            loop_id=LOOP,
            round=1,
            correlation_id=f"{LOOP}-round-1",
            expected_target_head=HEAD,
            expected_target_tree="c" * 40,
            rationale_summary="Wrong tree should fail.",
            next_command_proposal=None,
            model_route_evidence={"route": "browser"},
            submitted_at=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_disallowed_decision_is_rejected_at_submission(self):
        ledger = ReviewerLedger()
        ledger.append_request(request(allowed_decisions=["APPROVE"]))
        claim_request(
            ledger, REQ, claim_id="claim-001",
            reviewer_instance_id="sol-reviewer",
            reviewer_generation=1,
            role="semantic-reviewer",
            claimed_at=NOW,
        )
        result = submit_response(
            ledger, REQ,
            response_id="resp-001",
            reviewer_instance_id="sol-reviewer",
            reviewer_generation=1,
            decision="CHANGES_REQUIRED",
            evidence_refs=["evidence://diff"],
            loop_id=LOOP,
            round=1,
            correlation_id=f"{LOOP}-round-1",
            expected_target_head=HEAD,
            expected_target_tree=TREE,
            rationale_summary="Not permitted by this request.",
            next_command_proposal=None,
            model_route_evidence={"route": "browser"},
            submitted_at=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(ledger.responses, [])

    def test_nested_session_identity_in_response_is_rejected(self):
        ledger = ReviewerLedger()
        ledger.append_request(request())
        claim_request(
            ledger, REQ, claim_id="claim-001",
            reviewer_instance_id="sol-reviewer",
            reviewer_generation=1,
            role="semantic-reviewer",
            claimed_at=NOW,
        )
        result = submit_response(
            ledger, REQ,
            response_id="resp-001",
            reviewer_instance_id="sol-reviewer",
            reviewer_generation=1,
            decision="APPROVE",
            evidence_refs=["evidence://diff"],
            loop_id=LOOP,
            round=1,
            correlation_id=f"{LOOP}-round-1",
            expected_target_head=HEAD,
            expected_target_tree=TREE,
            rationale_summary="Session identity must not be correctness data.",
            next_command_proposal=None,
            model_route_evidence={"transport": {"browser_session_id": "forbidden"}},
            submitted_at=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
