import unittest
import os
import re

class TestModelVerificationProofContract(unittest.TestCase):
    def setUp(self):
        docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "docs")
        self.contract_path = os.path.join(docs_dir, "RELAY_MODEL_VERIFICATION_PROOF_CONTRACT.md")
        self.checkpoint_path = os.path.join(docs_dir, "RELAY_STATIC_CHECKPOINT.md")

        with open(self.contract_path, "r", encoding="utf-8") as f:
            self.contract_text = f.read()

        with open(self.checkpoint_path, "r", encoding="utf-8") as f:
            self.checkpoint_text = f.read()

    def test_provider_order_and_set(self):
        # tests must parse the contract and assert exact provider order/set openai, anthropic, google
        table_lines = [line for line in self.contract_text.split("\n") if line.strip().startswith("|") and not line.strip().startswith("| provider_id") and not line.strip().startswith("|---") and not line.strip().startswith("| Conceptual Field")]

        # Only parse the main Provider Contract State Table
        # We can distinguish by looking for exactly " openai " or similar
        provider_rows = [line for line in table_lines if "| openai |" in line or "| anthropic |" in line or "| google |" in line]
        self.assertEqual(len(provider_rows), 3)

        providers = [row.split("|")[1].strip() for row in provider_rows]
        self.assertEqual(providers, ["openai", "anthropic", "google"])

    def test_provider_row_states(self):
        # tests must assert each provider row remains EVIDENCE_REQUIRED / BLOCKED_UNKNOWN
        table_lines = [line for line in self.contract_text.split("\n") if line.strip().startswith("|")]
        provider_rows = [line for line in table_lines if "| openai |" in line or "| anthropic |" in line or "| google |" in line]

        for row in provider_rows:
            columns = [col.strip() for col in row.split("|")[1:-1]]
            # columns = [provider_id, requested_model_state, executed_model_state, independent_evidence_state, evidence_source_state, correlation_binding_state, mismatch_policy, missing_evidence, blocker_state]
            self.assertEqual(len(columns), 9)

            # blocker_state is the last column
            self.assertEqual(columns[-1], "BLOCKED_UNKNOWN")

            # All current evidence requirement columns remain conservative.
            for state_col in columns[1:6]:
                self.assertEqual(state_col, "EVIDENCE_REQUIRED")
            self.assertEqual(columns[6], "BLOCKED_UNKNOWN")
            self.assertEqual(columns[7], "EVIDENCE_REQUIRED")

    def test_state_vocabulary_is_bounded(self):
        provider_rows = [
            line for line in self.contract_text.split("\n")
            if "| openai |" in line or "| anthropic |" in line or "| google |" in line
        ]
        allowed = {"UNKNOWN", "STATIC_PREPARED", "EVIDENCE_REQUIRED", "BLOCKED_UNKNOWN"}
        for row in provider_rows:
            columns = [col.strip() for col in row.split("|")[1:-1]]
            for value in columns[1:]:
                self.assertIn(value, allowed)

    def test_requested_identity_insufficient(self):
        # tests must assert requested/configured identity is explicitly insufficient by itself
        self.assertIn("Requested/configured/default model identity alone is insufficient", self.contract_text)

    def test_provider_self_report_not_independent(self):
        # tests must assert provider self-report is not automatically independent verification
        self.assertIn("Provider self-report alone must not automatically be treated as independent verification", self.contract_text)

    def test_missing_evidence_fails_closed(self):
        self.assertIn("Missing executed-model evidence fails closed", self.contract_text)

    def test_malformed_evidence_fails_closed(self):
        self.assertIn("Malformed evidence fails closed", self.contract_text)

    def test_provider_mismatch_fails_closed(self):
        self.assertIn("Provider identity mismatch fails closed", self.contract_text)

    def test_correlation_turn_mismatch_fails_closed(self):
        self.assertIn("Correlation/turn mismatch fails closed", self.contract_text)

    def test_requested_vs_observed_conflict_fails_closed(self):
        self.assertIn("Requested-vs-observed conflict fails closed when both are present", self.contract_text)

    def test_unknown_untrusted_evidence_source_fails_closed(self):
        self.assertIn("Unknown/untrusted evidence source fails closed", self.contract_text)

    def test_contradictory_multiple_identities_fail_closed(self):
        self.assertIn("Contradictory multiple identities fail closed", self.contract_text)

    def test_unavailable_durable_readback_fails_closed(self):
        self.assertIn("Unavailable durable readback fails closed", self.contract_text)

    def test_no_automatic_retry_fallback_second_turn(self):
        self.assertIn("no automatic fallback or second model turn is authorized", self.contract_text)

    def test_conceptual_future_proof_record_fields(self):
        # tests must assert the conceptual future proof record includes all required fields
        required_fields = [
            "provider_id",
            "dispatch_correlation_id",
            "provider_session_or_turn_id",
            "requested_model_if_known",
            "observed_executed_model",
            "evidence_source",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state"
        ]
        for field in required_fields:
            self.assertIn(field, self.contract_text)

    def test_docs_checkpoint_zero_live_evidence_unresolved(self):
        # tests must assert docs/checkpoint say zero live evidence acquired and common_model_verification remains unresolved/BLOCKED_UNKNOWN
        self.assertIn("Zero live evidence is acquired", self.contract_text)
        self.assertIn("remains unresolved/BLOCKED_UNKNOWN", self.contract_text)

        # also assert in checkpoint file
        self.assertIn("PREPARED/static model-verification-proof-contract status only", self.checkpoint_text)
        self.assertIn("common_model_verification remains unresolved/BLOCKED_UNKNOWN", self.checkpoint_text)

    def test_oidc_attestation_not_authorized_or_required(self):
        self.assertIn("OIDC/attestation are not authorized or required", self.contract_text)
