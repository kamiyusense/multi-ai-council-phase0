import ast
import copy
import hashlib
import inspect
import os
import unittest
from typing import Any

import src.providers.live_provenance_request as provenance_mod
from src.providers.live_approval_receipt import build_live_approval_receipt
from src.providers.live_readiness_approval import build_live_readiness_approval_packet
from src.providers.live_readiness_snapshot import build_live_readiness_snapshot
from src.providers.live_provenance_request import (
    _canonical_json,
    build_live_provenance_request,
    render_provenance_request_ja,
)
from tests.relay.test_live_readiness_snapshot import TestLiveReadinessSnapshot


class TestLiveProvenanceBoundary(unittest.TestCase):
    def setUp(self) -> None:
        fixture = TestLiveReadinessSnapshot()
        fixture.setUp()
        self.provider_configs = copy.deepcopy(fixture.valid_configs)
        self.confirmed_inventory = copy.deepcopy(fixture.confirmed_inventory)
        self.unknown_inventory = copy.deepcopy(fixture.unknown_inventory)
        self.safe_locator = {
            "source_kind": "GITHUB_DURABLE_RECORD",
            "repository_full_name": "owner/repo",
            "ref": "main",
            "path": "path/to/record.json",
            "expected_record_sha256": "c" * 64,
        }

    def _input(self, inventory: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider_configs": copy.deepcopy(self.provider_configs),
            "inventory": copy.deepcopy(inventory),
        }

    def _approval(self, inventory: dict[str, Any]) -> dict[str, Any]:
        return build_live_readiness_approval_packet(self._input(inventory))

    def _receipt(
        self,
        approval: dict[str, Any],
        decision: str = "APPROVE_FIRST_LIVE_POC",
        one_shot: bool = True,
    ) -> dict[str, Any]:
        return build_live_approval_receipt(
            {
                "approval_packet": copy.deepcopy(approval),
                "approval_record": {
                    "decision": decision,
                    "scope": "FIRST_LIVE_POC_ONLY",
                    "one_shot": one_shot,
                    "recorded_at": "2026-09-29T09:00:00+09:00",
                    "target_approval_packet_sha256": approval[
                        "approval_packet_sha256"
                    ],
                    "target_snapshot_packet_sha256": approval[
                        "snapshot_packet_sha256"
                    ],
                },
            }
        )

    def _request(
        self,
        receipt: dict[str, Any],
        locator: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_live_provenance_request(
            {
                "approval_receipt": copy.deepcopy(receipt),
                "durable_locator": copy.deepcopy(
                    self.safe_locator if locator is None else locator
                ),
            }
        )

    def _assert_terminal_request(self, request: dict[str, Any]) -> None:
        self.assertEqual(request["state"], "PROVENANCE_VERIFICATION_REQUIRED")
        self.assertEqual(
            request["next_action"],
            "READBACK_DURABLE_HUMAN_PROVENANCE",
        )
        self.assertIs(request["provenance_verified"], False)
        self.assertIs(request["execution_authorized"], False)
        self.assertIs(request["dispatch_allowed"], False)
        self.assertIs(request["live_ready"], False)
        self.assertEqual(request["retry_count"], 0)
        self.assertEqual(request["fallback_state"], "disabled")

    def _assert_fail_closed(self, request: dict[str, Any]) -> None:
        self.assertEqual(request["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(request["next_action"], "RESOLVE_BLOCKERS")
        self.assertIs(request["provenance_verified"], False)
        self.assertIs(request["execution_authorized"], False)
        self.assertIs(request["dispatch_allowed"], False)
        self.assertIs(request["live_ready"], False)

    def test_synthetic_complete_chain_stops_at_provenance_required(self) -> None:
        snapshot = build_live_readiness_snapshot(
            self._input(self.confirmed_inventory)
        )
        approval = self._approval(self.confirmed_inventory)
        receipt = self._receipt(approval)
        request = self._request(receipt)

        self.assertEqual(snapshot["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertIs(snapshot["live_ready"], False)
        self.assertIs(snapshot["dispatch_allowed"], False)

        self.assertEqual(approval["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(approval["next_action"], "REQUEST_HUMAN_APPROVAL")
        self.assertIs(approval["approval_granted"], False)

        self.assertEqual(
            receipt["state"],
            "STRUCTURALLY_VALID_APPROVAL_RECORD",
        )
        self.assertEqual(
            receipt["next_action"],
            "VERIFY_DURABLE_HUMAN_PROVENANCE",
        )
        self.assertIs(receipt["provenance_verified"], False)
        self.assertIs(receipt["execution_authorized"], False)

        self._assert_terminal_request(request)

    def test_unknown_readiness_never_advances(self) -> None:
        approval = self._approval(self.unknown_inventory)
        receipt = self._receipt(approval)
        request = self._request(receipt)
        self._assert_fail_closed(request)

    def test_reject_and_defer_never_advance(self) -> None:
        approval = self._approval(self.confirmed_inventory)
        for decision in ("REJECT", "DEFER"):
            with self.subTest(decision=decision):
                receipt = self._receipt(
                    approval,
                    decision=decision,
                    one_shot=False,
                )
                self._assert_fail_closed(self._request(receipt))

    def test_receipt_tamper_matrix_fails_closed(self) -> None:
        approval = self._approval(self.confirmed_inventory)
        receipt = self._receipt(approval)
        cases = [
            ("state", "BLOCKED_UNKNOWN"),
            ("decision", "REJECT"),
            ("scope", "UNKNOWN"),
            ("one_shot", False),
            ("next_action", "RESOLVE_BLOCKERS"),
            ("live_ready", True),
            ("dispatch_allowed", True),
            ("execution_authorized", True),
            ("provenance_verified", True),
            ("retry_count", 1),
            ("retry_count", True),
            ("approval_packet_sha256", "0" * 64),
            ("snapshot_packet_sha256", "0" * 64),
            ("approval_record_sha256", "0" * 64),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                tampered = copy.deepcopy(receipt)
                tampered[field] = value
                self._assert_fail_closed(self._request(tampered))

    def test_locator_tamper_matrix_fails_closed(self) -> None:
        approval = self._approval(self.confirmed_inventory)
        receipt = self._receipt(approval)
        cases = [
            ("source_kind", "INVALID"),
            ("repository_full_name", "owner"),
            ("repository_full_name", "owner//repo"),
            ("repository_full_name", "../repo"),
            ("repository_full_name", "owner/."),
            ("ref", "main:evil"),
            ("ref", "main~1"),
            ("ref", "main^"),
            ("ref", "ma?in"),
            ("ref", "ma*in"),
            ("ref", "ma[in"),
            ("ref", ".hidden"),
            ("ref", "feature/.hidden"),
            ("ref", "feature/name."),
            ("ref", "feature/name.lock"),
            ("ref", "main/.."),
            ("ref", "/main"),
            ("ref", "main/"),
            ("ref", "a//b"),
            ("ref", "@{main}"),
            ("ref", "-main"),
            ("path", "/path/file.json"),
            ("path", "path\\file.json"),
            ("path", "path/./file.json"),
            ("path", "path/../file.json"),
            ("path", "path//file.json"),
            ("path", "path/file.txt"),
            ("expected_record_sha256", "C" * 64),
            ("expected_record_sha256", "g" * 64),
            ("expected_record_sha256", "0" * 63),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                locator = copy.deepcopy(self.safe_locator)
                locator[field] = value
                self._assert_fail_closed(self._request(receipt, locator))

    def test_hash_bindings_and_locator_sensitivity(self) -> None:
        approval = self._approval(self.confirmed_inventory)
        receipt = self._receipt(approval)
        request = self._request(receipt)

        receipt_payload = {
            key: value
            for key, value in receipt.items()
            if key != "approval_record_sha256"
        }
        self.assertEqual(
            receipt["approval_record_sha256"],
            hashlib.sha256(
                _canonical_json(receipt_payload).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(
            request["durable_locator_sha256"],
            hashlib.sha256(
                _canonical_json(self.safe_locator).encode("utf-8")
            ).hexdigest(),
        )
        request_payload = {
            key: value
            for key, value in request.items()
            if key != "provenance_request_sha256"
        }
        self.assertEqual(
            request["provenance_request_sha256"],
            hashlib.sha256(
                _canonical_json(request_payload).encode("utf-8")
            ).hexdigest(),
        )

        variants = []
        ref_changed = copy.deepcopy(self.safe_locator)
        ref_changed["ref"] = "feature/provenance-check"
        variants.append(ref_changed)

        path_changed = copy.deepcopy(self.safe_locator)
        path_changed["path"] = "other/record.json"
        variants.append(path_changed)

        hash_changed = copy.deepcopy(self.safe_locator)
        hash_changed["expected_record_sha256"] = "d" * 64
        variants.append(hash_changed)

        for locator in variants:
            changed = self._request(receipt, locator)
            self.assertNotEqual(
                changed["durable_locator_sha256"],
                request["durable_locator_sha256"],
            )
            self.assertNotEqual(
                changed["provenance_request_sha256"],
                request["provenance_request_sha256"],
            )

    def test_determinism_for_equivalent_key_order(self) -> None:
        approval = self._approval(self.confirmed_inventory)
        receipt = self._receipt(approval)

        first = self._request(receipt)
        reversed_locator = dict(reversed(list(self.safe_locator.items())))
        second = self._request(receipt, reversed_locator)
        third = self._request(copy.deepcopy(receipt))

        self.assertEqual(first, second)
        self.assertEqual(first, third)

    def test_renderer_and_output_do_not_leak_locator_material(self) -> None:
        approval = self._approval(self.confirmed_inventory)
        receipt = self._receipt(approval)
        locator = {
            "source_kind": "GITHUB_DURABLE_RECORD",
            "repository_full_name": "secret-owner/secret-repo",
            "ref": "feature/private-ref",
            "path": "private/approval-record.json",
            "expected_record_sha256": "d" * 64,
        }
        request = self._request(receipt, locator)
        rendered = render_provenance_request_ja(request)
        serialized = _canonical_json(request)

        for marker in (
            "secret-owner/secret-repo",
            "feature/private-ref",
            "private/approval-record.json",
            "GITHUB_DURABLE_RECORD",
            "recorded_at",
            "route_evidence",
            "provider_meta",
            "evidence_ref",
            "reasons",
            "https://",
            "http://",
        ):
            self.assertNotIn(marker, rendered)
            self.assertNotIn(marker, serialized)

        self.assertIn("STATIC / PREPARED", rendered)
        self.assertIn("人間由来: 未検証", rendered)
        self.assertIn("ライブ実行: 禁止", rendered)

    def test_ast_boundary_excludes_ambient_github_and_live_operations(self) -> None:
        source = inspect.getsource(provenance_mod)
        tree = ast.parse(source)
        banned_import_roots = {
            "os",
            "pathlib",
            "subprocess",
            "socket",
            "http",
            "urllib",
            "requests",
            "github",
            "time",
            "random",
        }
        banned_call_names = {
            "open",
            "exec",
            "eval",
            "__import__",
            "urlopen",
            "request",
            "now",
            "today",
            "utcnow",
            "validate_provider_static",
            "build_live_readiness_pipeline",
            "evaluate_live_readiness",
            "build_live_readiness_snapshot",
            "build_live_readiness_approval_packet",
            "build_live_approval_receipt",
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
                    self.assertNotIn(name, banned_call_names)

    def test_terminal_boundary_is_durable_in_docs(self) -> None:
        base = os.path.join(os.path.dirname(__file__), "..", "..", "docs")
        with open(
            os.path.join(base, "RELAY_LIVE_PROVENANCE_BOUNDARY_AUDIT.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            boundary = stream.read()
        with open(
            os.path.join(base, "RELAY_STATIC_CHECKPOINT.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            checkpoint = stream.read()

        required_boundary = (
            "PROVENANCE_VERIFICATION_REQUIRED is terminal for current static Relay code",
            "GitHub Actions readback alone is transport evidence, not independent human provenance",
            "OIDC and Artifact Attestation are NOT AUTHORIZED in this batch",
            "No `id-token: write`, `attestations: write`, or permission changes are made",
            "The production authenticator remains NOT_WIRED",
            "first live provider turn remains separately bounded and explicit-human-approved",
            "synthetic fixture data",
            "No real live blocker is resolved",
        )
        for statement in required_boundary:
            self.assertIn(statement, boundary)

        for statement in (
            "PROVENANCE_VERIFICATION_REQUIRED is terminal for current static Relay code",
            "production authenticators remain NOT_WIRED",
            "No real live blocker is resolved",
            "human provenance remains unverified",
            "first live provider turn remains unauthorized",
        ):
            self.assertIn(statement, checkpoint)
