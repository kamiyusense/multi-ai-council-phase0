import json
import os
import unittest

class TestLiveApprovalReceiptSchema(unittest.TestCase):
    def setUp(self) -> None:
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "../../schemas/relay_live_approval_receipt_v1.schema.json"
        )
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def test_schema_valid_json(self) -> None:
        self.assertEqual(self.schema["type"], "object")
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.schema["title"], "Relay Live Approval Receipt")

    def test_schema_requires_fields(self) -> None:
        required = set(self.schema["required"])
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
            "approval_record_sha256"
        }
        self.assertEqual(required, expected)

    def test_schema_fixed_flags(self) -> None:
        props = self.schema["properties"]
        self.assertFalse(props["live_ready"]["const"])
        self.assertFalse(props["dispatch_allowed"]["const"])
        self.assertFalse(props["execution_authorized"]["const"])
        self.assertFalse(props["provenance_verified"]["const"])
        self.assertEqual(props["retry_count"]["const"], 0)
        self.assertEqual(props["fallback_state"]["const"], "disabled")

    def test_schema_hashes(self) -> None:
        props = self.schema["properties"]

        app_sha = props["approval_packet_sha256"]
        self.assertEqual(app_sha["type"], ["string", "null"])
        self.assertEqual(app_sha["pattern"], "^[a-f0-9]{64}$")

        snap_sha = props["snapshot_packet_sha256"]
        self.assertEqual(snap_sha["type"], ["string", "null"])
        self.assertEqual(snap_sha["pattern"], "^[a-f0-9]{64}$")

        rec_sha = props["approval_record_sha256"]
        self.assertEqual(rec_sha["type"], "string") # not null
        self.assertEqual(rec_sha["pattern"], "^[a-f0-9]{64}$")
