import unittest
import os

class TestLiveEvidenceAcquisitionPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cls.audit_path = os.path.join(base_dir, "docs", "RELAY_STATIC_TO_LIVE_GAP_AUDIT.md")
        cls.plan_path = os.path.join(base_dir, "docs", "RELAY_LIVE_EVIDENCE_ACQUISITION_PLAN.md")
        cls.checkpoint_path = os.path.join(base_dir, "docs", "RELAY_STATIC_CHECKPOINT.md")

        with open(cls.audit_path, "r", encoding="utf-8") as f:
            cls.audit_content = f.read()

        with open(cls.plan_path, "r", encoding="utf-8") as f:
            cls.plan_content = f.read()

        with open(cls.checkpoint_path, "r", encoding="utf-8") as f:
            cls.checkpoint_content = f.read()

        cls.audit_rows = [l.strip() for l in cls.audit_content.splitlines() if l.strip().startswith("|") and "gap_id" not in l and "---" not in l]
        cls.plan_rows = [l.strip() for l in cls.plan_content.splitlines() if l.strip().startswith("|") and "gap_id" not in l and "---" not in l]

    def test_identical_gap_ids(self):
        audit_ids = [r.split("|")[1].strip() for r in self.audit_rows if r.strip()]
        plan_ids = [r.split("|")[1].strip() for r in self.plan_rows if r.strip()]

        self.assertEqual(len(audit_ids), 30)
        self.assertEqual(len(plan_ids), 30)
        self.assertEqual(set(audit_ids), set(plan_ids))

    def test_evidence_stage_allowed_values(self):
        allowed_stages = {
            "STATIC_PREPARATION_ONLY",
            "READ_ONLY_EVIDENCE_CANDIDATE",
            "REQUIRES_BOUNDED_LIVE_PROOF",
            "HUMAN_ARCHITECTURE_DECISION",
            "FINAL_HUMAN_APPROVAL",
            "DEFERRED_NOT_SELECTED"
        }
        for row in self.plan_rows:
            parts = [p.strip() for p in row.split("|")]
            stage = parts[3]
            self.assertIn(stage, allowed_stages)

    def test_no_success_state_in_fail_closed(self):
        forbidden_exact = {"READY", "LIVE", "AUTHORIZED", "VERIFIED", "PASS", "RESOLVED"}
        for row in self.plan_rows:
            parts = [p.strip() for p in row.split("|")]
            fail_closed = parts[7].upper()

            # NOT_AUTHORIZED is valid fail_closed
            if fail_closed == "NOT_AUTHORIZED":
                continue

            for forbidden in forbidden_exact:
                self.assertNotIn(forbidden, fail_closed)

    def test_runtime_behavior_gaps_not_static_preparation_only(self):
        runtime_gaps = {
            "common_timeout", "common_min_permissions", "common_model_verification",
            "common_subscription_route", "common_abort_readback", "common_sensitive_fanout",
            "common_confinement", "common_hidden_retry", "openai_request_retry",
            "openai_stream_replay", "openai_auth_replay", "openai_single_request_evidence",
            "claude_retry", "claude_fallback", "claude_recovery", "claude_account_auth",
            "claude_permissions", "claude_model_verification", "antigravity_account_route",
            "antigravity_billing_route", "antigravity_retry_fallback", "antigravity_model_verification",
            "antigravity_cancel", "antigravity_quota_billing"
        }
        for row in self.plan_rows:
            parts = [p.strip() for p in row.split("|")]
            gap_id = parts[1]
            stage = parts[3]
            if gap_id in runtime_gaps:
                self.assertNotEqual(stage, "STATIC_PREPARATION_ONLY")
                self.assertIn(stage, ["REQUIRES_BOUNDED_LIVE_PROOF", "READ_ONLY_EVIDENCE_CANDIDATE"])

    def test_provenance_rows_states(self):
        for row in self.plan_rows:
            parts = [p.strip() for p in row.split("|")]
            gap_id = parts[1]
            stage = parts[3]
            fail_closed = parts[7]

            if gap_id.startswith("provenance_"):
                self.assertEqual(stage, "HUMAN_ARCHITECTURE_DECISION")

                if gap_id == "provenance_actions_readback":
                    self.assertEqual(fail_closed, "TRANSPORT_EVIDENCE_ONLY")
                elif gap_id in ["provenance_oidc", "provenance_attestation"]:
                    self.assertEqual(fail_closed, "NOT_AUTHORIZED")
                elif gap_id == "provenance_keep_not_wired":
                    self.assertEqual(fail_closed, "KEEP_NOT_WIRED")

    def test_gemini_cli_state(self):
        for row in self.plan_rows:
            parts = [p.strip() for p in row.split("|")]
            if parts[1] == "gemini_cli":
                self.assertEqual(parts[3], "DEFERRED_NOT_SELECTED")

    def test_first_live_turn_state(self):
        for row in self.plan_rows:
            parts = [p.strip() for p in row.split("|")]
            if parts[1] == "first_live_turn":
                self.assertEqual(parts[3], "FINAL_HUMAN_APPROVAL")

    def test_non_empty_fields(self):
        for row in self.plan_rows:
            parts = [p.strip() for p in row.split("|") if p]
            self.assertEqual(len(parts), 7)
            for part in parts:
                self.assertTrue(bool(part))

    def test_checkpoint_explicitly_states_no_evidence_acquired_or_blocker_resolved(self):
        plan_checkpoint_section = self.checkpoint_content.split("## Live Evidence Acquisition Plan Checkpoint")[1]
        self.assertIn("Zero evidence was acquired", plan_checkpoint_section)
        self.assertIn("No real live blocker is resolved.", plan_checkpoint_section)
