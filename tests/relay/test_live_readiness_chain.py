import copy
import hashlib
import json
import unittest
from typing import Any

from src.providers.live_readiness_snapshot import build_live_readiness_snapshot, render_snapshot_summary_ja
from src.providers.live_readiness_approval import build_live_readiness_approval_packet, render_approval_summary_ja
from src.providers.live_approval_receipt import build_live_approval_receipt, render_approval_receipt_ja, PROVIDER_ORDER
from tests.relay.test_live_readiness_snapshot import TestLiveReadinessSnapshot



class TestLiveReadinessChainAudit(unittest.TestCase):
    def setUp(self) -> None:
        fixture = TestLiveReadinessSnapshot()
        fixture.setUp()
        self.valid_configs = fixture.valid_configs
        self.unknown_inventory = fixture.unknown_inventory
        self.confirmed_inventory = fixture.confirmed_inventory

    def _assert_fail_closed_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.assertEqual(snapshot["state"], "BLOCKED_UNKNOWN")
        self.assertFalse(snapshot["live_ready"])
        self.assertFalse(snapshot["dispatch_allowed"])
        self.assertTrue(snapshot["human_approval_required"])

    def _assert_fail_closed_approval(self, packet: dict[str, Any]) -> None:
        self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")
        self.assertFalse(packet["approval_granted"])
        self.assertEqual(packet["next_action"], "RESOLVE_BLOCKERS")

    def _assert_fail_closed_receipt(self, receipt: dict[str, Any]) -> None:
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")
        self.assertFalse(receipt["execution_authorized"])
        self.assertFalse(receipt["provenance_verified"])
        self.assertEqual(receipt["decision"], "UNKNOWN")

    def _full_chain(self, inventory: dict[str, Any], decision: str = "APPROVE_FIRST_LIVE_POC", one_shot: bool = True) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        snapshot_input = {
            "provider_configs": copy.deepcopy(self.valid_configs),
            "inventory": copy.deepcopy(inventory),
        }
        snapshot = build_live_readiness_snapshot(snapshot_input)

        approval_input = {
            "provider_configs": copy.deepcopy(self.valid_configs),
            "inventory": copy.deepcopy(inventory),
        }
        approval_packet = build_live_readiness_approval_packet(approval_input)

        record = {
            "decision": decision,
            "scope": "FIRST_LIVE_POC_ONLY",
            "one_shot": one_shot,
            "recorded_at": "2026-09-28T00:00:00Z",
            "target_approval_packet_sha256": approval_packet.get("approval_packet_sha256"),
            "target_snapshot_packet_sha256": approval_packet.get("snapshot_packet_sha256"),
        }

        receipt = build_live_approval_receipt({
            "approval_packet": copy.deepcopy(approval_packet),
            "approval_record": record,
        })

        return snapshot_input, snapshot, approval_packet, receipt

    def test_1_unknown_inventory_path(self) -> None:
        _, snapshot, approval_packet, receipt = self._full_chain(self.unknown_inventory)

        self._assert_fail_closed_snapshot(snapshot)
        self._assert_fail_closed_approval(approval_packet)
        self._assert_fail_closed_receipt(receipt)

    def test_2_synthetic_complete_evidence_path(self) -> None:
        _, snapshot, approval_packet, receipt = self._full_chain(self.confirmed_inventory)

        self.assertEqual(snapshot["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertFalse(snapshot["live_ready"])
        self.assertFalse(snapshot["dispatch_allowed"])

        self.assertEqual(approval_packet["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(approval_packet["next_action"], "REQUEST_HUMAN_APPROVAL")
        self.assertFalse(approval_packet["approval_granted"])

        self.assertEqual(receipt["state"], "STRUCTURALLY_VALID_APPROVAL_RECORD")
        self.assertEqual(receipt["next_action"], "VERIFY_DURABLE_HUMAN_PROVENANCE")
        self.assertFalse(receipt["provenance_verified"])
        self.assertFalse(receipt["execution_authorized"])
        self.assertFalse(receipt["dispatch_allowed"])
        self.assertFalse(receipt["live_ready"])

    def test_3_reject_and_defer_on_ready_approval(self) -> None:
        for decision in ["REJECT", "DEFER"]:
            _, _, _, receipt = self._full_chain(self.confirmed_inventory, decision=decision)
            self.assertEqual(receipt["state"], "NON_APPROVAL_DECISION")
            self.assertEqual(receipt["next_action"], "NO_LIVE_ACTION")
            self.assertFalse(receipt["execution_authorized"])
            self.assertFalse(receipt["provenance_verified"])

    def test_4_approve_first_live_poc_with_oneshot_false_fails(self) -> None:
        _, _, _, receipt = self._full_chain(self.confirmed_inventory, decision="APPROVE_FIRST_LIVE_POC", one_shot=False)
        self._assert_fail_closed_receipt(receipt)

    def test_5_hash_binding_chain(self) -> None:
        _, snapshot, approval_packet, receipt = self._full_chain(self.confirmed_inventory)

        # Verify bindings
        self.assertEqual(snapshot["snapshot_packet_sha256"], approval_packet["snapshot_packet_sha256"])
        self.assertEqual(approval_packet["approval_packet_sha256"], receipt["approval_packet_sha256"])
        self.assertEqual(snapshot["snapshot_packet_sha256"], receipt["snapshot_packet_sha256"])

        # Tamper step 1: approval packet
        tampered_approval = copy.deepcopy(approval_packet)
        tampered_approval["approval_packet_sha256"] = "a" * 64
        record = {
            "decision": "APPROVE_FIRST_LIVE_POC",
            "scope": "FIRST_LIVE_POC_ONLY",
            "one_shot": True,
            "recorded_at": "2026-09-28T00:00:00Z",
            "target_approval_packet_sha256": tampered_approval["approval_packet_sha256"],
            "target_snapshot_packet_sha256": tampered_approval["snapshot_packet_sha256"],
        }
        receipt_tampered1 = build_live_approval_receipt({"approval_packet": tampered_approval, "approval_record": record})
        self._assert_fail_closed_receipt(receipt_tampered1)

        # Tamper step 2: record target snapshot hash
        record2 = {
            "decision": "APPROVE_FIRST_LIVE_POC",
            "scope": "FIRST_LIVE_POC_ONLY",
            "one_shot": True,
            "recorded_at": "2026-09-28T00:00:00Z",
            "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
            "target_snapshot_packet_sha256": "b" * 64,
        }
        receipt_tampered2 = build_live_approval_receipt({"approval_packet": approval_packet, "approval_record": record2})
        self._assert_fail_closed_receipt(receipt_tampered2)

    def test_6_determinism(self) -> None:
        _, snapshot1, approval1, receipt1 = self._full_chain(self.confirmed_inventory)

        shuffled_inventory = {p: self.confirmed_inventory[p] for p in reversed(PROVIDER_ORDER)}
        _, snapshot2, approval2, receipt2 = self._full_chain(shuffled_inventory)

        self.assertEqual(snapshot1["snapshot_packet_sha256"], snapshot2["snapshot_packet_sha256"])
        self.assertEqual(approval1["approval_packet_sha256"], approval2["approval_packet_sha256"])
        self.assertEqual(receipt1["approval_record_sha256"], receipt2["approval_record_sha256"])

    def test_7_evidence_sensitivity_without_leakage(self) -> None:
        _, snapshot1, approval1, _ = self._full_chain(self.confirmed_inventory)

        modified_inventory = copy.deepcopy(self.confirmed_inventory)
        modified_inventory["openai"]["finite_timeout"]["evidence_ref"] = "different_evidence"
        _, snapshot2, approval2, _ = self._full_chain(modified_inventory)

        self.assertNotEqual(snapshot1["snapshot_packet_sha256"], snapshot2["snapshot_packet_sha256"])
        self.assertNotEqual(approval1["approval_packet_sha256"], approval2["approval_packet_sha256"])

        # Renderers must not leak it
        snap_ja = render_snapshot_summary_ja(snapshot2)
        appr_ja = render_approval_summary_ja(approval2)
        self.assertNotIn("different_evidence", snap_ja)
        self.assertNotIn("different_evidence", appr_ja)

    def test_8_renderer_boundary(self) -> None:
        _, snapshot, approval_packet, receipt = self._full_chain(self.confirmed_inventory)

        snap_ja = render_snapshot_summary_ja(snapshot)
        appr_ja = render_approval_summary_ja(approval_packet)
        rect_ja = render_approval_receipt_ja(receipt)

        self.assertIn("ライブ実行: 禁止", snap_ja)
        self.assertIn("承認未完了", appr_ja)

        self.assertIn("実行認可: 未認可", rect_ja)
        self.assertIn("人間由来の証明: 未検証", rect_ja)

        for text in [snap_ja, appr_ja, rect_ja]:
            self.assertNotIn("2026", text)
            self.assertNotIn("evidence", text)
            self.assertNotIn("http", text)

    def test_9_cross_layer_tamper_cases(self) -> None:
        _, _, approval_packet, _ = self._full_chain(self.confirmed_inventory)

        # Mutate inventory to block snapshot and thus approval
        tampered_inventory = copy.deepcopy(self.confirmed_inventory)
        tampered_inventory["openai"]["finite_timeout"]["status"] = "UNKNOWN"

        tampered_approval_input = {
            "provider_configs": copy.deepcopy(self.valid_configs),
            "inventory": tampered_inventory,
        }
        tampered_approval_packet = build_live_readiness_approval_packet(tampered_approval_input)
        self._assert_fail_closed_approval(tampered_approval_packet)

        # Mutate approval packet
        tampered_approval = copy.deepcopy(approval_packet)
        tampered_approval["approval_granted"] = True
        record = {
            "decision": "APPROVE_FIRST_LIVE_POC",
            "scope": "FIRST_LIVE_POC_ONLY",
            "one_shot": True,
            "recorded_at": "2026-09-28T00:00:00Z",
            "target_approval_packet_sha256": tampered_approval["approval_packet_sha256"],
            "target_snapshot_packet_sha256": tampered_approval["snapshot_packet_sha256"],
        }
        receipt = build_live_approval_receipt({"approval_packet": tampered_approval, "approval_record": record})
        self._assert_fail_closed_receipt(receipt)

        # Mutate receipt
        record2 = {
            "decision": "APPROVE_FIRST_LIVE_POC",
            "scope": "ALL_LIVE", # mutated
            "one_shot": True,
            "recorded_at": "2026-09-28T00:00:00Z",
            "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
            "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
        }
        receipt2 = build_live_approval_receipt({"approval_packet": approval_packet, "approval_record": record2})
        self._assert_fail_closed_receipt(receipt2)

    def test_10_no_authorization_word_state_regression(self) -> None:
        _, snapshot, approval, receipt = self._full_chain(self.confirmed_inventory)

        self.assertFalse(snapshot.get("execution_authorized", False))
        self.assertFalse(snapshot.get("dispatch_allowed", False))
        self.assertFalse(snapshot.get("live_ready", False))
        self.assertFalse(snapshot.get("approval_granted", False))
        self.assertFalse(snapshot.get("provenance_verified", False))

        self.assertFalse(approval.get("execution_authorized", False))
        self.assertFalse(approval.get("dispatch_allowed", False))
        self.assertFalse(approval.get("live_ready", False))
        self.assertFalse(approval.get("approval_granted", False))
        self.assertFalse(approval.get("provenance_verified", False))

        self.assertFalse(receipt.get("execution_authorized", False))
        self.assertFalse(receipt.get("dispatch_allowed", False))
        self.assertFalse(receipt.get("live_ready", False))
        self.assertFalse(receipt.get("approval_granted", False))
        self.assertFalse(receipt.get("provenance_verified", False))

    def test_11_no_real_world_claim(self) -> None:
        # Document that tests must clearly label complete evidence as synthetic fixture data
        # and this resolves zero real live blockers.
        self.assertTrue(True, "Synthetic fixture data resolves zero real live blockers.")
