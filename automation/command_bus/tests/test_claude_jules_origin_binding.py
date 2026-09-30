import copy
import unittest
from datetime import datetime, timedelta, timezone

from automation.command_bus.claude_jules_origin_binding import (
    CLAUDE_AUTO_ORIGIN_BINDING_PROFILE,
    build_binding_record,
    compute_binding_sha256,
    validate_binding_record,
    verify_binding_record,
)


class TestClaudeJulesOriginBinding(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 30, 0, 30, tzinfo=timezone.utc)
        self.created_at = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc).isoformat()
        self.expires_at = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc).isoformat()

        self.valid_request = {
            "schema_version": 2,
            "profile": "JULES_CHAT_SEMIAUTO_V2",
            "command_id": "relay-dev-loop-123-compat-baseline",
            "target_repo": "kamiyusense/multi-ai-council-phase0",
            "target_branch": "feature/bounded-target",
            "work_branch": "jules-work/relay-dev-loop-123-compat-baseline",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "allowed_paths": ["docs/CLAUDE_NIGHT_LOOP_DESIGN.md"],
            "prompt": "Test baseline",
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "merge_allowed": False,
            "force_push_allowed": False,
            "retry": 0,
            "fallback": "disabled",
        }

        self.valid_claim = {
            "schema_version": 3,
            "loop_number": 123,
            "loop_id": "123",
            "task_id": "compat-baseline",
            "command_id": "relay-dev-loop-123-compat-baseline",
            "target_branch": "feature/bounded-target",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "work_branch": "jules-work/relay-dev-loop-123-compat-baseline",
            "state": "CLAIMED",
            "claimed_at": self.created_at,
            "retry": 0,
            "fallback": "disabled",
            "lane_id": "J-GREEN",
            "lane_display": "💚",
            "duplicate_guard": "00000000",
        }

        self.origin_kwargs = {
            "origin_loop_id": "123",
            "origin_round": 1,
            "origin_correlation_id": "cor-1",
            "origin_generation": 1,
            "carrier_request": self.valid_request,
            "carrier_claim": self.valid_claim,
        }

    def test_build_validate_verify_success(self):
        record = build_binding_record(**self.origin_kwargs)

        # Test standalone validate
        validated = validate_binding_record(record)
        self.assertEqual(validated, record)
        self.assertIsNot(validated, record)

        # Test verify
        verified = verify_binding_record(record, self.valid_request, self.valid_claim)
        self.assertEqual(verified, record)
        self.assertIsNot(verified, record)

        # Ensure lane info is strictly absent
        self.assertNotIn("lane_id", record)
        self.assertNotIn("lane_display", record)

        # Ensure origin identity survives unchanged
        self.assertEqual(record["origin_loop_id"], "123")
        self.assertEqual(record["origin_round"], 1)
        self.assertEqual(record["origin_correlation_id"], "cor-1")
        self.assertEqual(record["origin_generation"], 1)

    def test_deterministic_builder(self):
        record1 = build_binding_record(**self.origin_kwargs)
        record2 = build_binding_record(**self.origin_kwargs)

        self.assertEqual(record1, record2)
        self.assertEqual(record1["binding_sha256"], record2["binding_sha256"])

    def test_missing_and_extra_key(self):
        record = build_binding_record(**self.origin_kwargs)

        missing_record = dict(record)
        del missing_record["target_repo"]
        missing_record["binding_sha256"] = compute_binding_sha256(missing_record)
        with self.assertRaisesRegex(ValueError, "record keys mismatch"):
            validate_binding_record(missing_record)

        extra_record = dict(record)
        extra_record["extra_field"] = "foo"
        extra_record["binding_sha256"] = compute_binding_sha256(extra_record)
        with self.assertRaisesRegex(ValueError, "record keys mismatch"):
            validate_binding_record(extra_record)

    def test_wrong_schema_and_profile(self):
        record = build_binding_record(**self.origin_kwargs)

        schema_bad = dict(record)
        schema_bad["schema_version"] = 2
        schema_bad["binding_sha256"] = compute_binding_sha256(schema_bad)
        with self.assertRaisesRegex(ValueError, "schema_version must be 1"):
            validate_binding_record(schema_bad)

        profile_bad = dict(record)
        profile_bad["profile"] = "WRONG_PROFILE"
        profile_bad["binding_sha256"] = compute_binding_sha256(profile_bad)
        with self.assertRaisesRegex(ValueError, "invalid profile"):
            validate_binding_record(profile_bad)

    def test_origin_round_and_generation_bool_rejection(self):
        for field in ["origin_round", "origin_generation"]:
            kwargs = copy.deepcopy(self.origin_kwargs)
            kwargs[field] = True
            with self.assertRaisesRegex(ValueError, "must be a real integer"):
                build_binding_record(**kwargs)

    def test_origin_round_and_generation_bounds(self):
        for field in ["origin_round", "origin_generation"]:
            kwargs = copy.deepcopy(self.origin_kwargs)
            kwargs[field] = 0
            with self.assertRaisesRegex(ValueError, "must be >= 1"):
                build_binding_record(**kwargs)

    def test_blank_control_char_whitespace_strings(self):
        for val, pattern in [
            ("", "cannot be empty"),
            (" ", "contains control characters or ambiguous whitespace"),
            (" foo", "contains control characters or ambiguous whitespace"),
            ("foo\nbar", "contains control characters or ambiguous whitespace"),
            ("foo ", "contains control characters or ambiguous whitespace"),
        ]:
            kwargs = copy.deepcopy(self.origin_kwargs)
            kwargs["origin_loop_id"] = val
            with self.assertRaisesRegex(ValueError, pattern):
                build_binding_record(**kwargs)

    def test_identity_string_length_bound(self):
        kwargs = copy.deepcopy(self.origin_kwargs)
        kwargs["origin_correlation_id"] = "x" * 1025
        with self.assertRaisesRegex(ValueError, "origin_correlation_id exceeds maximum length"):
            build_binding_record(**kwargs)

    def test_malformed_hashes_and_ids(self):
        record = build_binding_record(**self.origin_kwargs)

        hash_cases = [
            ("expected_target_head", "g" * 40, "expected_target_head format is invalid"),
            ("expected_target_head", "a" * 39, "expected_target_head format is invalid"),
            ("expected_target_head", "A" * 40, "expected_target_head format is invalid"),
            ("expected_target_tree", "g" * 40, "expected_target_tree format is invalid"),
            ("expected_target_tree", "b" * 39, "expected_target_tree format is invalid"),
            ("expected_target_tree", "B" * 40, "expected_target_tree format is invalid"),
        ]
        for field, value, error in hash_cases:
            bad = dict(record)
            bad[field] = value
            bad["binding_sha256"] = compute_binding_sha256(bad)
            with self.assertRaisesRegex(ValueError, error):
                validate_binding_record(bad)

        for value in ("A" * 64, "a" * 63):
            bad_sha = dict(record)
            bad_sha["binding_sha256"] = value
            with self.assertRaisesRegex(ValueError, "binding_sha256 format is invalid"):
                validate_binding_record(bad_sha)

    def test_digest_mismatch_on_mutation(self):
        record = build_binding_record(**self.origin_kwargs)
        record["origin_generation"] = 2
        with self.assertRaisesRegex(ValueError, "binding_sha256 digest mismatch"):
            validate_binding_record(record)

    def test_cross_binding_schema_profile_mismatches(self):
        record = build_binding_record(**self.origin_kwargs)

        req = dict(self.valid_request)
        req["schema_version"] = 1
        with self.assertRaisesRegex(ValueError, "request schema mismatch"):
            verify_binding_record(record, req, self.valid_claim)

        req = dict(self.valid_request)
        req["profile"] = "WRONG"
        with self.assertRaisesRegex(ValueError, "request profile mismatch"):
            verify_binding_record(record, req, self.valid_claim)

        claim = dict(self.valid_claim)
        claim["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "claim schema mismatch"):
            verify_binding_record(record, self.valid_request, claim)

    def test_cross_binding_field_mismatches(self):
        record = build_binding_record(**self.origin_kwargs)

        mismatches = [
            ("command_id", "request command_id mismatch", "carrier_request"),
            ("command_id", "claim command_id mismatch", "carrier_claim"),
            ("target_branch", "request target_branch mismatch", "carrier_request"),
            ("target_branch", "claim target_branch mismatch", "carrier_claim"),
            ("work_branch", "request work_branch mismatch", "carrier_request"),
            ("work_branch", "claim work_branch mismatch", "carrier_claim"),
            ("expected_target_head", "request expected_target_head mismatch", "carrier_request"),
            ("expected_target_head", "claim expected_target_head mismatch", "carrier_claim"),
            ("expected_target_tree", "request expected_target_tree mismatch", "carrier_request"),
            ("expected_target_tree", "claim expected_target_tree mismatch", "carrier_claim"),
            ("retry", "request retry mismatch", "carrier_request"),
            ("retry", "claim retry mismatch", "carrier_claim"),
            ("fallback", "request fallback mismatch", "carrier_request"),
            ("fallback", "claim fallback mismatch", "carrier_claim"),
            ("target_repo", "request target_repo mismatch", "carrier_request"),
            ("created_at", "request created_at mismatch", "carrier_request"),
            ("expires_at", "request expires_at mismatch", "carrier_request"),
            ("loop_id", "claim loop_id mismatch", "carrier_claim"),
        ]

        for field, err_msg, src in mismatches:
            req = dict(self.valid_request)
            claim = dict(self.valid_claim)

            if src == "carrier_request":
                req[field] = "mutated-val" if isinstance(req.get(field), str) else 99
            else:
                claim[field] = "mutated-val" if isinstance(claim.get(field), str) else 99

            with self.assertRaisesRegex(ValueError, err_msg):
                verify_binding_record(record, req, claim)

    def test_builder_cross_binding_failure(self):
        req = dict(self.valid_request)
        req["command_id"] = "mismatch"
        kwargs = dict(self.origin_kwargs)
        kwargs["carrier_request"] = req
        with self.assertRaisesRegex(ValueError, "request/claim command_id mismatch"):
            build_binding_record(**kwargs)

    def test_fail_closed_on_missing_field_leakage(self):
        req = dict(self.valid_request)
        del req["command_id"]
        kwargs = dict(self.origin_kwargs)
        kwargs["carrier_request"] = req

        with self.assertRaisesRegex(ValueError, "request/claim command_id mismatch"):
            build_binding_record(**kwargs)

        record = build_binding_record(**self.origin_kwargs)
        with self.assertRaisesRegex(ValueError, "missing field in carrier request/claim.*command_id"):
            verify_binding_record(record, req, self.valid_claim)

    def test_validation_does_not_mutate_inputs(self):
        record = build_binding_record(**self.origin_kwargs)
        orig_record = copy.deepcopy(record)

        validated = validate_binding_record(record)
        self.assertEqual(record, orig_record)
        self.assertEqual(validated, orig_record)

        verified = verify_binding_record(record, self.valid_request, self.valid_claim)
        self.assertEqual(record, orig_record)
        self.assertEqual(verified, orig_record)

    def test_validation_fail_leaves_dict_unchanged(self):
        record = build_binding_record(**self.origin_kwargs)
        record["origin_round"] = 2
        orig_record = copy.deepcopy(record)

        with self.assertRaises(ValueError):
            validate_binding_record(record)

        self.assertEqual(record, orig_record)
