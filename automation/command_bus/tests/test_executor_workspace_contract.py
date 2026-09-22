from datetime import datetime, timedelta, timezone
import json
import unittest

from automation.command_bus.executor import (
    ExecutorLedger,
    claim_executor,
    make_executor_request,
    submit_executor_result,
)
from automation.command_bus.executor_backend import (
    ExecutorContent,
    GitHubExecutorBackend,
)

NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()
HEAD = "a" * 40
TREE = "b" * 40


def request(**changes):
    values = dict(
        request_id="integrity-req-1",
        loop_id="integrity-loop",
        round=1,
        correlation_id="integrity-loop-round-1",
        executor_role="writer",
        executor_kind="generic",
        action="PREPARE_IMPLEMENTATION",
        expected_repo="kamiyusense/multi-ai-council-phase0",
        expected_pr=4,
        expected_target_head=HEAD,
        expected_target_tree=TREE,
        expires_at=EXP,
        path_policy=[
            {"path": "src/relay/**", "allowed_ops": ["ADD", "MODIFY"]},
            {"path": "tests/relay/**", "allowed_ops": ["ADD", "MODIFY"]},
        ],
    )
    values.update(changes)
    return make_executor_request(**values)


class FakeGitHub:
    def __init__(self):
        self.files = {}
        self.counter = 0

    def _content(self, path, text):
        self.counter += 1
        return ExecutorContent(path, text, f"sha-{self.counter}")

    def get(self, path, ref):
        return self.files.get(path)

    def list(self, prefix, ref):
        return [v for p, v in self.files.items() if p.startswith(prefix)]

    def create(self, path, text, message, branch):
        if path in self.files:
            raise ValueError("exists")
        value = self._content(path, text)
        self.files[path] = value
        return value

    def update(self, path, text, sha, message, branch):
        if path not in self.files or self.files[path].sha != sha:
            raise ValueError("stale")
        value = self._content(path, text)
        self.files[path] = value
        return value


class ExecutorWorkspaceContractTests(unittest.TestCase):
    def test_request_binds_head_tree_and_integrity_profile(self):
        item = request()
        self.assertEqual(item["expected_target_head"], HEAD)
        self.assertEqual(item["expected_target_tree"], TREE)
        self.assertTrue(item["requires_clean_workspace"])
        self.assertEqual(item["workspace_integrity_profile"], "TREE_IDENTITY_V1")
        self.assertEqual(item["mutation_lease_ttl_seconds"], 900)
        self.assertEqual(item["retry"], 0)
        self.assertEqual(item["fallback"], "disabled")

    def test_claim_can_bind_workspace_attestation(self):
        ledger = ExecutorLedger()
        ledger.append_request(request())
        result = claim_executor(
            ledger,
            "integrity-req-1",
            claim_id="claim-1",
            executor_instance_id="executor-a",
            executor_generation=1,
            capability="prepare-only",
            claimed_at=NOW,
            workspace_attestation_id="att-1",
            workspace_path_fingerprint="workspace-fp",
            observed_head=HEAD,
            observed_tree=TREE,
            observed_index_tree=TREE,
        )
        self.assertEqual(result.status, "CLAIMED")
        self.assertEqual(result.record["observed_index_tree"], TREE)

    def test_partial_workspace_attestation_claim_is_unknown(self):
        ledger = ExecutorLedger()
        ledger.append_request(request())
        result = claim_executor(
            ledger,
            "integrity-req-1",
            claim_id="claim-1",
            executor_instance_id="executor-a",
            executor_generation=1,
            capability="prepare-only",
            claimed_at=NOW,
            workspace_attestation_id="att-1",
        )
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(len(ledger.claims), 0)

    def test_result_inherits_expected_target_tree(self):
        ledger = ExecutorLedger()
        ledger.append_request(request())
        self.assertEqual(claim_executor(
            ledger,
            "integrity-req-1",
            claim_id="claim-1",
            executor_instance_id="executor-a",
            executor_generation=1,
            capability="prepare-only",
            claimed_at=NOW,
        ).status, "CLAIMED")
        result = submit_executor_result(
            ledger,
            "integrity-req-1",
            result_id="result-1",
            executor_instance_id="executor-a",
            executor_generation=1,
            result_state="PREPARED",
            evidence_refs=["artifact://prepared"],
            loop_id="integrity-loop",
            round=1,
            correlation_id="integrity-loop-round-1",
            expected_target_head=HEAD,
            submitted_at=NOW,
        )
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(result.record["expected_target_tree"], TREE)

    def test_result_wrong_target_tree_is_blocked(self):
        ledger = ExecutorLedger()
        ledger.append_request(request())
        claim_executor(
            ledger,
            "integrity-req-1",
            claim_id="claim-1",
            executor_instance_id="executor-a",
            executor_generation=1,
            capability="prepare-only",
            claimed_at=NOW,
        )
        result = submit_executor_result(
            ledger,
            "integrity-req-1",
            result_id="result-1",
            executor_instance_id="executor-a",
            executor_generation=1,
            result_state="PREPARED",
            evidence_refs=["artifact://prepared"],
            loop_id="integrity-loop",
            round=1,
            correlation_id="integrity-loop-round-1",
            expected_target_head=HEAD,
            expected_target_tree="c" * 40,
            submitted_at=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_result_integrity_refs_are_all_or_nothing(self):
        ledger = ExecutorLedger()
        ledger.append_request(request())
        claim_executor(
            ledger,
            "integrity-req-1",
            claim_id="claim-1",
            executor_instance_id="executor-a",
            executor_generation=1,
            capability="prepare-only",
            claimed_at=NOW,
        )
        result = submit_executor_result(
            ledger,
            "integrity-req-1",
            result_id="result-1",
            executor_instance_id="executor-a",
            executor_generation=1,
            result_state="PREPARED",
            evidence_refs=["artifact://prepared"],
            loop_id="integrity-loop",
            round=1,
            correlation_id="integrity-loop-round-1",
            expected_target_head=HEAD,
            submitted_at=NOW,
            workspace_attestation_ref="evidence://workspace",
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_backend_recovery_rejects_target_tree_mismatch(self):
        client = FakeGitHub()
        backend = GitHubExecutorBackend(client, branch="feature/chat-work-command-bus")
        req = request()
        self.assertEqual(backend.append("request", "integrity-loop", req).status, "ACCEPTED")

        claim = {
            "schema_version": 1,
            "claim_id": "claim-1",
            "execution_claim_id": "claim-1",
            "request_id": "integrity-req-1",
            "execution_request_id": "integrity-req-1",
            "executor_instance_id": "executor-a",
            "executor_generation": 1,
            "executor_role": "writer",
            "capability": "prepare-only",
            "claimed_at": NOW.isoformat(),
            "expires_at": EXP,
            "status": "ACTIVE",
        }
        self.assertEqual(backend.append("claim", "integrity-loop", claim).status, "ACCEPTED")

        result = {
            "schema_version": 1,
            "result_id": "result-1",
            "execution_result_id": "result-1",
            "request_id": "integrity-req-1",
            "execution_request_id": "integrity-req-1",
            "loop_id": "integrity-loop",
            "round": 1,
            "correlation_id": "integrity-loop-round-1",
            "expected_target_head": HEAD,
            "expected_target_tree": "c" * 40,
            "executor_instance_id": "executor-a",
            "executor_generation": 1,
            "result_state": "PREPARED",
            "artifact_refs": [],
            "evidence_refs": ["artifact://prepared"],
            "model_executed": False,
            "external_send_attempted": False,
            "retry_count": 0,
            "fallback_used": False,
            "live_started": False,
            "mutation_started": False,
            "target_head_revalidated": False,
            "push_attempted": False,
            "remote_readback_verified": False,
            "submitted_at": NOW.isoformat(),
            "status": "AVAILABLE",
        }
        # Deliberately bypass append validation to reproduce stale/corrupt durable data.
        path = "execution_results/integrity-loop/result-1.json"
        client.files[path] = ExecutorContent(path, json.dumps(result), "manual")
        state_path = "state/integrity-loop.json"
        client.files[state_path] = ExecutorContent(
            state_path,
            json.dumps({
                "schema_version": 1,
                "loop_id": "integrity-loop",
                "state": "RUNNING",
                "round": 0,
                "max_rounds": 6,
                "expires_at": EXP,
                "stop_requested": False,
                "last_command_id": None,
                "last_receipt_id": None,
                "expected_target": "work",
                "retry_policy": 0,
            }),
            "state",
        )
        self.assertEqual(backend.recover("integrity-loop").status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
