import json
import os
import unittest


PROVIDERS = ("openai", "anthropic", "google")


class TestLiveReadinessApprovalSchema(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "schemas",
            "relay_live_readiness_approval_v1.schema.json",
        )
        with open(schema_path, "r", encoding="utf-8") as stream:
            self.schema = json.load(stream)

    def test_metadata_and_exact_top_level_fields(self) -> None:
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
        }
        self.assertEqual(set(self.schema["required"]), expected)
        self.assertEqual(set(self.schema["properties"]), expected)

    def test_fixed_safety_constants_and_enums(self) -> None:
        props = self.schema["properties"]
        self.assertEqual(
            props["state"]["enum"],
            ["BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"],
        )
        self.assertIs(props["live_ready"]["const"], False)
        self.assertIs(props["dispatch_allowed"]["const"], False)
        self.assertIs(props["human_approval_required"]["const"], True)
        self.assertIs(props["approval_granted"]["const"], False)
        self.assertEqual(props["retry_count"]["type"], "integer")
        self.assertEqual(props["retry_count"]["const"], 0)
        self.assertEqual(props["fallback_state"]["const"], "disabled")
        self.assertEqual(
            props["next_action"]["enum"],
            ["RESOLVE_BLOCKERS", "REQUEST_HUMAN_APPROVAL"],
        )
        self.assertEqual(
            props["snapshot_state"]["enum"],
            ["BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"],
        )
        self.assertEqual(
            props["inventory_state"]["enum"],
            ["BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"],
        )

    def _assert_empty_or_exact_provider_map(self, field: str) -> dict:
        alternatives = self.schema["properties"][field]["oneOf"]
        self.assertEqual(len(alternatives), 2)
        empty, exact = alternatives

        self.assertEqual(empty["type"], "object")
        self.assertFalse(empty["additionalProperties"])
        self.assertEqual(empty["maxProperties"], 0)

        self.assertEqual(exact["type"], "object")
        self.assertFalse(exact["additionalProperties"])
        self.assertEqual(set(exact["required"]), set(PROVIDERS))
        self.assertEqual(set(exact["properties"]), set(PROVIDERS))
        return exact

    def test_exact_provider_maps(self) -> None:
        preflight = self._assert_empty_or_exact_provider_map(
            "preflight_states"
        )
        for provider in PROVIDERS:
            self.assertEqual(
                preflight["properties"][provider]["enum"],
                ["PASS", "UNKNOWN"],
            )

        states = self._assert_empty_or_exact_provider_map("provider_states")
        for provider in PROVIDERS:
            self.assertEqual(
                states["properties"][provider]["enum"],
                ["BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"],
            )

    def test_hash_nullability_and_patterns_match_runtime(self) -> None:
        props = self.schema["properties"]

        self.assertEqual(
            props["snapshot_packet_sha256"]["type"],
            ["string", "null"],
        )
        self.assertEqual(
            props["snapshot_packet_sha256"]["pattern"],
            "^[a-f0-9]{64}$",
        )

        self.assertEqual(
            props["approval_packet_sha256"]["type"],
            "string",
        )
        self.assertEqual(
            props["approval_packet_sha256"]["pattern"],
            "^[a-f0-9]{64}$",
        )

    def test_blocking_provider_schema_is_bounded(self) -> None:
        blocking = self.schema["properties"]["blocking_providers"]
        self.assertEqual(blocking["type"], "array")
        self.assertTrue(blocking["uniqueItems"])
        self.assertEqual(blocking["maxItems"], 3)
        self.assertEqual(blocking["items"]["enum"], list(PROVIDERS))

    def test_schema_contains_no_authorization_state(self) -> None:
        schema_text = json.dumps(self.schema, sort_keys=True)
        for forbidden in (
            "LIVE_TURN_ALLOWED",
            "READY_TO_DISPATCH",
            "DISPATCH_ALLOWED",
            "AUTO_APPROVED",
            "APPROVAL_GRANTED",
        ):
            self.assertNotIn(forbidden, schema_text)

        self.assertIn('"approval_granted"', schema_text)
        self.assertIn('"const": false', schema_text)
