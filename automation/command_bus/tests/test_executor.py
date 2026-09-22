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

    def test_live_request_is_rejected(self):
        with self.assertRaises(ValueError):
            request(execution_mode="LIVE", requires_live_model=True)

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
