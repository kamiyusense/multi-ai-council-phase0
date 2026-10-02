import ast
import copy
import hashlib
import inspect
import unittest
from typing import Any

import src.providers.live_approval_receipt as receipt_mod
from src.providers.live_approval_receipt import (
    build_live_approval_receipt,
    render_approval_receipt_ja,
)
from src.providers.live_readiness_approval import (
    _canonical_json as approval_canonical_json,
    build_live_readiness_approval_packet,
)
from tests.relay.test_live_readiness_snapshot import TestLiveReadinessSnapshot


def _ready_approval_packet() -> dict[str, Any]:
    fixture = TestLiveReadinessSnapshot()
    fixture.setUp()
    return build_live_readiness_approval_packet(
        {
            "provider_configs": copy.deepcopy(fixture.valid_configs),
            "inventory": copy.deepcopy(fixture.confirmed_inventory),
        }
    )


def _blocked_approval_packet() -> dict[str, Any]:
    fixture = TestLiveReadinessSnapshot()
    fixture.setUp()
    return build_live_readiness_approval_packet(
        {
            "provider_configs": copy.deepcopy(fixture.valid_configs),
            "inventory": copy.deepcopy(fixture.unknown_inventory),
        }
    )


def _rehash_packet(packet: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in packet.items()
        if key != "approval_packet_sha256"
    }
    packet["approval_packet_sha256"] = hashlib.sha256(
        approval_canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return packet


def _record(packet: dict[str, Any], decision: str = "APPROVE_FIRST_LIVE_POC") -> dict[str, Any]:
    return {
        "decision": decision,
        "scope": "FIRST_LIVE_POC_ONLY",
        "one_shot": True,
        "recorded_at": "2026-09-29T09:00:00+09:00",
        "target_approval_packet_sha256": packet["approval_packet_sha256"],
        "target_snapshot_packet_sha256": packet["snapshot_packet_sha256"],
    }


class TestLiveApprovalReceipt(unittest.TestCase):
    def assert_fail_closed(self, receipt: dict[str, Any]) -> None:
        self.assertEqual(receipt["state"], "BLOCKED_UNKNOWN")
        self.assertIs(receipt["live_ready"], False)
        self.assertIs(receipt["dispatch_allowed"], False)
        self.assertIs(receipt["execution_authorized"], False)
        self.assertIs(receipt["provenance_verified"], False)
        self.assertEqual(receipt["retry_count"], 0)
        self.assertEqual(receipt["fallback_state"], "disabled")
        self.assertEqual(receipt["decision"], "UNKNOWN")
        self.assertEqual(receipt["scope"], "UNKNOWN")
        self.assertIs(receipt["one_shot"], False)
        self.assertIsNone(receipt["approval_packet_sha256"])
        self.assertIsNone(receipt["snapshot_packet_sha256"])
        self.assertEqual(receipt["next_action"], "RESOLVE_BLOCKERS")
        self.assertRegex(receipt["approval_record_sha256"], r"^[a-f0-9]{64}$")

    def test_valid_approve_is_structural_only(self) -> None:
        packet = _ready_approval_packet()
        receipt = build_live_approval_receipt(
            {"approval_packet": packet, "approval_record": _record(packet)}
        )
        self.assertEqual(receipt["state"], "STRUCTURALLY_VALID_APPROVAL_RECORD")
        self.assertEqual(receipt["decision"], "APPROVE_FIRST_LIVE_POC")
        self.assertEqual(receipt["scope"], "FIRST_LIVE_POC_ONLY")
        self.assertIs(receipt["one_shot"], True)
        self.assertEqual(
            receipt["next_action"],
            "VERIFY_DURABLE_HUMAN_PROVENANCE",
        )
        self.assertIs(receipt["provenance_verified"], False)
        self.assertIs(receipt["execution_authorized"], False)
        self.assertIs(receipt["dispatch_allowed"], False)
        self.assertIs(receipt["live_ready"], False)
        self.assertEqual(
            receipt["approval_packet_sha256"],
            packet["approval_packet_sha256"],
        )
        self.assertEqual(
            receipt["snapshot_packet_sha256"],
            packet["snapshot_packet_sha256"],
        )

    def test_valid_reject_and_defer_are_non_approval(self) -> None:
        packet = _ready_approval_packet()
        for decision, one_shot in (("REJECT", False), ("DEFER", True)):
            with self.subTest(decision=decision):
                record = _record(packet, decision)
                record["one_shot"] = one_shot
                receipt = build_live_approval_receipt(
                    {"approval_packet": packet, "approval_record": record}
                )
                self.assertEqual(receipt["state"], "NON_APPROVAL_DECISION")
                self.assertEqual(receipt["decision"], decision)
                self.assertEqual(receipt["next_action"], "NO_LIVE_ACTION")
                self.assertIs(receipt["execution_authorized"], False)
                self.assertIs(receipt["provenance_verified"], False)

    def test_blocked_packet_never_accepts_record(self) -> None:
        packet = _blocked_approval_packet()
        record = {
            "decision": "APPROVE_FIRST_LIVE_POC",
            "scope": "FIRST_LIVE_POC_ONLY",
            "one_shot": True,
            "recorded_at": "2026-09-29T09:00:00+09:00",
            "target_approval_packet_sha256": packet["approval_packet_sha256"],
            "target_snapshot_packet_sha256": packet["snapshot_packet_sha256"],
        }
        self.assert_fail_closed(
            build_live_approval_receipt(
                {"approval_packet": packet, "approval_record": record}
            )
        )

    def test_malformed_and_nonserializable_top_level_fail_closed(self) -> None:
        packet = _ready_approval_packet()
        record = _record(packet)
        cases: list[Any] = [
            None,
            [],
            {},
            {"approval_packet": packet},
            {
                "approval_packet": packet,
                "approval_record": record,
                "extra": False,
            },
            {
                "approval_packet": packet,
                "approval_record": {
                    **record,
                    "recorded_at": object(),
                },
            },
        ]
        for index, case in enumerate(cases):
            with self.subTest(index=index):
                self.assert_fail_closed(build_live_approval_receipt(case))

    def test_packet_tamper_matrix_fails_closed(self) -> None:
        ready = _ready_approval_packet()
        cases: list[tuple[str, dict[str, Any]]] = []

        missing = copy.deepcopy(ready)
        missing.pop("state")
        cases.append(("missing", missing))

        extra = copy.deepcopy(ready)
        extra["extra"] = False
        cases.append(("extra", extra))

        for name, field, value in (
            ("state", "state", "BLOCKED_UNKNOWN"),
            ("next-action", "next_action", "RESOLVE_BLOCKERS"),
            ("snapshot-state", "snapshot_state", "BLOCKED_UNKNOWN"),
            ("live-ready", "live_ready", True),
            ("dispatch", "dispatch_allowed", True),
            ("human-required", "human_approval_required", False),
            ("approval-granted", "approval_granted", True),
            ("retry-one", "retry_count", 1),
            ("retry-bool", "retry_count", False),
            ("fallback", "fallback_state", "enabled"),
            ("inventory", "inventory_state", "UNRESOLVED"),
            ("count-one", "unresolved_count", 1),
            ("count-bool", "unresolved_count", False),
        ):
            item = copy.deepcopy(ready)
            item[field] = value
            cases.append((name, _rehash_packet(item)))

        bad_preflight_keys = copy.deepcopy(ready)
        bad_preflight_keys["preflight_states"] = {
            "foo": "PASS",
            "bar": "PASS",
            "baz": "PASS",
        }
        cases.append(("preflight-keys", _rehash_packet(bad_preflight_keys)))

        bad_preflight_value = copy.deepcopy(ready)
        bad_preflight_value["preflight_states"]["openai"] = "READY"
        cases.append(("preflight-value", _rehash_packet(bad_preflight_value)))

        bad_provider_keys = copy.deepcopy(ready)
        bad_provider_keys["provider_states"] = {
            "foo": "READY_FOR_HUMAN_APPROVAL",
            "bar": "READY_FOR_HUMAN_APPROVAL",
            "baz": "READY_FOR_HUMAN_APPROVAL",
        }
        cases.append(("provider-keys", _rehash_packet(bad_provider_keys)))

        bad_provider_value = copy.deepcopy(ready)
        bad_provider_value["provider_states"]["google"] = "BLOCKED_UNKNOWN"
        cases.append(("provider-value", _rehash_packet(bad_provider_value)))

        blockers = copy.deepcopy(ready)
        blockers["blocking_providers"] = ["openai"]
        cases.append(("blockers", _rehash_packet(blockers)))

        bad_snapshot_hash = copy.deepcopy(ready)
        bad_snapshot_hash["snapshot_packet_sha256"] = "g" * 64
        cases.append(("snapshot-hash", _rehash_packet(bad_snapshot_hash)))

        digest_mismatch = copy.deepcopy(ready)
        digest_mismatch["approval_packet_sha256"] = "0" * 64
        cases.append(("approval-digest", digest_mismatch))

        for name, packet in cases:
            with self.subTest(name=name):
                record = {
                    "decision": "APPROVE_FIRST_LIVE_POC",
                    "scope": "FIRST_LIVE_POC_ONLY",
                    "one_shot": True,
                    "recorded_at": "2026-09-29T09:00:00+09:00",
                    "target_approval_packet_sha256": packet.get(
                        "approval_packet_sha256",
                        "0" * 64,
                    ),
                    "target_snapshot_packet_sha256": packet.get(
                        "snapshot_packet_sha256",
                        "0" * 64,
                    ),
                }
                self.assert_fail_closed(
                    build_live_approval_receipt(
                        {"approval_packet": packet, "approval_record": record}
                    )
                )

    def test_record_tamper_matrix_fails_closed(self) -> None:
        packet = _ready_approval_packet()
        valid = _record(packet)
        cases: list[tuple[str, dict[str, Any]]] = []

        missing = copy.deepcopy(valid)
        missing.pop("decision")
        cases.append(("missing", missing))

        extra = copy.deepcopy(valid)
        extra["extra"] = False
        cases.append(("extra", extra))

        for name, field, value in (
            ("decision", "decision", "APPROVE_ALL"),
            ("scope", "scope", "ALL_LIVE"),
            ("one-shot-int", "one_shot", 1),
            ("approve-not-one-shot", "one_shot", False),
            ("no-timezone", "recorded_at", "2026-09-29T09:00:00"),
            ("invalid-date", "recorded_at", "2026-02-30T09:00:00+09:00"),
            ("invalid-offset", "recorded_at", "2026-09-29T09:00:00+99:00"),
            (
                "approval-target",
                "target_approval_packet_sha256",
                "b" * 64,
            ),
            (
                "snapshot-target",
                "target_snapshot_packet_sha256",
                "b" * 64,
            ),
            (
                "approval-target-nonhex",
                "target_approval_packet_sha256",
                "g" * 64,
            ),
        ):
            item = copy.deepcopy(valid)
            item[field] = value
            cases.append((name, item))

        for name, record in cases:
            with self.subTest(name=name):
                self.assert_fail_closed(
                    build_live_approval_receipt(
                        {"approval_packet": packet, "approval_record": record}
                    )
                )

    def test_timezone_aware_iso8601_examples_without_wall_clock(self) -> None:
        for value in (
            "2026-09-29T09:00:00Z",
            "2026-09-29T09:00:00+09:00",
            "2026-09-29T09:00:00.123456-04:30",
        ):
            with self.subTest(value=value):
                self.assertTrue(receipt_mod._is_valid_iso8601_offset(value))

        for value in (
            "",
            "2026-09-29 09:00:00+09:00",
            "2026-09-29T09:00:00",
            "2026-02-30T09:00:00+09:00",
            "2026-09-29T09:00:00+99:00",
        ):
            with self.subTest(value=value):
                self.assertFalse(receipt_mod._is_valid_iso8601_offset(value))

    def test_source_and_output_mutation_isolation(self) -> None:
        packet = _ready_approval_packet()
        record = _record(packet)
        source = {"approval_packet": packet, "approval_record": record}
        receipt = build_live_approval_receipt(source)
        digest = receipt["approval_record_sha256"]

        packet["state"] = "BLOCKED_UNKNOWN"
        record["decision"] = "REJECT"
        source["approval_record"]["recorded_at"] = "tampered"

        self.assertEqual(
            receipt["state"],
            "STRUCTURALLY_VALID_APPROVAL_RECORD",
        )
        self.assertEqual(receipt["decision"], "APPROVE_FIRST_LIVE_POC")
        self.assertEqual(receipt["approval_record_sha256"], digest)

    def test_equivalent_key_order_has_identical_receipt_digest(self) -> None:
        packet = _ready_approval_packet()
        record = _record(packet)
        first = {
            "approval_packet": copy.deepcopy(packet),
            "approval_record": copy.deepcopy(record),
        }
        second = {
            "approval_record": dict(reversed(list(record.items()))),
            "approval_packet": dict(reversed(list(packet.items()))),
        }
        self.assertEqual(
            build_live_approval_receipt(first)["approval_record_sha256"],
            build_live_approval_receipt(second)["approval_record_sha256"],
        )

    def test_recorded_at_not_exposed_in_output_or_renderer(self) -> None:
        packet = _ready_approval_packet()
        marker = "2026-09-29T09:12:34.567890+09:00"
        record = _record(packet)
        record["recorded_at"] = marker
        receipt = build_live_approval_receipt(
            {"approval_packet": packet, "approval_record": record}
        )
        self.assertNotIn(marker, receipt_mod._canonical_json(receipt))
        rendered = render_approval_receipt_ja(receipt)
        self.assertNotIn(marker, rendered)
        self.assertIn("状態: STATIC / PREPARED", rendered)
        self.assertIn("人間由来の証明: 未検証", rendered)
        self.assertIn("実行認可: 未認可", rendered)

    def test_renderer_sanitizes_arbitrary_strings(self) -> None:
        marker = "https://evil.invalid/?token=secret"
        rendered = render_approval_receipt_ja(
            {
                "state": marker,
                "decision": marker,
                "next_action": marker,
                "scope": marker,
                "one_shot": marker,
                "recorded_at": marker,
            }
        )
        self.assertNotIn(marker, rendered)
        self.assertNotIn("token=", rendered)
        self.assertIn("ブロッカー解消待ち・不明", rendered)
        self.assertIn("決定: 不明", rendered)

    def test_ast_static_boundary_has_no_ambient_or_live_operations(self) -> None:
        source = inspect.getsource(receipt_mod)
        tree = ast.parse(source)
        banned_import_roots = {
            "os",
            "pathlib",
            "subprocess",
            "socket",
            "urllib",
            "requests",
            "http",
            "time",
            "random",
        }
        banned_calls = {
            "open",
            "exec",
            "eval",
            "__import__",
            "now",
            "today",
            "utcnow",
            "time",
            "validate_provider_static",
            "build_live_readiness_pipeline",
            "evaluate_live_readiness",
            "build_live_readiness_snapshot",
            "build_live_readiness_approval_packet",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name.split(".")[0],
                        banned_import_roots,
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(
                        node.module.split(".")[0],
                        banned_import_roots,
                    )
            elif isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name is not None:
                    self.assertNotIn(name, banned_calls)
