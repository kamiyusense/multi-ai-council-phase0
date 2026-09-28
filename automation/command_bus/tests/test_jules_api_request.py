from datetime import datetime, timedelta, timezone
import unittest

from automation.command_bus.jules_api_request import (
    PROFILE,
    build_jules_prompt,
    validate_request,
)

NOW = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)


def request(**changes):
    values = {
        "schema_version": 1,
        "profile": PROFILE,
        "command_id": "chat-jules-001",
        "target_repo": "kamiyusense/multi-ai-council-phase0",
        "target_branch": "feature/relay-transport-7070955470193506982",
        "expected_target_head": "a" * 40,
        "expected_target_tree": "b" * 40,
        "allowed_paths": ["tests/relay/test_dispatcher.py"],
        "prompt": "Add one bounded regression test and run the declared checks.",
        "created_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "retry": 0,
        "fallback": "disabled",
        "merge_allowed": False,
        "force_push_allowed": False,
    }
    values.update(changes)
    return values


class JulesApiRequestTests(unittest.TestCase):
    def test_valid_request(self):
        self.assertEqual(validate_request(request(), now=NOW)["command_id"], "chat-jules-001")

    def test_default_branch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "default branch"):
            validate_request(request(target_branch="main"), now=NOW)

    def test_retry_and_fallback_are_fixed(self):
        with self.assertRaisesRegex(ValueError, "retry/fallback"):
            validate_request(request(retry=1), now=NOW)

    def test_expired_request_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expired"):
            validate_request(request(), now=NOW + timedelta(hours=2))

    def test_lifetime_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "lifetime"):
            validate_request(request(expires_at=(NOW + timedelta(hours=3)).isoformat()), now=NOW)

    def test_path_traversal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsafe allowed path"):
            validate_request(request(allowed_paths=["../secret.txt"]), now=NOW)

    def test_dangerous_publication_flags_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "dangerous publication"):
            validate_request(request(merge_allowed=True), now=NOW)

    def test_unknown_keys_are_rejected(self):
        bad = request()
        bad["thread_id"] = "not-correctness"
        with self.assertRaisesRegex(ValueError, "keys mismatch"):
            validate_request(bad, now=NOW)

    def test_prompt_binds_head_tree_and_allowlist(self):
        rendered = build_jules_prompt(request(), now=NOW)
        self.assertIn("Expected starting HEAD: " + "a" * 40, rendered)
        self.assertIn("Expected starting tree: " + "b" * 40, rendered)
        self.assertIn("tests/relay/test_dispatcher.py", rendered)
        self.assertIn("do not merge", rendered)
        self.assertIn("do not retry", rendered)


if __name__ == "__main__":
    unittest.main()
