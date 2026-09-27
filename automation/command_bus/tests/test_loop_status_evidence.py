from __future__ import annotations

import unittest

from automation.command_bus.loop_status_evidence import (
    validate_evidence_ref,
    verify_evidence_readbacks,
)


REF = "automation/command_bus/evidence/loop-015/owner-1.json"


class LoopStatusEvidenceTests(unittest.TestCase):
    def test_valid_ref_and_exact_readback_set(self):
        self.assertEqual(validate_evidence_ref(REF), REF)
        verified = verify_evidence_readbacks([REF], {REF: {"schema_version": 1, "kind": "owner"}})
        self.assertEqual(verified, {REF})

    def test_unsafe_or_non_evidence_ref_is_rejected(self):
        for ref in (
            "../owner.json",
            "automation/command_bus/receipts/loop-015/000001.json",
            "automation/command_bus/evidence/../owner.json",
            "https://example.com/evidence.json",
        ):
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError):
                    validate_evidence_ref(ref)

    def test_missing_extra_or_empty_readback_is_rejected(self):
        with self.assertRaises(ValueError):
            verify_evidence_readbacks([REF], {})
        with self.assertRaises(ValueError):
            verify_evidence_readbacks([REF], {REF: {"ok": True}, "automation/command_bus/evidence/loop-015/extra.json": {"ok": True}})
        with self.assertRaises(ValueError):
            verify_evidence_readbacks([REF], {REF: {}})

    def test_duplicate_required_ref_is_rejected(self):
        with self.assertRaises(ValueError):
            verify_evidence_readbacks([REF, REF], {REF: {"ok": True}})


if __name__ == "__main__":
    unittest.main()
