import json
import unittest
from pathlib import Path


class TestLiveReadinessBundleSchema(unittest.TestCase):
    def setUp(self):
        schema_path = Path("schemas/relay_live_readiness_bundle_v1.schema.json")
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_schema_is_draft_2020_12(self):
        self.assertEqual(
            self.schema.get("$schema"),
            "https://json-schema.org/draft/2020-12/schema",
        )

    def test_top_level_additional_properties_false(self):
        self.assertIs(self.schema.get("additionalProperties"), False)

    def test_fixed_safety_fields_are_constants(self):
        props = self.schema["properties"]

        self.assertEqual(props["live_ready"]["const"], False)
        self.assertEqual(props["dispatch_allowed"]["const"], False)
        self.assertEqual(props["human_approval_required"]["const"], True)
        self.assertEqual(props["retry_count"]["const"], 0)
        self.assertEqual(props["fallback_state"]["const"], "disabled")

        # Ensure LIVE_READY or other dispatch-allowing states aren't in enums
        self.assertEqual(
            set(props["state"]["enum"]),
            {"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"}
        )

    def test_provider_order_is_fixed(self):
        order_prop = self.schema["properties"]["provider_order"]
        self.assertEqual(
            order_prop["prefixItems"],
            [{"const": "openai"}, {"const": "anthropic"}, {"const": "google"}]
        )
        self.assertEqual(order_prop["minItems"], 3)
        self.assertEqual(order_prop["maxItems"], 3)

    def test_provider_states_are_strict(self):
        states_prop = self.schema["properties"]["provider_states"]
        self.assertIs(states_prop["additionalProperties"], False)

        for provider in ("openai", "anthropic", "google"):
            self.assertEqual(
                set(states_prop["properties"][provider]["enum"]),
                {"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"}
            )

    def test_packet_sha256_format(self):
        sha_prop = self.schema["properties"]["packet_sha256"]
        self.assertEqual(sha_prop["type"], "string")
        self.assertEqual(sha_prop["pattern"], "^[a-f0-9]{64}$")


if __name__ == "__main__":
    unittest.main()
