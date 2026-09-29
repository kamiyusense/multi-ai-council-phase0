import unittest
import re
from pathlib import Path

class TestAbortReadbackProofContract(unittest.TestCase):
    def setUp(self):
        self.doc_path = Path("docs/RELAY_ABORT_READBACK_PROOF_CONTRACT.md")
        self.checkpoint_path = Path("docs/RELAY_STATIC_CHECKPOINT.md")
        self.assertTrue(self.doc_path.exists(), "Contract document must exist")
        self.assertTrue(self.checkpoint_path.exists(), "Static checkpoint document must exist")
        self.content = self.doc_path.read_text(encoding="utf-8")
        self.checkpoint = self.checkpoint_path.read_text(encoding="utf-8")

    def test_provider_order_and_states(self):
        # tests must parse the contract and assert exact provider order/set openai, anthropic, google;
        # tests must assert each provider current row remains EVIDENCE_REQUIRED / BLOCKED_UNKNOWN;

        table_lines = [line for line in self.content.splitlines() if line.startswith('| openai') or line.startswith('| anthropic') or line.startswith('| google')]

        self.assertEqual(len(table_lines), 3, "Table must have exactly 3 provider rows")

        providers = []
        for line in table_lines:
            cols = [col.strip() for col in line.split('|') if col.strip()]
            self.assertGreaterEqual(len(cols), 9, "Row must have at least 9 columns")
            provider_id = cols[0]
            providers.append(provider_id)

            # Assert all state columns are EVIDENCE_REQUIRED except blocker_state which is BLOCKED_UNKNOWN
            for i in range(1, 8):
                self.assertEqual(cols[i], "EVIDENCE_REQUIRED", f"Column {i} for {provider_id} must be EVIDENCE_REQUIRED")
            self.assertEqual(cols[8], "BLOCKED_UNKNOWN", f"Blocker state for {provider_id} must be BLOCKED_UNKNOWN")

        self.assertEqual(providers, ["openai", "anthropic", "google"], "Provider order must be exactly openai, anthropic, google")

    def test_insufficiency_of_local_mock_abort(self):
        # tests must assert local/mock abort return alone is insufficient;
        self.assertIn("Calling a local/mock abort method or receiving a local return value alone is insufficient", self.content)

    def test_insufficiency_of_provider_ack(self):
        # tests must assert provider acknowledgment alone is insufficient;
        self.assertIn("provider-side acknowledgment alone is insufficient", self.content)

    def test_fail_closed_missing_abort_evidence(self):
        # tests must assert missing abort evidence fails closed;
        self.assertIn("Abort request evidence is missing.", self.content)

    def test_fail_closed_scope_mismatch(self):
        # tests must assert provider/session/turn scope mismatch fails closed;
        self.assertIn("Provider/session/turn scope is missing or mismatched.", self.content)

    def test_fail_closed_missing_ack(self):
        # tests must assert missing/malformed/contradictory acknowledgment fails closed;
        self.assertIn("Acknowledgment is missing, malformed, or contradictory.", self.content)

    def test_fail_closed_unproven_termination(self):
        # tests must assert unproven termination fails closed;
        self.assertIn("Termination cannot be proven.", self.content)

    def test_fail_closed_missing_readback(self):
        # tests must assert missing/unavailable post-abort readback fails closed;
        self.assertIn("Post-abort readback is missing/unavailable.", self.content)

    def test_fail_closed_additional_output(self):
        # tests must assert post-abort additional output/turn/restart fails closed;
        self.assertIn("Any additional model output/turn/restart appears after the abort boundary.", self.content)

    def test_fail_closed_contradictory_states(self):
        # tests must assert contradictory termination states fail closed;
        self.assertIn("Multiple conflicting termination states exist.", self.content)

    def test_fail_closed_untrusted_source(self):
        # tests must assert unknown/untrusted evidence source fails closed;
        self.assertIn("Evidence source is UNKNOWN/untrusted", self.content)

    def test_exact_dispatch_correlation(self):
        # tests must assert exact-dispatch correlation is mandatory;
        self.assertIn("exact single-dispatch binding is mandatory", self.content)
        self.assertIn("Durable evidence cannot be correlated to the exact dispatch.", self.content)

    def test_evidence_cannot_cross_satisfy(self):
        # tests must assert evidence cannot cross-satisfy another provider;
        self.assertIn("Evidence for one provider must not satisfy another provider's row.", self.content)

    def test_replay_prevention_requirements(self):
        # tests must assert retry=0, fallback disabled, and no second turn/restart are required;
        self.assertIn("No automatic second prompt/model turn", self.content)
        self.assertIn("No automatic fallback", self.content)
        self.assertIn("No automatic restart/recovery producing a new turn", self.content)
        self.assertIn("Retry remains 0", self.content)

    def test_future_proof_record_fields(self):
        # tests must assert all required future proof record conceptual fields are present;
        required_fields = [
            "provider_id",
            "dispatch_correlation_id",
            "provider_session_or_turn_id",
            "abort_requested_at",
            "abort_request_evidence",
            "provider_ack_evidence",
            "termination_evidence",
            "post_abort_readback_evidence",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state"
        ]
        for field in required_fields:
            self.assertIn(f"| {field}", self.content)

    def test_zero_live_evidence_and_unresolved_blocker(self):
        # tests must assert zero live abort/readback evidence acquired and common_abort_readback unresolved/BLOCKED_UNKNOWN;
        self.assertIn("Zero live abort/readback evidence is acquired by this batch", self.content)
        self.assertIn("`common_abort_readback` blocker remains completely unresolved / BLOCKED_UNKNOWN", self.content)
        self.assertIn("Zero live abort/readback evidence was acquired", self.checkpoint)
        self.assertIn("common_abort_readback remains unresolved/BLOCKED_UNKNOWN", self.checkpoint)

    def test_no_positive_live_state_claim(self):
        self.assertNotIn("or PASS", self.content)
        for forbidden in ("| PASS |", "| VERIFIED |", "| READY |", "| RESOLVED |", "| LIVE_AUTHORIZED |"):
            self.assertNotIn(forbidden, self.content)
        self.assertIn(
            "this static contract does not authorize a positive live state",
            self.content,
        )
