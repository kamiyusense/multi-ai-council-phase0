"""Tests for automation.command_bus.claude_jules_api_message (objective o2-jules-api-requests)."""

import unittest

from automation.command_bus.claude_jules_api_message import (
    build_message_request,
    message_request_path,
    validate_message_request,
)


class TestClaudeJulesApiMessage(unittest.TestCase):
    def test_validate_message_request_valid(self):
        valid_obj = {
            "session_id": "123456",
            "expected_state": "AWAITING_USER_FEEDBACK",
            "prompt": "Hello Jules",
        }
        self.assertEqual(validate_message_request(valid_obj), [])

        valid_obj2 = {
            "session_id": "0",
            "expected_state": "COMPLETED",
            "prompt": "a" * 4000,
        }
        self.assertEqual(validate_message_request(valid_obj2), [])

    def test_validate_message_request_not_dict(self):
        self.assertEqual(validate_message_request("not a dict"), ["request must be a dict"])

    def test_validate_message_request_invalid_keys(self):
        missing_keys_obj = {"session_id": "123"}
        problems = validate_message_request(missing_keys_obj)
        self.assertTrue(any("missing required key(s)" in p for p in problems))

        extra_keys_obj = {
            "session_id": "123",
            "expected_state": "COMPLETED",
            "prompt": "hi",
            "extra": "key",
        }
        problems = validate_message_request(extra_keys_obj)
        self.assertTrue(any("unexpected extra key(s)" in p for p in problems))

    def test_validate_message_request_invalid_session_id(self):
        invalid_ids = ["abc", "123a", "", "-123", 12345, None]
        for bad_id in invalid_ids:
            obj = {
                "session_id": bad_id,
                "expected_state": "COMPLETED",
                "prompt": "test",
            }
            problems = validate_message_request(obj)
            self.assertTrue(
                any("session_id must be a numeric string" in p for p in problems),
                f"Failed for bad_id={bad_id!r}",
            )

    def test_validate_message_request_invalid_expected_state(self):
        invalid_states = ["RUNNING", "completed", "AWAITING_USER_INPUT", "", None, 123]
        for bad_state in invalid_states:
            obj = {
                "session_id": "123",
                "expected_state": bad_state,
                "prompt": "test",
            }
            problems = validate_message_request(obj)
            self.assertTrue(
                any("expected_state must be" in p for p in problems),
                f"Failed for bad_state={bad_state!r}",
            )

    def test_validate_message_request_invalid_prompt(self):
        invalid_prompts = ["", "a" * 4001, None, 123, []]
        for bad_prompt in invalid_prompts:
            obj = {
                "session_id": "123",
                "expected_state": "COMPLETED",
                "prompt": bad_prompt,
            }
            problems = validate_message_request(obj)
            self.assertTrue(
                any("prompt must be a non-empty string" in p for p in problems),
                f"Failed for bad_prompt={bad_prompt!r}",
            )

    def test_build_message_request_valid(self):
        req = build_message_request(
            session_id="12345",
            prompt="Test prompt",
            expected_state="AWAITING_USER_FEEDBACK",
        )
        self.assertEqual(
            req,
            {
                "session_id": "12345",
                "expected_state": "AWAITING_USER_FEEDBACK",
                "prompt": "Test prompt",
            },
        )

    def test_build_message_request_invalid(self):
        with self.assertRaises(ValueError) as ctx:
            build_message_request(
                session_id="invalid",
                prompt="Test prompt",
                expected_state="AWAITING_USER_FEEDBACK",
            )
        self.assertIn("session_id must be a numeric string", str(ctx.exception))

    def test_message_request_path_valid(self):
        valid_ids = ["a", "req1", "req-1", "req_1", "req.1", "a" * 64]
        for req_id in valid_ids:
            path = message_request_path(req_id)
            self.assertEqual(
                path,
                f"automation/command_bus/jules_api_message_requests/{req_id}.json",
            )

    def test_message_request_path_invalid(self):
        invalid_ids = [
            "",
            "-startwithdash",
            ".startwithdot",
            "_startwithunderscore",
            "INVALID_CAPS",
            "a" * 65,
            "has space",
            None,
            123,
        ]
        for bad_id in invalid_ids:
            with self.assertRaises(ValueError, msg=f"Failed for bad_id={bad_id!r}"):
                message_request_path(bad_id)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
