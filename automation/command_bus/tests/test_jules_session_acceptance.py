from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from automation.command_bus.jules_session_acceptance import (
    extract_session_acceptance,
    load_session_acceptance,
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


if __name__ == "__main__":
    unittest.main()
