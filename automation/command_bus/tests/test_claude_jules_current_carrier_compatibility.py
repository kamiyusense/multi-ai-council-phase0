import unittest
import subprocess
import sys
import importlib.util
from datetime import datetime, timedelta, timezone

from automation.command_bus.claude_loop import prepare_jules_semiauto_request

class TestClaudeJulesCurrentCarrierCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Fetch the current carrier code exactly as requested without mutating branch
        # This isolates the test without depending on the current branch's files.
        carrier_sha = "28435327c8e065a977686c2e7d995336f1358d11"
        try:
            jules_api_request_src = subprocess.check_output(
                ["git", "show", f"{carrier_sha}:automation/command_bus/jules_api_request.py"]
            ).decode("utf-8")
            loop_id_claim_src = subprocess.check_output(
                ["git", "show", f"{carrier_sha}:automation/command_bus/loop_id_claim.py"]
            ).decode("utf-8")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Could not read carrier branch, test aborted: {e}")

        import tempfile
        import os

        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.sys_path_orig = list(sys.path)
        sys.path.insert(0, cls.temp_dir.name)

        jules_api_request_path = os.path.join(cls.temp_dir.name, "carrier_jules_api_request.py")
        loop_id_claim_path = os.path.join(cls.temp_dir.name, "carrier_loop_id_claim.py")

        with open(jules_api_request_path, "w") as f:
            f.write(jules_api_request_src)

        with open(loop_id_claim_path, "w") as f:
            f.write(loop_id_claim_src)

        cls.jules_mod = cls._load_module("carrier_jules_api_request", jules_api_request_path)
        cls.claim_mod = cls._load_module("carrier_loop_id_claim", loop_id_claim_path)

    @classmethod
    def tearDownClass(cls):
        sys.path = cls.sys_path_orig
        for mod in ["carrier_jules_api_request", "carrier_loop_id_claim"]:
            if mod in sys.modules:
                del sys.modules[mod]
        cls.temp_dir.cleanup()

    @classmethod
    def _load_module(cls, name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.expires = (self.now + timedelta(hours=1)).isoformat()
        self.created = self.now.isoformat()

        # This is a mock verdict that will be prepared by the bridge.
        self.verdict = {
            "schema_version": 1,
            "verdict_id": "v-123",
            "loop_id": "claude-night-123",
            "round": 1,
            "generation": 1,
            "correlation_id": "corr-123",
            "backend_mode": "CLAUDE_BACKEND",
            "decision": "CONTINUE",
            "reasons": ["some reason"],
            "next_prompt": "some prompt",
            "evidence_refs": [],
            "expected_target_head": "a" * 40,
            "expected_target_tree": "b" * 40,
            "terminal": False,
            "retry": 0,
            "fallback": "disabled",
            "execution_mode": "PREPARE_ONLY",
            "model_executed": False,
            "external_send_attempted": False,
        }
        self.prepared = {
            "request_id": "req-123",
            "loop_id": "claude-night-123",
            "round": 1,
            "generation": 1,
            "correlation_id": "corr-123",
            "executor_role": "implementation",
            "executor_kind": "jules-api",
            "action": "PREPARE_JULES_API_REQUEST",
            "execution_mode": "PREPARE_ONLY",
            "capability": "prepare-only",
            "expected_repo": "kamiyusense/multi-ai-council-phase0",
            "expected_pr": 123,
            "expected_target_head": "a" * 40,
            "expected_target_tree": "b" * 40,
            "workspace_integrity_profile": "TREE_IDENTITY_V1",
            "requires_live_model": False,
            "requires_github_write": False,
            "live_start_permitted": False,
            "objective": "Test objective",
            "path_policy": [{"path": "tests/example.py", "allowed_ops": ["MODIFY"]}],
            "expires_at": self.expires,
            "verdict_ref": "v-123",
            "retry": 0,
            "fallback": "disabled"
        }

        # Actual request out of the target-side bridge
        result = prepare_jules_semiauto_request(
            self.prepared,
            target_branch="feature/bounded-target",
            default_branch="main",
            created_at=self.created,
            command_id="claude-night-123",
        )
        self.assertEqual(result.status, "PREPARED")
        self.bridge_request = result.request

        # -------------------------------------------------------------
        # This valid request is what the CARRIER BRANCH expects.
        # It is used for pure carrier negative tests.
        self.valid_carrier_request = {
            "schema_version": 2,
            "profile": self.jules_mod.PROFILE,
            "command_id": "claude-night-123",
            "target_repo": "kamiyusense/multi-ai-council-phase0",
            "target_branch": "feature/bounded-target",
            "work_branch": "jules-work/claude-night-123",
            "expected_target_head": "a" * 40,
            "expected_target_tree": "b" * 40,
            "allowed_paths": ["tests/example.py"],
            "prompt": "Test task",
            "created_at": self.created,
            "expires_at": self.expires,
            "retry": 0,
            "fallback": "disabled",
            "merge_allowed": False,
            "force_push_allowed": False,
        }
        self.valid_carrier_claim = {
            "schema_version": 3,
            "loop_number": 123,
            "loop_id": "123",
            "task_id": "",
            "command_id": "claude-night-123",
            "target_branch": "feature/bounded-target",
            "expected_target_head": "a" * 40,
            "expected_target_tree": "b" * 40,
            "work_branch": "jules-work/claude-night-123",
            "state": "CLAIMED",
            "lane_id": "J-GREEN",
            "lane_display": "💚",
            "claimed_at": self.created,
            "duplicate_guard": self.claim_mod.DUPLICATE_GUARD,
            "retry": 0,
            "fallback": "disabled",
        }

    def test_actual_bridge_output_mismatch(self):
        # 2. Demonstrate the target-side prepare_jules_semiauto_request() output contract directly
        self.assertEqual(self.bridge_request["schema_version"], 1)
        self.assertEqual(self.bridge_request["profile"], "JULES_CHAT_SEMIAUTO_V2")
        self.assertEqual(self.bridge_request["origin_loop_id"], "claude-night-123")
        self.assertEqual(self.bridge_request["origin_round"], 1)
        self.assertEqual(self.bridge_request["origin_correlation_id"], "corr-123")
        self.assertEqual(self.bridge_request["origin_generation"], 1)

        # 3. Prove exact mismatch between the bridge's output and the carrier.
        # The carrier validator will reject it because:
        # a) the carrier requires schema_version = 2 (bridge outputs 1)
        # b) the carrier rejects 'origin_*' fields (bridge outputs them)
        # c) the carrier requires 'work_branch' (bridge output doesn't have it natively)
        with self.assertRaises(ValueError) as cm:
            self.jules_mod.validate_request(self.bridge_request, now=self.now)

        err = str(cm.exception)
        self.assertTrue("request keys mismatch" in err or "unsupported request profile" in err or "missing=" in err)

        # Even if we "fix" the schema version, the keys mismatch (missing work_branch, extra origin fields)
        patched_req = dict(self.bridge_request)
        patched_req["schema_version"] = 2
        with self.assertRaises(ValueError) as cm2:
            self.jules_mod.validate_request(patched_req, now=self.now)
        err2 = str(cm2.exception)
        self.assertIn("request keys mismatch", err2)
        self.assertIn("origin_loop_id", err2)

    def test_valid_carrier_request(self):
        self.assertEqual(self.jules_mod.validate_request(self.valid_carrier_request, now=self.now), self.valid_carrier_request)

    def test_request_schema_version_mismatch(self):
        req = dict(self.valid_carrier_request)
        req["schema_version"] = 1
        with self.assertRaises(ValueError):
            self.jules_mod.validate_request(req, now=self.now)

    def test_missing_work_branch(self):
        req = dict(self.valid_carrier_request)
        del req["work_branch"]
        with self.assertRaises(ValueError):
            self.jules_mod.validate_request(req, now=self.now)

    def test_wrong_work_branch_derivation(self):
        req = dict(self.valid_carrier_request)
        req["work_branch"] = "jules-work/wrong-id"
        with self.assertRaises(ValueError):
            self.jules_mod.validate_request(req, now=self.now)

    def test_target_branch_equals_work_branch(self):
        req = dict(self.valid_carrier_request)
        req["target_branch"] = req["work_branch"]
        with self.assertRaises(ValueError):
            self.jules_mod.validate_request(req, now=self.now)

    def test_unsupported_extra_origin_fields(self):
        req = dict(self.valid_carrier_request)
        req["origin_loop_id"] = "xyz"
        with self.assertRaises(ValueError):
            self.jules_mod.validate_request(req, now=self.now)

    def test_missing_claim_handled_by_verify_command_claim(self):
        with self.assertRaises(ValueError):
            self.claim_mod.verify_command_claim(self.valid_carrier_request, {"missing": "claim"})

    def test_claim_schema_version_mismatch(self):
        claim = dict(self.valid_carrier_claim)
        claim["schema_version"] = 2
        with self.assertRaises(ValueError):
            self.claim_mod.verify_command_claim(self.valid_carrier_request, claim)

    def test_claim_state_not_claimed(self):
        claim = dict(self.valid_carrier_claim)
        claim["state"] = "HISTORICAL_BACKFILL"
        with self.assertRaises(ValueError):
            self.claim_mod.verify_command_claim(self.valid_carrier_request, claim)

    def test_lane_id_display_mismatch(self):
        claim = dict(self.valid_carrier_claim)
        claim["lane_id"] = "J-GREEN"
        claim["lane_display"] = "❤️"
        with self.assertRaises(ValueError):
            self.claim_mod.verify_command_claim(self.valid_carrier_request, claim)

    def test_claim_request_head_mismatch(self):
        req = dict(self.valid_carrier_request)
        req["expected_target_head"] = "c" * 40
        with self.assertRaises(ValueError):
            self.claim_mod.verify_command_claim(req, self.valid_carrier_claim)

    def test_claim_request_tree_mismatch(self):
        req = dict(self.valid_carrier_request)
        req["expected_target_tree"] = "c" * 40
        with self.assertRaises(ValueError):
            self.claim_mod.verify_command_claim(req, self.valid_carrier_claim)

    def test_claim_request_work_branch_mismatch(self):
        req = dict(self.valid_carrier_request)
        req["command_id"] = "claude-night-456"
        req["work_branch"] = "jules-work/claude-night-456"
        with self.assertRaises(ValueError):
            self.claim_mod.verify_command_claim(req, self.valid_carrier_claim)

    def test_origin_binding_gap(self):
        # Prove ORIGIN_BINDING_GAP / BLOCKED_UNKNOWN
        # The carrier's validation strictly fails if AUTO correctness identity fields are present,
        # and its REQUIRED_KEYS / V3_REQUIRED_KEYS do not mandate them.

        self.assertNotIn("origin_loop_id", self.jules_mod.REQUIRED_KEYS)
        self.assertNotIn("origin_round", self.jules_mod.REQUIRED_KEYS)
        self.assertNotIn("origin_correlation_id", self.jules_mod.REQUIRED_KEYS)
        self.assertNotIn("origin_generation", self.jules_mod.REQUIRED_KEYS)

        self.assertNotIn("origin_loop_id", self.claim_mod.V3_REQUIRED_KEYS)
        self.assertNotIn("origin_round", self.claim_mod.V3_REQUIRED_KEYS)
        self.assertNotIn("origin_correlation_id", self.claim_mod.V3_REQUIRED_KEYS)
        self.assertNotIn("origin_generation", self.claim_mod.V3_REQUIRED_KEYS)

if __name__ == '__main__':
    unittest.main()
