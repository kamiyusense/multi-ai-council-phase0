"""Tests for automation.command_bus.claude_jules_api_status (objective o2-jules-api-requests)."""
from __future__ import annotations

import unittest

from automation.command_bus.claude_jules_api_status import (
    build_status_request,
    status_request_path,
    validate_status_request,
)


class TestValidateStatusRequest(unittest.TestCase):
    def test_valid_request(self):
        self.assertEqual(
            validate_status_request({"session_id": "12345", "include_activities": True}),
            [],
        )
        self.assertEqual(
            validate_status_request({"session_id": "12345", "include_activities": False}),
            [],
        )

    def test_valid_request_without_optional_include_activities(self):
        self.assertEqual(validate_status_request({"session_id": "999"}), [])

    def test_non_dict_input(self):
        self.assertEqual(validate_status_request(None), ["request must be a dict"])
        self.assertEqual(validate_status_request([]), ["request must be a dict"])
        self.assertEqual(validate_status_request("12345"), ["request must be a dict"])
        self.assertEqual(validate_status_request(12345), ["request must be a dict"])

    def test_missing_session_id(self):
        problems = validate_status_request({"include_activities": True})
        self.assertIn("missing required key: session_id", problems)

    def test_session_id_type_invalid(self):
        for bad_id in (123, True, None, ["123"]):
            problems = validate_status_request({"session_id": bad_id, "include_activities": True})
            self.assertIn("session_id must be a str", problems)

    def test_session_id_format_invalid(self):
        for bad_id in ("", "abc", "123a", "-1", "12.3", " 123 ", "123\n"):
            problems = validate_status_request({"session_id": bad_id, "include_activities": True})
            self.assertTrue(
                any("invalid session_id" in p for p in problems),
                f"Expected invalid session_id error for {bad_id!r}",
            )

    def test_include_activities_type_invalid(self):
        for bad_act in ("true", "false", 1, 0, None, []):
            problems = validate_status_request({"session_id": "123", "include_activities": bad_act})
            self.assertIn("include_activities must be a bool", problems)

    def test_unexpected_keys(self):
        problems = validate_status_request(
            {"session_id": "123", "include_activities": True, "extra_key": "value"}
        )
        self.assertTrue(any("unexpected keys" in p for p in problems))


class TestBuildStatusRequest(unittest.TestCase):
    def test_build_valid_request_default(self):
        req = build_status_request("12345")
        self.assertEqual(req, {"session_id": "12345", "include_activities": True})

    def test_build_valid_request_explicit_false(self):
        req = build_status_request("67890", include_activities=False)
        self.assertEqual(req, {"session_id": "67890", "include_activities": False})

    def test_build_invalid_session_id_raises(self):
        with self.assertRaises(ValueError):
            build_status_request("abc")
        with self.assertRaises(ValueError):
            build_status_request(123)  # type: ignore[arg-type]

    def test_build_invalid_include_activities_raises(self):
        with self.assertRaises(ValueError):
            build_status_request("12345", include_activities="true")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            build_status_request("12345", include_activities=1)  # type: ignore[arg-type]


class TestStatusRequestPath(unittest.TestCase):
    def test_valid_request_id(self):
        self.assertEqual(
            status_request_path("req1"),
            "automation/command_bus/jules_api_status_requests/req1.json",
        )
        self.assertEqual(
            status_request_path("claude-c1-status-001"),
            "automation/command_bus/jules_api_status_requests/claude-c1-status-001.json",
        )
        self.assertEqual(
            status_request_path("a.b_c-d"),
            "automation/command_bus/jules_api_status_requests/a.b_c-d.json",
        )
        self.assertEqual(
            status_request_path("a" * 64),
            f"automation/command_bus/jules_api_status_requests/{'a' * 64}.json",
        )

    def test_invalid_request_id_raises(self):
        for bad_req_id in (
            "",
            "Req1",
            "Upper",
            "../x",
            "a/b",
            "_req",
            ".req",
            "-req",
            "req@1",
            "a" * 65,
            None,
            123,
        ):
            with self.assertRaises(ValueError, msg=f"Should raise for {bad_req_id!r}"):
                status_request_path(bad_req_id)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
