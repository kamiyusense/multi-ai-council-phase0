from datetime import datetime, timedelta, timezone
import unittest

from automation.command_bus.reviewer import make_request_v2
from automation.command_bus.reviewer_transport import (
    MockReviewerTransport,
    ReviewWakeCoordinator,
)
from automation.command_bus.reviewer_wake_backend import (
    DurableWakeBackend,
    WakeContent,
    wake_attempt_path,
)

NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()
CREATED = NOW.isoformat()
HEAD = "a" * 40
TREE = "b" * 40
LOOP = "wake-backend-001"
REQ = "req-001"
ATTEMPT = "attempt-001"
REF = f"automation/command_bus/review_requests/{LOOP}/{REQ}.json"


class FakeGitHub:
    def __init__(self):
        self.files = {}
        self.counter = 0
        self.create_calls = 0

    def _content(self, path, text):
        self.counter += 1
        return WakeContent(path, text, f"sha-{self.counter}")

    def get(self, path, ref):
        return self.files.get(path)

    def list(self, prefix, ref):
        return [value for path, value in self.files.items() if path.startswith(prefix)]

    def create(self, path, text, message, branch):
        self.create_calls += 1
        if path in self.files:
            raise ValueError("exists")
        value = self._content(path, text)
        self.files[path] = value
        return value


class NoReadbackGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.hide_after_create = False

    def get(self, path, ref):
        if self.hide_after_create:
            return None
        return super().get(path, ref)

    def create(self, path, text, message, branch):
        value = super().create(path, text, message, branch)
        self.hide_after_create = True
        return value


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
        evidence_refs=["evidence://relay"],
        allowed_decisions=["APPROVE", "CHANGES_REQUIRED", "UNKNOWN"],
        expires_at=EXP,
    )
    values.update(changes)
    return make_request_v2(**values)


class DurableWakeBackendTests(unittest.TestCase):
    def test_first_reservation_is_append_only_and_readback_verified(self):
        client = FakeGitHub()
        backend = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        result = backend.reserve(
            request(),
            attempt_id=ATTEMPT,
            request_ref=REF,
            route="browser",
            created_at=CREATED,
        )
        self.assertEqual(result.status, "RESERVED")
        self.assertTrue(result.evidence["fresh_reservation"])
        self.assertEqual(result.evidence["attempt_id"], ATTEMPT)
        self.assertEqual(client.create_calls, 1)
        path = wake_attempt_path(LOOP, REQ)
        self.assertIn(path, client.files)

    def test_same_request_cannot_reserve_second_attempt(self):
        client = FakeGitHub()
        backend = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        first = backend.reserve(
            request(), attempt_id=ATTEMPT, request_ref=REF,
            route="browser", created_at=CREATED,
        )
        second = backend.reserve(
            request(), attempt_id="attempt-002", request_ref=REF,
            route="browser", created_at=CREATED,
        )
        self.assertEqual(first.status, "RESERVED")
        self.assertEqual(second.status, "BLOCKED")
        self.assertEqual(second.evidence["existing_attempt_id"], ATTEMPT)
        self.assertFalse(second.evidence["fresh_reservation"])
        self.assertEqual(client.create_calls, 1)

    def test_unverifiable_write_is_unknown_and_fresh_session_cannot_resend(self):
        client = NoReadbackGitHub()
        backend = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        first = backend.reserve(
            request(), attempt_id=ATTEMPT, request_ref=REF,
            route="browser", created_at=CREATED,
        )
        self.assertEqual(first.status, "UNKNOWN")
        self.assertFalse(first.evidence["fresh_reservation"])
        self.assertEqual(client.create_calls, 1)

        # Simulate a later fresh session where the already-created record is visible.
        client.hide_after_create = False
        fresh = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        recovered = fresh.read_for_request(request(), request_ref=REF, route="browser")
        self.assertEqual(recovered.status, "READ")
        self.assertFalse(recovered.evidence["fresh_reservation"])

        transport = MockReviewerTransport("browser")
        result = ReviewWakeCoordinator().dispatch_reserved(
            request(), request_ref=REF, transport=transport, reservation=recovered
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(transport.sent, [])

    def test_fresh_verified_reservation_authorizes_one_mock_wake(self):
        client = FakeGitHub()
        backend = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        reservation = backend.reserve(
            request(), attempt_id=ATTEMPT, request_ref=REF,
            route="browser", created_at=CREATED,
        )
        transport = MockReviewerTransport("browser")
        coordinator = ReviewWakeCoordinator()
        result = coordinator.dispatch_reserved(
            request(), request_ref=REF, transport=transport, reservation=reservation
        )
        self.assertEqual(result.status, "SIMULATED")
        self.assertEqual(len(transport.sent), 1)
        replay = coordinator.dispatch_reserved(
            request(), request_ref=REF, transport=transport, reservation=reservation
        )
        self.assertEqual(replay.status, "BLOCKED")
        self.assertEqual(len(transport.sent), 1)

    def test_recovered_reservation_never_authorizes_send(self):
        client = FakeGitHub()
        backend = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        self.assertEqual(backend.reserve(
            request(), attempt_id=ATTEMPT, request_ref=REF,
            route="direct", created_at=CREATED,
        ).status, "RESERVED")
        fresh = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        recovered = fresh.read_for_request(request(), request_ref=REF, route="direct")
        self.assertEqual(recovered.status, "READ")
        transport = MockReviewerTransport("direct")
        result = ReviewWakeCoordinator().dispatch_reserved(
            request(), request_ref=REF, transport=transport, reservation=recovered
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(transport.sent, [])

    def test_corrupt_path_identity_is_unknown(self):
        client = FakeGitHub()
        backend = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        reservation = backend.reserve(
            request(), attempt_id=ATTEMPT, request_ref=REF,
            route="browser", created_at=CREATED,
        )
        self.assertEqual(reservation.status, "RESERVED")
        correct = wake_attempt_path(LOOP, REQ)
        content = client.files.pop(correct)
        wrong = f"review_wake_attempts/{LOOP}/wrong-request.json"
        client.files[wrong] = WakeContent(wrong, content.text, content.sha)
        result = DurableWakeBackend(
            client, branch="feature/chat-work-command-bus"
        ).read_for_request(request(), request_ref=REF, route="browser")
        self.assertEqual(result.status, "UNKNOWN")

    def test_route_mismatch_is_unknown_on_recovery(self):
        client = FakeGitHub()
        backend = DurableWakeBackend(client, branch="feature/chat-work-command-bus")
        self.assertEqual(backend.reserve(
            request(), attempt_id=ATTEMPT, request_ref=REF,
            route="browser", created_at=CREATED,
        ).status, "RESERVED")
        recovered = DurableWakeBackend(
            client, branch="feature/chat-work-command-bus"
        ).read_for_request(request(), request_ref=REF, route="direct")
        self.assertEqual(recovered.status, "UNKNOWN")

    def test_unsafe_path_components_rejected(self):
        with self.assertRaises(ValueError):
            wake_attempt_path("../escape", ATTEMPT)
        with self.assertRaises(ValueError):
            wake_attempt_path(LOOP, "../../escape")


if __name__ == "__main__":
    unittest.main()
