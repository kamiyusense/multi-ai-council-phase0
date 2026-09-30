import unittest
import os
import re

class TestHiddenRetryProofContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'RELAY_HIDDEN_RETRY_PROOF_CONTRACT.md')
        with open(path, 'r', encoding='utf-8') as f:
            cls.content = f.read()

    def test_status_remains_unresolved(self):
        self.assertIn("PREPARED static contract only", self.content)
        self.assertIn("Zero live hidden-retry evidence is acquired", self.content)
        self.assertIn("common_hidden_retry` blocker remains completely unresolved / BLOCKED_UNKNOWN", self.content)

    def test_insufficient_mock_state(self):
        self.assertIn("Explicitly, retry=0/fallback=disabled in Relay code", self.content)
        self.assertIn("do NOT prove end-to-end hidden provider behavior", self.content)
        self.assertIn("static declarations may be `STATIC_PREPARED`, but provider-internal and runtime replay evidence remain `EVIDENCE_REQUIRED`", self.content)

    def test_fail_closed_rules(self):
        self.assertIn("outbound_model_request_count=1", self.content)
        self.assertIn("zero provider retry/reconnect/auth-recovery/restart replay counts", self.content)
        self.assertIn("`fallback_observed=false`", self.content)
        self.assertIn("Missing or ambiguous observation fails closed.", self.content)
        self.assertIn("provider-internal retry UNKNOWN fails closed.", self.content)
        self.assertIn("outbound_model_request_count missing, ambiguous, zero, or greater than one fails proof.", self.content)
        self.assertIn("any provider retry/reconnect/auth-recovery/restart replay count greater than zero fails proof.", self.content)
        self.assertIn("fallback_observed missing/UNKNOWN/true fails proof.", self.content)
        self.assertIn("missing proof_correlation_id or provider/event binding fails proof.", self.content)
        self.assertIn("cross-provider evidence cannot satisfy another provider.", self.content)
        self.assertIn("replayed/reused evidence event cannot satisfy a distinct proof event.", self.content)

    def test_extra_turns_paths_distinguished(self):
        self.assertIn("Relay/controller retry:", self.content)
        self.assertIn("Transport retry:", self.content)
        self.assertIn("Provider/SDK internal retry:", self.content)
        self.assertIn("Stream reconnect/replay:", self.content)
        self.assertIn("Auth recovery/replay:", self.content)
        self.assertIn("Restart/recovery replay:", self.content)
        self.assertIn("Model fallback:", self.content)

    def test_conceptual_proof_record(self):
        self.assertIn("No raw tokens, credentials, private prompts, or secret values belong in future evidence", self.content)
        for field in [
            "provider_id",
            "proof_correlation_id",
            "session_or_turn_id",
            "relay_prompt_attempts_observed",
            "outbound_model_request_count",
            "provider_retry_count_observed",
            "reconnect_replay_count",
            "auth_recovery_replay_count",
            "restart_replay_count",
            "fallback_observed",
            "requested_model",
            "executed_model",
            "evidence_source",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state"
        ]:
            self.assertIn(field, self.content)

    def test_state_table_format_and_vocabulary(self):
        # Extract rows from state table
        table_match = re.search(r'\| provider_id \|.*?\| blocker_state \|\n\|--.*?\n(.*?\n.*?\n.*?)\n', self.content, re.DOTALL)
        self.assertIsNotNone(table_match, "State table not found")
        rows = table_match.group(1).strip().split('\n')
        self.assertEqual(len(rows), 3)

        providers = []
        allowed_vocab = {'UNKNOWN', 'STATIC_PREPARED', 'EVIDENCE_REQUIRED', 'BLOCKED_UNKNOWN'}
        for row in rows:
            cols = [c.strip() for c in row.split('|') if c.strip()]
            self.assertEqual(len(cols), 11, "Expected 11 columns in state table")
            provider = cols[0]
            providers.append(provider)
            # Check vocab for other columns
            for col in cols[1:]:
                self.assertIn(col, allowed_vocab)

        self.assertEqual(providers, ['openai', 'anthropic', 'google'], "Exact provider order required")

        # openai check
        openai_cols = [c.strip() for c in rows[0].split('|') if c.strip()]
        self.assertEqual(openai_cols[1], 'STATIC_PREPARED')
        self.assertEqual(openai_cols[2], 'STATIC_PREPARED')
        self.assertEqual(openai_cols[3], 'EVIDENCE_REQUIRED')
        self.assertEqual(openai_cols[-1], 'BLOCKED_UNKNOWN')
