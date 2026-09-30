import json
import unittest
from datetime import datetime, timezone
import os
import sys
import subprocess
import tempfile
import copy

class TestClaudeJulesCurrentCarrierCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We need to dynamically load the feature branch files since this is an audit of the current carrier.
        # But for tests, we should write them to a temp dir and add it to sys.path
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(cls.temp_dir.name, 'automation_compat', 'command_bus'), exist_ok=True)
        with open(os.path.join(cls.temp_dir.name, 'automation_compat', '__init__.py'), 'w') as init_file:
            pass
        with open(os.path.join(cls.temp_dir.name, 'automation_compat', 'command_bus', '__init__.py'), 'w') as init_file:
            pass

        # origin/feature/chat-work-command-bus
        req_src = subprocess.check_output(['git', 'show', 'origin/feature/chat-work-command-bus:automation/command_bus/jules_api_request.py']).decode('utf-8')
        with open(os.path.join(cls.temp_dir.name, 'automation_compat', 'command_bus', 'jules_api_request.py'), 'w') as req_file:
            req_file.write(req_src)

        claim_src = subprocess.check_output(['git', 'show', 'origin/feature/chat-work-command-bus:automation/command_bus/loop_id_claim.py']).decode('utf-8')
        with open(os.path.join(cls.temp_dir.name, 'automation_compat', 'command_bus', 'loop_id_claim.py'), 'w') as claim_file:
            claim_file.write(claim_src)

        sys.path.insert(0, cls.temp_dir.name)

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.temp_dir.name)
        cls.temp_dir.cleanup()
        to_del = [k for k in sys.modules if k.startswith('automation_compat')]
        for k in to_del:
            del sys.modules[k]

    def setUp(self):
        self.now = datetime(2026, 9, 30, 0, 30, tzinfo=timezone.utc)
        self.created_at = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc).isoformat()
        self.expires_at = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc).isoformat()

        self.valid_request = {
            "schema_version": 2,
            "profile": "JULES_CHAT_SEMIAUTO_V2",
            "command_id": "relay-dev-loop-123-compat-baseline",
            "target_repo": "kamiyusense/multi-ai-council-phase0",
            "target_branch": "feature/bounded-target",
            "work_branch": "jules-work/relay-dev-loop-123-compat-baseline",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "allowed_paths": ["docs/CLAUDE_NIGHT_LOOP_DESIGN.md"],
            "prompt": "Test baseline",
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "retry": 0,
            "fallback": "disabled",
            "merge_allowed": False,
            "force_push_allowed": False
        }

        self.valid_claim = {
            "schema_version": 3,
            "loop_number": 123,
            "loop_id": "123",
            "task_id": "compat-baseline",
            "command_id": "relay-dev-loop-123-compat-baseline",
            "target_branch": "feature/bounded-target",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "work_branch": "jules-work/relay-dev-loop-123-compat-baseline",
            "state": "CLAIMED",
            "claimed_at": self.created_at,
            "retry": 0,
            "fallback": "disabled",
            "lane_id": "J-GREEN",
            "lane_display": "💚",
            "duplicate_guard": "one file per loop number; create-only; if exists choose a new number"
        }

    def test_baseline_validates(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        from automation_compat.command_bus.loop_id_claim import validate_claim, verify_command_claim
        req = validate_request(self.valid_request, now=self.now)
        self.assertIsNotNone(req)
        claim = validate_claim(self.valid_claim)
        self.assertIsNotNone(claim)
        verified = verify_command_claim(self.valid_request, self.valid_claim)
        self.assertIsNotNone(verified)

    def test_real_target_side_bridge_proof(self):
        from automation.command_bus.claude_loop import prepare_jules_semiauto_request, LoopResult
        from automation_compat.command_bus.jules_api_request import validate_request, REQUIRED_KEYS

        prepared = {
            "request_id": "req-1",
            "loop_id": "123",
            "round": 1,
            "correlation_id": "cor-1",
            "generation": 1,
            "expected_repo": "kamiyusense/multi-ai-council-phase0",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "expected_pr": 99,
            "path_policy": [{"path": "docs/CLAUDE_NIGHT_LOOP_DESIGN.md", "allowed_ops": ["ADD"]}],
            "objective": "Test",
            "expires_at": self.expires_at,
            "executor_kind": "jules-api",
            "action": "PREPARE_JULES_API_REQUEST",
            "execution_mode": "PREPARE_ONLY",
            "capability": "prepare-only",
            "retry": 0,
            "fallback": "disabled",
            "workspace_integrity_profile": "TREE_IDENTITY_V1",
            "requires_live_model": False,
            "requires_github_write": False,
            "live_start_permitted": False,
        }

        result = prepare_jules_semiauto_request(
            prepared,
            target_branch="feature/bounded-target",
            default_branch="main",
            created_at=self.created_at,
            command_id="relay-dev-loop-123-compat-baseline"
        )
        self.assertEqual(result.status, "PREPARED")
        req = result.request

        # Output carries origin_loop_id, origin_round, origin_correlation_id, origin_generation
        self.assertEqual(req["origin_loop_id"], "123")
        self.assertEqual(req["origin_round"], 1)
        self.assertEqual(req["origin_correlation_id"], "cor-1")
        self.assertEqual(req["origin_generation"], 1)

        # Validate with current carrier validator, proves rejection
        with self.assertRaises(ValueError) as cm:
            validate_request(req, now=self.now)
        self.assertIn("request keys mismatch", str(cm.exception))

        # Change schema_version to 2, still rejected
        req["schema_version"] = 2
        with self.assertRaises(ValueError) as cm:
            validate_request(req, now=self.now)
        self.assertIn("request keys mismatch", str(cm.exception))
        self.assertIn("'work_branch'", str(cm.exception))

    def test_request_schema_version_mismatch(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        req_copy["schema_version"] = 1
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("unsupported request profile", str(cm.exception))

    def test_request_missing_work_branch(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        del req_copy["work_branch"]
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("request keys mismatch", str(cm.exception))
        self.assertIn("work_branch", str(cm.exception))

    def test_request_wrong_work_branch_derivation(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        req_copy["work_branch"] = "jules-work/wrong-branch-name"
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("work_branch must be the isolated per-command branch", str(cm.exception))

    def test_request_target_branch_equals_work_branch(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        # Set target_branch to the valid work_branch so that the derivation check passes,
        # but the equality check fails.
        req_copy["target_branch"] = req_copy["work_branch"]
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("work_branch must differ from canonical target_branch", str(cm.exception))

    def test_request_unsupported_origin_field(self):
        from automation_compat.command_bus.jules_api_request import validate_request
        req_copy = self.valid_request.copy()
        req_copy["origin_loop_id"] = "456"
        with self.assertRaises(ValueError) as cm:
            validate_request(req_copy, now=self.now)
        self.assertIn("request keys mismatch", str(cm.exception))
        self.assertIn("origin_loop_id", str(cm.exception))

    def test_claim_missing_claim_file_through_verify_claim_file(self):
        from automation_compat.command_bus.loop_id_claim import verify_claim_file
        import json
        import os

        with tempfile.TemporaryDirectory() as td:
            req_path = os.path.join(td, "request.json")
            with open(req_path, "w") as f:
                json.dump(self.valid_request, f)

            claims_dir = os.path.join(td, "claims")
            os.makedirs(claims_dir, exist_ok=True)

            with self.assertRaises(ValueError) as cm:
                verify_claim_file(req_path, claims_dir)
            self.assertIn("missing durable Loop claim", str(cm.exception))

    def test_claim_schema_version_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["schema_version"] = 2
        claim_copy["lane_id"] = "J-GREEN"
        claim_copy["lane_display"] = "🟩"  # Legacy lane display to pass validate_claim
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("numbered dispatch requires claim schema_version 3", str(cm.exception))

    def test_claim_historical_backfill(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["state"] = "HISTORICAL_BACKFILL"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("numbered dispatch requires a pre-dispatch CLAIMED claim", str(cm.exception))

    def test_claim_lane_id_lane_display_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import validate_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["lane_display"] = "❤️" # mismatched display for J-GREEN
        with self.assertRaises(ValueError) as cm:
            validate_claim(claim_copy)
        self.assertIn("lane_id/lane_display mismatch", str(cm.exception))

    def test_cross_binding_expected_target_head_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["expected_target_head"] = "0000000000000000000000000000000000000000"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("command/claim expected_target_head mismatch", str(cm.exception))

    def test_cross_binding_expected_target_tree_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["expected_target_tree"] = "0000000000000000000000000000000000000000"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("command/claim expected_target_tree mismatch", str(cm.exception))

    def test_cross_binding_work_branch_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        claim_copy["work_branch"] = "jules-work/relay-dev-loop-123-different"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("claim work_branch/command_id mismatch", str(cm.exception))

    def test_cross_binding_command_id_mismatch(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        claim_copy = self.valid_claim.copy()
        # Change command_id and work_branch in claim so that validate_claim succeeds but cross-binding fails
        claim_copy["command_id"] = "relay-dev-loop-123-different"
        claim_copy["work_branch"] = "jules-work/relay-dev-loop-123-different"
        claim_copy["task_id"] = "different"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(self.valid_request, claim_copy)
        self.assertIn("command/claim command_id mismatch", str(cm.exception))

    def test_cross_binding_mismatch_with_request_mutation(self):
        from automation_compat.command_bus.loop_id_claim import verify_command_claim
        req_copy = self.valid_request.copy()
        req_copy["work_branch"] = "jules-work/relay-dev-loop-123-different"
        with self.assertRaises(ValueError) as cm:
            verify_command_claim(req_copy, self.valid_claim)
        self.assertIn("command/claim work_branch mismatch", str(cm.exception))

    def test_origin_fields_not_in_required_keys_and_rejected_if_added(self):
        from automation_compat.command_bus.jules_api_request import validate_request, REQUIRED_KEYS
        from automation_compat.command_bus.loop_id_claim import validate_claim, V3_REQUIRED_KEYS

        origin_fields = ["origin_loop_id", "origin_round", "origin_correlation_id", "origin_generation"]

        # Verify fields are absent from REQUIRED_KEYS and V3_REQUIRED_KEYS
        for field in origin_fields:
            self.assertNotIn(field, REQUIRED_KEYS)
            self.assertNotIn(field, V3_REQUIRED_KEYS)

        # Verify request rejects them
        req_copy = self.valid_request.copy()
        for field in origin_fields:
            req_copy[field] = "some-value"
        with self.assertRaises(ValueError) as cm_req:
            validate_request(req_copy, now=self.now)
        self.assertIn("request keys mismatch", str(cm_req.exception))
        for field in origin_fields:
            self.assertIn(field, str(cm_req.exception))

        # Verify claim rejects them
        claim_copy = self.valid_claim.copy()
        for field in origin_fields:
            claim_copy[field] = "some-value"
        with self.assertRaises(ValueError) as cm_claim:
            validate_claim(claim_copy)
        self.assertIn("claim keys mismatch", str(cm_claim.exception))
        for field in origin_fields:
            self.assertIn(field, str(cm_claim.exception))
