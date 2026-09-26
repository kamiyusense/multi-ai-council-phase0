from datetime import datetime, timedelta, timezone
import json
import unittest

from automation.command_bus.executor import (
    ExecutorLedger, claim_executor, consume_executor_result,
    make_executor_request, request_executor, submit_executor_result,
)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()


def state(**changes):
    value = {"schema_version": 1, "loop_id": "exec-loop", "state": "RUNNING",
             "round": 0, "max_rounds": 6, "expires_at": EXP,
             "stop_requested": False, "last_command_id": None,
             "last_receipt_id": None, "expected_target": "work", "retry_policy": 0}
    value.update(changes)
    return value


def request(**changes):
    data = dict(request_id="exec-req-1", loop_id="exec-loop", round=1,
                correlation_id="exec-loop-round-1", executor_role="writer",
                executor_kind="jules", action="PREPARE_IMPLEMENTATION",
                expected_repo="kamiyusense/multi-ai-council-phase0", expected_pr=4,
                expected_target_head="head-a", expires_at=EXP)
    data.update(changes)
    return make_executor_request(**data)


class ExecutorProtocolTests(unittest.TestCase):
    def setUp(self):
        self.ledger = ExecutorLedger()
        self.ledger.append_request(request())

    def claim(self, generation=1, instance="executor-a", at=NOW, expires_at=None, state_value=None):
        return claim_executor(
            self.ledger, "exec-req-1", claim_id=f"claim-{generation}",
            executor_instance_id=instance, executor_generation=generation,
            capability="prepare-only", claimed_at=at, expires_at=expires_at,
            state=state_value,
        )

    def result(self, state_value=None, **changes):
        data = dict(
            result_id="result-1", executor_instance_id="executor-a",
            executor_generation=1, result_state="PREPARED",
            evidence_refs=["artifact://prepared"], loop_id="exec-loop", round=1,
            correlation_id="exec-loop-round-1", expected_target_head="head-a",
            submitted_at=NOW,
        )
        data.update(changes)
        return submit_executor_result(self.ledger, "exec-req-1", state=state_value, **data)

    def consume(self, ledger=None, state_value=None, now=NOW):
        return consume_executor_result(
            ledger or self.ledger, "exec-req-1", loop_id="exec-loop", round=1,
            correlation_id="exec-loop-round-1", expected_target_head="head-a",
            state=state_value, now=now,
        )

    def test_prepare_only_handoff_without_thread_id(self):
        self.assertEqual(self.claim().status, "CLAIMED")
        self.assertEqual(self.result().status, "ACCEPTED")
        self.assertEqual(self.consume().status, "VALID")

    def test_request_contract_is_provider_neutral_and_bounded(self):
        item = request(executor_kind="generic")
        self.assertEqual(item["target_role"], "executor")
        self.assertEqual(item["execution_request_id"], item["request_id"])
        self.assertEqual(item["execution_mode"], "PREPARE_ONLY")
        self.assertFalse(item["live_start_permitted"])
        self.assertFalse(item["requires_live_model"])
        self.assertEqual(item["retry"], 0)
        self.assertEqual(item["fallback"], "disabled")
        self.assertIn("LIVE_START", item["prohibited_actions"])

    def test_user_approval_boundary_fails_closed(self):
        pending = request(requires_user_approval=True, approval_state="PENDING")
        self.assertEqual(request_executor(ExecutorLedger(), pending).status, "BLOCKED")
        ledger = ExecutorLedger()
        ledger.append_request(pending)
        self.assertEqual(claim_executor(
            ledger, "exec-req-1", claim_id="approval-claim",
            executor_instance_id="executor-a", executor_generation=1,
            capability="prepare-only", claimed_at=NOW,
        ).status, "BLOCKED")

    def test_approved_request_can_be_claimed(self):
        approved = request(requires_user_approval=True, approval_state="APPROVED")
        ledger = ExecutorLedger()
        self.assertEqual(request_executor(ledger, approved).status, "REQUESTED")
        self.assertEqual(claim_executor(
            ledger, "exec-req-1", claim_id="approved-claim",
            executor_instance_id="executor-a", executor_generation=1,
            capability="prepare-only", claimed_at=NOW,
        ).status, "CLAIMED")

    def test_live_request_is_rejected(self):
        with self.assertRaises(ValueError):
            request(execution_mode="LIVE", requires_live_model=True)
        with self.assertRaises(ValueError):
            request(live_start_permitted=True)

    def test_claim_replacement_and_stale_generation(self):
        short = (NOW + timedelta(seconds=1)).isoformat()
        self.assertEqual(self.claim(expires_at=short).status, "CLAIMED")
        later = NOW + timedelta(seconds=2)
        self.assertEqual(self.claim(generation=2, instance="executor-b", at=later).status, "CLAIMED")
        self.assertEqual(self.claim(generation=1, instance="executor-a", at=later).status, "BLOCKED")

    def test_wrong_context_and_owner_fail_closed(self):
        self.assertEqual(self.claim().status, "CLAIMED")
        self.assertEqual(self.result(executor_generation=2).status, "BLOCKED")
        self.assertEqual(self.result(result_id="r2", correlation_id="wrong").status, "BLOCKED")
        self.assertEqual(self.result(result_id="r3", expected_target_head="head-b").status, "BLOCKED")

    def test_duplicate_result_and_receipt_are_noop(self):
        self.claim()
        self.assertEqual(self.result().status, "ACCEPTED")
        self.assertEqual(self.result().status, "NO-OP")
        self.assertEqual(self.consume().status, "VALID")
        self.assertEqual(self.consume().status, "NO-OP")

    def test_prepare_result_has_required_safety_fields_and_aliases(self):
        self.claim()
        accepted = self.result(artifact_refs=["artifact://patch"])
        record = accepted.record
        self.assertEqual(record["execution_result_id"], record["result_id"])
        self.assertEqual(record["execution_request_id"], record["request_id"])
        self.assertEqual(record["artifact_refs"], ["artifact://patch"])
        self.assertFalse(record["model_executed"])
        self.assertFalse(record["external_send_attempted"])
        self.assertFalse(record["live_started"])
        self.assertEqual(record["retry_count"], 0)
        self.assertFalse(record["fallback_used"])

    def test_unsafe_recovered_result_is_rejected(self):
        self.claim()
        self.result()
        data = self.ledger.export_records()
        data["results"][0]["live_started"] = True
        with self.assertRaises(ValueError):
            ExecutorLedger.from_records(data)

    def test_state_gates_apply(self):
        stopped = state(state="HALTED", stop_requested=True)
        self.assertEqual(self.claim(state_value=stopped).status, "BLOCKED")
        maxed = state(round=6)
        self.assertEqual(self.claim(state_value=maxed).status, "BLOCKED")
        expired = state(expires_at=(NOW - timedelta(seconds=1)).isoformat())
        self.assertEqual(self.claim(state_value=expired).status, "BLOCKED")

    def test_fresh_session_recovery_no_thread_identity(self):
        self.claim()
        self.result()
        data = json.loads(json.dumps(self.ledger.export_records()))
        fresh = ExecutorLedger.from_records(data)
        self.assertEqual(self.consume(ledger=fresh).status, "VALID")
        serialized = json.dumps(data).lower()
        self.assertNotIn("thread_id", serialized)
        self.assertNotIn("conversation_id", serialized)


if __name__ == "__main__":
    unittest.main()
