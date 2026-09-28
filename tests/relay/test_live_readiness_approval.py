import ast
import copy
import hashlib
import inspect
import unittest
from typing import Any
from unittest import mock

import src.providers.live_readiness_approval as approval_mod
from src.providers.live_readiness_approval import (
    PROVIDER_ORDER,
    build_live_readiness_approval_packet,
    render_approval_summary_ja,
)
from src.providers.live_readiness_snapshot import (
    _canonical_json as snapshot_canonical_json,
    build_live_readiness_snapshot as real_build_live_readiness_snapshot,
)
from tests.relay.test_live_readiness_snapshot import TestLiveReadinessSnapshot


def _explicit_input(*, ready: bool) -> dict[str, Any]:
    fixture = TestLiveReadinessSnapshot()
    fixture.setUp()
    return {
        "provider_configs": copy.deepcopy(fixture.valid_configs),
        "inventory": copy.deepcopy(
            fixture.confirmed_inventory if ready else fixture.unknown_inventory
        ),
    }


def _snapshot(*, ready: bool) -> dict[str, Any]:
    return real_build_live_readiness_snapshot(_explicit_input(ready=ready))


def _rehash_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in snapshot.items()
        if key != "snapshot_packet_sha256"
    }
    snapshot["snapshot_packet_sha256"] = hashlib.sha256(
        snapshot_canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return snapshot


def _rehash_preflights(snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot["preflight_packet_sha256"] = hashlib.sha256(
        snapshot_canonical_json(snapshot["preflight_snapshots"]).encode("utf-8")
    ).hexdigest()
    return _rehash_snapshot(snapshot)


class TestLiveReadinessApproval(unittest.TestCase):
    def assert_fail_closed(self, packet: dict[str, Any]) -> None:
        self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")
        self.assertIs(packet["live_ready"], False)
        self.assertIs(packet["dispatch_allowed"], False)
        self.assertIs(packet["human_approval_required"], True)
        self.assertIs(packet["approval_granted"], False)
        self.assertEqual(packet["retry_count"], 0)
        self.assertEqual(packet["fallback_state"], "disabled")
        self.assertEqual(packet["next_action"], "RESOLVE_BLOCKERS")
        self.assertEqual(packet["snapshot_state"], "BLOCKED_UNKNOWN")
        self.assertIsNone(packet["snapshot_packet_sha256"])
        self.assertEqual(packet["preflight_states"], {})
        self.assertEqual(packet["inventory_state"], "BLOCKED_UNKNOWN")
        self.assertEqual(packet["unresolved_count"], -1)
        self.assertEqual(packet["provider_states"], {})
        self.assertEqual(packet["blocking_providers"], list(PROVIDER_ORDER))
        self.assertRegex(packet["approval_packet_sha256"], r"^[a-f0-9]{64}$")

    def test_blocked_snapshot_maps_only_to_resolve_blockers(self) -> None:
        packet = build_live_readiness_approval_packet(_explicit_input(ready=False))
        self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(packet["next_action"], "RESOLVE_BLOCKERS")
        self.assertIs(packet["approval_granted"], False)
        self.assertIs(packet["live_ready"], False)
        self.assertIs(packet["dispatch_allowed"], False)
        self.assertIs(packet["human_approval_required"], True)
        self.assertEqual(packet["snapshot_state"], "BLOCKED_UNKNOWN")
        self.assertRegex(packet["snapshot_packet_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(packet["blocking_providers"], list(PROVIDER_ORDER))
        self.assertRegex(packet["approval_packet_sha256"], r"^[a-f0-9]{64}$")

    def test_ready_snapshot_maps_only_to_request_human_approval(self) -> None:
        packet = build_live_readiness_approval_packet(_explicit_input(ready=True))
        self.assertEqual(packet["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(packet["next_action"], "REQUEST_HUMAN_APPROVAL")
        self.assertIs(packet["approval_granted"], False)
        self.assertIs(packet["live_ready"], False)
        self.assertIs(packet["dispatch_allowed"], False)
        self.assertIs(packet["human_approval_required"], True)
        self.assertEqual(packet["snapshot_state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(packet["blocking_providers"], [])
        self.assertRegex(packet["approval_packet_sha256"], r"^[a-f0-9]{64}$")

    def test_output_is_exact_safe_summary_without_raw_inputs(self) -> None:
        packet = build_live_readiness_approval_packet(_explicit_input(ready=True))
        self.assertEqual(
            set(packet),
            {
                "state",
                "live_ready",
                "dispatch_allowed",
                "human_approval_required",
                "approval_granted",
                "retry_count",
                "fallback_state",
                "next_action",
                "snapshot_state",
                "snapshot_packet_sha256",
                "preflight_states",
                "inventory_state",
                "unresolved_count",
                "provider_states",
                "blocking_providers",
                "approval_packet_sha256",
            },
        )
        serialized = approval_mod._canonical_json(packet)
        for forbidden in (
            "route_evidence",
            "provider_meta",
            "evidence_ref",
            "preflight_snapshots",
            "reasons",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_dependency_called_exactly_once_for_valid_input(self) -> None:
        with mock.patch(
            "src.providers.live_readiness_approval.build_live_readiness_snapshot",
            wraps=real_build_live_readiness_snapshot,
        ) as dependency:
            packet = build_live_readiness_approval_packet(
                _explicit_input(ready=False)
            )
        dependency.assert_called_once()
        self.assertEqual(packet["state"], "BLOCKED_UNKNOWN")

    def test_malformed_or_nonserializable_input_calls_dependency_zero_times(self) -> None:
        valid = _explicit_input(ready=False)
        cases: list[Any] = [
            None,
            {},
            {"provider_configs": valid["provider_configs"]},
            {
                "provider_configs": valid["provider_configs"],
                "inventory": valid["inventory"],
                "extra": False,
            },
        ]

        bad_provider_set = copy.deepcopy(valid)
        bad_provider_set["provider_configs"].pop("google")
        cases.append(bad_provider_set)

        bad_inventory_set = copy.deepcopy(valid)
        bad_inventory_set["inventory"].pop("anthropic")
        cases.append(bad_inventory_set)

        bad_provider_value = copy.deepcopy(valid)
        bad_provider_value["provider_configs"]["openai"] = "bad"
        cases.append(bad_provider_value)

        bad_inventory_value = copy.deepcopy(valid)
        bad_inventory_value["inventory"]["google"] = []
        cases.append(bad_inventory_value)

        nonserializable = copy.deepcopy(valid)
        first_proof = next(iter(nonserializable["inventory"]["openai"]))
        nonserializable["inventory"]["openai"][first_proof] = object()
        cases.append(nonserializable)

        with mock.patch(
            "src.providers.live_readiness_approval.build_live_readiness_snapshot"
        ) as dependency:
            for index, case in enumerate(cases):
                with self.subTest(index=index):
                    self.assert_fail_closed(
                        build_live_readiness_approval_packet(case)
                    )
            dependency.assert_not_called()

    def test_snapshot_exception_is_one_attempt_and_fails_closed(self) -> None:
        with mock.patch(
            "src.providers.live_readiness_approval.build_live_readiness_snapshot",
            side_effect=RuntimeError("boom"),
        ) as dependency:
            packet = build_live_readiness_approval_packet(
                _explicit_input(ready=True)
            )
        dependency.assert_called_once()
        self.assert_fail_closed(packet)

    def test_malformed_snapshot_matrix_fails_closed(self) -> None:
        ready = _snapshot(ready=True)
        blocked = _snapshot(ready=False)
        cases: list[tuple[str, dict[str, Any]]] = []

        missing = copy.deepcopy(ready)
        missing.pop("state")
        cases.append(("missing-key", missing))

        extra = copy.deepcopy(ready)
        extra["extra"] = False
        cases.append(("extra-key", extra))

        for name, field, value in (
            ("bad-state", "state", "LIVE"),
            ("live-ready", "live_ready", True),
            ("dispatch", "dispatch_allowed", True),
            ("human-required", "human_approval_required", False),
            ("retry-one", "retry_count", 1),
            ("retry-bool", "retry_count", False),
            ("fallback", "fallback_state", "enabled"),
            ("bad-inventory-state", "inventory_state", "READY"),
            ("count-bool", "unresolved_count", False),
            ("count-negative", "unresolved_count", -2),
        ):
            item = copy.deepcopy(ready)
            item[field] = value
            cases.append((name, _rehash_snapshot(item)))

        bad_preflight_reasons = copy.deepcopy(ready)
        bad_preflight_reasons["preflight_snapshots"]["openai"]["reasons"] = ["ok", 7]
        cases.append(
            (
                "preflight-reasons",
                _rehash_preflights(bad_preflight_reasons),
            )
        )

        bad_agent = copy.deepcopy(ready)
        bad_agent["preflight_snapshots"]["openai"]["external_agent"] = "tampered"
        cases.append(("preflight-agent", _rehash_preflights(bad_agent)))

        bad_version = copy.deepcopy(ready)
        bad_version["preflight_snapshots"]["google"]["pinned_version"] = "0.0.0"
        cases.append(("preflight-version", _rehash_preflights(bad_version)))

        bad_preflight_status_link = copy.deepcopy(ready)
        bad_preflight_status_link["preflight_states"]["openai"] = "UNKNOWN"
        cases.append(("preflight-status-link", _rehash_snapshot(bad_preflight_status_link)))

        bad_preflight_hash = copy.deepcopy(ready)
        bad_preflight_hash["preflight_packet_sha256"] = "g" * 64
        cases.append(("preflight-hash", _rehash_snapshot(bad_preflight_hash)))

        bad_counts = copy.deepcopy(ready)
        bad_counts["unresolved_by_provider"]["openai"] = 1
        cases.append(("count-sum", _rehash_snapshot(bad_counts)))

        unresolved_zero = copy.deepcopy(blocked)
        unresolved_zero["inventory_state"] = "UNRESOLVED"
        unresolved_zero["unresolved_count"] = 0
        unresolved_zero["unresolved_by_provider"] = {
            "openai": 0,
            "anthropic": 0,
            "google": 0,
        }
        cases.append(("unresolved-zero", _rehash_snapshot(unresolved_zero)))

        provider_set = copy.deepcopy(ready)
        provider_set["provider_states"].pop("google")
        cases.append(("provider-set", _rehash_snapshot(provider_set)))

        provider_value = copy.deepcopy(ready)
        provider_value["provider_states"]["openai"] = "LIVE"
        cases.append(("provider-value", _rehash_snapshot(provider_value)))

        duplicate_blocker = copy.deepcopy(blocked)
        duplicate_blocker["blocking_providers"] = ["openai", "openai"]
        cases.append(("blocker-duplicate", _rehash_snapshot(duplicate_blocker)))

        wrong_order = copy.deepcopy(blocked)
        wrong_order["blocking_providers"] = ["google", "anthropic", "openai"]
        cases.append(("blocker-order", _rehash_snapshot(wrong_order)))

        blocked_all_ready = copy.deepcopy(ready)
        blocked_all_ready["state"] = "BLOCKED_UNKNOWN"
        cases.append(("state-cross-field", _rehash_snapshot(blocked_all_ready)))

        empty_states_no_blockers = copy.deepcopy(blocked)
        empty_states_no_blockers["blocking_providers"] = []
        cases.append(("empty-state-blockers", _rehash_snapshot(empty_states_no_blockers)))

        for field in (
            "inventory_packet_sha256",
            "bundle_packet_sha256",
            "pipeline_packet_sha256",
        ):
            item = copy.deepcopy(ready)
            item[field] = "g" * 64
            cases.append((f"{field}-nonhex", _rehash_snapshot(item)))

        ready_no_inventory_hash = copy.deepcopy(ready)
        ready_no_inventory_hash["inventory_packet_sha256"] = None
        cases.append(("ready-inventory-hash", _rehash_snapshot(ready_no_inventory_hash)))

        ready_no_bundle_hash = copy.deepcopy(ready)
        ready_no_bundle_hash["bundle_packet_sha256"] = None
        cases.append(("ready-bundle-hash", _rehash_snapshot(ready_no_bundle_hash)))

        ready_no_pipeline_hash = copy.deepcopy(ready)
        ready_no_pipeline_hash["pipeline_packet_sha256"] = None
        cases.append(("ready-pipeline-hash", _rehash_snapshot(ready_no_pipeline_hash)))

        digest_mismatch = copy.deepcopy(ready)
        digest_mismatch["snapshot_packet_sha256"] = "0" * 64
        cases.append(("snapshot-digest", digest_mismatch))

        for name, bad_snapshot in cases:
            with self.subTest(name=name), mock.patch(
                "src.providers.live_readiness_approval.build_live_readiness_snapshot",
                return_value=bad_snapshot,
            ):
                self.assert_fail_closed(
                    build_live_readiness_approval_packet(
                        _explicit_input(ready=True)
                    )
                )

    def test_dependency_result_and_source_mutation_isolation(self) -> None:
        source = _explicit_input(ready=True)
        external_snapshot = _snapshot(ready=True)

        with mock.patch(
            "src.providers.live_readiness_approval.build_live_readiness_snapshot",
            return_value=external_snapshot,
        ):
            packet = build_live_readiness_approval_packet(source)

        digest = packet["approval_packet_sha256"]
        source["provider_configs"]["openai"]["auth_kind"] = "tampered"
        proof = next(iter(source["inventory"]["openai"]))
        source["inventory"]["openai"][proof]["evidence_ref"] = "tampered"
        external_snapshot["state"] = "BLOCKED_UNKNOWN"
        external_snapshot["provider_states"]["openai"] = "BLOCKED_UNKNOWN"

        self.assertEqual(packet["approval_packet_sha256"], digest)
        self.assertEqual(packet["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(
            packet["provider_states"]["openai"],
            "READY_FOR_HUMAN_APPROVAL",
        )

    def test_equivalent_input_key_order_has_identical_digest(self) -> None:
        first = _explicit_input(ready=True)
        second = _explicit_input(ready=True)
        reordered = {
            "inventory": second["inventory"],
            "provider_configs": second["provider_configs"],
        }
        one = build_live_readiness_approval_packet(first)
        two = build_live_readiness_approval_packet(reordered)
        self.assertEqual(
            one["approval_packet_sha256"],
            two["approval_packet_sha256"],
        )

    def test_valid_evidence_ref_change_changes_digest_but_renderer_hides_value(self) -> None:
        first = _explicit_input(ready=True)
        second = copy.deepcopy(first)
        proof = next(iter(second["inventory"]["openai"]))
        second["inventory"]["openai"][proof]["evidence_ref"] = "different-evidence-ref"

        one = build_live_readiness_approval_packet(first)
        two = build_live_readiness_approval_packet(second)

        self.assertNotEqual(
            one["snapshot_packet_sha256"],
            two["snapshot_packet_sha256"],
        )
        self.assertNotEqual(
            one["approval_packet_sha256"],
            two["approval_packet_sha256"],
        )
        rendered = render_approval_summary_ja(two)
        self.assertNotIn("different-evidence-ref", rendered)
        self.assertNotIn("evidence_ref", rendered)

    def test_renderer_uses_safe_japanese_action_and_sanitizes_untrusted_values(self) -> None:
        ready = build_live_readiness_approval_packet(_explicit_input(ready=True))
        rendered = render_approval_summary_ja(ready)
        self.assertIn("ライブ実行: 禁止", rendered)
        self.assertIn("人間承認が必要: 承認未完了", rendered)
        self.assertIn("次アクション: 人間承認を要求可能（未承認）", rendered)
        self.assertNotIn("次アクション: REQUEST_HUMAN_APPROVAL", rendered)

        marker = "https://evil.invalid/?token=secret"
        tampered = {
            "state": marker,
            "next_action": marker,
            "unresolved_count": marker,
            "preflight_states": {
                "openai": marker,
                "anthropic": "PASS",
                "google": "PASS",
            },
            "provider_states": {
                "openai": marker,
                "anthropic": "READY_FOR_HUMAN_APPROVAL",
                "google": "READY_FOR_HUMAN_APPROVAL",
            },
            "blocking_providers": [marker],
        }
        safe = render_approval_summary_ja(tampered)
        self.assertNotIn(marker, safe)
        self.assertNotIn("token=", safe)
        self.assertIn("全体状態: BLOCKED_UNKNOWN", safe)
        self.assertIn("次アクション: ブロッカー解消が必要", safe)
        self.assertIn("未解決の証明数: -1", safe)

    def test_sha256_validator_is_exact_lowercase_hex(self) -> None:
        self.assertTrue(approval_mod._is_sha256("0" * 64))
        self.assertTrue(approval_mod._is_sha256("abcdef0123456789" * 4))
        self.assertFalse(approval_mod._is_sha256("g" * 64))
        self.assertFalse(approval_mod._is_sha256("A" * 64))
        self.assertFalse(approval_mod._is_sha256("0" * 63))

    def test_ast_static_boundary_has_only_snapshot_dependency(self) -> None:
        source = inspect.getsource(approval_mod)
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
            "validate_provider_static",
            "build_live_readiness_pipeline",
            "evaluate_live_readiness",
            "build_live_readiness_bundle",
        }
        snapshot_calls = 0

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
                for alias in node.names:
                    self.assertNotIn(alias.name, banned_calls)
            elif isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name == "build_live_readiness_snapshot":
                    snapshot_calls += 1
                if name is not None:
                    self.assertNotIn(name, banned_calls)

        self.assertEqual(snapshot_calls, 1)
