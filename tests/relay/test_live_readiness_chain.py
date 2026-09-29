import copy
import hashlib
import json
import os
import unittest
from typing import Any
from unittest import mock

from src.providers.live_approval_receipt import (
    PROVIDER_ORDER,
    build_live_approval_receipt,
    render_approval_receipt_ja,
)
from src.providers.live_readiness_approval import (
    build_live_readiness_approval_packet,
    render_approval_summary_ja,
)
from src.providers.live_readiness_snapshot import (
    build_live_readiness_snapshot,
    render_snapshot_summary_ja,
)
from tests.relay.test_live_readiness_snapshot import TestLiveReadinessSnapshot


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _rehash_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in snapshot.items()
        if key != "snapshot_packet_sha256"
    }
    snapshot["snapshot_packet_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return snapshot


def _rehash_approval(packet: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in packet.items()
        if key != "approval_packet_sha256"
    }
    packet["approval_packet_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return packet


def _rehash_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in receipt.items()
        if key != "approval_record_sha256"
    }
    receipt["approval_record_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return receipt


class TestLiveReadinessChainAudit(unittest.TestCase):
    def setUp(self) -> None:
        fixture = TestLiveReadinessSnapshot()
        fixture.setUp()
        self.valid_configs = copy.deepcopy(fixture.valid_configs)
        self.unknown_inventory = copy.deepcopy(fixture.unknown_inventory)
        self.confirmed_inventory = copy.deepcopy(fixture.confirmed_inventory)

    def _snapshot_input(self, inventory: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_configs": copy.deepcopy(self.valid_configs),
            "inventory": copy.deepcopy(inventory),
        }

    def _record(
        self,
        approval_packet: dict[str, Any],
        *,
        decision: str = "APPROVE_FIRST_LIVE_POC",
        one_shot: bool = True,
        recorded_at: str = "2026-09-29T09:00:00+09:00",
    ) -> dict[str, Any]:
        return {
            "decision": decision,
            "scope": "FIRST_LIVE_POC_ONLY",
            "one_shot": one_shot,
            "recorded_at": recorded_at,
            "target_approval_packet_sha256": approval_packet[
                "approval_packet_sha256"
            ],
            "target_snapshot_packet_sha256": approval_packet[
                "snapshot_packet_sha256"
            ],
        }

    def _full_chain(
        self,
        inventory: dict[str, Any],
        *,
        decision: str = "APPROVE_FIRST_LIVE_POC",
        one_shot: bool = True,
        recorded_at: str = "2026-09-29T09:00:00+09:00",
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        snapshot = build_live_readiness_snapshot(
            self._snapshot_input(inventory)
        )
        approval = build_live_readiness_approval_packet(
            self._snapshot_input(inventory)
        )
        receipt = build_live_approval_receipt(
            {
                "approval_packet": copy.deepcopy(approval),
                "approval_record": self._record(
                    approval,
                    decision=decision,
                    one_shot=one_shot,
                    recorded_at=recorded_at,
                ),
            }
        )
        return snapshot, approval, receipt

    def _assert_no_authorization(self, value: dict[str, Any]) -> None:
        for field in (
            "execution_authorized",
            "dispatch_allowed",
            "live_ready",
            "approval_granted",
            "provenance_verified",
        ):
            self.assertIs(value.get(field, False), False, field)

    def _assert_fail_closed_approval(self, packet: dict[str, Any]) -> None:
        self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(packet["next_action"], "RESOLVE_BLOCKERS")
        self.assertIs(packet["approval_granted"], False)
        self.assertIs(packet["live_ready"], False)
        self.assertIs(packet["dispatch_allowed"], False)
        self.assertIs(packet["human_approval_required"], True)

    def _assert_fail_closed_receipt(self, receipt: dict[str, Any]) -> None:
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(receipt["next_action"], "RESOLVE_BLOCKERS")
        self.assertEqual(receipt["decision"], "UNKNOWN")
        self.assertEqual(receipt["scope"], "UNKNOWN")
        self.assertIs(receipt["execution_authorized"], False)
        self.assertIs(receipt["provenance_verified"], False)
        self.assertIs(receipt["dispatch_allowed"], False)
        self.assertIs(receipt["live_ready"], False)

    def test_unknown_inventory_stays_blocked_end_to_end(self) -> None:
        snapshot, approval, receipt = self._full_chain(
            self.unknown_inventory
        )

        self.assertEqual(snapshot["state"], "BLOCKED_UNKNOWN")
        self.assertIs(snapshot["live_ready"], False)
        self.assertIs(snapshot["dispatch_allowed"], False)
        self.assertIs(snapshot["human_approval_required"], True)

        self._assert_fail_closed_approval(approval)
        self._assert_fail_closed_receipt(receipt)

    def test_synthetic_complete_evidence_stops_at_structural_receipt(self) -> None:
        snapshot, approval, receipt = self._full_chain(
            self.confirmed_inventory
        )

        self.assertEqual(
            snapshot["state"],
            "READY_FOR_HUMAN_APPROVAL",
        )
        self.assertIs(snapshot["live_ready"], False)
        self.assertIs(snapshot["dispatch_allowed"], False)

        self.assertEqual(
            approval["state"],
            "READY_FOR_HUMAN_APPROVAL",
        )
        self.assertEqual(
            approval["next_action"],
            "REQUEST_HUMAN_APPROVAL",
        )
        self.assertIs(approval["approval_granted"], False)
        self.assertIs(approval["live_ready"], False)
        self.assertIs(approval["dispatch_allowed"], False)

        self.assertEqual(
            receipt["state"],
            "STRUCTURALLY_VALID_APPROVAL_RECORD",
        )
        self.assertEqual(
            receipt["next_action"],
            "VERIFY_DURABLE_HUMAN_PROVENANCE",
        )
        self._assert_no_authorization(receipt)

    def test_reject_and_defer_produce_no_live_action(self) -> None:
        for decision in ("REJECT", "DEFER"):
            with self.subTest(decision=decision):
                _, _, receipt = self._full_chain(
                    self.confirmed_inventory,
                    decision=decision,
                )
                self.assertEqual(
                    receipt["state"],
                    "NON_APPROVAL_DECISION",
                )
                self.assertEqual(
                    receipt["next_action"],
                    "NO_LIVE_ACTION",
                )
                self._assert_no_authorization(receipt)

    def test_approve_requires_one_shot_true(self) -> None:
        _, _, receipt = self._full_chain(
            self.confirmed_inventory,
            decision="APPROVE_FIRST_LIVE_POC",
            one_shot=False,
        )
        self._assert_fail_closed_receipt(receipt)

    def test_hash_binding_chain_recomputes_every_safe_output_digest(self) -> None:
        snapshot, approval, receipt = self._full_chain(
            self.confirmed_inventory
        )

        snapshot_copy = copy.deepcopy(snapshot)
        snapshot_hash = snapshot_copy.pop("snapshot_packet_sha256")
        self.assertEqual(
            snapshot_hash,
            hashlib.sha256(
                _canonical_json(snapshot_copy).encode("utf-8")
            ).hexdigest(),
        )

        approval_copy = copy.deepcopy(approval)
        approval_hash = approval_copy.pop("approval_packet_sha256")
        self.assertEqual(
            approval_hash,
            hashlib.sha256(
                _canonical_json(approval_copy).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(
            approval["snapshot_packet_sha256"],
            snapshot["snapshot_packet_sha256"],
        )

        receipt_copy = copy.deepcopy(receipt)
        receipt_hash = receipt_copy.pop("approval_record_sha256")
        self.assertEqual(
            receipt_hash,
            hashlib.sha256(
                _canonical_json(receipt_copy).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(
            receipt["approval_packet_sha256"],
            approval["approval_packet_sha256"],
        )
        self.assertEqual(
            receipt["snapshot_packet_sha256"],
            snapshot["snapshot_packet_sha256"],
        )

    def test_snapshot_tamper_is_rejected_by_approval_boundary(self) -> None:
        valid_snapshot = build_live_readiness_snapshot(
            self._snapshot_input(self.confirmed_inventory)
        )
        cases: list[tuple[str, dict[str, Any]]] = []

        state = copy.deepcopy(valid_snapshot)
        state["state"] = "BLOCKED_UNKNOWN"
        cases.append(("state", _rehash_snapshot(state)))

        dispatch = copy.deepcopy(valid_snapshot)
        dispatch["dispatch_allowed"] = True
        cases.append(("dispatch", _rehash_snapshot(dispatch)))

        live_ready = copy.deepcopy(valid_snapshot)
        live_ready["live_ready"] = True
        cases.append(("live-ready", _rehash_snapshot(live_ready)))

        digest = copy.deepcopy(valid_snapshot)
        digest["snapshot_packet_sha256"] = "0" * 64
        cases.append(("digest", digest))

        for name, tampered in cases:
            with self.subTest(name=name), mock.patch(
                "src.providers.live_readiness_approval.build_live_readiness_snapshot",
                return_value=tampered,
            ):
                approval = build_live_readiness_approval_packet(
                    self._snapshot_input(self.confirmed_inventory)
                )
                self._assert_fail_closed_approval(approval)

    def test_approval_packet_tamper_is_rejected_by_receipt_boundary(self) -> None:
        approval = build_live_readiness_approval_packet(
            self._snapshot_input(self.confirmed_inventory)
        )
        cases: list[tuple[str, dict[str, Any]]] = []

        granted = copy.deepcopy(approval)
        granted["approval_granted"] = True
        cases.append(("approval-granted", _rehash_approval(granted)))

        provider_keys = copy.deepcopy(approval)
        provider_keys["provider_states"] = {
            "foo": "READY_FOR_HUMAN_APPROVAL",
            "bar": "READY_FOR_HUMAN_APPROVAL",
            "baz": "READY_FOR_HUMAN_APPROVAL",
        }
        cases.append(("provider-keys", _rehash_approval(provider_keys)))

        digest = copy.deepcopy(approval)
        digest["approval_packet_sha256"] = "0" * 64
        cases.append(("digest", digest))

        for name, tampered in cases:
            with self.subTest(name=name):
                receipt = build_live_approval_receipt(
                    {
                        "approval_packet": tampered,
                        "approval_record": {
                            "decision": "APPROVE_FIRST_LIVE_POC",
                            "scope": "FIRST_LIVE_POC_ONLY",
                            "one_shot": True,
                            "recorded_at": "2026-09-29T09:00:00+09:00",
                            "target_approval_packet_sha256": tampered[
                                "approval_packet_sha256"
                            ],
                            "target_snapshot_packet_sha256": tampered[
                                "snapshot_packet_sha256"
                            ],
                        },
                    }
                )
                self._assert_fail_closed_receipt(receipt)

    def test_approval_record_scope_timestamp_and_hash_tamper_fail_closed(self) -> None:
        approval = build_live_readiness_approval_packet(
            self._snapshot_input(self.confirmed_inventory)
        )
        valid = self._record(approval)

        cases: list[tuple[str, dict[str, Any]]] = []

        scope = copy.deepcopy(valid)
        scope["scope"] = "ALL_LIVE"
        cases.append(("scope", scope))

        timestamp = copy.deepcopy(valid)
        timestamp["recorded_at"] = "2026-02-30T09:00:00+09:00"
        cases.append(("timestamp", timestamp))

        approval_target = copy.deepcopy(valid)
        approval_target["target_approval_packet_sha256"] = "b" * 64
        cases.append(("approval-target", approval_target))

        snapshot_target = copy.deepcopy(valid)
        snapshot_target["target_snapshot_packet_sha256"] = "c" * 64
        cases.append(("snapshot-target", snapshot_target))

        for name, record in cases:
            with self.subTest(name=name):
                receipt = build_live_approval_receipt(
                    {
                        "approval_packet": approval,
                        "approval_record": record,
                    }
                )
                self._assert_fail_closed_receipt(receipt)

    def test_equivalent_dict_order_and_identical_inputs_are_deterministic(self) -> None:
        first_snapshot, first_approval, first_receipt = self._full_chain(
            self.confirmed_inventory
        )

        reversed_configs = dict(reversed(list(self.valid_configs.items())))
        reversed_inventory = dict(
            reversed(list(self.confirmed_inventory.items()))
        )
        second_snapshot = build_live_readiness_snapshot(
            {
                "inventory": copy.deepcopy(reversed_inventory),
                "provider_configs": copy.deepcopy(reversed_configs),
            }
        )
        second_approval = build_live_readiness_approval_packet(
            {
                "inventory": copy.deepcopy(reversed_inventory),
                "provider_configs": copy.deepcopy(reversed_configs),
            }
        )
        second_receipt = build_live_approval_receipt(
            {
                "approval_record": dict(
                    reversed(
                        list(
                            self._record(second_approval).items()
                        )
                    )
                ),
                "approval_packet": dict(
                    reversed(list(second_approval.items()))
                ),
            }
        )

        self.assertEqual(first_snapshot, second_snapshot)
        self.assertEqual(first_approval, second_approval)
        self.assertEqual(first_receipt, second_receipt)

        third_snapshot, third_approval, third_receipt = self._full_chain(
            self.confirmed_inventory
        )
        self.assertEqual(first_snapshot, third_snapshot)
        self.assertEqual(first_approval, third_approval)
        self.assertEqual(first_receipt, third_receipt)

    def test_valid_evidence_change_changes_hashes_without_leakage(self) -> None:
        first_snapshot, first_approval, _ = self._full_chain(
            self.confirmed_inventory
        )

        modified = copy.deepcopy(self.confirmed_inventory)
        first_proof = next(iter(modified["openai"]))
        modified["openai"][first_proof]["evidence_ref"] = (
            "sensitive-evidence-marker-123"
        )

        second_snapshot, second_approval, second_receipt = self._full_chain(
            modified
        )

        self.assertNotEqual(
            first_snapshot["snapshot_packet_sha256"],
            second_snapshot["snapshot_packet_sha256"],
        )
        self.assertNotEqual(
            first_approval["approval_packet_sha256"],
            second_approval["approval_packet_sha256"],
        )

        marker = "sensitive-evidence-marker-123"
        for rendered in (
            render_snapshot_summary_ja(second_snapshot),
            render_approval_summary_ja(second_approval),
            render_approval_receipt_ja(second_receipt),
        ):
            self.assertNotIn(marker, rendered)
            self.assertNotIn("evidence_ref", rendered)

    def test_all_renderers_preserve_static_terminal_boundary(self) -> None:
        snapshot, approval, receipt = self._full_chain(
            self.confirmed_inventory,
            recorded_at="2026-09-29T09:12:34.567890+09:00",
        )

        snapshot_text = render_snapshot_summary_ja(snapshot)
        approval_text = render_approval_summary_ja(approval)
        receipt_text = render_approval_receipt_ja(receipt)

        self.assertIn("ライブ実行: 禁止", snapshot_text)
        self.assertIn("承認未完了", approval_text)
        self.assertIn("ライブ実行: 禁止", receipt_text)
        self.assertIn("人間由来の証明: 未検証", receipt_text)
        self.assertIn("実行認可: 未認可", receipt_text)

        forbidden_literals = (
            "2026-09-29T09:12:34.567890+09:00",
            "provider_meta",
            "route_evidence",
            "evidence_ref",
        )
        for text in (snapshot_text, approval_text, receipt_text):
            for literal in forbidden_literals:
                self.assertNotIn(literal, text)

    def test_no_runtime_mapping_contains_true_authorization_flags(self) -> None:
        blocked = self._full_chain(self.unknown_inventory)
        ready = self._full_chain(self.confirmed_inventory)
        reject = self._full_chain(
            self.confirmed_inventory,
            decision="REJECT",
        )
        defer = self._full_chain(
            self.confirmed_inventory,
            decision="DEFER",
        )

        for chain in (blocked, ready, reject, defer):
            for mapping in chain:
                self._assert_no_authorization(mapping)

    def test_audit_docs_explicitly_deny_real_world_completion(self) -> None:
        docs_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "docs",
            "RELAY_LIVE_READINESS_CHAIN_AUDIT.md",
        )
        checkpoint_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "docs",
            "RELAY_STATIC_CHECKPOINT.md",
        )

        with open(docs_path, "r", encoding="utf-8") as stream:
            audit_doc = stream.read()
        with open(checkpoint_path, "r", encoding="utf-8") as stream:
            checkpoint = stream.read()

        self.assertIn(
            "STATIC chain complete != human provenance verified != first live command authorized",
            audit_doc,
        )
        self.assertIn("synthetic fixture data", audit_doc)
        self.assertIn("No real blocker is resolved", audit_doc)
        self.assertIn("Real live proofs remain UNKNOWN", checkpoint)
        self.assertIn("human provenance is unverified", checkpoint)
        self.assertIn("first live command is unauthorized", checkpoint)
