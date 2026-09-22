from datetime import datetime, timedelta, timezone
import json
import unittest

from automation.command_bus.github_backend import GitHubContent, GitHubRecordBackend, record_path
from automation.command_bus.reviewer import ReviewerLedger, claim_request, make_request, submit_response

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()


class FakeGitHub:
    def __init__(self):
        self.files = {}
        self.counter = 0

    def _content(self, path, text):
        self.counter += 1
        return GitHubContent(path, text, f"sha-{self.counter}")

    def get(self, path, ref):
        return self.files.get(path)

    def list(self, prefix, ref):
        return [value for path, value in self.files.items() if path.startswith(prefix)]

    def create(self, path, text, message, branch):
        if path in self.files:
            raise ValueError("already exists")
        value = self._content(path, text)
        self.files[path] = value
        return value

    def update(self, path, text, sha, message, branch):
        if path not in self.files or self.files[path].sha != sha:
            raise ValueError("stale state sha")
        value = self._content(path, text)
        self.files[path] = value
        return value


def loop_state(loop_id="loop-1"):
    return {"schema_version": 1, "loop_id": loop_id, "state": "RUNNING",
            "round": 0, "max_rounds": 6, "expires_at": EXP,
            "stop_requested": False, "last_command_id": None,
            "last_receipt_id": None, "expected_target": "work", "retry_policy": 0}


def records():
    ledger = ReviewerLedger()
    request = make_request(request_id="req-1", loop_id="loop-1", round=1,
                           correlation_id="loop-1-round-1", expected_target_head="head-a",
                           expires_at=EXP)
    ledger.append_request(request)
    assert claim_request(ledger, "req-1", claim_id="claim-1",
                         reviewer_instance_id="reviewer-a", reviewer_generation=1,
                         claimed_at=NOW).status == "CLAIMED"
    assert submit_response(ledger, "req-1", response_id="resp-1",
                           reviewer_instance_id="reviewer-a", reviewer_generation=1,
                           decision="APPROVE", evidence_refs=["ev-1"], loop_id="loop-1",
                           round=1, correlation_id="loop-1-round-1",
                           expected_target_head="head-a", submitted_at=NOW).status == "ACCEPTED"
    return ledger


class NoReadbackGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.hide = False

    def get(self, path, ref):
        if self.hide:
            return None
        return super().get(path, ref)

    def create(self, path, text, message, branch):
        value = super().create(path, text, message, branch)
        self.hide = True
        return value


class GitHubBackendHardeningTests(unittest.TestCase):
    def test_write_requires_independent_readback(self):
        client = NoReadbackGitHub()
        backend = GitHubRecordBackend(client, branch="feature/chat-work-command-bus")
        request = records().requests[0]
        self.assertEqual(backend.append("request", "loop-1", request).status, "UNKNOWN")

    def test_loop_and_state_path_identity_fail_closed(self):
        client = FakeGitHub()
        backend = GitHubRecordBackend(client, branch="feature/chat-work-command-bus")
        request = records().requests[0]
        self.assertEqual(backend.append("request", "other-loop", request).status, "UNKNOWN")
        self.assertEqual(backend.write_state("other-loop", loop_state("loop-1")).status, "UNKNOWN")

    def test_claim_requires_durable_request(self):
        client = FakeGitHub()
        backend = GitHubRecordBackend(client, branch="feature/chat-work-command-bus")
        claim = records().claims[0]
        self.assertEqual(backend.append("claim", "loop-1", claim).status, "UNKNOWN")

    def test_response_requires_unique_durable_claim(self):
        client = FakeGitHub()
        backend = GitHubRecordBackend(client, branch="feature/chat-work-command-bus")
        ledger = records()
        self.assertEqual(backend.append("request", "loop-1", ledger.requests[0]).status, "ACCEPTED")
        self.assertEqual(backend.append("response", "loop-1", ledger.responses[0]).status, "UNKNOWN")

    def test_recovery_rejects_receipt_context_mismatch(self):
        client = FakeGitHub()
        backend = GitHubRecordBackend(client, branch="feature/chat-work-command-bus")
        ledger = records()
        for kind, values in (("request", ledger.requests), ("claim", ledger.claims), ("response", ledger.responses)):
            for value in values:
                self.assertEqual(backend.append(kind, "loop-1", value).status, "ACCEPTED")
        self.assertEqual(backend.write_state("loop-1", loop_state()).status, "ACCEPTED")
        bad = {"schema_version": 1, "receipt_id": "review-resp-1", "response_id": "resp-1",
               "request_id": "req-1", "state": "CONSUMED", "loop_id": "loop-1", "round": 1,
               "correlation_id": "loop-1-round-1", "expected_target_head": "wrong-head"}
        path = record_path("receipt", "loop-1", "review-resp-1")
        client.files[path] = GitHubContent(path, json.dumps(bad), "bad-sha")
        self.assertEqual(backend.recover("loop-1").status, "UNKNOWN")

    def test_recovery_rejects_listed_path_identity_mismatch(self):
        client = FakeGitHub()
        backend = GitHubRecordBackend(client, branch="feature/chat-work-command-bus")
        self.assertEqual(backend.write_state("loop-1", loop_state()).status, "ACCEPTED")
        request = records().requests[0]
        wrong_path = "review_requests/loop-1/not-the-id.json"
        client.files[wrong_path] = GitHubContent(wrong_path, json.dumps(request), "bad-sha")
        self.assertEqual(backend.recover("loop-1").status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
