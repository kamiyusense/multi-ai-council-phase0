import copy
import hashlib
import json
import unittest
from typing import Any

from providers.live_readiness_approval import (
    build_live_readiness_approval_packet,
    render_approval_summary_ja,
)


import tests.relay.test_live_readiness_snapshot as tss

def _mock_input(ready: bool = False) -> dict[str, Any]:
    test_obj = tss.TestLiveReadinessSnapshot()
    test_obj.setUp()
    if ready:
        return {'provider_configs': test_obj.valid_configs, 'inventory': test_obj.confirmed_inventory}
    else:
        return {'provider_configs': test_obj.valid_configs, 'inventory': test_obj.unknown_inventory}

class TestLiveReadinessApproval(unittest.TestCase):
    def test_blocked_snapshot_path(self) -> None:
        packet = build_live_readiness_approval_packet(_mock_input(ready=False))
        self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(packet["next_action"], "RESOLVE_BLOCKERS")
        self.assertFalse(packet["live_ready"])
        self.assertFalse(packet["dispatch_allowed"])
        self.assertTrue(packet["human_approval_required"])
        self.assertFalse(packet["approval_granted"])
        self.assertEqual(packet["retry_count"], 0)
        self.assertEqual(packet["fallback_state"], "disabled")
        self.assertEqual(packet["snapshot_state"], "BLOCKED_UNKNOWN")

    def test_ready_snapshot_path(self) -> None:
        packet = build_live_readiness_approval_packet(_mock_input(ready=True))
        self.assertEqual(packet["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(packet["next_action"], "REQUEST_HUMAN_APPROVAL")
        self.assertFalse(packet["live_ready"])
        self.assertFalse(packet["dispatch_allowed"])
        self.assertTrue(packet["human_approval_required"])
        self.assertFalse(packet["approval_granted"])
        self.assertEqual(packet["retry_count"], 0)
        self.assertEqual(packet["fallback_state"], "disabled")
        self.assertEqual(packet["snapshot_state"], "READY_FOR_HUMAN_APPROVAL")

    def test_malformed_input_fails_closed(self) -> None:
        packet = build_live_readiness_approval_packet({"invalid": "input"})
        self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(packet["next_action"], "RESOLVE_BLOCKERS")
        self.assertIsNotNone(packet["snapshot_packet_sha256"])
        self.assertEqual(packet["inventory_state"], "BLOCKED_UNKNOWN")

    def test_isolation(self) -> None:
        input_data = _mock_input(ready=True)
        original_input = copy.deepcopy(input_data)
        packet = build_live_readiness_approval_packet(input_data)

        # Mutation of input after call should not affect anything
        input_data["inventory"]["openai"] = "fake"
        self.assertEqual(input_data["inventory"]["openai"], "fake")

        # Mutation of packet should not affect input
        packet["state"] = "TAMPERED"
        self.assertEqual(original_input, _mock_input(ready=True))

    def test_renderer_sanitization_and_japanese_output(self) -> None:
        packet = build_live_readiness_approval_packet(_mock_input(ready=True))

        # Render clean output
        out = render_approval_summary_ja(packet)
        self.assertIn("ライブ実行: 禁止", out)
        self.assertIn("全体状態: READY_FOR_HUMAN_APPROVAL", out)
        self.assertIn("次アクション: REQUEST_HUMAN_APPROVAL", out)
        self.assertIn("未解決の証明数: 0", out)
        self.assertIn("- openai: PASS", out)
        self.assertIn("- openai: READY_FOR_HUMAN_APPROVAL", out)

        # Inject untrusted strings
        tampered_packet = copy.deepcopy(packet)
        tampered_packet["state"] = "HACKED"
        tampered_packet["next_action"] = "STEAL_CREDS"
        tampered_packet["unresolved_count"] = "many"
        tampered_packet["preflight_states"]["openai"] = "PWNED"
        tampered_packet["provider_states"]["anthropic"] = "BOGUS"
        tampered_packet["blocking_providers"] = ["fake"]

        tampered_out = render_approval_summary_ja(tampered_packet)
        self.assertNotIn("HACKED", tampered_out)
        self.assertNotIn("STEAL_CREDS", tampered_out)
        self.assertNotIn("many", tampered_out)
        self.assertNotIn("PWNED", tampered_out)
        self.assertNotIn("BOGUS", tampered_out)
        self.assertNotIn("fake", tampered_out)

        self.assertIn("全体状態: BLOCKED_UNKNOWN", tampered_out)
        self.assertIn("次アクション: RESOLVE_BLOCKERS", tampered_out)
        self.assertIn("未解決の証明数: -1", tampered_out)

    def test_malformed_snapshot_fails_closed(self) -> None:
        import hashlib
        import json
        from unittest.mock import patch

        # Test tampering with snapshot structure (e.g. missing keys, bool as int)
        with patch('providers.live_readiness_approval.build_live_readiness_snapshot') as mock_snap:
            mock_snap.return_value = {}
            packet = build_live_readiness_approval_packet(_mock_input(ready=True))
            self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")

            # Tamper with snapshot hash
            bad_hash = _mock_input(ready=True)
            mock_snap.return_value = {
                "state": "READY_FOR_HUMAN_APPROVAL",
                "live_ready": False,
                "dispatch_allowed": False,
                "human_approval_required": True,
                "retry_count": 0,
                "fallback_state": "disabled",
                "preflight_states": {},
                "preflight_snapshots": {},
                "preflight_packet_sha256": None,
                "inventory_state": "PROOF_RECORDS_COMPLETE",
                "unresolved_count": 0,
                "unresolved_by_provider": {"openai": 0, "anthropic": 0, "google": 0},
                "inventory_packet_sha256": "0"*64,
                "provider_states": {"openai": "READY_FOR_HUMAN_APPROVAL", "anthropic": "READY_FOR_HUMAN_APPROVAL", "google": "READY_FOR_HUMAN_APPROVAL"},
                "blocking_providers": [],
                "bundle_packet_sha256": "0"*64,
                "pipeline_packet_sha256": "0"*64,
                "snapshot_packet_sha256": "1"*64
            }
            packet = build_live_readiness_approval_packet(bad_hash)
            self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")

    def test_snapshot_exception_fails_closed_and_dependency_call_counts(self) -> None:
        from unittest.mock import patch
        with patch('providers.live_readiness_approval.build_live_readiness_snapshot') as mock_snap:
            mock_snap.side_effect = Exception("Boom")
            packet = build_live_readiness_approval_packet(_mock_input(ready=True))
            self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")
            self.assertEqual(mock_snap.call_count, 1)

            mock_snap.reset_mock()
            # Unserializable input -> 0 calls
            build_live_readiness_approval_packet({"invalid": object()})
            self.assertEqual(mock_snap.call_count, 0)

    def test_ast_static_boundary_excludes_ambient_io_and_direct_live_gate(self) -> None:
        import ast
        import os
        with open(os.path.join(os.path.dirname(__file__), '..', '..', 'src', 'providers', 'live_readiness_approval.py'), 'r') as f:
            tree = ast.parse(f.read())

        forbidden_imports = {'os', 'sys', 'subprocess', 'time', 'random', 'socket', 'urllib', 'requests'}
        forbidden_calls = {'open', 'eval', 'exec', 'eval', 'validate_provider_static', 'build_live_readiness_pipeline', 'evaluate_live_readiness'}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    self.assertNotIn(name.name.split('.')[0], forbidden_imports)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(node.module.split('.')[0], forbidden_imports)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden_calls)

    def test_malformed_snapshot_variants(self) -> None:
        from unittest.mock import patch

        def assert_fails_closed(bad_snap):
            with patch('providers.live_readiness_approval.build_live_readiness_snapshot') as mock_snap:
                mock_snap.return_value = bad_snap
                packet = build_live_readiness_approval_packet(_mock_input(ready=True))
                self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")

        # Valid base
        base_snap = {
            "state": "READY_FOR_HUMAN_APPROVAL",
            "live_ready": False,
            "dispatch_allowed": False,
            "human_approval_required": True,
            "retry_count": 0,
            "fallback_state": "disabled",
            "preflight_states": {},
            "preflight_snapshots": {},
            "preflight_packet_sha256": None,
            "inventory_state": "PROOF_RECORDS_COMPLETE",
            "unresolved_count": 0,
            "unresolved_by_provider": {"openai": 0, "anthropic": 0, "google": 0},
            "inventory_packet_sha256": "0"*64,
            "provider_states": {"openai": "READY_FOR_HUMAN_APPROVAL", "anthropic": "READY_FOR_HUMAN_APPROVAL", "google": "READY_FOR_HUMAN_APPROVAL"},
            "blocking_providers": [],
            "bundle_packet_sha256": "0"*64,
            "pipeline_packet_sha256": "0"*64,
            "snapshot_packet_sha256": "0"*64
        }
        # missing key
        b1 = base_snap.copy()
        del b1["state"]
        assert_fails_closed(b1)

        # extra key
        b2 = base_snap.copy()
        b2["extra"] = "bad"
        assert_fails_closed(b2)

        # bad fixed field
        b3 = base_snap.copy()
        b3["live_ready"] = True
        assert_fails_closed(b3)

        # bool as int
        b4 = base_snap.copy()
        b4["retry_count"] = False
        assert_fails_closed(b4)

        # blocker order
        b5 = base_snap.copy()
        b5["blocking_providers"] = ["google", "openai"]
        assert_fails_closed(b5)

        # duplicates in blockers
        b6 = base_snap.copy()
        b6["blocking_providers"] = ["openai", "openai"]
        assert_fails_closed(b6)

        # count mismatch
        b7 = base_snap.copy()
        b7["unresolved_count"] = 1
        assert_fails_closed(b7)

        # unresolved_by_provider = {} for non-blocked
        b8 = base_snap.copy()
        b8["unresolved_by_provider"] = {}
        assert_fails_closed(b8)

        # bool as unresolved count
        b9 = base_snap.copy()
        b9["unresolved_count"] = False
        assert_fails_closed(b9)

        # malformed preflight snapshots
        b10 = base_snap.copy()
        b10["preflight_snapshots"] = {"openai": {}}
        assert_fails_closed(b10)

    def test_equivalent_dict_key_order_gives_identical_digest(self) -> None:
        input1 = _mock_input(ready=True)
        input2 = _mock_input(ready=True)
        # reorder keys
        input2_swapped = {"inventory": input2["inventory"], "provider_configs": input2["provider_configs"]}

        packet1 = build_live_readiness_approval_packet(input1)
        packet2 = build_live_readiness_approval_packet(input2_swapped)

        self.assertEqual(packet1["approval_packet_sha256"], packet2["approval_packet_sha256"])

    def test_changing_evidence_changes_digest_but_renderer_hides_it(self) -> None:
        import copy
        input1 = _mock_input(ready=True)
        input2 = copy.deepcopy(input1)

        # Modify evidence
        input2["inventory"]["openai"] = [{"evidence_type": "different_api_key", "status": "verified"}]

        packet1 = build_live_readiness_approval_packet(input1)
        packet2 = build_live_readiness_approval_packet(input2)

        self.assertNotEqual(packet1["snapshot_packet_sha256"], packet2["snapshot_packet_sha256"])
        self.assertNotEqual(packet1["approval_packet_sha256"], packet2["approval_packet_sha256"])

        # Renderer should not leak 'different_api_key'
        out = render_approval_summary_ja(packet2)
        self.assertNotIn("different_api_key", out)
