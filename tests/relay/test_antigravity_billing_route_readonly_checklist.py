import os
import unittest


class TestAntigravityBillingRouteReadonlyChecklist(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        cls.root = os.path.abspath(root)
        doc_path = os.path.join(cls.root, "docs", "RELAY_ANTIGRAVITY_BILLING_ROUTE_READONLY_CHECKLIST.md")
        checkpoint_path = os.path.join(cls.root, "docs", "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(doc_path):
            raise AssertionError("antigravity billing route readonly checklist document is missing")
        if not os.path.isfile(checkpoint_path):
            raise AssertionError("static checkpoint document is missing")
        with open(doc_path, "r", encoding="utf-8") as stream:
            cls.doc = stream.read()
        with open(checkpoint_path, "r", encoding="utf-8") as stream:
            cls.checkpoint = stream.read()
        cls.rows = cls._parse_table(cls.doc)

    @staticmethod
    def _parse_table(content: str) -> dict[str, dict[str, str]]:
        headers = [
            "provider_id",
            "gap_id",
            "static_api_key_guard_state",
            "static_cloud_billing_guard_state",
            "static_overage_guard_state",
            "static_adc_vertex_guard_state",
            "observed_api_key_route_state",
            "observed_cloud_billing_route_state",
            "observed_overage_route_state",
            "observed_payment_responsibility_state",
            "quota_billing_visibility_state",
            "readonly_inspection_state",
            "evidence_provenance_state",
            "blocker_state",
        ]
        in_table = False
        parsed: dict[str, dict[str, str]] = {}
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("| provider_id |"):
                in_table = True
                continue
            if in_table and line.startswith("| ---"):
                continue
            if in_table and not line:
                break
            if in_table and line.startswith("|"):
                parts = [p.strip() for p in line.strip("|").split("|")]
                if len(parts) >= len(headers):
                    pid = parts[0]
                    gap = parts[1]
                    parsed[f"{pid}:{gap}"] = dict(zip(headers, parts))
        return parsed

    def test_parse_exact_provider_and_gap_id(self) -> None:
        keys = list(self.rows.keys())
        self.assertEqual(len(keys), 1, "should have exactly 1 row")
        self.assertEqual(keys[0], "google:antigravity_billing_route")

    def test_assert_current_rows_remain_conservative_and_common_blocker_is_blocked_unknown(self) -> None:
        row = self.rows["google:antigravity_billing_route"]
        self.assertEqual(row["static_api_key_guard_state"], "STATIC_PREPARED")
        self.assertEqual(row["static_cloud_billing_guard_state"], "STATIC_PREPARED")
        self.assertEqual(row["static_overage_guard_state"], "STATIC_PREPARED")
        self.assertEqual(row["static_adc_vertex_guard_state"], "STATIC_PREPARED")
        for field in [
            "observed_api_key_route_state",
            "observed_cloud_billing_route_state",
            "observed_overage_route_state",
            "observed_payment_responsibility_state",
            "quota_billing_visibility_state"
        ]:
            self.assertEqual(row[field], "EVIDENCE_REQUIRED", f"{field} should be EVIDENCE_REQUIRED")
        self.assertEqual(row["readonly_inspection_state"], "UNKNOWN")
        self.assertEqual(row["evidence_provenance_state"], "UNKNOWN")
        self.assertEqual(row["blocker_state"], "BLOCKED_UNKNOWN")

    def test_assert_configured_default_route_and_static_checks_alone_are_insufficient(self) -> None:
        self.assertIn(
            "Checked-in config/defaults, successful preflight, binary/profile selection, successful login/account label, or repository absence of API-key/billing config are individually insufficient to prove the actual billing/payment route.",
            self.doc
        )
        self.assertIn(
            "static preflight guard `api_key_present=false`",
            self.doc
        )
        self.assertIn(
            "static preflight guard `cloud_billing_selected=false`",
            self.doc
        )
        self.assertIn(
            "static preflight guard `overages_enabled=false`",
            self.doc
        )
        self.assertIn(
            "static preflight guards for ADC/Vertex/gateway/external-cloud",
            self.doc
        )

    def test_assert_unknown_ambiguous_fields_fail_closed(self) -> None:
        fail_closed_triggers = [
            "API-key route absence",
            "Cloud Billing route absence",
            "overage/extra-pay route absence",
            "ADC route absence",
            "Vertex route absence",
            "payment responsibility/route ownership",
            "quota/billing visibility where needed for the decision",
            "provider/inspection binding",
            "evidence provenance"
        ]
        self.assertIn("Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:", self.doc)
        for trigger in fail_closed_triggers:
            self.assertIn(trigger, self.doc)

    def test_assert_alternate_routes_and_mismatched_payment_fail_proof(self) -> None:
        self.assertIn(
            "Any observed selected API-key, Cloud Billing, overage/extra-pay, ADC, Vertex, gateway, external-cloud, or mismatched payment route is a hard proof failure for the intended subscription-only path and must not be normalized to safe.",
            self.doc
        )

    def test_assert_insufficient_visibility_fails_closed(self) -> None:
        self.assertIn(
            "If the current product/runtime cannot expose enough read-only quota/billing evidence to prove route ownership/payment responsibility, explicitly remain BLOCKED_UNKNOWN rather than inferring from static config or account identity.",
            self.doc
        )

    def test_assert_evidence_is_provider_inspection_bound_and_cannot_cross_satisfy_another_provider(self) -> None:
        self.assertIn(
            "Evidence must be Google/Antigravity inspection-event bound. Evidence from OpenAI, Anthropic, another Google account, another product route, another cloud project/account, or another inspection cannot satisfy this gap.",
            self.doc
        )

    def test_assert_secrets_tokens_account_payment_raw_values_are_forbidden_from_future_evidence_records(self) -> None:
        self.assertIn(
            "If proof would require sending a model/provider turn, reading a raw secret/private billing identifier, changing login/auth/settings/permissions/billing, enabling API key/Cloud Billing/overages, or widening access, that proof method is outside this batch and forbidden.",
            self.doc
        )
        self.assertIn(
            "Evidence stores classifications/durable locators or hashes only. No raw secrets, API keys, OAuth tokens, cookies, passwords, account emails, account IDs, billing account IDs, cloud project IDs tied to billing, payment instruments, quota identifiers, invoices, transaction records, or full private profile dumps.",
            self.doc
        )

    def test_assert_all_conceptual_evidence_record_field_names_are_present(self) -> None:
        fields = [
            "provider_id",
            "gap_id",
            "inspection_correlation_id",
            "intended_billing_route",
            "observed_api_key_route_state",
            "observed_cloud_billing_route_state",
            "observed_overage_route_state",
            "observed_adc_route_state",
            "observed_vertex_route_state",
            "observed_payment_responsibility_class",
            "quota_billing_visibility_state",
            "evidence_source",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state"
        ]
        for field in fields:
            self.assertIn(f"`{field}`", self.doc)

    def test_assert_zero_external_read_only_billing_evidence_acquired_and_gap_unresolved(self) -> None:
        self.assertIn(
            "Zero external/read-only billing-route evidence is acquired by this batch.",
            self.doc
        )
        self.assertIn(
            "`antigravity_billing_route` remains unresolved/BLOCKED_UNKNOWN.",
            self.doc
        )

    def test_assert_account_route_is_explicitly_separate(self) -> None:
        self.assertIn(
            "`antigravity_account_route` is separate; even if account identity were later proven, it would not by itself prove billing ownership/payment route.",
            self.doc
        )

    def test_assert_checkpoint_contains_the_same_prepared_unresolved_boundary(self) -> None:
        self.assertIn(
            "This checkpoint is strictly PREPARED/static Antigravity billing-route checklist status only.",
            self.checkpoint
        )
        self.assertIn(
            "No live blocker becomes resolved.",
            self.checkpoint
        )
