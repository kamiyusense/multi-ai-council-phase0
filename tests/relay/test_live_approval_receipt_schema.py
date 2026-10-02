import json
import os
import unittest


class TestLiveApprovalReceiptSchema(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "schemas",
            "relay_live_approval_receipt_v1.schema.json",
        )
        with open(schema_path, "r", encoding="utf-8") as stream:
            self.schema = json.load(stream)

    def test_metadata_and_exact_fields(self) -> None:
        self.assertEqual(
            self.schema["$schema"],
            "https://json-schema.org/draft/2020-12/schema",
        )
        self.assertEqual(self.schema["type"], "object")
        self.assertFalse(self.schema["additionalProperties"])

        expected = {
            "state",
            "live_ready",
            "dispatch_allowed",
            "execution_authorized",
            "provenance_verified",
            "retry_count",
            "fallback_state",
            "decision",
            "scope",
            "one_shot",
            "approval_packet_sha256",
            "snapshot_packet_sha256",
            "next_action",
            "approval_record_sha256",
        }
        self.assertEqual(set(self.schema["required"]), expected)
        self.assertEqual(set(self.schema["properties"]), expected)

    def test_fixed_safety_constants(self) -> None:
        props = self.schema["properties"]
        self.assertIs(props["live_ready"]["const"], False)
        self.assertIs(props["dispatch_allowed"]["const"], False)
        self.assertIs(props["execution_authorized"]["const"], False)
        self.assertIs(props["provenance_verified"]["const"], False)
        self.assertEqual(props["retry_count"]["type"], "integer")
        self.assertEqual(props["retry_count"]["const"], 0)
        self.assertEqual(props["fallback_state"]["const"], "disabled")

    def test_state_decision_scope_and_action_enums(self) -> None:
        props = self.schema["properties"]
        self.assertEqual(
            props["state"]["enum"],
            [
                "BLOCKED_UNKNOWN",
                "STRUCTURALLY_VALID_APPROVAL_RECORD",
                "NON_APPROVAL_DECISION",
            ],
        )
        self.assertEqual(
            props["decision"]["enum"],
            [
                "APPROVE_FIRST_LIVE_POC",
                "REJECT",
                "DEFER",
                "UNKNOWN",
            ],
        )
        self.assertEqual(
            props["scope"]["enum"],
            ["FIRST_LIVE_POC_ONLY", "UNKNOWN"],
        )
        self.assertEqual(
            props["next_action"]["enum"],
            [
                "RESOLVE_BLOCKERS",
                "VERIFY_DURABLE_HUMAN_PROVENANCE",
                "NO_LIVE_ACTION",
            ],
        )
        self.assertEqual(props["one_shot"]["type"], "boolean")

    def test_hash_patterns_and_nullability_match_runtime(self) -> None:
        props = self.schema["properties"]

        for field in (
            "approval_packet_sha256",
            "snapshot_packet_sha256",
        ):
            self.assertEqual(props[field]["type"], ["string", "null"])
            self.assertEqual(props[field]["pattern"], "^[a-f0-9]{64}$")

        self.assertEqual(
            props["approval_record_sha256"]["type"],
            "string",
        )
        self.assertEqual(
            props["approval_record_sha256"]["pattern"],
            "^[a-f0-9]{64}$",
        )

    def test_schema_has_no_execution_authorizing_values(self) -> None:
        schema_text = json.dumps(self.schema, sort_keys=True)
        for forbidden in (
            "EXECUTION_AUTHORIZED",
            "DISPATCH_ALLOWED",
            "LIVE_READY",
            "PROVENANCE_VERIFIED",
            "AUTO_APPROVED",
            "READY_TO_DISPATCH",
        ):
            self.assertNotIn(forbidden, schema_text)

        self.assertIn('"execution_authorized"', schema_text)
        self.assertIn('"provenance_verified"', schema_text)
        self.assertIn('"const": false', schema_text)
