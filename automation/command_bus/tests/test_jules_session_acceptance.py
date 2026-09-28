from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from automation.command_bus.jules_session_acceptance import (
    extract_session_acceptance,
    extract_session_timing_readback,
    load_session_acceptance,
    verify_session_acceptance_readback,
    verify_timing_readback_matches_acceptance,
)


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "jules_session_acceptance" / "create_session_response.json"


def response():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class JulesSessionAcceptanceTests(unittest.TestCase):
    def test_create_time_is_normalized_to_utc_and_jst(self):
        result = extract_session_acceptance(
            response(),
            expected_branch="feature/example",
        )
        self.assertEqual(result.source_kind, "JULES_CREATE_SESSION_RESPONSE_CREATE_TIME")
        self.assertEqual(result.session_name, "sessions/31415926535897932384")
        self.assertEqual(result.session_id, "31415926535897932384")
        self.assertEqual(result.starting_branch, "feature/example")
        self.assertEqual(result.session_create_time, "2026-09-28T03:59:00Z")
        self.assertEqual(result.accepted_at_jst, "2026-09-28T12:59:00+09:00")

    def test_offset_provider_time_is_canonicalized(self):
        value = response()
        value["createTime"] = "2026-09-28T12:59:00+09:00"
        result = extract_session_acceptance(value, expected_branch="feature/example")
        self.assertEqual(result.session_create_time, "2026-09-28T03:59:00Z")
        self.assertEqual(result.accepted_at_jst, "2026-09-28T12:59:00+09:00")

    def test_starting_branch_mismatch_blocks(self):
        with self.assertRaisesRegex(ValueError, "branch mismatch"):
            extract_session_acceptance(
                response(),
                expected_branch="feature/other",
            )

    def test_missing_or_naive_create_time_blocks(self):
        missing = response()
        missing.pop("createTime")
        with self.assertRaisesRegex(ValueError, "createTime"):
            extract_session_acceptance(missing, expected_branch="feature/example")

        naive = response()
        naive["createTime"] = "2026-09-28T03:59:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            extract_session_acceptance(naive, expected_branch="feature/example")

    def test_malformed_session_name_blocks(self):
        value = response()
        value["name"] = "sessions/not-numeric"
        with self.assertRaisesRegex(ValueError, "session name"):
            extract_session_acceptance(value, expected_branch="feature/example")

    def test_loader_reads_existing_response_file_without_mutating_it(self):
        before = response()
        loaded = load_session_acceptance(FIXTURE, expected_branch="feature/example")
        self.assertEqual(loaded.accepted_at_jst, "2026-09-28T12:59:00+09:00")
        self.assertEqual(response(), before)

    def test_private_session_url_is_not_part_of_acceptance_record(self):
        value = response()
        value["url"] = "https://jules.google.com/session/private"
        result = extract_session_acceptance(value, expected_branch="feature/example")
        self.assertFalse(hasattr(result, "url"))
        self.assertNotIn("https://", json.dumps(result.__dict__))

    def test_response_file_round_trip(self):
        value = response()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "response.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            result = load_session_acceptance(path, expected_branch="feature/example")
        self.assertEqual(result.session_id, "31415926535897932384")


    def test_later_session_readback_confirms_same_acceptance_time(self):
        accepted = extract_session_acceptance(
            response(),
            expected_branch="feature/example",
        )
        observed = verify_session_acceptance_readback(accepted, response())
        self.assertEqual(observed, accepted)

    def test_later_session_readback_time_or_identity_mismatch_blocks(self):
        accepted = extract_session_acceptance(
            response(),
            expected_branch="feature/example",
        )

        wrong_time = response()
        wrong_time["createTime"] = "2026-09-28T04:00:00Z"
        with self.assertRaisesRegex(ValueError, "createTime mismatch"):
            verify_session_acceptance_readback(accepted, wrong_time)

        wrong_name = response()
        wrong_name["name"] = "sessions/999999"
        with self.assertRaisesRegex(ValueError, "name mismatch"):
            verify_session_acceptance_readback(accepted, wrong_name)

        wrong_branch = response()
        wrong_branch["sourceContext"]["githubRepoContext"]["startingBranch"] = "feature/other"
        with self.assertRaisesRegex(ValueError, "branch mismatch"):
            verify_session_acceptance_readback(accepted, wrong_branch)

    def test_session_get_timing_readback_is_bound_to_exact_session_id(self):
        observed = extract_session_timing_readback(
            response(),
            expected_session_id="31415926535897932384",
        )
        self.assertEqual(
            observed.source_kind,
            "JULES_SESSION_GET_CREATE_TIME_READBACK",
        )
        self.assertEqual(observed.session_create_time, "2026-09-28T03:59:00Z")
        self.assertEqual(observed.accepted_at_jst, "2026-09-28T12:59:00+09:00")

        with self.assertRaisesRegex(ValueError, "name mismatch"):
            extract_session_timing_readback(
                response(),
                expected_session_id="999999",
            )

    def test_session_get_timing_must_match_create_acceptance_record(self):
        accepted = extract_session_acceptance(
            response(),
            expected_branch="feature/example",
        )
        observed = extract_session_timing_readback(
            response(),
            expected_session_id=accepted.session_id,
        )
        verify_timing_readback_matches_acceptance(accepted, observed)

        changed = response()
        changed["createTime"] = "2026-09-28T04:01:00Z"
        changed_observed = extract_session_timing_readback(
            changed,
            expected_session_id=accepted.session_id,
        )
        with self.assertRaisesRegex(ValueError, "createTime mismatch"):
            verify_timing_readback_matches_acceptance(
                accepted,
                changed_observed,
            )

if __name__ == "__main__":
    unittest.main()
