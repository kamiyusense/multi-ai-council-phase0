from datetime import datetime, timedelta, timezone
import json
import unittest

from automation.command_bus.github_backend import GitHubContent, GitHubRecordBackend, record_path
from automation.command_bus.reviewer import ReviewerLedger, claim_request, consume_response, make_request, submit_response

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


def state():
    return {"schema_version": 1, "loop_id": "loop-1", "state": "RUNNING",
            "round": 0, "max_rounds": 6, "expires_at": EXP,
            "stop_requested": False, "last_command_id": None,
            "last_receipt_id": None, "expected_target": "work", "retry_policy": 0}


def build_ledger():
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


class GitHubBackendTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGitHub()
        self.backend = GitHubRecordBackend(self.client, branch="feature/chat-work-command-bus")
        self.ledger = build_ledger()

    def persist_records(self):
        for record in self.ledger.requests:
            self.assertEqual(self.backend.append("request", "loop-1", record).status, "ACCEPTED")
        for record in self.ledger.claims:
            self.assertEqual(self.backend.append("claim", "loop-1", record).status, "ACCEPTED")
        for record in self.ledger.responses:
            self.assertEqual(self.backend.append("response", "loop-1", record).status, "ACCEPTED")
        self.assertEqual(self.backend.write_state("loop-1", state()).status, "ACCEPTED")

    def test_append_and_read_all_record_types(self):
        self.persist_records()
        receipt = {"schema_version": 1, "receipt_id": "review-resp-1", "response_id": "resp-1",
                   "request_id": "req-1", "state": "CONSUMED"}
        self.assertEqual(self.backend.append("receipt", "loop-1", receipt).status, "ACCEPTED")
        for kind, record_id in (("request", "req-1"), ("claim", "claim-1"),
                                ("response", "resp-1"), ("receipt", "review-resp-1")):
            result = self.backend.read(kind, "loop-1", record_id)
            self.assertEqual(result.status, "READ")
            self.assertEqual(result.record["%s_id" % kind], record_id) if kind != "receipt" else self.assertEqual(result.record["receipt_id"], record_id)

    def test_duplicate_append_is_rejected(self):
        self.persist_records()
        self.assertEqual(self.backend.append("request", "loop-1", self.ledger.requests[0]).status, "BLOCKED")

    def test_state_is_the_only_mutable_record(self):
        self.persist_records()
        updated = state(); updated["round"] = 1; updated["last_command_id"] = "000001"
        self.assertEqual(self.backend.write_state("loop-1", updated).status, "ACCEPTED")
        self.assertEqual(self.backend.read_state("loop-1").record["round"], 1)
        self.assertEqual(self.backend.append("response", "loop-1", self.ledger.responses[0]).status, "BLOCKED")

    def test_fresh_backend_session_recovers_all_records(self):
        self.persist_records()
        receipt = {"schema_version": 1, "receipt_id": "review-resp-1", "response_id": "resp-1",
                   "request_id": "req-1", "state": "CONSUMED"}
        self.backend.append("receipt", "loop-1", receipt)
        recovered = GitHubRecordBackend(self.client, branch="feature/chat-work-command-bus").recover(
            "loop-1", expected_ids={"request": ["req-1"], "claim": ["claim-1"],
                                     "response": ["resp-1"], "receipt": ["review-resp-1"]})
        self.assertEqual(recovered.status, "RECOVERED")
        self.assertEqual(recovered.record["state"]["loop_id"], "loop-1")
        self.assertEqual(len(recovered.record["ledger"].responses), 1)

    def test_missing_malformed_and_partial_record_are_unknown(self):
        self.persist_records()
        self.assertEqual(self.backend.read("response", "loop-1", "missing").status, "UNKNOWN")
        path = record_path("response", "loop-1", "resp-1")
        self.client.files[path] = GitHubContent(path, "{malformed", "bad")
        self.assertEqual(self.backend.read("response", "loop-1", "resp-1").status, "UNKNOWN")
        recovery = self.backend.recover("loop-1", expected_ids={"response": ["resp-1"]})
        self.assertEqual(recovery.status, "UNKNOWN")

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            record_path("request", "../escape", "req-1")
        with self.assertRaises(ValueError):
            record_path("request", "loop-1", "../../escape")
        self.assertEqual(self.backend.append("request", "../escape", self.ledger.requests[0]).status, "UNKNOWN")

    def test_two_fresh_recoveries_preserve_exactly_once(self):
        self.persist_records()
        first = self.backend.recover("loop-1", expected_ids={"request": ["req-1"], "response": ["resp-1"]})
        self.assertEqual(first.status, "RECOVERED")
        first_ledger = first.record["ledger"]
        self.assertEqual(consume_response(first_ledger, "req-1", loop_id="loop-1", round=1,
                                          correlation_id="loop-1-round-1", expected_target_head="head-a",
                                          now=NOW).status, "VALID")
        self.assertEqual(self.backend.append("receipt", "loop-1", first_ledger.receipts[0]).status, "ACCEPTED")
        second = self.backend.recover("loop-1", expected_ids={"receipt": ["review-resp-1"]})
        self.assertEqual(second.status, "RECOVERED")
        self.assertEqual(consume_response(second.record["ledger"], "req-1", loop_id="loop-1", round=1,
                                          correlation_id="loop-1-round-1", expected_target_head="head-a",
                                          now=NOW).status, "NO-OP")

    def test_persisted_correctness_data_has_no_chat_or_thread_identity(self):
        self.persist_records()
        serialized = json.dumps({path: content.text for path, content in self.client.files.items()}, sort_keys=True).lower()
        self.assertNotIn("thread_id", serialized)
        self.assertNotIn("conversation_id", serialized)


if __name__ == "__main__":
    unittest.main()
