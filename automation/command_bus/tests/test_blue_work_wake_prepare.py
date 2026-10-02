import json
import unittest
from datetime import datetime, timedelta, timezone

from automation.command_bus.blue_jules_result_event import EventClassificationResult, EventDecision
from automation.command_bus.blue_work_wake_prepare import (
    CarrierSnapshot,
    TargetSnapshot,
    PrepareResult,
    prepare_blue_work_wake,
)


class TestBlueWorkWakePrepare(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.expires_at = (self.now + timedelta(hours=1)).isoformat()

        self.valid_classification = EventClassificationResult(
            decision=EventDecision.WAKE,
            command_id=f"blue-jules-result-pr42-{'a'*40}",
            reason="eligible for wake"
        )

        self.valid_carrier = CarrierSnapshot(
            protocol_version=1,
            lane="blue",
            command_prefix="[CW_BLUE_V1]",
            worker_generation=1,
        )

        self.valid_target = TargetSnapshot(
            target_repository="kamiyusense/multi-ai-council-phase0",
            target_pr=42,
            target_branch="jules-work/test-branch",
            expected_target_head="a"*40,
            current_target_head="a"*40,
        )

        self.valid_existing_ids = []

    def call_prepare(self, classification=None, carrier=None, target=None, existing_ids=Ellipsis, expires_at=Ellipsis, now=None):
        return prepare_blue_work_wake(
            classification=classification if classification is not None else self.valid_classification,
            carrier=carrier if carrier is not None else self.valid_carrier,
            target=target if target is not None else self.valid_target,
            existing_command_ids=existing_ids if existing_ids is not Ellipsis else self.valid_existing_ids,
            expires_at=expires_at if expires_at is not Ellipsis else self.expires_at,
            now=now if now is not None else self.now,
        )

    def test_valid_wake_returns_prepared_and_parseable_body(self):
        result = self.call_prepare()
        self.assertEqual(result.status, "PREPARED")
        self.assertEqual(result.command_id, self.valid_classification.command_id)

        # Verify body starts with prefix
        self.assertTrue(result.review_body.startswith("[CW_BLUE_V1]\n"))

        # Parse body as JSON
        json_str = result.review_body[len("[CW_BLUE_V1]\n"):]
        parsed = json.loads(json_str)

        # Assert exact key set and fixed values
        expected_keys = {
            "protocol_version", "command_id", "worker_generation", "target_repository",
            "target_pr", "target_branch", "expected_target_head", "expires_at",
            "task", "allowed_paths", "verification", "live_provider_or_model_allowed",
            "retry", "fallback"
        }
        self.assertEqual(set(parsed.keys()), expected_keys)
        self.assertEqual(parsed["protocol_version"], 1)
        self.assertEqual(parsed["command_id"], self.valid_classification.command_id)
        self.assertEqual(parsed["worker_generation"], 1)
        self.assertEqual(parsed["target_repository"], "kamiyusense/multi-ai-council-phase0")
        self.assertEqual(parsed["target_pr"], 42)
        self.assertEqual(parsed["target_branch"], "jules-work/test-branch")
        self.assertEqual(parsed["expected_target_head"], "a"*40)
        self.assertEqual(parsed["expires_at"], self.expires_at)
        self.assertEqual(parsed["allowed_paths"], [])
        self.assertEqual(parsed["live_provider_or_model_allowed"], False)
        self.assertEqual(parsed["retry"], 0)
        self.assertEqual(parsed["fallback"], "disabled")

    def test_malformed_decision_value_returns_unknown(self):
        for decision in ("WAKE", "BOGUS", None):
            with self.subTest(decision=decision):
                classification = EventClassificationResult(
                    decision=decision,
                    command_id=self.valid_classification.command_id,
                )
                result = self.call_prepare(classification=classification)
                self.assertEqual(result.status, "UNKNOWN")
                self.assertIsNone(result.review_body)

    def test_ignore_returns_no_op(self):
        classification = EventClassificationResult(
            decision=EventDecision.IGNORE,
            command_id="some-id"
        )
        result = self.call_prepare(classification=classification)
        self.assertEqual(result.status, "NO_OP")
        self.assertEqual(result.command_id, "some-id")
        self.assertIsNone(result.review_body)

    def test_unknown_returns_unknown(self):
        classification = EventClassificationResult(
            decision=EventDecision.UNKNOWN,
            command_id="some-id"
        )
        result = self.call_prepare(classification=classification)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIsNone(result.review_body)

    def test_duplicate_returns_no_op(self):
        result = self.call_prepare(existing_ids=[self.valid_classification.command_id])
        self.assertEqual(result.status, "NO_OP")
        self.assertEqual(result.command_id, self.valid_classification.command_id)
        self.assertIsNone(result.review_body)

    def test_mismatched_deterministic_identity_returns_unknown(self):
        classification = EventClassificationResult(
            decision=EventDecision.WAKE,
            command_id=f"blue-jules-result-pr42-{'b'*40}", # Mismatched head
        )
        result = self.call_prepare(classification=classification)
        self.assertEqual(result.status, "UNKNOWN")

        classification2 = EventClassificationResult(
            decision=EventDecision.WAKE,
            command_id=f"blue-jules-result-pr99-{'a'*40}", # Mismatched PR
        )
        result2 = self.call_prepare(classification=classification2)
        self.assertEqual(result2.status, "UNKNOWN")

    def test_current_head_moved_returns_stale(self):
        target = TargetSnapshot(
            target_repository="kamiyusense/multi-ai-council-phase0",
            target_pr=42,
            target_branch="jules-work/test-branch",
            expected_target_head="a"*40,
            current_target_head="b"*40,
        )
        result = self.call_prepare(target=target)
        self.assertEqual(result.status, "STALE")
        self.assertEqual(result.command_id, self.valid_classification.command_id)
        self.assertIsNone(result.review_body)

    def test_malformed_heads_returns_unknown(self):
        for bad_head in ["a"*39, "z"*40, 123, None, ""]:
            target = TargetSnapshot(
                target_repository="kamiyusense/multi-ai-council-phase0",
                target_pr=42,
                target_branch="jules-work/test-branch",
                expected_target_head=bad_head,
                current_target_head="a"*40,
            )
            self.assertEqual(self.call_prepare(target=target).status, "UNKNOWN")

            target2 = TargetSnapshot(
                target_repository="kamiyusense/multi-ai-council-phase0",
                target_pr=42,
                target_branch="jules-work/test-branch",
                expected_target_head="a"*40,
                current_target_head=bad_head,
            )
            self.assertEqual(self.call_prepare(target=target2).status, "UNKNOWN")

    def test_wrong_repo_default_branch_malformed_pr_returns_unknown(self):
        # wrong repo
        target_repo = TargetSnapshot(
            target_repository="other/repo",
            target_pr=42,
            target_branch="jules-work/test-branch",
            expected_target_head="a"*40,
            current_target_head="a"*40,
        )
        self.assertEqual(self.call_prepare(target=target_repo).status, "UNKNOWN")

        # default branch
        for branch in ["main", "master"]:
            target_branch = TargetSnapshot(
                target_repository="kamiyusense/multi-ai-council-phase0",
                target_pr=42,
                target_branch=branch,
                expected_target_head="a"*40,
                current_target_head="a"*40,
            )
            self.assertEqual(self.call_prepare(target=target_branch).status, "UNKNOWN")

        # malformed PR
        for pr in [0, -1, "42", True, None]:
            target_pr = TargetSnapshot(
                target_repository="kamiyusense/multi-ai-council-phase0",
                target_pr=pr,
                target_branch="jules-work/test-branch",
                expected_target_head="a"*40,
                current_target_head="a"*40,
            )
            self.assertEqual(self.call_prepare(target=target_pr).status, "UNKNOWN")

    def test_wrong_prefix_lane_protocol_returns_unknown(self):
        # prefix
        carrier_prefix = CarrierSnapshot(1, "blue", "[CW_YELLOW_V1]", 1)
        self.assertEqual(self.call_prepare(carrier=carrier_prefix).status, "UNKNOWN")

        # lane
        carrier_lane = CarrierSnapshot(1, "red", "[CW_BLUE_V1]", 1)
        self.assertEqual(self.call_prepare(carrier=carrier_lane).status, "UNKNOWN")

        # protocol
        carrier_proto = CarrierSnapshot(2, "blue", "[CW_BLUE_V1]", 1)
        self.assertEqual(self.call_prepare(carrier=carrier_proto).status, "UNKNOWN")

    def test_generation_zero_negative_bool_non_int_returns_unknown(self):
        for gen in [0, -1, True, False, "1", None, 1.5]:
            carrier = CarrierSnapshot(1, "blue", "[CW_BLUE_V1]", gen)
            self.assertEqual(self.call_prepare(carrier=carrier).status, "UNKNOWN")

    def test_expires_at_none_returns_unknown(self):
        self.assertEqual(self.call_prepare(expires_at=None).status, "UNKNOWN")

    def test_expires_at_empty_string_returns_unknown(self):
        self.assertEqual(self.call_prepare(expires_at="").status, "UNKNOWN")

    def test_malformed_naive_equal_now_expired_expiry_returns_unknown(self):
        # malformed
        self.assertEqual(self.call_prepare(expires_at="not-a-date").status, "UNKNOWN")

        # naive
        naive_dt = datetime(2026, 10, 1, 13, 0, 0).isoformat()
        self.assertEqual(self.call_prepare(expires_at=naive_dt).status, "UNKNOWN")

        # equal now
        self.assertEqual(self.call_prepare(expires_at=self.now.isoformat()).status, "UNKNOWN")

        # expired
        past_dt = (self.now - timedelta(hours=1)).isoformat()
        self.assertEqual(self.call_prepare(expires_at=past_dt).status, "UNKNOWN")

    def test_naive_now_returns_unknown(self):
        naive_now = datetime(2026, 10, 1, 12, 0, 0)
        self.assertEqual(self.call_prepare(now=naive_now).status, "UNKNOWN")

    def test_malformed_existing_command_ids_returns_unknown(self):
        for existing in [None, 123, [123], {"a": 1}]:
            self.assertEqual(self.call_prepare(existing_ids=existing).status, "UNKNOWN")

    def test_identical_inputs_byte_identical_body(self):
        res1 = self.call_prepare()
        res2 = self.call_prepare()
        self.assertEqual(res1.review_body, res2.review_body)

if __name__ == '__main__':
    unittest.main()
