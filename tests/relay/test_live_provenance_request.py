import copy
import hashlib
import json
import unittest

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
