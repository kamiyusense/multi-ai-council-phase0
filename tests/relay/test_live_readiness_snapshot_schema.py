import json
import os
import unittest


PROVIDERS = ("openai", "anthropic", "google")
PREFLIGHT_FIELDS = {
    "static_configuration_status",
    "live_readiness",
    "reasons",
    "provider_id",
    "external_agent",
    "pinned_version",
    "retry_count",
    "fallback_state",
    "live_ready",
}


class TestLiveReadinessSnapshotSchema(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "schemas",
            "relay_live_readiness_snapshot_v1.schema.json",
        )
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_schema_structure_and_exact_required_fields(self) -> None:
        self.assertEqual(
            self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(self.schema["type"], "object")
        self.assertFalse(self.schema["additionalProperties"])

        expected = {
            "state",
            "live_ready",
            "dispatch_allowed",
            "human_approval_required",
            "retry_count",
            "fallback_state",
            "preflight_states",
            "preflight_snapshots",
            "preflight_packet_sha256",
            "inventory_state",
            "unresolved_count",
            "unresolved_by_provider",
            "inventory_packet_sha256",
            "provider_states",
            "blocking_providers",
            "bundle_packet_sha256",
            "pipeline_packet_sha256",
            "snapshot_packet_sha256",
        }
        self.assertEqual(set(self.schema["required"]), expected)
        self.assertEqual(set(self.schema["properties"]), expected)

    def test_fixed_safety_fields_and_safe_enums(self) -> None:
        props = self.schema["properties"]
        self.assertIs(props["live_ready"]["const"], False)
        self.assertIs(props["dispatch_allowed"]["const"], False)
        self.assertIs(props["human_approval_required"]["const"], True)
        self.assertEqual(props["retry_count"]["const"], 0)
        self.assertEqual(props["fallback_state"]["const"], "disabled")
        self.assertEqual(
            props["state"]["enum"],
            ["BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"],
        )
        self.assertEqual(
            props["inventory_state"]["enum"],
            ["BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"],
        )

        schema_text = json.dumps(self.schema, sort_keys=True)
        for forbidden in (
            '"LIVE_READY"',
            '"READY_TO_DISPATCH"',
            '"DISPATCH_ALLOWED"',
            '"AUTHORIZED"',
            '"AUTO_APPROVED"',
        ):
            self.assertNotIn(forbidden, schema_text)

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
        preflight_states = self._assert_empty_or_exact_provider_map(
            "preflight_states"
        )
        for provider in PROVIDERS:
            self.assertEqual(
                preflight_states["properties"][provider]["enum"],
                ["PASS", "UNKNOWN"],
            )

        unresolved = self._assert_empty_or_exact_provider_map(
            "unresolved_by_provider"
        )
        for provider in PROVIDERS:
            provider_schema = unresolved["properties"][provider]
            self.assertEqual(provider_schema["type"], "integer")
            self.assertEqual(provider_schema["minimum"], 0)

        provider_states = self._assert_empty_or_exact_provider_map(
            "provider_states"
        )
        for provider in PROVIDERS:
            self.assertEqual(
                provider_states["properties"][provider]["enum"],
                ["BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"],
            )

    def test_preflight_snapshot_map_is_exact_at_fixed_layers(self) -> None:
        exact = self._assert_empty_or_exact_provider_map("preflight_snapshots")
        for provider in PROVIDERS:
            schema = exact["properties"][provider]
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), PREFLIGHT_FIELDS)
            self.assertEqual(set(schema["properties"]), PREFLIGHT_FIELDS)

            props = schema["properties"]
            self.assertEqual(
                props["static_configuration_status"]["enum"],
                ["PASS", "UNKNOWN"],
            )
            self.assertEqual(props["live_readiness"]["const"], "BLOCKED")
            self.assertEqual(props["provider_id"]["const"], provider)
            self.assertEqual(props["reasons"]["type"], "array")
            self.assertEqual(props["reasons"]["items"]["type"], "string")
            self.assertEqual(props["retry_count"]["const"], 0)
            self.assertEqual(props["fallback_state"]["const"], "disabled")
            self.assertIs(props["live_ready"]["const"], False)
            self.assertEqual(props["external_agent"]["type"], "string")
            self.assertEqual(props["pinned_version"]["type"], "string")

    def test_hash_constraints_match_fail_closed_and_valid_outputs(self) -> None:
        props = self.schema["properties"]

        self.assertEqual(props["snapshot_packet_sha256"]["type"], "string")
        self.assertEqual(
            props["snapshot_packet_sha256"]["pattern"],
            "^[a-f0-9]{64}$",
        )

        for field in (
            "preflight_packet_sha256",
            "inventory_packet_sha256",
            "bundle_packet_sha256",
            "pipeline_packet_sha256",
        ):
            self.assertEqual(props[field]["type"], ["string", "null"])
            self.assertEqual(props[field]["pattern"], "^[a-f0-9]{64}$")

    def test_blocking_provider_schema_is_bounded_and_canonical_members_only(self) -> None:
        blocking = self.schema["properties"]["blocking_providers"]
        self.assertEqual(blocking["type"], "array")
        self.assertTrue(blocking["uniqueItems"])
        self.assertEqual(blocking["maxItems"], 3)
        self.assertEqual(blocking["items"]["enum"], list(PROVIDERS))

    def test_integer_fields_do_not_accept_schema_level_strings(self) -> None:
        props = self.schema["properties"]
        self.assertEqual(props["unresolved_count"]["type"], "integer")
        self.assertEqual(props["unresolved_count"]["minimum"], -1)
        self.assertEqual(props["retry_count"]["type"], "integer")
        self.assertEqual(props["retry_count"]["const"], 0)
