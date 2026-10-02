import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from automation.command_bus.blue_jules_result_event import (
    EventDecision,
    EventLineage,
    classify_blue_jules_result_event,
)
from automation.command_bus.blue_work_wake_prepare import (
    CarrierSnapshot,
    TargetSnapshot,
    prepare_blue_work_wake,
)
from automation.command_bus.claude_loop import (
    BackendMode,
    VerdictDecision,
    make_structured_verdict,
    numbered_command_id,
    prepare_jules_semiauto_bundle,
    prepare_jules_semiauto_request,
    prepare_loop_claim,
    prepare_next_action,
)
# The Jules carrier owns the request contract. Origin identity travels in
# the durable origin-binding record instead of the carrier request body.
from automation.command_bus.jules_carrier_current.jules_api_request import validate_request


class TestBlueWorkJulesWebhookStaticE2E(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.expires_at = "2026-10-01T13:00:00+00:00"
        self.repo = "kamiyusense/multi-ai-council-phase0"
        self.pr_number = 42
        self.work_branch = "jules-work/test-branch"
        self.head_sha_1 = "a" * 40
        self.head_sha_2 = "b" * 40
        self.base_sha = "c" * 40
        self.tree_sha = "d" * 40
        self.cmd_id = "source-cmd-123"
        self.worker_generation = 1

    def make_event(self, head_sha, action="opened"):
        return {
            "action": action,
            "repository": {"full_name": self.repo},
            "pull_request": {
                "number": self.pr_number,
                "head": {"sha": head_sha},
                "base": {"ref": self.work_branch, "sha": self.base_sha},
            },
        }

    def make_lineage(self, expected_target_head):
        return EventLineage(
            source_command_id=self.cmd_id,
            work_branch=self.work_branch,
            expected_target_head=expected_target_head,
            expected_repository=self.repo,
        )

    @staticmethod
    def mock_generation_gate(command_generation, active_generation, fixed_worker_generation):
        return (
            type(command_generation) is int
            and type(active_generation) is int
            and type(fixed_worker_generation) is int
            and command_generation > 0
            and command_generation == active_generation == fixed_worker_generation
        )

    @staticmethod
    def mock_receipt_gate(receipt, expected_command, expected_generation):
        if not isinstance(receipt, dict) or not isinstance(expected_command, dict):
            return False
        expected = {
            "protocol_version": 1,
            "command_id": expected_command["command_id"],
            "worker_generation": expected_generation,
            "status": "PASS",
            "target_repository": expected_command["target_repository"],
            "target_pr": expected_command["target_pr"],
            "target_branch": expected_command["target_branch"],
            "target_head_before": expected_command["expected_target_head"],
            "target_head_after": expected_command["expected_target_head"],
            "terminal": True,
        }
        return (
            type(receipt.get("protocol_version")) is int
            and type(receipt.get("worker_generation")) is int
            and type(receipt.get("target_pr")) is int
            and type(receipt.get("terminal")) is bool
            and all(receipt.get(key) == value for key, value in expected.items())
        )

    @staticmethod
    def make_receipt(command):
        return {
            "protocol_version": 1,
            "command_id": command["command_id"],
            "worker_generation": command["worker_generation"],
            "status": "PASS",
            "target_repository": command["target_repository"],
            "target_pr": command["target_pr"],
            "target_branch": command["target_branch"],
            "target_head_before": command["expected_target_head"],
            "target_head_after": command["expected_target_head"],
            "verification": ["mock independent diff and test evidence inspected"],
            "terminal": True,
        }

    def test_basic_flow(self):
        # 1. mock Jules PR opened event -> BWJ-1 classifier
        event = self.make_event(self.head_sha_1)
        lineage = self.make_lineage(self.base_sha)
        classification = classify_blue_jules_result_event(event, lineage, ())
        self.assertEqual(classification.decision, EventDecision.WAKE)
        self.assertEqual(classification.command_id, f"blue-jules-result-pr{self.pr_number}-{self.head_sha_1}")

        # 2. BWJ-2 prepare-only Blue wake command
        carrier = CarrierSnapshot(1, "blue", "[CW_BLUE_V1]", self.worker_generation)
        target = TargetSnapshot(self.repo, self.pr_number, self.work_branch, self.head_sha_1, self.head_sha_1)
        prepare_res = prepare_blue_work_wake(classification, carrier, target, (), self.expires_at, self.now)
        self.assertEqual(prepare_res.status, "PREPARED")
        self.assertTrue(prepare_res.review_body.startswith("[CW_BLUE_V1]\n"))

        parsed = json.loads(prepare_res.review_body.split("\n", 1)[1])
        self.assertEqual(parsed["worker_generation"], self.worker_generation)
        self.assertEqual(parsed["target_pr"], self.pr_number)
        self.assertEqual(parsed["target_branch"], self.work_branch)
        self.assertEqual(parsed["expected_target_head"], self.head_sha_1)
        self.assertEqual(parsed["retry"], 0)
        self.assertEqual(parsed["fallback"], "disabled")
        self.assertEqual(parsed["live_provider_or_model_allowed"], False)
        self.assertEqual(parsed["allowed_paths"], [])

        # 3. Current Blue worker, carrier state and command must all match.
        self.assertTrue(self.mock_generation_gate(
            parsed["worker_generation"], self.worker_generation, self.worker_generation
        ))

        # 4. Only a matching terminal PASS receipt permits Controller continuation.
        blue_receipt = self.make_receipt(parsed)
        self.assertTrue(self.mock_receipt_gate(
            blue_receipt, parsed, self.worker_generation
        ))
        verdict = make_structured_verdict(
            verdict_id="verdict-1",
            loop_id="loop-1",
            round=1,
            generation=self.worker_generation,
            correlation_id="loop-1-round-1",
            mode=BackendMode.JULES_BACKEND.value,
            decision=VerdictDecision.CONTINUE.value,
            expected_target_head=self.head_sha_1,
            expected_target_tree=self.tree_sha,
            reasons=["looks good"],
            evidence_refs=["some_evidence"],
            next_prompt="do next thing",
            terminal=False,
        )
        verdict["retry"] = 0
        verdict["fallback"] = "disabled"
        verdict["execution_mode"] = "PREPARE_ONLY"
        verdict["model_executed"] = False
        verdict["external_send_attempted"] = False

        # 5. prepare_next_action
        path_policy = [{"path": "some/path", "allowed_ops": ["ADD", "MODIFY"]}]
        next_action = prepare_next_action(
            verdict,
            expected_repo=self.repo,
            expected_pr=self.pr_number,
            expires_at=self.expires_at,
            path_policy=path_policy,
        )
        self.assertEqual(next_action.status, "PREPARED")

        # 6. prepare current carrier request + schema-v3 claim + origin binding
        command_id = numbered_command_id(1, "blue-e2e")
        common = dict(
            target_branch=self.work_branch,
            default_branch="main",
            created_at=self.now.isoformat(),
            command_id=command_id,
        )
        jules_req = prepare_jules_semiauto_request(next_action.request, **common)
        self.assertEqual(jules_req.status, "PREPARED")
        req = jules_req.request
        claim_res = prepare_loop_claim(req, lane_id="J-BLUE", claimed_at=self.now.isoformat())
        self.assertEqual(claim_res.status, "PREPARED", claim_res.reason)
        bundle = prepare_jules_semiauto_bundle(next_action.request, claim_res.request, **common)
        self.assertEqual(bundle.status, "PREPARED", bundle.reason)
        binding = bundle.request["origin_binding"]

        # 7. validate_request with the current carrier validator
        validated = validate_request(req, now=self.now)
        self.assertEqual(validated["profile"], "JULES_CHAT_SEMIAUTO_V2")
        self.assertEqual(validated["target_branch"], self.work_branch)
        self.assertEqual(validated["expected_target_head"], self.head_sha_1)
        self.assertEqual(validated["expected_target_tree"], self.tree_sha)
        self.assertEqual(validated["retry"], 0)
        self.assertEqual(validated["fallback"], "disabled")
        self.assertEqual(validated["merge_allowed"], False)
        self.assertEqual(validated["force_push_allowed"], False)
        self.assertEqual(binding["origin_loop_id"], "loop-1")
        self.assertEqual(binding["origin_round"], 1)
        self.assertEqual(binding["origin_correlation_id"], "loop-1-round-1")
        self.assertEqual(binding["origin_generation"], self.worker_generation)
        self.assertEqual(binding["command_id"], command_id)

        # 8. Replay identical event -> duplicate
        classification_dup = classify_blue_jules_result_event(event, lineage, (classification.command_id,))
        self.assertEqual(classification_dup.decision, EventDecision.IGNORE)
        dup_prepare_res = prepare_blue_work_wake(classification_dup, carrier, target, (classification.command_id,), self.expires_at, self.now)
        self.assertEqual(dup_prepare_res.status, "NO_OP")
        self.assertIsNone(dup_prepare_res.review_body)

        # 9. New head -> new identity
        event_new = self.make_event(self.head_sha_2)
        classification_new = classify_blue_jules_result_event(event_new, lineage, (classification.command_id,))
        self.assertEqual(classification_new.decision, EventDecision.WAKE)
        self.assertNotEqual(classification_new.command_id, classification.command_id)
        target_new = TargetSnapshot(
            self.repo, self.pr_number, self.work_branch,
            self.head_sha_2, self.head_sha_2,
        )
        new_prepared = prepare_blue_work_wake(
            classification_new, carrier, target_new,
            (classification.command_id,), self.expires_at, self.now,
        )
        self.assertEqual(new_prepared.status, "PREPARED")
        new_payload = json.loads(new_prepared.review_body.split("\n", 1)[1])
        self.assertEqual(new_payload["command_id"], classification_new.command_id)
        self.assertEqual(new_payload["expected_target_head"], self.head_sha_2)
        self.assertNotEqual(new_prepared.review_body, prepare_res.review_body)

        # Duplicate protection also applies if classifier inputs were not pre-deduplicated.
        direct_duplicate = prepare_blue_work_wake(
            classification, carrier, target,
            (classification.command_id,), self.expires_at, self.now,
        )
        self.assertEqual(direct_duplicate.status, "NO_OP")
        self.assertIsNone(direct_duplicate.review_body)

        # 10. Stale old-head case
        target_stale = TargetSnapshot(self.repo, self.pr_number, self.work_branch, self.head_sha_1, self.head_sha_2)
        prepare_res_stale = prepare_blue_work_wake(classification, carrier, target_stale, (), self.expires_at, self.now)
        self.assertEqual(prepare_res_stale.status, "STALE")
        self.assertIsNone(prepare_res_stale.review_body)

        # 11. Either current state or fixed worker being stale prevents continuation.
        self.assertFalse(self.mock_generation_gate(
            parsed["worker_generation"], self.worker_generation + 1, self.worker_generation
        ))
        self.assertFalse(self.mock_generation_gate(
            parsed["worker_generation"], self.worker_generation, self.worker_generation + 1
        ))
        self.assertFalse(self.mock_generation_gate(
            True, self.worker_generation, self.worker_generation
        ))

        # 12. Terminal receipt replay prevents next Jules preparation
        receipt = {
            "receipt_id": "r1",
            "state": "CONSUMED",
            "loop_id": "loop-1",
            "round": 1,
            "correlation_id": "loop-1-round-1",
            "expected_target_head": self.head_sha_1,
            "expected_target_tree": self.tree_sha
        }
        next_action_re = prepare_next_action(
            verdict,
            expected_repo=self.repo,
            expected_pr=self.pr_number,
            expires_at=self.expires_at,
            path_policy=path_policy,
            existing_terminal_receipts=[receipt]
        )
        self.assertEqual(next_action_re.status, "NO-OP")

    def test_mock_receipt_gate(self):
        command = {
            "command_id": "blue-jules-result-pr42-" + "a" * 40,
            "worker_generation": 3,
            "target_repository": self.repo,
            "target_pr": 42,
            "target_branch": self.work_branch,
            "expected_target_head": self.head_sha_1,
        }
        valid = self.make_receipt(command)
        self.assertTrue(self.mock_receipt_gate(valid, command, 3))
        cases = {
            "wrong command": {"command_id": "other-command"},
            "wrong generation": {"worker_generation": 2},
            "bool generation": {"worker_generation": True},
            "wrong repository": {"target_repository": "other/repo"},
            "wrong PR": {"target_pr": 43},
            "wrong branch": {"target_branch": "main"},
            "wrong head before": {"target_head_before": self.head_sha_2},
            "wrong head after": {"target_head_after": self.head_sha_2},
            "not terminal": {"terminal": False},
            "truthy nonboolean terminal": {"terminal": 1},
            "not PASS": {"status": "UNKNOWN"},
            "wrong protocol": {"protocol_version": 2},
        }
        for name, changes in cases.items():
            with self.subTest(name=name):
                tampered = {**valid, **changes}
                self.assertFalse(self.mock_receipt_gate(tampered, command, 3))
                # No Controller next-task preparation is allowed on an invalid receipt.
                with patch(
                    "automation.command_bus.tests.test_blue_work_jules_webhook_static_e2e.prepare_next_action"
                ) as forbidden_prepare:
                    if self.mock_receipt_gate(tampered, command, 3):
                        prepare_next_action(None, expected_repo=self.repo,
                                            expected_pr=42, expires_at=self.expires_at,
                                            path_policy=[])
                    forbidden_prepare.assert_not_called()

        for missing in ("command_id", "worker_generation", "target_repository",
                        "target_pr", "target_branch", "target_head_before",
                        "target_head_after", "terminal"):
            with self.subTest(missing=missing):
                tampered = dict(valid)
                del tampered[missing]
                self.assertFalse(self.mock_receipt_gate(tampered, command, 3))
