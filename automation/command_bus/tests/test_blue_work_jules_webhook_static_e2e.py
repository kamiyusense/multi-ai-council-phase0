import json
import unittest
from datetime import datetime, timezone

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
    prepare_jules_semiauto_request,
    prepare_next_action,
)
from automation.command_bus.jules_api_request import validate_request


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

        # 3. mock Blue Work terminal receipt (test-only helper)
        def check_generation_fence(cmd_gen, active_gen, expected_gen):
            if cmd_gen != active_gen or active_gen != expected_gen:
                return False
            return True

        self.assertTrue(check_generation_fence(parsed["worker_generation"], self.worker_generation, self.worker_generation))

        # 4. Mock terminal receipt & mock Controller PASS/CONTINUE next-task decision
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

        # 6. prepare_jules_semiauto_request
        jules_req = prepare_jules_semiauto_request(
            next_action.request,
            target_branch=self.work_branch,
            default_branch="main",
            created_at=self.now.isoformat(),
        )
        self.assertEqual(jules_req.status, "PREPARED")
        req = jules_req.request

        # 7. validate_request
        validated = validate_request(req, now=self.now)
        self.assertEqual(validated["profile"], "JULES_CHAT_SEMIAUTO_V2")
        self.assertEqual(validated["target_branch"], self.work_branch)
        self.assertEqual(validated["expected_target_head"], self.head_sha_1)
        self.assertEqual(validated["expected_target_tree"], self.tree_sha)
        self.assertEqual(validated["retry"], 0)
        self.assertEqual(validated["fallback"], "disabled")
        self.assertEqual(validated["merge_allowed"], False)
        self.assertEqual(validated["force_push_allowed"], False)
        self.assertEqual(validated["origin_loop_id"], "loop-1")
        self.assertEqual(validated["origin_round"], 1)
        self.assertEqual(validated["origin_correlation_id"], "loop-1-round-1")
        self.assertEqual(validated["origin_generation"], self.worker_generation)

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

        # 10. Stale old-head case
        target_stale = TargetSnapshot(self.repo, self.pr_number, self.work_branch, self.head_sha_1, self.head_sha_2)
        prepare_res_stale = prepare_blue_work_wake(classification, carrier, target_stale, (), self.expires_at, self.now)
        self.assertEqual(prepare_res_stale.status, "STALE")

        # 11. Generation mismatch
        self.assertFalse(check_generation_fence(parsed["worker_generation"], self.worker_generation + 1, self.worker_generation))
        self.assertFalse(check_generation_fence(parsed["worker_generation"], self.worker_generation, self.worker_generation + 1))

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
        def mock_receipt_gate(receipt, expected_cmd_id, expected_gen, expected_head):
            if receipt.get("command_id") != expected_cmd_id:
                return False
            if receipt.get("worker_generation") != expected_gen:
                return False
            if receipt.get("expected_target_head") != expected_head:
                return False
            if not receipt.get("terminal"):
                return False
            return True

        valid_receipt = {
            "command_id": "cmd-1",
            "worker_generation": 1,
            "expected_target_head": "h1",
            "terminal": True
        }
        self.assertTrue(mock_receipt_gate(valid_receipt, "cmd-1", 1, "h1"))

        self.assertFalse(mock_receipt_gate(valid_receipt, "cmd-2", 1, "h1"))
        self.assertFalse(mock_receipt_gate(valid_receipt, "cmd-1", 2, "h1"))
        self.assertFalse(mock_receipt_gate(valid_receipt, "cmd-1", 1, "h2"))

        invalid_terminal = dict(valid_receipt, terminal=False)
        self.assertFalse(mock_receipt_gate(invalid_terminal, "cmd-1", 1, "h1"))
