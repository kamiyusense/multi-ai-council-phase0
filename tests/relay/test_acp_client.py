from __future__ import annotations

import json
import unittest

from providers.policy import ProviderPolicy
from relay.acp_client import ACPClient


class ACPClientTests(unittest.TestCase):
    def setUp(self):
        self.policy = ProviderPolicy(
            provider_id="test",
            external_agent="test-agent",
            pinned_version="1.0.0",
            required_auth_kind="account",
        )

    def test_initialize_validation_fails_closed(self):
        client = ACPClient(self.policy)

        # 1. Not a dict
        client.mock_initialize_response = []
        with self.assertRaisesRegex(ValueError, "mock_initialize_response must be a dict"):
            client.initialize("test")

        # 2. Missing/wrong protocol_version
        with open("fixtures/relay/acp_initialize_unsupported.json") as f:
            client.mock_initialize_response = json.load(f)
        with self.assertRaisesRegex(ValueError, "protocol_version must be 1"):
            client.initialize("test")

        # 3. Missing capabilities
        client.mock_initialize_response = {"protocol_version": 1}
        with self.assertRaisesRegex(ValueError, "capabilities must be a dictionary"):
            client.initialize("test")

        # 4. Capability field not a dict
        client.mock_initialize_response = {
            "protocol_version": 1,
            "capabilities": {"auth": "account", "tools": []}
        }
        with self.assertRaisesRegex(ValueError, "capability field tools must be a dictionary"):
            client.initialize("test")

        # 5. Unsupported auth
        client.mock_initialize_response = {
            "protocol_version": 1,
            "capabilities": {"auth": "api_key"}
        }
        with self.assertRaisesRegex(ValueError, "unsupported auth kind: api_key"):
            client.initialize("test")

        # 6. Valid (from fixture)
        with open("fixtures/relay/acp_initialize_account.json") as f:
            client.mock_initialize_response = json.load(f)
        result = client.initialize("test")
        self.assertEqual(result["protocol_version"], 1)
        self.assertFalse(result["live_process_started"])

    def test_prompt_preserves_terminal_bytes(self):
        client = ACPClient(self.policy)
        session_id = client.open_session("test", cwd="/tmp")

        # Type error if not bytes
        client.mock_terminal_responses[session_id] = {"wrong": "type"}
        with self.assertRaisesRegex(TypeError, "terminal response must be strictly bytes"):
            client.prompt("test", session_id, {})

        session_id_2 = client.open_session("test", cwd="/tmp")
        # Should return exactly the bytes we set
        expected_bytes = b'{"status": "ok", "bytes": "\\x00\\x01"}'
        client.mock_terminal_responses[session_id_2] = expected_bytes

        result = client.prompt("test", session_id_2, {})
        self.assertEqual(result, expected_bytes)

    def test_evidence_preserves_raw_snapshot(self):
        client = ACPClient(self.policy)
        session_id = client.open_session("test", cwd="/tmp")

        # Setup an update
        update = {"event": "start", "data": {"key": "val"}}
        client.mock_updates = [update]

        client.prompt("test", session_id, {})

        # Ensure it was captured
        self.assertEqual(len(client.evidence[session_id]), 1)

        # Mutate the original update
        update["event"] = "mutated"
        update["data"]["key"] = "mutated_val"

        # Snapshot in evidence should be unaffected
        snapshot = client.evidence[session_id][0]
        self.assertEqual(snapshot["event"], "start")
        self.assertEqual(snapshot["data"]["key"], "val")

    def test_safety_callbacks_reject(self):
        client = ACPClient(self.policy)

        req = {"test": 1}
        self.assertFalse(client.handle_permission_request(req))
        self.assertFalse(client.handle_file_read(req))
        self.assertFalse(client.handle_file_write(req))
        self.assertFalse(client.handle_terminal_request(req))
        self.assertFalse(client.handle_elicitation_request(req))
        self.assertFalse(client.handle_unknown_notification(req))

        self.assertEqual(len(client.permission_requests), 1)
        self.assertEqual(len(client.file_reads), 1)
        self.assertEqual(len(client.file_writes), 1)
        self.assertEqual(len(client.terminal_requests), 1)
        self.assertEqual(len(client.elicitation_requests), 1)
        self.assertEqual(len(client.unknown_notifications), 1)

        # Mutate req to ensure deepcopy was used
        req["test"] = 2
        self.assertEqual(client.permission_requests[0]["test"], 1)

    def test_lifecycle_invariants(self):
        client = ACPClient(self.policy)

        # Prompt without session fails
        with self.assertRaisesRegex(ValueError, "session not open"):
            client.prompt("test", "bad_session", {})

        session_id = client.open_session("test", cwd="/tmp")

        # Cancel once works
        client.cancel("test", session_id)
        # Second cancel fails
        with self.assertRaisesRegex(ValueError, "session already cancelled"):
            client.cancel("test", session_id)

        # First prompt works
        client.prompt("test", session_id, {})
        # Second prompt fails
        with self.assertRaisesRegex(ValueError, "session already prompted"):
            client.prompt("test", session_id, {})

        # Close once works
        client.close("test", session_id)
        # Second close fails
        with self.assertRaisesRegex(ValueError, "session already closed"):
            client.close("test", session_id)

        # Cancel after close fails
        with self.assertRaisesRegex(ValueError, "session already closed"):
            client.cancel("test", session_id)
