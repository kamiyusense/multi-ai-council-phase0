import json
import os
import unittest


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

    def test_schema_structure(self) -> None:
        self.assertEqual(
            self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        self.assertEqual(self.schema["type"], "object")
        self.assertFalse(self.schema["additionalProperties"])

        req = self.schema["required"]
        self.assertIn("state", req)
        self.assertIn("live_ready", req)
        self.assertIn("dispatch_allowed", req)
        self.assertIn("human_approval_required", req)
        self.assertIn("retry_count", req)
        self.assertIn("fallback_state", req)
        self.assertIn("preflight_states", req)
        self.assertIn("preflight_snapshots", req)
        self.assertIn("preflight_packet_sha256", req)
        self.assertIn("inventory_state", req)
        self.assertIn("unresolved_count", req)
        self.assertIn("unresolved_by_provider", req)
        self.assertIn("inventory_packet_sha256", req)
        self.assertIn("provider_states", req)
        self.assertIn("blocking_providers", req)
        self.assertIn("bundle_packet_sha256", req)
        self.assertIn("pipeline_packet_sha256", req)
        self.assertIn("snapshot_packet_sha256", req)

    def test_fixed_safety_fields(self) -> None:
        props = self.schema["properties"]
        self.assertEqual(props["live_ready"]["const"], False)
        self.assertEqual(props["dispatch_allowed"]["const"], False)
        self.assertEqual(props["human_approval_required"]["const"], True)
        self.assertEqual(props["retry_count"]["const"], 0)
        self.assertEqual(props["fallback_state"]["const"], "disabled")

    def test_enum_constraints(self) -> None:
        props = self.schema["properties"]
        self.assertEqual(
            props["state"]["enum"],
            ["BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"]
        )
        self.assertEqual(
            props["inventory_state"]["enum"],
            ["BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"]
        )

    def test_hash_constraints(self) -> None:
        props = self.schema["properties"]

        # snapshot_packet_sha256 must be exact string
        self.assertEqual(props["snapshot_packet_sha256"]["type"], "string")
        self.assertEqual(props["snapshot_packet_sha256"]["pattern"], "^[a-f0-9]{64}$")

        # pipeline_packet_sha256 must be exact string
        self.assertEqual(props["pipeline_packet_sha256"]["type"], "string")
        self.assertEqual(props["pipeline_packet_sha256"]["pattern"], "^[a-f0-9]{64}$")

        # others can be null
        for field in ("preflight_packet_sha256", "inventory_packet_sha256", "bundle_packet_sha256"):
            self.assertEqual(props[field]["type"], ["string", "null"])
            self.assertEqual(props[field]["pattern"], "^[a-f0-9]{64}$")
