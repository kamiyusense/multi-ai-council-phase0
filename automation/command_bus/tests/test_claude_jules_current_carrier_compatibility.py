import unittest
from typing import Any
from datetime import datetime, timezone, timedelta

from automation.command_bus.claude_loop import prepare_jules_semiauto_request

# Mirrored carrier protocol exact required keys (from feature/chat-work-command-bus)
CARRIER_REQUIRED_KEYS = {
    "schema_version",
    "profile",
    "command_id",
    "target_repo",
    "target_branch",
    "work_branch",
    "expected_target_head",
    "expected_target_tree",
    "allowed_paths",
    "prompt",
    "created_at",
    "expires_at",
    "retry",
    "fallback",
    "merge_allowed",
    "force_push_allowed",
}
CARRIER_PROFILE = "JULES_CHAT_SEMIAUTO_V2"

class TestClaudeJulesCurrentCarrierCompatibility(unittest.TestCase):
    def test_main_bridge_vs_carrier_mismatch(self) -> None:
        """
        Pin the exact static incompatibility between the merged Claude AUTO
        JULES_BACKEND bridge on main and the current Jules semi-auto carrier protocol.
        """
        created_at = datetime.now(timezone.utc)
        expires_at = (created_at + timedelta(hours=1)).isoformat()
        created_at_iso = created_at.isoformat()

        prepared_request = {
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
            "path_policy": [
                {"path": "foo.py", "allowed_ops": ["ADD", "MODIFY"]}
            ],
            "objective": "Test objective",
            "request_id": "req-1",
            "loop_id": "001",
            "correlation_id": "corr-123",
            "expected_repo": "kamiyusense/multi-ai-council-phase0",
            "expected_target_head": "a" * 40,
            "expected_target_tree": "b" * 40,
            "expires_at": expires_at,
            "round": 1,
            "expected_pr": 1,
            "generation": 1,
        }

        target_branch = "feature/test-branch"
        default_branch = "main"

        result = prepare_jules_semiauto_request(
            prepared_request,
            target_branch=target_branch,
            default_branch=default_branch,
            created_at=created_at_iso,
            command_id="001-julesapi-1"
        )

        self.assertEqual(result.status, "PREPARED", msg=result.reason)
        main_output = result.request
        self.assertIsNotNone(main_output)

        # 1. schema_version mismatch
        self.assertEqual(main_output["schema_version"], 1)
        self.assertNotEqual(main_output["schema_version"], 2)

        # 2. profile check
        self.assertEqual(main_output["profile"], CARRIER_PROFILE)

        # 3. Exact required key set mismatch
        main_keys = set(main_output.keys())
        self.assertNotEqual(main_keys, CARRIER_REQUIRED_KEYS)

        # 4. work_branch missing and target/work branch separation gap
        self.assertNotIn("work_branch", main_keys)
        self.assertIn("work_branch", CARRIER_REQUIRED_KEYS)
        # Carrier expects target_branch != work_branch, but main only knows target_branch.

        # 5. extra origin fields rejected by exact carrier schema
        for origin_field in ["origin_loop_id", "origin_round", "origin_correlation_id", "origin_generation"]:
            self.assertIn(origin_field, main_keys)
            self.assertNotIn(origin_field, CARRIER_REQUIRED_KEYS)

        # 6. expected_target_head/tree binding: they exist in main_output, but missing work_branch means
        # the payload cannot satisfy the carrier's full branch binding requirements.
        self.assertIn("expected_target_head", main_keys)
        self.assertIn("expected_target_tree", main_keys)

        # 7. Claim schema v3 / cross-binding:
        # We verify that main does not output lane_id, lane_display, or a schema_version 3 claim payload natively.
        # Main only outputs the request dictionary above, lacking any claim structure.
        self.assertNotIn("lane_id", main_keys)
        self.assertNotIn("lane_display", main_keys)
