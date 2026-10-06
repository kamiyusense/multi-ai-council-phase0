from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from automation.command_bus.symphony_autonomous_policy import (
    UPSTREAM_SYMPHONY_REFERENCE_POLICY,
)


class SymphonyUpstreamReferenceTests(unittest.TestCase):
    def test_pinned_reference_defaults_match_policy_valves(self):
        path = Path(__file__).resolve().parents[1] / "symphony_upstream_reference.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["repository"], "openai/symphony")
        self.assertRegex(data["commit"], r"^[0-9a-f]{40}$")
        defaults = data["upstream_defaults"]
        policy = UPSTREAM_SYMPHONY_REFERENCE_POLICY
        self.assertEqual(policy.max_concurrent_agents, defaults["max_concurrent_agents"])
        self.assertEqual(policy.max_turns_per_task, defaults["max_turns"])
        self.assertEqual(policy.continuation_retry_seconds * 1000, defaults["continuation_retry_ms"])
        self.assertEqual(policy.failure_retry_base_seconds * 1000, defaults["failure_retry_base_ms"])
        self.assertEqual(policy.max_retry_backoff_seconds * 1000, defaults["max_retry_backoff_ms"])
        self.assertEqual(policy.stall_timeout_seconds * 1000, defaults["stall_timeout_ms"])
        self.assertIn("per-issue workspace lifecycle", data["reuse_from_upstream"])
        self.assertIn("GitHub-backed hash-linked campaign checkpoints", data["track_b_extensions"])

    def test_reference_is_metadata_only_not_an_execution_switch(self):
        path = Path(__file__).resolve().parents[1] / "symphony_upstream_reference.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        serialized = json.dumps(data)
        self.assertNotIn("live_provider_or_model_allowed", serialized)
        forbidden_credential_keys = {"api_key", "token", "secret", "password", "credential"}

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotIn(str(key).lower(), forbidden_credential_keys)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(data)


if __name__ == "__main__":
    unittest.main()
