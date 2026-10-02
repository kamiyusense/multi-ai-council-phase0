import json
import unittest
from pathlib import Path
from typing import Any

from providers.live_readiness_inventory import build_empty_inventory, normalize_inventory

class TestLiveReadinessInventorySchema(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = Path("schemas/relay_live_readiness_inventory_v1.schema.json")
        with open(schema_path) as f:
            self.schema = json.load(f)

    def test_schema_valid_draft_2020_12(self) -> None:
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(self.schema["type"], "object")
        self.assertFalse(self.schema["additionalProperties"])

    def test_schema_exact_provider_structure(self) -> None:
        props = self.schema["properties"]

        # unresolved_by_provider
        up = props["unresolved_by_provider"]
        self.assertFalse(up["additionalProperties"])
        self.assertEqual(set(up["required"]), {"openai", "anthropic", "google"})
        self.assertEqual(set(up["properties"].keys()), {"openai", "anthropic", "google"})

        # inventory
        inv = props["inventory"]
        self.assertFalse(inv["additionalProperties"])
        self.assertEqual(set(inv["required"]), {"openai", "anthropic", "google"})
        self.assertEqual(set(inv["properties"].keys()), {"openai", "anthropic", "google"})

        from providers.live_readiness import COMMON_PROOFS, PROVIDER_PROOFS

        for provider in ["openai", "anthropic", "google"]:
            p_obj = inv["properties"][provider]
            self.assertEqual(p_obj["type"], "object")
            self.assertFalse(p_obj["additionalProperties"])
            expected = COMMON_PROOFS | PROVIDER_PROOFS[provider]
            self.assertEqual(set(p_obj["required"]), expected)
            self.assertEqual(set(p_obj["properties"]), expected)
            self.assertNotIn("patternProperties", p_obj)
            for key in expected:
                self.assertEqual(p_obj["properties"][key], {"$ref": "#/$defs/proof_record"})

    def test_schema_fixed_safety_fields(self) -> None:
        props = self.schema["properties"]

        self.assertEqual(props["live_ready"], {"type": "boolean", "const": False})
        self.assertEqual(props["dispatch_allowed"], {"type": "boolean", "const": False})
        self.assertEqual(props["human_approval_required"], {"type": "boolean", "const": True})
        self.assertEqual(props["retry_count"], {"type": "integer", "const": 0})
        self.assertEqual(props["fallback_state"], {"type": "string", "const": "disabled"})

    def test_schema_aggregate_state_enum(self) -> None:
        state_prop = self.schema["properties"]["state"]
        self.assertEqual(state_prop["type"], "string")
        self.assertEqual(set(state_prop["enum"]), {"UNRESOLVED", "PROOF_RECORDS_COMPLETE"})

    def test_schema_no_live_authorization_state_strings(self) -> None:
        state_prop = self.schema["properties"]["state"]
        self.assertNotIn("READY_FOR_HUMAN_APPROVAL", state_prop["enum"])
        self.assertNotIn("PASS", state_prop["enum"])
        self.assertNotIn("BLOCKED_UNKNOWN", state_prop["enum"])

        serialized = json.dumps(self.schema, sort_keys=True)
        for forbidden in ("LIVE_READY", "AUTO_APPROVED", "DISPATCH_ALLOWED"):
            self.assertNotIn(forbidden, serialized)

    def test_schema_proof_record_defs(self) -> None:
        proof_record = self.schema["$defs"]["proof_record"]
        self.assertEqual(proof_record["type"], "object")
        self.assertFalse(proof_record["additionalProperties"])
        self.assertEqual(set(proof_record["required"]), {"status", "evidence_ref"})

        oneOf = proof_record["oneOf"]
        self.assertEqual(len(oneOf), 2)

        # UNKNOWN case
        unknown_case = [case for case in oneOf if case["properties"]["status"].get("const") == "UNKNOWN"][0]
        self.assertEqual(unknown_case["properties"]["evidence_ref"], {"type": "null"})

        # CONFIRMED case
        confirmed_case = [case for case in oneOf if case["properties"]["status"].get("const") == "CONFIRMED"][0]
        self.assertEqual(confirmed_case["properties"]["evidence_ref"], {"type": "string", "minLength": 1})

if __name__ == "__main__":
    unittest.main()
