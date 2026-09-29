import json
import os
import unittest

class TestLiveProvenanceRequestSchema(unittest.TestCase):
    def setUp(self):
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "../../schemas/relay_live_provenance_request_v1.schema.json"
        )
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_schema_structure(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(self.schema["type"], "object")
        self.assertEqual(self.schema["additionalProperties"], False)

    def test_required_fields(self):
        expected_required = [
            "state",
            "live_ready",
            "dispatch_allowed",
            "execution_authorized",
            "provenance_verified",
            "retry_count",
            "fallback_state",
            "next_action",
            "approval_record_sha256",
            "approval_packet_sha256",
            "snapshot_packet_sha256",
            "durable_locator_sha256",
            "expected_record_sha256",
            "provenance_request_sha256"
        ]
        self.assertEqual(sorted(self.schema["required"]), sorted(expected_required))

    def test_fixed_authorization_flags(self):
        props = self.schema["properties"]
        self.assertEqual(props["live_ready"], {"type": "boolean", "const": False})
        self.assertEqual(props["dispatch_allowed"], {"type": "boolean", "const": False})
        self.assertEqual(props["execution_authorized"], {"type": "boolean", "const": False})
        self.assertEqual(props["provenance_verified"], {"type": "boolean", "const": False})
        self.assertEqual(props["retry_count"], {"type": "integer", "const": 0})
        self.assertEqual(props["fallback_state"], {"type": "string", "const": "disabled"})

    def test_enums(self):
        props = self.schema["properties"]
        self.assertEqual(
            set(props["state"]["enum"]),
            {"BLOCKED_UNKNOWN", "PROVENANCE_VERIFICATION_REQUIRED"}
        )
        self.assertEqual(
            set(props["next_action"]["enum"]),
            {"RESOLVE_BLOCKERS", "READBACK_DURABLE_HUMAN_PROVENANCE"}
        )

    def test_hashes(self):
        props = self.schema["properties"]
        hash_keys_nullable = [
            "approval_record_sha256",
            "approval_packet_sha256",
            "snapshot_packet_sha256",
            "durable_locator_sha256",
            "expected_record_sha256"
        ]
        for key in hash_keys_nullable:
            self.assertEqual(set(props[key]["type"]), {"string", "null"})
            self.assertEqual(props[key]["pattern"], "^[0-9a-f]{64}$")

        self.assertEqual(props["provenance_request_sha256"]["type"], "string")
        self.assertEqual(props["provenance_request_sha256"]["pattern"], "^[0-9a-f]{64}$")

    def test_properties_are_exactly_the_required_fields(self):
        self.assertEqual(
            set(self.schema["properties"]),
            set(self.schema["required"]),
        )

    def test_schema_contains_no_authorizing_true_or_live_state(self):
        schema_text = json.dumps(self.schema, sort_keys=True)
        for forbidden in (
            "EXECUTION_AUTHORIZED",
            "DISPATCH_ALLOWED",
            "LIVE_READY",
            "PROVENANCE_VERIFIED",
            "READY_TO_EXECUTE",
            "AUTHORIZED",
        ):
            self.assertNotIn(forbidden, schema_text)

        for field in (
            "live_ready",
            "dispatch_allowed",
            "execution_authorized",
            "provenance_verified",
        ):
            self.assertIs(
                self.schema["properties"][field]["const"],
                False,
            )

    def test_request_digest_is_always_nonnullable(self):
        prop = self.schema["properties"]["provenance_request_sha256"]
        self.assertEqual(prop["type"], "string")
        self.assertEqual(prop["pattern"], "^[0-9a-f]{64}$")

