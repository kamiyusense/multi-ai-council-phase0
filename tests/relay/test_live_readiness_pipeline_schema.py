import unittest
import json
import os

class TestLiveReadinessPipelineSchema(unittest.TestCase):
    def setUp(self):
        schema_path = os.path.join(os.path.dirname(__file__), "..", "..", "schemas", "relay_live_readiness_pipeline_v1.schema.json")
        with open(schema_path, "r") as f:
            self.schema = json.load(f)

    def test_schema_valid_draft_2020_12(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_schema_rejects_additional_properties(self):
        self.assertFalse(self.schema.get("additionalProperties", True))

    def test_schema_required_keys(self):
        expected_keys = [
            "state", "live_ready", "dispatch_allowed", "human_approval_required",
            "retry_count", "fallback_state", "inventory_state", "unresolved_count",
            "unresolved_by_provider", "inventory_packet_sha256", "provider_states",
            "blocking_providers", "bundle_packet_sha256", "pipeline_packet_sha256"
        ]
        self.assertEqual(set(self.schema["required"]), set(expected_keys))

    def test_schema_constants(self):
        props = self.schema["properties"]
        self.assertFalse(props["live_ready"]["const"])
        self.assertFalse(props["dispatch_allowed"]["const"])
        self.assertTrue(props["human_approval_required"]["const"])
        self.assertEqual(props["retry_count"]["const"], 0)
        self.assertEqual(props["fallback_state"]["const"], "disabled")

    def test_schema_enums(self):
        props = self.schema["properties"]
        self.assertEqual(set(props["state"]["enum"]), {"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"})
        self.assertEqual(set(props["inventory_state"]["enum"]), {"BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"})

    def test_schema_provider_maps_are_empty_or_exact_three(self):
        props = self.schema["properties"]
        for key in ("unresolved_by_provider", "provider_states"):
            one_of = props[key]["oneOf"]
            self.assertEqual(len(one_of), 2)
            empty = one_of[0]
            exact = one_of[1]
            self.assertFalse(empty["additionalProperties"])
            self.assertEqual(empty["maxProperties"], 0)
            self.assertFalse(exact["additionalProperties"])
            self.assertEqual(set(exact["required"]), {"openai", "anthropic", "google"})
            self.assertEqual(set(exact["properties"]), {"openai", "anthropic", "google"})

    def test_schema_hashes_are_strict(self):
        props = self.schema["properties"]
        self.assertEqual(props["inventory_packet_sha256"]["pattern"], "^[a-f0-9]{64}$")
        self.assertEqual(props["bundle_packet_sha256"]["pattern"], "^[a-f0-9]{64}$")
        self.assertEqual(props["pipeline_packet_sha256"]["type"], "string")
        self.assertEqual(props["pipeline_packet_sha256"]["pattern"], "^[a-f0-9]{64}$")
        self.assertEqual(props["blocking_providers"]["maxItems"], 3)

    def test_schema_has_no_authorization_states(self):
        serialized = json.dumps(self.schema, sort_keys=True)
        for forbidden in ("LIVE_READY", "AUTO_APPROVED", "DISPATCH_ALLOWED"):
            self.assertNotIn(forbidden, serialized)

if __name__ == '__main__':
    unittest.main()
