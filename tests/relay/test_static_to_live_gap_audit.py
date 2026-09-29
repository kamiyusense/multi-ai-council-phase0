import os
import unittest


class TestStaticToLiveGapAudit(unittest.TestCase):
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
            os.path.join(base, "RELAY_LIVE_BLOCKERS.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.blockers = stream.read()
        with open(
            os.path.join(
                base,
                "RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md",
            ),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.trust = stream.read()
        with open(
            os.path.join(base, "RELAY_STATIC_CHECKPOINT.md"),
            "r",
            encoding="utf-8",
        ) as stream:
            cls.checkpoint = stream.read()

        cls.rows = {}
        for line in cls.audit.splitlines():
            if not line.startswith("| "):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells or cells[0] in {"gap_id", "---"}:
                continue
            cls.rows[cells[0]] = {
                "scope": cells[1],
                "class": cells[2],
                "current_state": cells[3],
                "canonical_source": cells[4],
                "missing": cells[5],
                "forbidden": cells[6],
            }

    def test_exact_gap_id_set(self) -> None:
        expected = {
            "common_timeout",
            "common_min_permissions",
            "common_model_verification",
            "common_subscription_route",
            "common_abort_readback",
            "common_sensitive_fanout",
            "common_confinement",
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
            "gemini_cli",
            "provenance_keep_not_wired",
            "provenance_actions_readback",
            "provenance_oidc",
            "provenance_attestation",
            "first_live_turn",
        }
        self.assertEqual(set(self.rows), expected)

    def test_common_blockers_match_canonical_source_exactly(self) -> None:
        mapping = {
            "common_timeout": "exact finite timeout values",
            "common_min_permissions": "exact minimum permission profile",
            "common_model_verification": "executed-model verification mechanism",
            "common_subscription_route": (
                "proof that the intended subscription/auth route is the route "
                "actually paying for the turn"
            ),
            "common_abort_readback": "provider-specific abort/readback evidence",
            "common_sensitive_fanout": (
                "final secret/PII/private-code fan-out patterns"
            ),
            "common_confinement": (
                "live filesystem/network confinement feasibility"
            ),
            "common_hidden_retry": (
                "end-to-end proof that no hidden retry/fallback violates "
                "Phase 0 policy"
            ),
        }
        for gap_id, phrase in mapping.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(phrase, self.blockers)
                self.assertEqual(self.rows[gap_id]["missing"], phrase)
                self.assertEqual(
                    self.rows[gap_id]["canonical_source"],
                    "RELAY_LIVE_BLOCKERS.md",
                )
                self.assertEqual(
                    self.rows[gap_id]["class"],
                    "EVIDENCE_REQUIRED",
                )

    def test_openai_blockers_match_canonical_source_exactly(self) -> None:
        mapping = {
            "openai_request_retry": (
                "built-in ChatGPT-auth provider can be configured/verified "
                "with zero automatic request retry"
            ),
            "openai_stream_replay": (
                "zero stream/reconnect replay that can cause another model request"
            ),
            "openai_auth_replay": (
                "no auth recovery path silently replays a turn"
            ),
            "openai_single_request_evidence": (
                "evidence can distinguish a single model request from a replay"
            ),
        }
        for gap_id, phrase in mapping.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(phrase, self.blockers)
                self.assertEqual(self.rows[gap_id]["missing"], phrase)
                self.assertEqual(self.rows[gap_id]["scope"], "OpenAI/Codex")
                self.assertEqual(
                    self.rows[gap_id]["current_state"],
                    "BLOCKED_UNKNOWN",
                )

    def test_claude_blockers_match_canonical_source_exactly(self) -> None:
        mapping = {
            "claude_retry": (
                "provider/SDK automatic model-call retry can be disabled "
                "or deterministically prevented"
            ),
            "claude_fallback": "model fallback can be disabled",
            "claude_recovery": (
                "no restart/recovery path creates another model turn "
                "without a new human/Phase0 dispatch"
            ),
            "claude_account_auth": "subscription auth status remains `account`",
            "claude_permissions": (
                "`allowDangerouslySkipPermissions=false` is effective on new/load"
            ),
            "claude_model_verification": (
                "executed model is independently verified"
            ),
        }
        for gap_id, phrase in mapping.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(phrase, self.blockers)
                self.assertEqual(self.rows[gap_id]["missing"], phrase)
                self.assertEqual(self.rows[gap_id]["scope"], "Claude")
                self.assertEqual(
                    self.rows[gap_id]["current_state"],
                    "BLOCKED_UNKNOWN",
                )

    def test_antigravity_blockers_match_canonical_source_exactly(self) -> None:
        mapping = {
            "antigravity_account_route": (
                "the authenticated identity is the intended Google AI "
                "Pro/Antigravity account route"
            ),
            "antigravity_billing_route": (
                "API-key/Cloud Billing/overage paths are not selected"
            ),
            "antigravity_retry_fallback": (
                "internal retry/fallback behavior satisfies Phase0 "
                "auto-retry=0/no-fallback"
            ),
            "antigravity_model_verification": "executed model is verifiable",
            "antigravity_cancel": (
                "active-turn cancellation/process teardown can be proven "
                "without automatic restart"
            ),
            "antigravity_quota_billing": (
                "quota/billing UNKNOWN can be detected and stops before send"
            ),
        }
        for gap_id, phrase in mapping.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(phrase, self.blockers)
                self.assertEqual(self.rows[gap_id]["missing"], phrase)
                self.assertEqual(
                    self.rows[gap_id]["scope"],
                    "Google Antigravity",
                )
                self.assertEqual(
                    self.rows[gap_id]["current_state"],
                    "BLOCKED_UNKNOWN",
                )

    def test_gemini_cli_remains_deferred_and_not_fallback(self) -> None:
        row = self.rows["gemini_cli"]
        self.assertIn(
            "Gemini CLI is not the selected Google transport for the current design",
            self.blockers,
        )
        self.assertIn("DEFERRED, not an automatic fallback", self.blockers)
        self.assertEqual(row["class"], "DEFERRED_NOT_SELECTED")
        self.assertEqual(row["current_state"], "DEFERRED")
        self.assertEqual(row["forbidden"], "automatic fallback to Gemini CLI")

    def test_provenance_rows_match_decision_support(self) -> None:
        expectations = {
            "provenance_keep_not_wired": (
                "KEEP_NOT_WIRED",
                "KEEP_NOT_WIRED = current safe default / no provenance advancement",
            ),
            "provenance_actions_readback": (
                "TRANSPORT_EVIDENCE_ONLY",
                "GITHUB_ACTIONS_READBACK_ONLY = transport evidence only / insufficient as an independent authenticator",
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
        for gap_id, (state, phrase) in expectations.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(phrase, self.trust)
                row = self.rows[gap_id]
                self.assertEqual(row["class"], "HUMAN_DECISION_REQUIRED")
                self.assertEqual(row["current_state"], state)
                self.assertEqual(row["missing"], phrase)

    def test_final_live_turn_is_separate_explicit_human_boundary(self) -> None:
        row = self.rows["first_live_turn"]
        self.assertIn(
            "the first real provider/model turn remains a separate explicit-user-approval boundary",
            self.blockers,
        )
        self.assertEqual(row["class"], "FINAL_HUMAN_APPROVAL")
        self.assertEqual(
            row["current_state"],
            "EXPLICIT_HUMAN_APPROVAL_REQUIRED",
        )
        self.assertEqual(
            row["forbidden"],
            "first real provider/model turn",
        )

    def test_every_row_has_expected_source_and_forbidden_action(self) -> None:
        for gap_id, row in self.rows.items():
            with self.subTest(gap_id=gap_id):
                self.assertIn(
                    row["canonical_source"],
                    {
                        "RELAY_LIVE_BLOCKERS.md",
                        "RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md",
                    },
                )
                self.assertTrue(row["missing"])
                self.assertTrue(row["forbidden"])
                self.assertIn(
                    row["class"],
                    {
                        "EVIDENCE_REQUIRED",
                        "HUMAN_DECISION_REQUIRED",
                        "FINAL_HUMAN_APPROVAL",
                        "DEFERRED_NOT_SELECTED",
                    },
                )

    def test_terminal_separation_is_explicit(self) -> None:
        required = (
            "STATIC/PREPARED complete",
            "!= real blocker resolved",
            "!= human provenance verified",
            "!= execution authorized",
            "!= first live provider turn approved",
        )
        for phrase in required:
            self.assertIn(phrase, self.audit)

    def test_checked_in_snapshot_not_fresh_external_verification(self) -> None:
        self.assertIn(
            "current checked-in canonical evidence only",
            self.audit,
        )
        self.assertIn(
            "not fresh external provider verification",
            self.audit,
        )
        self.assertIn(
            "resolves zero real live blockers",
            self.audit,
        )

    def test_no_dangerous_resolved_or_authorized_claims(self) -> None:
        for forbidden in (
            "real_live_ready=true",
            "execution_authorized=true",
            "provenance_verified=true",
            "dispatch_allowed=true",
            "LIVE_AUTHORIZED",
            "REAL_BLOCKERS_RESOLVED",
        ):
            self.assertNotIn(forbidden, self.audit)

        self.assertNotIn("| RESOLVED |", self.audit)
        self.assertNotIn("| VERIFIED |", self.audit)
        self.assertNotIn("| PASS |", self.audit)

    def test_next_safe_work_preserves_human_boundaries(self) -> None:
        for phrase in (
            "static maintenance and regression audits may continue",
            "read-only evidence gathering may continue when separately authorized and non-live",
            "permission/auth/trust-source changes require explicit human architecture authorization",
            "first real provider/model turn requires separate explicit human approval",
        ):
            self.assertIn(phrase, self.audit)

    def test_checkpoint_is_prepared_static_only(self) -> None:
        for phrase in (
            "This checkpoint is strictly PREPARED/static gap-audit status only.",
            "No real live blocker is resolved.",
            "First live provider turn remains unauthorized.",
        ):
            self.assertIn(phrase, self.checkpoint)
