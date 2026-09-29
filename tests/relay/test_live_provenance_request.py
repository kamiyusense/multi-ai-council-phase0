import ast
import copy
import hashlib
import inspect
import json
import unittest

import providers.live_provenance_request as provenance_mod
from providers.live_provenance_request import (
    build_live_provenance_request,
    render_provenance_request_ja,
    _canonical_json,
)

class TestLiveProvenanceRequest(unittest.TestCase):
    def setUp(self):
        receipt_payload = {
            "state": "STRUCTURALLY_VALID_APPROVAL_RECORD",
            "live_ready": False,
            "dispatch_allowed": False,
            "execution_authorized": False,
            "provenance_verified": False,
            "retry_count": 0,
            "fallback_state": "disabled",
            "decision": "APPROVE_FIRST_LIVE_POC",
            "scope": "FIRST_LIVE_POC_ONLY",
            "one_shot": True,
            "approval_packet_sha256": "a" * 64,
            "snapshot_packet_sha256": "b" * 64,
            "next_action": "VERIFY_DURABLE_HUMAN_PROVENANCE",
        }
        receipt_payload["approval_record_sha256"] = hashlib.sha256(
            _canonical_json(receipt_payload).encode("utf-8")
        ).hexdigest()

        self.valid_receipt = receipt_payload

        self.valid_locator = {
            "source_kind": "GITHUB_DURABLE_RECORD",
            "repository_full_name": "owner/repo",
            "ref": "main",
            "path": "path/to/record.json",
            "expected_record_sha256": "c" * 64,
        }

        self.valid_input = {
            "approval_receipt": self.valid_receipt,
            "durable_locator": self.valid_locator,
        }

    def test_valid_input(self):
        result = build_live_provenance_request(self.valid_input)
        self.assertEqual(result["state"], "PROVENANCE_VERIFICATION_REQUIRED")
        self.assertEqual(result["next_action"], "READBACK_DURABLE_HUMAN_PROVENANCE")
        self.assertEqual(result["approval_record_sha256"], self.valid_receipt["approval_record_sha256"])
        self.assertEqual(result["approval_packet_sha256"], self.valid_receipt["approval_packet_sha256"])
        self.assertEqual(result["snapshot_packet_sha256"], self.valid_receipt["snapshot_packet_sha256"])
        self.assertEqual(result["expected_record_sha256"], self.valid_locator["expected_record_sha256"])
        self.assertEqual(result["live_ready"], False)
        self.assertEqual(result["dispatch_allowed"], False)
        self.assertEqual(result["execution_authorized"], False)
        self.assertEqual(result["provenance_verified"], False)
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")

        # Ensure durable_locator_sha256 is correctly calculated
        expected_locator_sha256 = hashlib.sha256(
            _canonical_json(self.valid_locator).encode("utf-8")
        ).hexdigest()
        self.assertEqual(result["durable_locator_sha256"], expected_locator_sha256)

        # Ensure provenance_request_sha256 is correct
        payload = {k: v for k, v in result.items() if k != "provenance_request_sha256"}
        expected_request_sha256 = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        self.assertEqual(result["provenance_request_sha256"], expected_request_sha256)

    def test_blocked_receipt(self):
        input_data = copy.deepcopy(self.valid_input)
        input_data["approval_receipt"]["state"] = "BLOCKED_UNKNOWN"
        input_data["approval_receipt"]["next_action"] = "RESOLVE_BLOCKERS"
        payload = {k: v for k, v in input_data["approval_receipt"].items() if k != "approval_record_sha256"}
        input_data["approval_receipt"]["approval_record_sha256"] = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()

        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(result["next_action"], "RESOLVE_BLOCKERS")

    def test_non_approval_receipt(self):
        input_data = copy.deepcopy(self.valid_input)
        input_data["approval_receipt"]["state"] = "NON_APPROVAL_DECISION"
        input_data["approval_receipt"]["decision"] = "REJECT"
        input_data["approval_receipt"]["next_action"] = "NO_LIVE_ACTION"
        payload = {k: v for k, v in input_data["approval_receipt"].items() if k != "approval_record_sha256"}
        input_data["approval_receipt"]["approval_record_sha256"] = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()

        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(result["next_action"], "RESOLVE_BLOCKERS")

    def test_malformed_receipt_flags(self):
        for flag in ["live_ready", "dispatch_allowed", "execution_authorized", "provenance_verified"]:
            with self.subTest(flag=flag):
                input_data = copy.deepcopy(self.valid_input)
                input_data["approval_receipt"][flag] = True
                payload = {k: v for k, v in input_data["approval_receipt"].items() if k != "approval_record_sha256"}
                input_data["approval_receipt"]["approval_record_sha256"] = hashlib.sha256(
                    _canonical_json(payload).encode("utf-8")
                ).hexdigest()
                result = build_live_provenance_request(input_data)
                self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_malformed_receipt_bool_as_int(self):
        input_data = copy.deepcopy(self.valid_input)
        input_data["approval_receipt"]["one_shot"] = 1
        payload = {k: v for k, v in input_data["approval_receipt"].items() if k != "approval_record_sha256"}
        input_data["approval_receipt"]["approval_record_sha256"] = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_malformed_receipt_digest_mismatch(self):
        input_data = copy.deepcopy(self.valid_input)
        input_data["approval_receipt"]["approval_record_sha256"] = "f" * 64
        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_receipt_missing_extra_keys(self):
        input_data = copy.deepcopy(self.valid_input)
        del input_data["approval_receipt"]["state"]
        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

        input_data = copy.deepcopy(self.valid_input)
        input_data["approval_receipt"]["extra"] = True
        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_locator_missing_extra_keys(self):
        input_data = copy.deepcopy(self.valid_input)
        del input_data["durable_locator"]["ref"]
        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

        input_data = copy.deepcopy(self.valid_input)
        input_data["durable_locator"]["extra"] = True
        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_invalid_source_kind(self):
        input_data = copy.deepcopy(self.valid_input)
        input_data["durable_locator"]["source_kind"] = "OTHER_KIND"
        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_repo_invalid_formats(self):
        invalid_repos = ["owner", "owner/repo/extra", "owner/re po", "/repo", "owner/", "own#er/repo"]
        for repo in invalid_repos:
            with self.subTest(repo=repo):
                input_data = copy.deepcopy(self.valid_input)
                input_data["durable_locator"]["repository_full_name"] = repo
                result = build_live_provenance_request(input_data)
                self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_ref_invalid_formats(self):
        invalid_refs = [" main", "main\n", "ma\\in", "/main", "main/", "ma//in", "ma..in", "ma@{in", "-main"]
        for ref in invalid_refs:
            with self.subTest(ref=ref):
                input_data = copy.deepcopy(self.valid_input)
                input_data["durable_locator"]["ref"] = ref
                result = build_live_provenance_request(input_data)
                self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_path_invalid_formats(self):
        invalid_paths = [
            "/path.json", "path\\to.json", "path/./to.json", "path/../to.json",
            "path//to.json", "path.txt", "", "path/to/\n.json"
        ]
        for path in invalid_paths:
            with self.subTest(path=path):
                input_data = copy.deepcopy(self.valid_input)
                input_data["durable_locator"]["path"] = path
                result = build_live_provenance_request(input_data)
                self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_expected_record_sha256_invalid(self):
        invalid_hashes = ["C" * 64, "c" * 63, "g" * 64, 123]
        for h in invalid_hashes:
            with self.subTest(h=h):
                input_data = copy.deepcopy(self.valid_input)
                input_data["durable_locator"]["expected_record_sha256"] = h
                result = build_live_provenance_request(input_data)
                self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_nonserializable_input(self):
        input_data = copy.deepcopy(self.valid_input)
        input_data["durable_locator"]["ref"] = object()
        result = build_live_provenance_request(input_data)
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_source_result_mutation_isolation(self):
        input_data = copy.deepcopy(self.valid_input)
        result = build_live_provenance_request(input_data)
        input_data["durable_locator"]["ref"] = "other"
        self.assertEqual(result["state"], "PROVENANCE_VERIFICATION_REQUIRED")

    def test_equivalent_key_ordering(self):
        input1 = self.valid_input
        input2 = {
            "durable_locator": self.valid_locator,
            "approval_receipt": self.valid_receipt,
        }
        result1 = build_live_provenance_request(input1)
        result2 = build_live_provenance_request(input2)
        self.assertEqual(result1["provenance_request_sha256"], result2["provenance_request_sha256"])

    def test_locator_change_determinism(self):
        result1 = build_live_provenance_request(self.valid_input)

        input2 = copy.deepcopy(self.valid_input)
        input2["durable_locator"]["path"] = "other/path.json"
        result2 = build_live_provenance_request(input2)

        self.assertNotEqual(result1["durable_locator_sha256"], result2["durable_locator_sha256"])
        self.assertNotEqual(result1["provenance_request_sha256"], result2["provenance_request_sha256"])

    def test_render_sanitization(self):
        input_data = copy.deepcopy(self.valid_input)
        input_data["durable_locator"]["repository_full_name"] = "evil/repo"
        result = build_live_provenance_request(input_data)
        rendered = render_provenance_request_ja(result)

        self.assertNotIn("evil/repo", rendered)
        self.assertNotIn("main", rendered)
        self.assertNotIn("path/to/record.json", rendered)
        self.assertIn("STATIC / PREPARED", rendered)
        self.assertIn("人間由来: 未検証", rendered)
        self.assertIn("execution: 未認可", rendered)
        self.assertIn("durable readback is required", rendered)
        self.assertIn("ライブ実行: 禁止", rendered)

    def test_reject_and_defer_receipts_cannot_advance(self):
        for decision in ("REJECT", "DEFER"):
            with self.subTest(decision=decision):
                input_data = copy.deepcopy(self.valid_input)
                receipt = input_data["approval_receipt"]
                receipt["state"] = "NON_APPROVAL_DECISION"
                receipt["decision"] = decision
                receipt["next_action"] = "NO_LIVE_ACTION"
                payload = {
                    k: v
                    for k, v in receipt.items()
                    if k != "approval_record_sha256"
                }
                receipt["approval_record_sha256"] = hashlib.sha256(
                    _canonical_json(payload).encode("utf-8")
                ).hexdigest()

                result = build_live_provenance_request(input_data)
                self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
                self.assertEqual(result["next_action"], "RESOLVE_BLOCKERS")
                self.assertFalse(result["provenance_verified"])
                self.assertFalse(result["execution_authorized"])

    def test_additional_nonconservative_ref_formats_are_rejected(self):
        invalid_refs = [
            "refs/heads/main:evil",
            "refs/heads/main~1",
            "refs/heads/main^",
            "refs/heads/ma?in",
            "refs/heads/ma*in",
            "refs/heads/ma[in",
            ".hidden",
            "feature/.hidden",
            "feature/name.",
            "feature/name.lock",
            "@",
        ]
        for ref in invalid_refs:
            with self.subTest(ref=ref):
                input_data = copy.deepcopy(self.valid_input)
                input_data["durable_locator"]["ref"] = ref
                result = build_live_provenance_request(input_data)
                self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_dot_only_repository_segments_are_rejected(self):
        for repository in (".", ".."):
            for value in (f"{repository}/repo", f"owner/{repository}"):
                with self.subTest(repository=value):
                    input_data = copy.deepcopy(self.valid_input)
                    input_data["durable_locator"]["repository_full_name"] = value
                    result = build_live_provenance_request(input_data)
                    self.assertEqual(result["state"], "BLOCKED_UNKNOWN")

    def test_locator_ref_and_expected_hash_changes_rebind_digests_without_leakage(self):
        baseline = build_live_provenance_request(
            copy.deepcopy(self.valid_input)
        )

        variants = []
        ref_changed = copy.deepcopy(self.valid_input)
        ref_changed["durable_locator"]["ref"] = "feature/provenance-check"
        variants.append(("feature/provenance-check", ref_changed))

        hash_changed = copy.deepcopy(self.valid_input)
        hash_changed["durable_locator"]["expected_record_sha256"] = "d" * 64
        variants.append(("d" * 64, hash_changed))

        path_changed = copy.deepcopy(self.valid_input)
        path_changed["durable_locator"]["path"] = "other/approval-record.json"
        variants.append(("other/approval-record.json", path_changed))

        for marker, variant in variants:
            with self.subTest(marker=marker):
                result = build_live_provenance_request(variant)
                self.assertEqual(
                    result["state"],
                    "PROVENANCE_VERIFICATION_REQUIRED",
                )
                self.assertNotEqual(
                    result["durable_locator_sha256"],
                    baseline["durable_locator_sha256"],
                )
                self.assertNotEqual(
                    result["provenance_request_sha256"],
                    baseline["provenance_request_sha256"],
                )
                rendered = render_provenance_request_ja(result)
                self.assertNotIn(marker, rendered)
                self.assertNotIn(
                    variant["durable_locator"]["repository_full_name"],
                    rendered,
                )

    def test_source_and_result_are_independent_after_return(self):
        source = copy.deepcopy(self.valid_input)
        result = build_live_provenance_request(source)
        original_digest = result["provenance_request_sha256"]
        original_locator_digest = result["durable_locator_sha256"]

        source["approval_receipt"]["decision"] = "REJECT"
        source["durable_locator"]["path"] = "mutated/record.json"
        result["state"] = "BLOCKED_UNKNOWN"

        fresh = build_live_provenance_request(
            copy.deepcopy(self.valid_input)
        )
        self.assertEqual(
            fresh["provenance_request_sha256"],
            original_digest,
        )
        self.assertEqual(
            fresh["durable_locator_sha256"],
            original_locator_digest,
        )
        self.assertEqual(
            fresh["state"],
            "PROVENANCE_VERIFICATION_REQUIRED",
        )

    def test_ast_static_boundary_excludes_ambient_github_and_live_operations(self):
        source = inspect.getsource(provenance_mod)
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
            "github",
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
            "request",
            "urlopen",
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
                    self.assertNotIn(name, banned_calls)

