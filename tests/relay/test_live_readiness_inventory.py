import unittest
import copy
from typing import Any

from providers.live_readiness import COMMON_PROOFS, PROVIDER_PROOFS
from providers.live_readiness_inventory import (
    build_empty_inventory,
    normalize_inventory,
    render_inventory_ja,
    convert_to_live_readiness_proofs,
    PROVIDER_ORDER
)

class TestLiveReadinessInventory(unittest.TestCase):
    def test_empty_inventory_returns_all_unknown(self) -> None:
        result = build_empty_inventory()

        self.assertEqual(result["state"], "UNRESOLVED")
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["dispatch_allowed"])
        self.assertTrue(result["human_approval_required"])
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")

        expected_unresolved_count = 0
        for provider in PROVIDER_ORDER:
            expected_keys = len(COMMON_PROOFS) + len(PROVIDER_PROOFS[provider])
            self.assertEqual(result["unresolved_by_provider"][provider], expected_keys)
            expected_unresolved_count += expected_keys

            for record in result["inventory"][provider].values():
                self.assertEqual(record["status"], "UNKNOWN")
                self.assertIsNone(record["evidence_ref"])

        self.assertEqual(result["unresolved_count"], expected_unresolved_count)
        self.assertIn("packet_sha256", result)

    def test_exact_keys_per_provider(self) -> None:
        result = build_empty_inventory()

        for provider in PROVIDER_ORDER:
            keys = set(result["inventory"][provider].keys())
            expected = COMMON_PROOFS | PROVIDER_PROOFS[provider]
            self.assertEqual(keys, expected)

    def test_one_confirmed_reduces_unresolved_count_by_one(self) -> None:
        empty = build_empty_inventory()
        input_inv = empty["inventory"]

        # Confirm one proof
        provider = "openai"
        key = list(input_inv[provider].keys())[0]
        input_inv[provider][key] = {"status": "CONFIRMED", "evidence_ref": "https://example.com/evidence1"}

        result = normalize_inventory(input_inv)
        self.assertEqual(result["state"], "UNRESOLVED")
        self.assertEqual(result["unresolved_count"], empty["unresolved_count"] - 1)
        self.assertEqual(result["unresolved_by_provider"][provider], empty["unresolved_by_provider"][provider] - 1)

    def test_all_synthetic_confirmed_yields_proof_records_complete(self) -> None:
        empty = build_empty_inventory()
        input_inv = empty["inventory"]

        for provider in PROVIDER_ORDER:
            for key in input_inv[provider].keys():
                input_inv[provider][key] = {"status": "CONFIRMED", "evidence_ref": f"ref_{provider}_{key}"}

        result = normalize_inventory(input_inv)
        self.assertEqual(result["state"], "PROOF_RECORDS_COMPLETE")
        self.assertEqual(result["unresolved_count"], 0)

        # Must still be blocked
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["dispatch_allowed"])
        self.assertTrue(result["human_approval_required"])

    def test_missing_provider_fails_closed(self) -> None:
        empty = build_empty_inventory()
        input_inv = empty["inventory"]
        del input_inv["openai"]

        result = normalize_inventory(input_inv)
        self.assertEqual(result["state"], "UNRESOLVED")
        self.assertEqual(result["unresolved_count"], empty["unresolved_count"])

    def test_extra_provider_fails_closed(self) -> None:
        empty = build_empty_inventory()
        input_inv = empty["inventory"]
        input_inv["extra_provider"] = {}

        result = normalize_inventory(input_inv)
        self.assertEqual(result["state"], "UNRESOLVED")
        self.assertEqual(result["unresolved_count"], empty["unresolved_count"])

    def test_missing_proof_key_fails_closed(self) -> None:
        empty = build_empty_inventory()
        input_inv = empty["inventory"]
        key = list(input_inv["openai"].keys())[0]
        del input_inv["openai"][key]

        result = normalize_inventory(input_inv)
        self.assertEqual(result["state"], "UNRESOLVED")
        self.assertEqual(result["unresolved_count"], empty["unresolved_count"])

    def test_extra_proof_key_fails_closed(self) -> None:
        empty = build_empty_inventory()
        input_inv = empty["inventory"]
        input_inv["openai"]["extra_key"] = {"status": "UNKNOWN", "evidence_ref": None}

        result = normalize_inventory(input_inv)
        self.assertEqual(result["state"], "UNRESOLVED")
        self.assertEqual(result["unresolved_count"], empty["unresolved_count"])

    def test_malformed_status_evidence_ref_fails_closed(self) -> None:
        empty = build_empty_inventory()
        base_inv = empty["inventory"]
        key = list(base_inv["openai"].keys())[0]

        malformed_cases = [
            {"status": "CONFIRMED", "evidence_ref": None},
            {"status": "CONFIRMED", "evidence_ref": ""},
            {"status": "CONFIRMED", "evidence_ref": "   "},
            {"status": "UNKNOWN", "evidence_ref": "some_ref"},
            {"status": "INVALID", "evidence_ref": None},
            {"state": "UNKNOWN", "evidence": None}, # wrong keys
        ]

        for case in malformed_cases:
            with self.subTest(case=case):
                input_inv = copy.deepcopy(base_inv)
                input_inv["openai"][key] = case
                result = normalize_inventory(input_inv)
                self.assertEqual(result["state"], "UNRESOLVED")
                self.assertEqual(result["unresolved_count"], empty["unresolved_count"])

    def test_non_json_serializable_input_fails_closed(self) -> None:
        class Unserializable:
            pass

        empty = build_empty_inventory()
        input_inv = empty["inventory"]
        key = list(input_inv["openai"].keys())[0]
        input_inv["openai"][key] = {"status": "UNKNOWN", "evidence_ref": Unserializable()}

        result = normalize_inventory(input_inv)
        self.assertEqual(result["state"], "UNRESOLVED")
        self.assertEqual(result["unresolved_count"], empty["unresolved_count"])

    def test_caller_mutation_isolation(self) -> None:
        empty = build_empty_inventory()
        input_inv = empty["inventory"]

        key = list(input_inv["openai"].keys())[0]
        record = {"status": "CONFIRMED", "evidence_ref": "ref"}
        input_inv["openai"][key] = record

        result = normalize_inventory(input_inv)

        # Mutate original
        record["status"] = "UNKNOWN"
        record["evidence_ref"] = None

        # Result should not be affected
        self.assertEqual(result["inventory"]["openai"][key]["status"], "CONFIRMED")
        self.assertEqual(result["inventory"]["openai"][key]["evidence_ref"], "ref")

        # Mutate result
        result["inventory"]["openai"][key]["status"] = "UNKNOWN"
        result["inventory"]["openai"][key]["evidence_ref"] = None

        # Subsequent operations should not use mutated state
        # (This just verifies python dictionary references aren't unintentionally shared)
        self.assertEqual(input_inv["openai"][key]["status"], "UNKNOWN")

    def test_equivalent_key_order_gives_identical_digest(self) -> None:
        empty = build_empty_inventory()
        input1 = empty["inventory"]

        input2 = {"google": input1["google"], "anthropic": input1["anthropic"], "openai": input1["openai"]}

        res1 = normalize_inventory(input1)
        res2 = normalize_inventory(input2)

        self.assertEqual(res1["packet_sha256"], res2["packet_sha256"])

    def test_changing_evidence_ref_changes_digest(self) -> None:
        empty = build_empty_inventory()
        input1 = empty["inventory"]
        key = list(input1["openai"].keys())[0]

        input2 = copy.deepcopy(input1)

        input1["openai"][key] = {"status": "CONFIRMED", "evidence_ref": "ref1"}
        input2["openai"][key] = {"status": "CONFIRMED", "evidence_ref": "ref2"}

        res1 = normalize_inventory(input1)
        res2 = normalize_inventory(input2)

        self.assertNotEqual(res1["packet_sha256"], res2["packet_sha256"])

    def test_japanese_renderer_never_contains_evidence_ref(self) -> None:
        empty = build_empty_inventory()
        input_inv = empty["inventory"]

        for provider in PROVIDER_ORDER:
            for key in input_inv[provider].keys():
                input_inv[provider][key] = {"status": "CONFIRMED", "evidence_ref": f"SECRET_REF_{provider}_{key}"}

        result = normalize_inventory(input_inv)
        rendered = render_inventory_ja(result)

        self.assertNotIn("SECRET_REF", rendered)
        self.assertIn("確認済", rendered)
        self.assertIn("ライブ実行: 禁止", rendered)

    def test_convert_to_live_readiness_proofs(self) -> None:
        # Partial inventory -> fails closed (returns {})
        empty = build_empty_inventory()
        self.assertEqual(convert_to_live_readiness_proofs(empty), {})

        # All CONFIRMED inventory -> returns mapping
        input_inv = empty["inventory"]
        for provider in PROVIDER_ORDER:
            for key in input_inv[provider].keys():
                input_inv[provider][key] = {"status": "CONFIRMED", "evidence_ref": f"ref_{provider}_{key}"}

        result = normalize_inventory(input_inv)
        proofs = convert_to_live_readiness_proofs(result)

        self.assertEqual(set(proofs.keys()), set(PROVIDER_ORDER))
        for provider in PROVIDER_ORDER:
            expected_keys = COMMON_PROOFS | PROVIDER_PROOFS[provider]
            self.assertEqual(set(proofs[provider].keys()), expected_keys)
            for key in expected_keys:
                self.assertEqual(proofs[provider][key]["status"], "CONFIRMED")
                self.assertEqual(proofs[provider][key]["evidence_ref"], f"ref_{provider}_{key}")

    def test_ast_no_ambient_io(self) -> None:
        import ast
        from pathlib import Path

        src_path = Path("src/providers/live_readiness_inventory.py")
        with open(src_path) as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    self.assertNotIn(name.name, ["os", "sys", "subprocess", "urllib", "requests", "time", "random"])
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, ["os", "sys", "subprocess", "urllib", "requests", "time", "random"])

if __name__ == "__main__":
    unittest.main()
