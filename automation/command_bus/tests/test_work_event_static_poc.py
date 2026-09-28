"""Static GitHub-event-to-Work handoff proof; no Work or provider is started."""

from datetime import datetime, timedelta, timezone
import unittest

from automation.command_bus.event_processor import EventProcessor
from automation.command_bus.ledger import InMemoryLedger
from automation.command_bus.reviewer import make_request_v2
from automation.command_bus.reviewer_transport import MockReviewerTransport, ReviewWakeCoordinator
from automation.command_bus.reviewer_wake_backend import DurableWakeBackend, WakeContent


NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
LOOP = "work-event-static-poc"
REPO = "kamiyusense/multi-ai-council-phase0"
HEAD = "a" * 40
TREE = "b" * 40
REQUEST_ID = "review-001"
REQUEST_REF = f"automation/command_bus/review_requests/{LOOP}/{REQUEST_ID}.json"


class FakeContents:
    def __init__(self):
        self.files = {}
        self.creates = 0

    def get(self, path, ref):
        return self.files.get(path)

    def list(self, prefix, ref):
        return [v for p, v in self.files.items() if p.startswith(prefix)]

    def create(self, path, text, message, branch):
        if path in self.files:
            raise ValueError("duplicate append")
        self.creates += 1
        content = WakeContent(path, text, f"fixture-sha-{self.creates}")
        self.files[path] = content
        return content


def ledger():
    state = {
        "schema_version": 1,
        "loop_id": LOOP,
        "state": "RUNNING",
        "round": 0,
        "max_rounds": 6,
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "stop_requested": False,
        "last_command_id": None,
        "last_receipt_id": None,
        "expected_target": "work",
        "retry_policy": 0,
    }
    return InMemoryLedger(state)


def command(head=HEAD):
    return {
        "schema_version": 1,
        "command_id": "000001",
        "loop_id": LOOP,
        "round": 1,
        "correlation_id": f"{LOOP}-round-1",
        "target": "work",
        "action": "ECHO_AND_RECEIPT",
        "expected_repo": REPO,
        "expected_pr": 4,
        "expected_target_head": head,
        "retry": 0,
        "fallback": "disabled",
        "requires_live_model": False,
        "requires_github_write": False,
    }


def review_request():
    return make_request_v2(
        request_id=REQUEST_ID,
        loop_id=LOOP,
        round=1,
        correlation_id=f"{LOOP}-round-1",
        expected_target_head=HEAD,
        expected_target_tree=TREE,
        reviewer_role="semantic-reviewer",
        review_kind="RELAY_SAFETY_DIFF",
        evidence_refs=["evidence://fixture"],
        allowed_decisions=["APPROVE", "CHANGES_REQUIRED", "UNKNOWN"],
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
    )


class WorkEventStaticPocTests(unittest.TestCase):
    def test_duplicate_event_and_fresh_session_cannot_repeat_wake(self):
        records = ledger()
        records.add_command(command())
        processor = EventProcessor(records, repo=REPO, pr=4, observed_head=HEAD)
        self.assertEqual(processor.process("000001", now=NOW).status, "PROCESSED")
        self.assertEqual(processor.process("000001", now=NOW).status, "NO-OP")

        contents = FakeContents()
        backend = DurableWakeBackend(contents, branch="fixture-carrier")
        request = review_request()
        reservation = backend.reserve(
            request, attempt_id="attempt-001", request_ref=REQUEST_REF,
            route="scheduled", created_at=NOW.isoformat(),
        )
        self.assertEqual(reservation.status, "RESERVED")
        transport = MockReviewerTransport("scheduled")
        first = ReviewWakeCoordinator().dispatch_reserved(
            request, request_ref=REQUEST_REF, transport=transport,
            reservation=reservation,
        )
        self.assertEqual(first.status, "SIMULATED")
        self.assertEqual(len(transport.sent), 1)

        fresh_backend = DurableWakeBackend(contents, branch="fixture-carrier")
        replay = fresh_backend.read_for_request(
            request, request_ref=REQUEST_REF, route="scheduled"
        )
        self.assertEqual(replay.status, "READ")
        blocked = ReviewWakeCoordinator().dispatch_reserved(
            request, request_ref=REQUEST_REF, transport=transport,
            reservation=replay,
        )
        self.assertEqual(blocked.status, "BLOCKED")
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(contents.creates, 1)
        self.assertEqual(records.receipts[0]["retry_count"], 0)
        self.assertFalse(records.receipts[0]["fallback_used"])

    def test_stale_target_blocks_before_any_wake(self):
        records = ledger()
        records.add_command(command(head="c" * 40))
        result = EventProcessor(records, repo=REPO, pr=4, observed_head=HEAD).process(
            "000001", now=NOW
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.receipt["state"], "BLOCKED")
        self.assertFalse(result.receipt["external_send_attempted"])


if __name__ == "__main__":
    unittest.main()
