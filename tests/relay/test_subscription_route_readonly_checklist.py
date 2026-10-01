import os
import unittest


class TestSubscriptionRouteReadonlyChecklist(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        cls.root = os.path.abspath(root)
        doc_path = os.path.join(cls.root, "docs", "RELAY_SUBSCRIPTION_ROUTE_READONLY_CHECKLIST.md")
        checkpoint_path = os.path.join(cls.root, "docs", "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(doc_path):
            raise AssertionError("subscription route readonly checklist document is missing")
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
            "intended_route_state",
            "authenticated_identity_state",
            "credential_kind_state",
            "api_key_absence_state",
            "cloud_billing_absence_state",
            "overage_absence_state",
            "route_ownership_evidence_state",
            "readonly_inspection_state",
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
                    parsed[pid] = dict(zip(headers, parts))
        return parsed

    def test_parse_exact_provider_order_openai_anthropic_google(self) -> None:
        keys = list(self.rows.keys())
        self.assertEqual(len(keys), 3, "should have exactly 3 providers")
        self.assertEqual(keys[0], "openai")
        self.assertEqual(keys[1], "anthropic")
        self.assertEqual(keys[2], "google")

    def test_assert_current_rows_remain_conservative_and_common_blocker_is_blocked_unknown(self) -> None:
        for provider, row in self.rows.items():
            self.assertEqual(row["intended_route_state"], "STATIC_PREPARED")
            for field in [
                "authenticated_identity_state",
                "credential_kind_state",
                "api_key_absence_state",
                "cloud_billing_absence_state",
                "overage_absence_state",
                "route_ownership_evidence_state"
            ]:
                self.assertEqual(row[field], "EVIDENCE_REQUIRED", f"{provider} {field} should be EVIDENCE_REQUIRED")
            self.assertEqual(row["readonly_inspection_state"], "UNKNOWN")
            self.assertEqual(row["blocker_state"], "BLOCKED_UNKNOWN")

    def test_assert_configured_default_route_alone_is_insufficient(self) -> None:
        self.assertIn(
            "Checked-in config/profile/default/auth-kind values alone are insufficient to prove the real route actually used or billed.",
            self.doc
        )

    def test_assert_repository_absence_of_an_api_key_alone_is_insufficient(self) -> None:
        self.assertIn(
            "The absence of an API key in repository source alone is insufficient to prove no API-key environment/credential path exists at runtime.",
            self.doc
        )

    def test_assert_successful_login_account_label_alone_is_insufficient(self) -> None:
        self.assertIn(
            "A successful login/account label alone is insufficient to prove the intended subscription route is the route funding the turn.",
            self.doc
        )

    def test_assert_ambiguous_identity_fails_closed(self) -> None:
        self.assertIn(
            "authenticated identity is unavailable or ambiguous;",
            self.doc
        )

    def test_assert_unknown_credential_kind_fails_closed(self) -> None:
        self.assertIn(
            "credential kind is UNKNOWN;",
            self.doc
        )

    def test_assert_inability_to_prove_api_key_absence_fails_closed(self) -> None:
        self.assertIn(
            "API-key route absence cannot be proven;",
            self.doc
        )

    def test_assert_inability_to_prove_cloud_billing_overage_absence_fails_closed_where_applicable(self) -> None:
        self.assertIn(
            "Cloud Billing route absence cannot be proven where applicable;",
            self.doc
        )
        self.assertIn(
            "overage/extra-pay route absence cannot be proven where applicable;",
            self.doc
        )

    def test_assert_intended_vs_observed_route_conflict_fails_closed(self) -> None:
        self.assertIn(
            "intended route and observed route conflict;",
            self.doc
        )

    def test_assert_unproven_route_ownership_payment_responsibility_remains_blocked(self) -> None:
        self.assertIn(
            "route ownership/payment responsibility cannot be established read-only;",
            self.doc
        )

    def test_assert_unknown_untrusted_evidence_source_remains_blocked(self) -> None:
        self.assertIn(
            "evidence source is UNKNOWN/untrusted under then-approved provenance policy;",
            self.doc
        )

    def test_assert_evidence_is_provider_inspection_bound_and_cannot_cross_satisfy_another_provider(self) -> None:
        self.assertIn(
            "evidence cannot be bound to the exact provider/inspection;",
            self.doc
        )
        self.assertIn(
            "Evidence must be bounded to a specific inspection event and provider. Evidence from one provider cannot satisfy another.",
            self.doc
        )

    def test_assert_secrets_tokens_account_payment_raw_values_are_forbidden_from_future_evidence_records(self) -> None:
        self.assertIn(
            "evidence would require revealing/storing a secret;",
            self.doc
        )
        self.assertIn(
            "No secrets, tokens, or account numbers are included as required fields.",
            self.doc
        )
        self.assertIn(
            "No API keys, OAuth tokens, cookies, passwords, account numbers, payment instrument data, or full private profile dumps belong in evidence.",
            self.doc
        )

    def test_assert_all_conceptual_evidence_record_field_names_are_present(self) -> None:
        fields = [
            "provider_id",
            "inspection_correlation_id",
            "intended_route",
            "observed_authenticated_identity_class",
            "observed_credential_kind",
            "api_key_route_state",
            "cloud_billing_route_state",
            "overage_route_state",
            "route_ownership_evidence",
            "evidence_source",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state"
        ]
        for field in fields:
            self.assertIn(f"`{field}`", self.doc)

    def test_assert_zero_external_read_only_account_billing_evidence_acquired_and_common_subscription_route_unresolved_blocked_unknown(self) -> None:
        self.assertIn(
            "Zero external/read-only account or billing evidence is acquired by this batch.",
            self.doc
        )
        self.assertIn(
            "`common_subscription_route` remains unresolved/BLOCKED_UNKNOWN.",
            self.doc
        )

    def test_assert_checkpoint_contains_the_same_prepared_unresolved_boundary(self) -> None:
        self.assertIn(
            "This checkpoint is strictly PREPARED/static subscription-route-readonly-checklist status only.",
            self.checkpoint
        )
        self.assertIn(
            "Zero external/read-only account or billing evidence is acquired by this batch.",
            self.checkpoint
        )
        self.assertIn(
            "common_subscription_route remains unresolved/BLOCKED_UNKNOWN.",
            self.checkpoint
        )
        self.assertIn(
            "No real live blocker is resolved.",
            self.checkpoint
        )
