import os
import unittest


class TestAntigravityAccountRouteReadonlyChecklist(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        cls.root = os.path.abspath(root)
        doc_path = os.path.join(cls.root, "docs", "RELAY_ANTIGRAVITY_ACCOUNT_ROUTE_READONLY_CHECKLIST.md")
        checkpoint_path = os.path.join(cls.root, "docs", "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(doc_path):
            raise AssertionError("antigravity account route readonly checklist document is missing")
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
            "static_expected_auth_kind_state",
            "static_alternate_route_guard_state",
            "observed_authenticated_identity_state",
            "observed_credential_kind_state",
            "observed_product_route_state",
            "api_key_route_absence_state",
            "adc_route_absence_state",
            "vertex_route_absence_state",
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
                    # using gap_id as unique key to prevent any possible provider overlap in a single row logic, though pid is google
                    gap = parts[1]
                    parsed[f"{pid}:{gap}"] = dict(zip(headers, parts))
        return parsed

    def test_parse_exact_provider_and_gap_id(self) -> None:
        keys = list(self.rows.keys())
        self.assertEqual(len(keys), 1, "should have exactly 1 row")
        self.assertEqual(keys[0], "google:antigravity_account_route")

    def test_assert_current_rows_remain_conservative_and_common_blocker_is_blocked_unknown(self) -> None:
        row = self.rows["google:antigravity_account_route"]
        self.assertEqual(row["static_expected_auth_kind_state"], "STATIC_PREPARED")
        self.assertEqual(row["static_alternate_route_guard_state"], "STATIC_PREPARED")
        for field in [
            "observed_authenticated_identity_state",
            "observed_credential_kind_state",
            "observed_product_route_state",
            "api_key_route_absence_state",
            "adc_route_absence_state",
            "vertex_route_absence_state"
        ]:
            self.assertEqual(row[field], "EVIDENCE_REQUIRED", f"{field} should be EVIDENCE_REQUIRED")
        self.assertEqual(row["readonly_inspection_state"], "UNKNOWN")
        self.assertEqual(row["evidence_provenance_state"], "UNKNOWN")
        self.assertEqual(row["blocker_state"], "BLOCKED_UNKNOWN")

    def test_assert_configured_default_route_and_static_checks_alone_are_insufficient(self) -> None:
        self.assertIn(
            "Checked-in config/defaults, successful preflight, binary/profile selection, successful login label, or repository absence of API-key material are individually insufficient to prove the actual authenticated account route.",
            self.doc
        )
        self.assertIn(
            "ProviderPolicy required_auth_kind=account",
            self.doc
        )
        self.assertIn(
            "preflight static rejection of API-key/gateway/external-cloud/ADC/Vertex alternate routes",
            self.doc
        )

    def test_assert_unknown_ambiguous_fields_fail_closed(self) -> None:
        fail_closed_triggers = [
            "observed auth kind",
            "authenticated identity class",
            "credential kind",
            "product/account route",
            "API-key route absence",
            "ADC route absence",
            "Vertex route absence",
            "provider/inspection binding",
            "evidence provenance"
        ]
        self.assertIn("Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:", self.doc)
        for trigger in fail_closed_triggers:
            self.assertIn(trigger, self.doc)

    def test_assert_alternate_routes_and_mismatched_account_fail_proof(self) -> None:
        self.assertIn(
            "Any observed API-key, ADC, Vertex, gateway, external-cloud, or mismatched product/account route is a hard proof failure for this gap and must not be normalized to the intended account route.",
            self.doc
        )

    def test_assert_evidence_is_provider_inspection_bound_and_cannot_cross_satisfy_another_provider(self) -> None:
        self.assertIn(
            "Evidence must be bounded to a specific inspection event and provider. Evidence from OpenAI, Anthropic, another Google account, another product route, or another inspection cannot satisfy this gap.",
            self.doc
        )

    def test_assert_secrets_tokens_account_payment_raw_values_are_forbidden_from_future_evidence_records(self) -> None:
        self.assertIn(
            "If proof would require sending a model/provider turn, reading a raw secret/private account identifier, changing login/auth/settings/permissions/billing, enabling an API key/Cloud Billing/overage route, or widening access, that proof method is outside this batch and forbidden.",
            self.doc
        )
        self.assertIn(
            "No secrets, tokens, or account numbers are included as required fields.",
            self.doc
        )
        self.assertIn(
            "Evidence stores classifications/durable locators or hashes only. No raw secrets, API keys, OAuth tokens, cookies, passwords, account emails, account IDs, full private profile dumps, payment identifiers, or billing data.",
            self.doc
        )

    def test_assert_all_conceptual_evidence_record_field_names_are_present(self) -> None:
        fields = [
            "provider_id",
            "gap_id",
            "inspection_correlation_id",
            "intended_account_route",
            "observed_auth_kind",
            "observed_identity_class",
            "observed_credential_kind",
            "observed_product_route",
            "api_key_route_state",
            "adc_route_state",
            "vertex_route_state",
            "evidence_source",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state"
        ]
        for field in fields:
            self.assertIn(f"`{field}`", self.doc)

    def test_assert_zero_external_read_only_account_billing_evidence_acquired_and_gap_unresolved(self) -> None:
        self.assertIn(
            "Zero external/read-only account-route evidence is acquired by this batch.",
            self.doc
        )
        self.assertIn(
            "`antigravity_account_route` remains unresolved/BLOCKED_UNKNOWN.",
            self.doc
        )

    def test_assert_billing_route_gap_is_explicitly_separate_and_unresolved(self) -> None:
        self.assertIn(
            "`antigravity_billing_route` is separate and remains unresolved/BLOCKED_UNKNOWN; this checklist must not claim billing ownership/payment route is proven.",
            self.doc
        )

    def test_assert_checkpoint_contains_the_same_prepared_unresolved_boundary(self) -> None:
        self.assertIn(
            "This checkpoint is strictly PREPARED/static Antigravity account-route checklist status only.",
            self.checkpoint
        )
        self.assertIn(
            "No live blocker becomes resolved.",
            self.checkpoint
        )
