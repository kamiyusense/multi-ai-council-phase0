from datetime import datetime, timedelta, timezone
import unittest

from automation.command_bus.jules_api_request import (
    PROFILE, PROFILE_V2,
    build_jules_prompt,
    derived_work_branch,
    validate_request,
)

NOW = datetime.now(timezone.utc)


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

    def test_v2_preserves_origin_correlation(self):
        value = request(
            profile=PROFILE_V2,
            origin_loop_id="claude-night-001",
            origin_round=2,
            origin_correlation_id="corr-001",
            origin_generation=3,
        )
        self.assertEqual(validate_request(value, now=NOW)["profile"], PROFILE_V2)
        rendered = build_jules_prompt(value, now=NOW)
        self.assertIn("Origin loop: claude-night-001", rendered)
        self.assertIn("Origin round: 2", rendered)
        self.assertIn("Origin correlation: corr-001", rendered)
        self.assertIn("Origin generation: 3", rendered)

    def test_v2_rejects_missing_or_invalid_origin_identity(self):
        base = request(
            profile=PROFILE_V2,
            origin_loop_id="claude-night-001",
            origin_round=2,
            origin_correlation_id="corr-001",
            origin_generation=3,
        )
        for key, value in (
            ("origin_loop_id", ""),
            ("origin_round", 0),
            ("origin_correlation_id", ""),
            ("origin_generation", 0),
        ):
            changed = dict(base)
            changed[key] = value
            with self.assertRaises(ValueError, msg=key):
                validate_request(changed, now=NOW)

    def test_v1_remains_backward_compatible(self):
        value = request()
        self.assertEqual(value["profile"], PROFILE)
        self.assertEqual(validate_request(value, now=NOW)["command_id"], "chat-jules-001")

    def test_prompt_binds_isolated_work_branch_head_tree_and_allowlist(self):
        value = request()
        rendered = build_jules_prompt(value, now=NOW)
        self.assertEqual(derived_work_branch(value), "jules-work/chat-jules-001")
        self.assertIn("Canonical target branch (READ-ONLY identity): " + value["target_branch"], rendered)
        self.assertIn("Isolated Jules starting work branch: jules-work/chat-jules-001", rendered)
        self.assertIn("Expected snapshot HEAD: " + "a" * 40, rendered)
        self.assertIn("Expected snapshot tree: " + "b" * 40, rendered)
        self.assertIn("do not mutate the canonical target branch", rendered)
        self.assertIn("tests/relay/test_dispatcher.py", rendered)
        self.assertIn("do not merge", rendered)
        self.assertIn("do not retry", rendered)

    def test_work_branch_is_deterministic_from_command_id(self):
        self.assertEqual(
            derived_work_branch(request(command_id="claude-jules-integrated-proof-20260928-001")),
            "jules-work/claude-jules-integrated-proof-20260928-001",
        )


if __name__ == "__main__":
    unittest.main()
