import json
import os
import unittest

class TestLiveReadinessApprovalSchema(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "schemas",
            "relay_live_readiness_approval_v1.schema.json",
        )
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_schema_metadata(self) -> None:
        self.assertEqual(
            self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.schema["type"], "object")

    def test_required_fields(self) -> None:
        expected_required = [
            "state",
            "live_ready",
            "dispatch_allowed",
            "human_approval_required",
            "approval_granted",
            "retry_count",
            "fallback_state",
            "next_action",
            "snapshot_state",
            "snapshot_packet_sha256",
            "preflight_states",
            "inventory_state",
            "unresolved_count",
            "provider_states",
            "blocking_providers",
            "approval_packet_sha256",
        ]
        self.assertEqual(self.schema["required"], expected_required)

    def test_constant_and_enum_fields(self) -> None:
        props = self.schema["properties"]

        self.assertEqual(props["state"]["enum"], ["BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"])
        self.assertFalse(props["live_ready"]["const"])
        self.assertFalse(props["dispatch_allowed"]["const"])
        self.assertTrue(props["human_approval_required"]["const"])
        self.assertFalse(props["approval_granted"]["const"])
        self.assertEqual(props["retry_count"]["const"], 0)
        self.assertEqual(props["retry_count"]["type"], "integer")
        self.assertEqual(props["fallback_state"]["const"], "disabled")
        self.assertEqual(props["next_action"]["enum"], ["RESOLVE_BLOCKERS", "REQUEST_HUMAN_APPROVAL"])
        self.assertEqual(props["snapshot_state"]["enum"], ["BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"])
        self.assertEqual(props["inventory_state"]["enum"], ["BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"])

    def test_provider_maps_and_hash_patterns_and_absence_of_auth_strings(self) -> None:
        props = self.schema["properties"]

        # Hashes
        self.assertEqual(props["snapshot_packet_sha256"]["type"], ["string", "null"])
        self.assertEqual(props["snapshot_packet_sha256"]["pattern"], "^[a-f0-9]{64}$")
        self.assertEqual(props["approval_packet_sha256"]["type"], ["string", "null"])
        self.assertEqual(props["approval_packet_sha256"]["pattern"], "^[a-f0-9]{64}$")

        # Absence of auth strings
        state_enum = props["state"]["enum"]
        self.assertNotIn("LIVE_TURN_ALLOWED", state_enum)
        self.assertNotIn("APPROVED", state_enum)

        # Provider maps
        preflight_states = props["preflight_states"]["oneOf"]
        self.assertEqual(preflight_states[0]["maxProperties"], 0)
        self.assertEqual(preflight_states[1]["required"], ["openai", "anthropic", "google"])

        provider_states = props["provider_states"]["oneOf"]
        self.assertEqual(provider_states[0]["maxProperties"], 0)
        self.assertEqual(provider_states[1]["required"], ["openai", "anthropic", "google"])

        blocking = props["blocking_providers"]
        self.assertEqual(blocking["items"]["enum"], ["openai", "anthropic", "google"])
