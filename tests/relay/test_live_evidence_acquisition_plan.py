import os
import unittest


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
            expected_header=(
                "gap_id",
                "scope/provider",
                "class",
                "current_state",
                "canonical_source",
                "missing_evidence_or_decision",
                "forbidden_until_resolved",
            ),
        )
        cls.plan_rows = cls._parse_table(
            cls.plan_content,
            expected_header=(
                "gap_id",
                "current_gap_class",
                "evidence_stage",
                "safe_now_action",
                "external_or_live_boundary",
                "completion_evidence_required",
                "result_state_if_not_proven",
            ),
        )

    @staticmethod
    def _parse_table(content: str, *, expected_header: tuple[str, ...]) -> dict[str, dict[str, str]]:
        header = None
        rows: dict[str, dict[str, str]] = {}
        for line in content.splitlines():
            if not line.startswith("| "):
                continue
            cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
            if cells == expected_header:
                header = cells
                continue
            if not header:
                continue
            if all(set(cell) <= {"-", ":"} for cell in cells):
                continue
            if len(cells) != len(header):
                continue
            row = dict(zip(header, cells))
            gap_id = row["gap_id"]
            if gap_id in rows:
                raise AssertionError(f"duplicate gap_id: {gap_id}")
            rows[gap_id] = row
        if header != expected_header:
            raise AssertionError(f"expected table header not found: {expected_header}")
        return rows

    def test_exact_gap_id_set_is_preserved(self) -> None:
        self.assertEqual(len(self.audit_rows), 30)
        self.assertEqual(len(self.plan_rows), 30)
        self.assertEqual(set(self.plan_rows), set(self.audit_rows))

    def test_current_gap_class_matches_loop056_source_exactly(self) -> None:
        for gap_id, audit in self.audit_rows.items():
            with self.subTest(gap_id=gap_id):
                self.assertEqual(
                    self.plan_rows[gap_id]["current_gap_class"],
                    audit["class"],
                )

    def test_completion_evidence_matches_loop056_source_exactly(self) -> None:
        for gap_id, audit in self.audit_rows.items():
            with self.subTest(gap_id=gap_id):
                self.assertEqual(
                    self.plan_rows[gap_id]["completion_evidence_required"],
                    audit["missing_evidence_or_decision"],
                )

    def test_every_plan_row_has_nonempty_action_boundary_evidence_and_fail_state(self) -> None:
        for gap_id, row in self.plan_rows.items():
            with self.subTest(gap_id=gap_id):
                for field in (
                    "safe_now_action",
                    "external_or_live_boundary",
                    "completion_evidence_required",
                    "result_state_if_not_proven",
                ):
                    self.assertTrue(row[field], field)

    def test_evidence_stage_uses_only_allowed_values(self) -> None:
        allowed = {
            "STATIC_PREPARATION_ONLY",
            "READ_ONLY_EVIDENCE_CANDIDATE",
            "REQUIRES_BOUNDED_LIVE_PROOF",
            "HUMAN_ARCHITECTURE_DECISION",
            "FINAL_HUMAN_APPROVAL",
            "DEFERRED_NOT_SELECTED",
        }
        for gap_id, row in self.plan_rows.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(row["evidence_stage"], allowed)

    def test_fail_closed_states_never_claim_success(self) -> None:
        dangerous_tokens = {
            "READY",
            "LIVE",
            "AUTHORIZED",
            "VERIFIED",
            "PASS",
            "RESOLVED",
        }
        allowed_exact = {
            "NOT_AUTHORIZED",
            "KEEP_NOT_WIRED",
            "TRANSPORT_EVIDENCE_ONLY",
            "EXPLICIT_HUMAN_APPROVAL_REQUIRED",
            "BLOCKED_UNKNOWN",
            "DEFERRED",
            "UNKNOWN",
        }
        for gap_id, row in self.plan_rows.items():
            with self.subTest(gap_id=gap_id):
                state = row["result_state_if_not_proven"]
                self.assertIn(state, allowed_exact)
                if state == "NOT_AUTHORIZED":
                    continue
                for token in dangerous_tokens:
                    self.assertNotIn(token, state)

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
                self.assertIn(
                    self.plan_rows[gap_id]["evidence_stage"],
                    {
                        "READ_ONLY_EVIDENCE_CANDIDATE",
                        "REQUIRES_BOUNDED_LIVE_PROOF",
                    },
                )

    def test_provenance_rows_remain_human_architecture_decisions(self) -> None:
        expected = {
            "provenance_keep_not_wired": (
                "KEEP_NOT_WIRED",
                "KEEP_NOT_WIRED = current safe default / no provenance advancement",
            ),
            "provenance_actions_readback": (
                "TRANSPORT_EVIDENCE_ONLY",
                "GITHUB_ACTIONS_READBACK_ONLY = transport evidence only / insufficient as authenticator",
            ),
            "provenance_oidc": (
                "NOT_AUTHORIZED",
                "GITHUB_OIDC_AUTHENTICATOR = candidate / NOT_AUTHORIZED",
            ),
            "provenance_attestation": (
                "NOT_AUTHORIZED",
                "GITHUB_ARTIFACT_ATTESTATION = strong candidate / NOT_AUTHORIZED",
            ),
        }
        for gap_id, (fail_state, evidence) in expected.items():
            with self.subTest(gap_id=gap_id):
                row = self.plan_rows[gap_id]
                self.assertEqual(row["evidence_stage"], "HUMAN_ARCHITECTURE_DECISION")
                self.assertEqual(row["result_state_if_not_proven"], fail_state)
                self.assertEqual(row["completion_evidence_required"], evidence)
                self.assertEqual(row["safe_now_action"], "architectural review")

    def test_actions_readback_never_becomes_authenticator(self) -> None:
        row = self.plan_rows["provenance_actions_readback"]
        self.assertIn("transport evidence only", row["completion_evidence_required"])
        self.assertIn("insufficient as authenticator", row["completion_evidence_required"])
        self.assertEqual(row["result_state_if_not_proven"], "TRANSPORT_EVIDENCE_ONLY")

    def test_oidc_and_attestation_remain_not_authorized(self) -> None:
        for gap_id in ("provenance_oidc", "provenance_attestation"):
            with self.subTest(gap_id=gap_id):
                row = self.plan_rows[gap_id]
                self.assertEqual(row["evidence_stage"], "HUMAN_ARCHITECTURE_DECISION")
                self.assertEqual(row["result_state_if_not_proven"], "NOT_AUTHORIZED")
                self.assertIn("NOT_AUTHORIZED", row["completion_evidence_required"])

    def test_gemini_cli_remains_deferred_and_never_fallback(self) -> None:
        row = self.plan_rows["gemini_cli"]
        self.assertEqual(row["evidence_stage"], "DEFERRED_NOT_SELECTED")
        self.assertEqual(row["result_state_if_not_proven"], "DEFERRED")
        self.assertEqual(row["safe_now_action"], "none")
        self.assertEqual(
            row["external_or_live_boundary"],
            "automatic fallback to Gemini CLI",
        )

    def test_first_live_turn_cannot_be_satisfied_by_this_plan(self) -> None:
        row = self.plan_rows["first_live_turn"]
        self.assertEqual(row["evidence_stage"], "FINAL_HUMAN_APPROVAL")
        self.assertEqual(
            row["result_state_if_not_proven"],
            "EXPLICIT_HUMAN_APPROVAL_REQUIRED",
        )
        self.assertEqual(row["safe_now_action"], "none")
        self.assertEqual(
            row["external_or_live_boundary"],
            "first real provider/model turn",
        )

    def test_safe_work_queue_categories_exist_without_ranking(self) -> None:
        for phrase in (
            "static preparation/audits",
            "separately authorized read-only evidence gathering",
            "bounded live proof requiring explicit authorization",
            "human architecture decision",
            "final human approval",
        ):
            self.assertIn(phrase, self.plan_content)

        for ranking_word in ("best", "winner", "recommended", "priority 1"):
            self.assertNotIn(ranking_word, self.plan_content.lower())

    def test_plan_explicitly_performs_zero_evidence_acquisition(self) -> None:
        for phrase in (
            "zero evidence acquisition",
            "no provider/network/GitHub readback is performed by this batch",
            "no real live blocker is resolved",
            "no provenance is verified",
            "no execution is authorized",
        ):
            self.assertIn(phrase, self.plan_content)

    def test_checkpoint_is_prepared_static_only(self) -> None:
        marker = "## Live Evidence Acquisition Plan Checkpoint"
        self.assertIn(marker, self.checkpoint_content)
        section = self.checkpoint_content.split(marker, 1)[1]
        for phrase in (
            "strictly PREPARED/static evidence-acquisition-plan status only",
            "Zero evidence was acquired",
            "no provider/network/GitHub readback is performed here",
            "No real live blocker is resolved",
            "No provenance is verified",
            "no execution is authorized",
        ):
            self.assertIn(phrase, section)
