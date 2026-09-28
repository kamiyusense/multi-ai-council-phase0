import copy
import hashlib
import json
import unittest
from typing import Any

from providers.live_approval_receipt import (
    build_live_approval_receipt,
    render_approval_receipt_ja,
    _canonical_json,
)

class TestLiveApprovalReceipt(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_snapshot_hash = "a" * 64
        self.mock_approval_packet = {
            "state": "READY_FOR_HUMAN_APPROVAL",
            "live_ready": False,
            "dispatch_allowed": False,
            "human_approval_required": True,
            "approval_granted": False,
            "retry_count": 0,
            "fallback_state": "disabled",
            "next_action": "REQUEST_HUMAN_APPROVAL",
            "snapshot_state": "READY_FOR_HUMAN_APPROVAL",
            "snapshot_packet_sha256": self.mock_snapshot_hash,
            "preflight_states": {"openai": "PASS", "anthropic": "PASS", "google": "UNKNOWN"},
            "inventory_state": "PROOF_RECORDS_COMPLETE",
            "unresolved_count": 0,
            "provider_states": {
                "openai": "READY_FOR_HUMAN_APPROVAL",
                "anthropic": "READY_FOR_HUMAN_APPROVAL",
                "google": "READY_FOR_HUMAN_APPROVAL"
            },
            "blocking_providers": [],
        }

        payload = copy.deepcopy(self.mock_approval_packet)
        self.mock_approval_hash = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        self.mock_approval_packet["approval_packet_sha256"] = self.mock_approval_hash

        self.valid_approve_record = {
            "decision": "APPROVE_FIRST_LIVE_POC",
            "scope": "FIRST_LIVE_POC_ONLY",
            "one_shot": True,
            "recorded_at": "2026-09-21T12:00:00Z",
            "target_approval_packet_sha256": self.mock_approval_hash,
            "target_snapshot_packet_sha256": self.mock_snapshot_hash,
        }

    def _build_input(self, packet: Any, record: Any) -> dict[str, Any]:
        return {
            "approval_packet": packet,
            "approval_record": record,
        }

    def test_valid_approve_receipt(self) -> None:
        receipt = build_live_approval_receipt(self._build_input(self.mock_approval_packet, self.valid_approve_record))

        self.assertEqual(receipt["state"], "STRUCTURALLY_VALID_APPROVAL_RECORD")
        self.assertEqual(receipt["next_action"], "VERIFY_DURABLE_HUMAN_PROVENANCE")
        self.assertFalse(receipt["live_ready"])
        self.assertFalse(receipt["dispatch_allowed"])
        self.assertFalse(receipt["execution_authorized"])
        self.assertFalse(receipt["provenance_verified"])
        self.assertEqual(receipt["decision"], "APPROVE_FIRST_LIVE_POC")
        self.assertEqual(receipt["scope"], "FIRST_LIVE_POC_ONLY")
        self.assertTrue(receipt["one_shot"])
        self.assertEqual(receipt["approval_packet_sha256"], self.mock_approval_hash)
        self.assertEqual(receipt["snapshot_packet_sha256"], self.mock_snapshot_hash)
        self.assertEqual(len(receipt["approval_record_sha256"]), 64)

    def test_valid_reject_receipt(self) -> None:
        record = copy.deepcopy(self.valid_approve_record)
        record["decision"] = "REJECT"
        record["one_shot"] = False

        receipt = build_live_approval_receipt(self._build_input(self.mock_approval_packet, record))

        self.assertEqual(receipt["state"], "NON_APPROVAL_DECISION")
        self.assertEqual(receipt["next_action"], "NO_LIVE_ACTION")
        self.assertEqual(receipt["decision"], "REJECT")

    def test_valid_defer_receipt(self) -> None:
        record = copy.deepcopy(self.valid_approve_record)
        record["decision"] = "DEFER"
        record["one_shot"] = True

        receipt = build_live_approval_receipt(self._build_input(self.mock_approval_packet, record))

        self.assertEqual(receipt["state"], "NON_APPROVAL_DECISION")
        self.assertEqual(receipt["next_action"], "NO_LIVE_ACTION")
        self.assertEqual(receipt["decision"], "DEFER")

    def test_blocked_approval_packet_fails(self) -> None:
        packet = copy.deepcopy(self.mock_approval_packet)
        packet["state"] = "BLOCKED_UNKNOWN"
        packet["next_action"] = "RESOLVE_BLOCKERS"
        packet["blocking_providers"] = ["openai"]

        packet_payload = {k: v for k, v in packet.items() if k != "approval_packet_sha256"}
        packet["approval_packet_sha256"] = hashlib.sha256(_canonical_json(packet_payload).encode("utf-8")).hexdigest()

        record = copy.deepcopy(self.valid_approve_record)
        record["target_approval_packet_sha256"] = packet["approval_packet_sha256"]

        receipt = build_live_approval_receipt(self._build_input(packet, record))
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")

    def test_tampered_approval_packet_fails(self) -> None:
        packet = copy.deepcopy(self.mock_approval_packet)
        packet["approval_granted"] = True

        # Keep old hash to simulate tampering
        receipt = build_live_approval_receipt(self._build_input(packet, self.valid_approve_record))
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")

    def test_malformed_input_fails_closed(self) -> None:
        # Not a dict
        self.assertEqual(build_live_approval_receipt([])["state"], "BLOCKED_UNKNOWN")

        # Missing keys
        self.assertEqual(build_live_approval_receipt({"approval_packet": self.mock_approval_packet})["state"], "BLOCKED_UNKNOWN")

    def test_bad_record_hash_mismatch(self) -> None:
        record = copy.deepcopy(self.valid_approve_record)
        record["target_approval_packet_sha256"] = "b" * 64

        receipt = build_live_approval_receipt(self._build_input(self.mock_approval_packet, record))
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")

    def test_bad_one_shot_for_approve(self) -> None:
        record = copy.deepcopy(self.valid_approve_record)
        record["one_shot"] = False

        receipt = build_live_approval_receipt(self._build_input(self.mock_approval_packet, record))
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")

    def test_invalid_recorded_at_format(self) -> None:
        record = copy.deepcopy(self.valid_approve_record)
        record["recorded_at"] = "2026-09-21 12:00:00" # Missing T and Z

        receipt = build_live_approval_receipt(self._build_input(self.mock_approval_packet, record))
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")

    def test_bool_as_int_rejected(self) -> None:
        record = copy.deepcopy(self.valid_approve_record)
        record["one_shot"] = 1 # Not a strict bool

        receipt = build_live_approval_receipt(self._build_input(self.mock_approval_packet, record))
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")

    def test_isolation_no_mutation(self) -> None:
        input_data = self._build_input(self.mock_approval_packet, self.valid_approve_record)
        input_copy = copy.deepcopy(input_data)

        receipt = build_live_approval_receipt(input_data)
        self.assertEqual(input_data, input_copy)

    def test_renderer_sanitizes_output(self) -> None:
        record = copy.deepcopy(self.valid_approve_record)
        # Attempt to inject something through recorded_at, though valid ISO regex prevents arbitrary injection here.
        # But let's check that recorded_at is NOT in the renderer output.
        receipt = build_live_approval_receipt(self._build_input(self.mock_approval_packet, record))
        out = render_approval_receipt_ja(receipt)

        self.assertIn("状態: STATIC / PREPARED", out)
        self.assertIn("実行認可: 未認可", out)
        self.assertIn("構造的に有効な承認記録", out)
        self.assertNotIn("2026-09-21", out)
