import os
import unittest


def _parse_markdown_table(text: str, header_first_cell: str) -> dict[str, dict[str, str]]:
    lines = text.splitlines()
    header_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith(f"| {header_first_cell} |")
    )
    header = [
        cell.strip()
        for cell in lines[header_index].strip("|").split("|")
    ]

    rows: dict[str, dict[str, str]] = {}
    for line in lines[header_index + 2 :]:
        if not line.startswith("| "):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(header):
            raise AssertionError(
                f"table row has {len(cells)} cells, expected {len(header)}: {line}"
            )
        row = dict(zip(header, cells))
        key = row[header_first_cell]
        if key in rows:
            raise AssertionError(f"duplicate row: {key}")
        rows[key] = row
    return rows


class TestLiveEvidenceAcquisitionPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = os.path.join(os.path.dirname(__file__), "..", "..", "docs")
        with open(
            os.path.join(base, "RELAY_STATIC_TO_LIVE_GAP_AUDIT.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.audit = stream.read()
        with open(
            os.path.join(base, "RELAY_LIVE_EVIDENCE_ACQUISITION_PLAN.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.plan = stream.read()
        with open(
            os.path.join(base, "RELAY_STATIC_CHECKPOINT.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.checkpoint = stream.read()

        cls.audit_rows = _parse_markdown_table(cls.audit, "gap_id")
        cls.plan_rows = _parse_markdown_table(cls.plan, "gap_id")

    def test_exact_gap_ids_classes_and_required_evidence_match_loop056(self) -> None:
        self.assertEqual(len(self.audit_rows), 30)
        self.assertEqual(len(self.plan_rows), 30)
        self.assertEqual(set(self.plan_rows), set(self.audit_rows))

        for gap_id, audit_row in self.audit_rows.items():
            with self.subTest(gap_id=gap_id):
                plan_row = self.plan_rows[gap_id]
                self.assertEqual(
                    plan_row["current_gap_class"],
                    audit_row["class"],
                )
                self.assertEqual(
                    plan_row["completion_evidence_required"],
                    audit_row["missing_evidence_or_decision"],
                )

    def test_exact_conservative_stage_map(self) -> None:
        static_only = {
            "common_timeout",
            "common_min_permissions",
            "common_sensitive_fanout",
        }
        read_only = {
            "common_subscription_route",
            "claude_account_auth",
            "claude_permissions",
            "antigravity_account_route",
            "antigravity_billing_route",
        }
        bounded_live = {
            "common_model_verification",
            "common_abort_readback",
            "common_confinement",
            "common_hidden_retry",
            "openai_request_retry",
            "openai_stream_replay",
            "openai_auth_replay",
            "openai_single_request_evidence",
            "claude_retry",
            "claude_fallback",
            "claude_recovery",
            "claude_model_verification",
            "antigravity_retry_fallback",
            "antigravity_model_verification",
            "antigravity_cancel",
            "antigravity_quota_billing",
        }
        human_decision = {
            "provenance_keep_not_wired",
            "provenance_actions_readback",
            "provenance_oidc",
            "provenance_attestation",
        }

        expected = {}
        expected.update(
            {gap_id: "STATIC_PREPARATION_ONLY" for gap_id in static_only}
        )
        expected.update(
            {gap_id: "READ_ONLY_EVIDENCE_CANDIDATE" for gap_id in read_only}
        )
        expected.update(
            {gap_id: "REQUIRES_BOUNDED_LIVE_PROOF" for gap_id in bounded_live}
        )
        expected.update(
            {gap_id: "HUMAN_ARCHITECTURE_DECISION" for gap_id in human_decision}
        )
        expected["gemini_cli"] = "DEFERRED_NOT_SELECTED"
        expected["first_live_turn"] = "FINAL_HUMAN_APPROVAL"

        self.assertEqual(set(expected), set(self.plan_rows))
        for gap_id, stage in expected.items():
            with self.subTest(gap_id=gap_id):
                self.assertEqual(
                    self.plan_rows[gap_id]["evidence_stage"],
                    stage,
                )

    def test_runtime_sensitive_gaps_are_never_static_or_read_only(self) -> None:
        runtime_sensitive = {
            "common_model_verification",
            "common_abort_readback",
            "common_confinement",
            "common_hidden_retry",
            "openai_request_retry",
            "openai_stream_replay",
            "openai_auth_replay",
            "openai_single_request_evidence",
            "claude_retry",
            "claude_fallback",
            "claude_recovery",
            "claude_model_verification",
            "antigravity_retry_fallback",
            "antigravity_model_verification",
            "antigravity_cancel",
            "antigravity_quota_billing",
        }
        for gap_id in runtime_sensitive:
            with self.subTest(gap_id=gap_id):
                self.assertEqual(
                    self.plan_rows[gap_id]["evidence_stage"],
                    "REQUIRES_BOUNDED_LIVE_PROOF",
                )
                self.assertIn(
                    "separately authorized",
                    self.plan_rows[gap_id]["external_or_live_boundary"],
                )

    def test_read_only_candidates_do_not_claim_resolution(self) -> None:
        read_only = {
            "common_subscription_route",
            "claude_account_auth",
            "claude_permissions",
            "antigravity_account_route",
            "antigravity_billing_route",
        }
        for gap_id in read_only:
            with self.subTest(gap_id=gap_id):
                row = self.plan_rows[gap_id]
                self.assertEqual(
                    row["evidence_stage"],
                    "READ_ONLY_EVIDENCE_CANDIDATE",
                )
                self.assertIn("read-only", row["safe_now_action"])
                self.assertEqual(
                    row["result_state_if_not_proven"],
                    "BLOCKED_UNKNOWN",
                )

    def test_static_preparation_rows_still_fail_closed(self) -> None:
        for gap_id in (
            "common_timeout",
            "common_min_permissions",
            "common_sensitive_fanout",
        ):
            with self.subTest(gap_id=gap_id):
                row = self.plan_rows[gap_id]
                self.assertEqual(
                    row["evidence_stage"],
                    "STATIC_PREPARATION_ONLY",
                )
                self.assertEqual(
                    row["result_state_if_not_proven"],
                    "BLOCKED_UNKNOWN",
                )
                self.assertNotIn("resolved", row["safe_now_action"].lower())

    def test_every_row_has_nonempty_action_boundary_evidence_and_fail_state(self) -> None:
        allowed_stages = {
            "STATIC_PREPARATION_ONLY",
            "READ_ONLY_EVIDENCE_CANDIDATE",
            "REQUIRES_BOUNDED_LIVE_PROOF",
            "HUMAN_ARCHITECTURE_DECISION",
            "FINAL_HUMAN_APPROVAL",
            "DEFERRED_NOT_SELECTED",
        }
        forbidden_exact_results = {
            "READY",
            "LIVE",
            "AUTHORIZED",
            "VERIFIED",
            "PASS",
            "RESOLVED",
        }

        for gap_id, row in self.plan_rows.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(row["evidence_stage"], allowed_stages)
                self.assertTrue(row["safe_now_action"])
                self.assertTrue(row["external_or_live_boundary"])
                self.assertTrue(row["completion_evidence_required"])
                self.assertTrue(row["result_state_if_not_proven"])
                self.assertNotIn(
                    row["result_state_if_not_proven"],
                    forbidden_exact_results,
                )

    def test_provenance_rows_preserve_human_architecture_boundary(self) -> None:
        expected = {
            "provenance_keep_not_wired": (
                "KEEP_NOT_WIRED",
                "current safe default / no provenance advancement",
            ),
            "provenance_actions_readback": (
                "TRANSPORT_EVIDENCE_ONLY",
                "transport evidence only / insufficient as authenticator",
            ),
            "provenance_oidc": (
                "NOT_AUTHORIZED",
                "candidate / NOT_AUTHORIZED",
            ),
            "provenance_attestation": (
                "NOT_AUTHORIZED",
                "strong candidate / NOT_AUTHORIZED",
            ),
        }
        for gap_id, (result_state, required_phrase) in expected.items():
            with self.subTest(gap_id=gap_id):
                row = self.plan_rows[gap_id]
                self.assertEqual(
                    row["evidence_stage"],
                    "HUMAN_ARCHITECTURE_DECISION",
                )
                self.assertEqual(
                    row["result_state_if_not_proven"],
                    result_state,
                )
                self.assertIn(
                    required_phrase,
                    row["completion_evidence_required"],
                )

    def test_gemini_cli_is_deferred_and_never_automatic_fallback(self) -> None:
        row = self.plan_rows["gemini_cli"]
        self.assertEqual(row["evidence_stage"], "DEFERRED_NOT_SELECTED")
        self.assertEqual(row["result_state_if_not_proven"], "DEFERRED")
        self.assertIn(
            "automatic fallback to Gemini CLI",
            row["external_or_live_boundary"],
        )
        self.assertIn(
            "not the selected Google transport",
            row["completion_evidence_required"],
        )

    def test_first_live_turn_remains_final_explicit_human_approval(self) -> None:
        row = self.plan_rows["first_live_turn"]
        self.assertEqual(row["evidence_stage"], "FINAL_HUMAN_APPROVAL")
        self.assertEqual(
            row["result_state_if_not_proven"],
            "EXPLICIT_HUMAN_APPROVAL_REQUIRED",
        )
        self.assertIn(
            "explicit human approval",
            row["safe_now_action"],
        )
        self.assertIn(
            "first real provider/model turn",
            row["external_or_live_boundary"],
        )

    def test_plan_and_checkpoint_state_zero_evidence_acquisition(self) -> None:
        for phrase in (
            "zero evidence acquisition",
            "No provider/network/GitHub readback is performed by this batch",
            "No real live blocker is resolved",
            "Human provenance remains unverified",
            "Execution remains unauthorized",
        ):
            self.assertIn(phrase, self.plan)

        for phrase in (
            "strictly PREPARED/static evidence-acquisition-plan status only",
            "Zero evidence was acquired",
            "No real live blocker is resolved.",
            "No provenance is verified, no execution is authorized.",
        ):
            self.assertIn(phrase, self.checkpoint)

    def test_plan_contains_no_live_authorization_claim(self) -> None:
        for forbidden in (
            "real_live_ready=true",
            "execution_authorized=true",
            "provenance_verified=true",
            "dispatch_allowed=true",
            "LIVE_AUTHORIZED",
            "REAL_BLOCKERS_RESOLVED",
        ):
            self.assertNotIn(forbidden, self.plan)

    def test_safe_work_queue_contains_all_categories_without_ranking(self) -> None:
        for category in (
            "static preparation/audits",
            "separately authorized read-only evidence gathering",
            "bounded live proof requiring explicit authorization",
            "human architecture decision",
            "final human approval",
        ):
            self.assertIn(category, self.plan)
        self.assertNotIn("best option", self.plan.lower())
        self.assertNotIn("recommended winner", self.plan.lower())
