import os
import unittest


ALLOWED_STAGES = {
    "STATIC_PREPARATION_ONLY",
    "READ_ONLY_EVIDENCE_CANDIDATE",
    "REQUIRES_BOUNDED_LIVE_PROOF",
    "HUMAN_ARCHITECTURE_DECISION",
    "FINAL_HUMAN_APPROVAL",
    "DEFERRED_NOT_SELECTED",
}

FORBIDDEN_UNPROVEN_STATES = {
    "READY",
    "LIVE",
    "AUTHORIZED",
    "VERIFIED",
    "PASS",
    "RESOLVED",
}


class TestLiveEvidenceAcquisitionPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = os.path.join(os.path.dirname(__file__), "..", "..", "docs")
        with open(
            os.path.join(base, "RELAY_STATIC_TO_LIVE_GAP_AUDIT.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.audit_content = stream.read()
        with open(
            os.path.join(base, "RELAY_LIVE_EVIDENCE_ACQUISITION_PLAN.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.plan_content = stream.read()
        with open(
            os.path.join(base, "RELAY_STATIC_CHECKPOINT.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.checkpoint_content = stream.read()

        cls.audit_rows = cls._parse_table(
            cls.audit_content,
            {
                "gap_id",
                "scope/provider",
                "class",
                "current_state",
                "canonical_source",
                "missing_evidence_or_decision",
                "forbidden_until_resolved",
            },
        )
        cls.plan_rows = cls._parse_table(
            cls.plan_content,
            {
                "gap_id",
                "current_gap_class",
                "evidence_stage",
                "safe_now_action",
                "external_or_live_boundary",
                "completion_evidence_required",
                "result_state_if_not_proven",
            },
        )

    @staticmethod
    def _parse_table(content: str, expected_headers: set[str]) -> dict[str, dict[str, str]]:
        lines = content.splitlines()
        header_index = None
        headers = None
        for index, line in enumerate(lines):
            if not line.startswith("| "):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if set(cells) == expected_headers:
                header_index = index
                headers = cells
                break

        if header_index is None or headers is None:
            raise AssertionError(f"required table header not found: {expected_headers}")

        rows: dict[str, dict[str, str]] = {}
        for line in lines[header_index + 2 :]:
            if not line.startswith("| "):
                break
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != len(headers):
                raise AssertionError(f"malformed table row: {line}")
            row = dict(zip(headers, cells))
            gap_id = row["gap_id"]
            if gap_id in rows:
                raise AssertionError(f"duplicate gap_id: {gap_id}")
            rows[gap_id] = row
        return rows

    def test_exact_same_30_gap_ids_as_loop056(self) -> None:
        self.assertEqual(len(self.audit_rows), 30)
        self.assertEqual(len(self.plan_rows), 30)
        self.assertEqual(set(self.plan_rows), set(self.audit_rows))

    def test_current_gap_class_is_copied_exactly_from_loop056(self) -> None:
        for gap_id, audit_row in self.audit_rows.items():
            with self.subTest(gap_id=gap_id):
                self.assertEqual(
                    self.plan_rows[gap_id]["current_gap_class"],
                    audit_row["class"],
                )

    def test_every_row_has_allowed_stage_and_nonempty_contract_fields(self) -> None:
        for gap_id, row in self.plan_rows.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(row["evidence_stage"], ALLOWED_STAGES)
                for field in (
                    "safe_now_action",
                    "external_or_live_boundary",
                    "completion_evidence_required",
                    "result_state_if_not_proven",
                ):
                    self.assertTrue(row[field], field)

    def test_unproven_result_states_never_claim_success(self) -> None:
        for gap_id, row in self.plan_rows.items():
            with self.subTest(gap_id=gap_id):
                self.assertNotIn(
                    row["result_state_if_not_proven"].upper(),
                    FORBIDDEN_UNPROVEN_STATES,
                )

    def test_runtime_sensitive_gaps_are_never_static_only(self) -> None:
        runtime_sensitive = {
            "common_model_verification",
            "common_subscription_route",
            "common_abort_readback",
            "common_hidden_retry",
            "openai_request_retry",
            "openai_stream_replay",
            "openai_auth_replay",
            "openai_single_request_evidence",
            "claude_retry",
            "claude_fallback",
            "claude_recovery",
            "claude_account_auth",
            "claude_permissions",
            "claude_model_verification",
            "antigravity_account_route",
            "antigravity_billing_route",
            "antigravity_retry_fallback",
            "antigravity_model_verification",
            "antigravity_cancel",
            "antigravity_quota_billing",
        }
        for gap_id in runtime_sensitive:
            with self.subTest(gap_id=gap_id):
                self.assertIn(gap_id, self.plan_rows)
                self.assertNotEqual(
                    self.plan_rows[gap_id]["evidence_stage"],
                    "STATIC_PREPARATION_ONLY",
                )

    def test_provenance_rows_remain_human_architecture_decisions(self) -> None:
        expected_states = {
            "provenance_keep_not_wired": "KEEP_NOT_WIRED",
            "provenance_actions_readback": "TRANSPORT_EVIDENCE_ONLY",
            "provenance_oidc": "NOT_AUTHORIZED",
            "provenance_attestation": "NOT_AUTHORIZED",
        }
        for gap_id, fail_state in expected_states.items():
            with self.subTest(gap_id=gap_id):
                row = self.plan_rows[gap_id]
                self.assertEqual(
                    row["evidence_stage"],
                    "HUMAN_ARCHITECTURE_DECISION",
                )
                self.assertEqual(row["result_state_if_not_proven"], fail_state)

    def test_actions_readback_boundary_is_explicit(self) -> None:
        row = self.plan_rows["provenance_actions_readback"]
        self.assertIn(
            "transport evidence only / insufficient as authenticator",
            row["completion_evidence_required"],
        )
        self.assertIn(
            "GitHub Actions readback remains **transport evidence only / insufficient as authenticator**",
            self.plan_content,
        )

    def test_oidc_and_attestation_remain_not_authorized(self) -> None:
        for gap_id in ("provenance_oidc", "provenance_attestation"):
            with self.subTest(gap_id=gap_id):
                self.assertEqual(
                    self.plan_rows[gap_id]["result_state_if_not_proven"],
                    "NOT_AUTHORIZED",
                )
        self.assertIn("OIDC remains **NOT_AUTHORIZED**", self.plan_content)
        self.assertIn(
            "Artifact Attestation remains **NOT_AUTHORIZED**",
            self.plan_content,
        )

    def test_gemini_cli_stays_deferred_and_not_automatic_fallback(self) -> None:
        row = self.plan_rows["gemini_cli"]
        self.assertEqual(row["evidence_stage"], "DEFERRED_NOT_SELECTED")
        self.assertEqual(row["result_state_if_not_proven"], "DEFERRED")
        self.assertIn("automatic fallback", row["external_or_live_boundary"])
        self.assertIn(
            "Gemini CLI remains **DEFERRED_NOT_SELECTED** and is not an automatic fallback",
            self.plan_content,
        )

    def test_first_live_turn_stays_final_human_approval(self) -> None:
        row = self.plan_rows["first_live_turn"]
        self.assertEqual(row["evidence_stage"], "FINAL_HUMAN_APPROVAL")
        self.assertEqual(
            row["result_state_if_not_proven"],
            "EXPLICIT_HUMAN_APPROVAL_REQUIRED",
        )
        self.assertIn(
            "cannot be satisfied automatically by this plan",
            self.plan_content,
        )

    def test_plan_and_checkpoint_prove_zero_acquisition_and_zero_resolution(self) -> None:
        plan_phrases = (
            "zero evidence acquisition",
            "no provider/network/GitHub readback",
            "No real live blocker is resolved",
            "No provenance is verified",
            "No execution is authorized",
        )
        for phrase in plan_phrases:
            self.assertIn(phrase.lower(), self.plan_content.lower())

        checkpoint_section = self.checkpoint_content.split(
            "## Live Evidence Acquisition Plan Checkpoint",
            1,
        )[1]
        for phrase in (
            "Zero evidence was acquired",
            "no provider/network/GitHub readback",
            "No real live blocker is resolved.",
            "No provenance is verified",
            "no execution is authorized",
        ):
            self.assertIn(phrase.lower(), checkpoint_section.lower())

    def test_plan_contains_only_advisory_safe_work_queue_categories(self) -> None:
        for phrase in (
            "static preparation/audits",
            "separately authorized read-only evidence gathering",
            "bounded live proof requiring explicit authorization",
            "human architecture decision",
            "final human approval",
        ):
            self.assertIn(phrase, self.plan_content)
