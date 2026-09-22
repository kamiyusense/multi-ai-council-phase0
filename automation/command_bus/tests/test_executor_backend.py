from datetime import datetime, timedelta, timezone
import json
import unittest

from automation.command_bus.executor import (
    ExecutorLedger, claim_executor, make_executor_request, submit_executor_result,
)
from automation.command_bus.executor_backend import (
    ExecutorContent, GitHubExecutorBackend, executor_record_path,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()


class FakeGitHub:
    def __init__(self):
        self.files = {}
        self.counter = 0

    def _value(self, path, text):
        self.counter += 1
        return ExecutorContent(path, text, f"sha-{self.counter}")

    def get(self, path, ref):
        return self.files.get(path)

    def list(self, prefix, ref):
        return [v for p, v in self.files.items() if p.startswith(prefix)]

    def create(self, path, text, message, branch):
        if path in self.files:
            raise ValueError("exists")
        value = self._value(path, text)
        self.files[path] = value
        return value

    def update(self, path, text, sha, message, branch):
        if path not in self.files or self.files[path].sha != sha:
            raise ValueError("stale")
        value = self._value(path, text)
        self.files[path] = value
        return value


def state():
    return {"schema_version": 1, "loop_id": "exec-loop", "state": "RUNNING",
            "round": 0, "max_rounds": 6, "expires_at": EXP,
            "stop_requested": False, "last_command_id": None,
            "last_receipt_id": None, "expected_target": "work", "retry_policy": 0}


def build():
    ledger = ExecutorLedger()
    req = make_executor_request(
        request_id="req-1", loop_id="exec-loop", round=1,
        correlation_id="exec-loop-round-1", executor_role="writer",
        executor_kind="jules", action="PREPARE_IMPLEMENTATION",
        expected_repo="kamiyusense/multi-ai-council-phase0", expected_pr=4,
        expected_target_head="head-a", expires_at=EXP,
    )
    ledger.append_request(req)
    assert claim_executor(
        ledger, "req-1", claim_id="claim-1", executor_instance_id="executor-a",
        executor_generation=1, capability="prepare-only", claimed_at=NOW,
    ).status == "CLAIMED"
    assert submit_executor_result(
        ledger, "req-1", result_id="result-1", executor_instance_id="executor-a",
        executor_generation=1, result_state="PREPARED",
        evidence_refs=["artifact://prepared"], loop_id="exec-loop", round=1,
        correlation_id="exec-loop-round-1", expected_target_head="head-a",
        submitted_at=NOW,
    ).status == "ACCEPTED"
    return ledger


class ExecutorBackendTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGitHub()
        self.backend = GitHubExecutorBackend(self.client, branch="feature/chat-work-command-bus")
        self.ledger = build()

    def persist(self):
        for kind, records in (
            ("request", self.ledger.requests),
            ("claim", self.ledger.claims),
            ("result", self.ledger.results),
        ):
            for record in records:
                self.assertEqual(self.backend.append(kind, "exec-loop", record).status, "ACCEPTED")
        self.assertEqual(self.backend.write_state("exec-loop", state()).status, "ACCEPTED")

    def test_append_and_fresh_recovery(self):
        self.persist()
        receipt = {
            "schema_version": 1, "receipt_id": "executor-result-1",
            "execution_receipt_id": "executor-result-1",
            "result_id": "result-1", "request_id": "req-1", "state": "CONSUMED",
            "execution_result_id": "result-1", "execution_request_id": "req-1",
            "loop_id": "exec-loop", "round": 1,
            "correlation_id": "exec-loop-round-1", "expected_target_head": "head-a",
        }
        self.assertEqual(self.backend.append("receipt", "exec-loop", receipt).status, "ACCEPTED")
        recovered = GitHubExecutorBackend(
            self.client, branch="feature/chat-work-command-bus"
        ).recover("exec-loop")
        self.assertEqual(recovered.status, "RECOVERED")
        self.assertEqual(len(recovered.record["ledger"].receipts), 1)

    def test_execution_paths_and_identity_aliases(self):
        self.assertEqual(
            executor_record_path("request", "exec-loop", "req-1"),
            "execution_requests/exec-loop/req-1.json",
        )
        request = self.ledger.requests[0]
        self.assertEqual(request["execution_request_id"], request["request_id"])

    def test_duplicate_append_blocked(self):
        self.assertEqual(self.backend.append("request", "exec-loop", self.ledger.requests[0]).status, "ACCEPTED")
        self.assertEqual(self.backend.append("request", "exec-loop", self.ledger.requests[0]).status, "BLOCKED")

    def test_missing_predecessor_is_unknown(self):
        self.assertEqual(self.backend.append("claim", "exec-loop", self.ledger.claims[0]).status, "UNKNOWN")

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            executor_record_path("request", "../escape", "req-1")

    def test_recovery_rejects_path_identity_mismatch(self):
        self.assertEqual(self.backend.write_state("exec-loop", state()).status, "ACCEPTED")
        req = self.ledger.requests[0]
        path = "execution_requests/exec-loop/wrong.json"
        self.client.files[path] = ExecutorContent(path, json.dumps(req), "bad")
        self.assertEqual(self.backend.recover("exec-loop").status, "UNKNOWN")

    def test_persisted_data_has_no_thread_identity(self):
        self.persist()
        data = json.dumps({p: c.text for p, c in self.client.files.items()}).lower()
        self.assertNotIn("thread_id", data)
        self.assertNotIn("conversation_id", data)

    def test_exactly_once_receipt_survives_fresh_recovery(self):
        self.persist()
        receipt = {
            "schema_version": 1, "receipt_id": "executor-result-1",
            "execution_receipt_id": "executor-result-1",
            "result_id": "result-1", "execution_result_id": "result-1",
            "request_id": "req-1", "execution_request_id": "req-1",
            "state": "CONSUMED", "loop_id": "exec-loop", "round": 1,
            "correlation_id": "exec-loop-round-1", "expected_target_head": "head-a",
        }
        self.assertEqual(self.backend.append("receipt", "exec-loop", receipt).status, "ACCEPTED")
        fresh = GitHubExecutorBackend(self.client, branch="feature/chat-work-command-bus")
        self.assertEqual(fresh.recover("exec-loop").status, "RECOVERED")
        self.assertEqual(fresh.append("receipt", "exec-loop", receipt).status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
