"""Provider / billing route guard: unknown or paid routes stop provider execution, never safe local work."""
from __future__ import annotations

import unittest

from automation.command_bus.claude_jules_provider_route import (
    ALLOW, API_KEY_CONFIRMED, AUTH_BROKEN, HARD_STOP, LOCAL_STATIC, METERED_CONFIRMED, OVERAGE_CONFIRMED,
    PAID_OR_UNKNOWN_PROVIDER, READ_ONLY_LIVE, STOP_PROVIDER, SUBSCRIPTION_CONFIRMED, SUBSCRIPTION_MODEL_WORK,
    UNKNOWN_BILLING_ROUTE, RouteVerdict, build_route_declaration, classify_route, detect_route_drift, gate,
)

NOW = "2026-10-08T00:00:00+00:00"


def declaration(**overrides):
    fields = dict(provider="jules", auth_method="oauth_subscription", billing_route="subscription", auth_state="ok",
                  declared_by="user", evidence_refs=["docs/route.md"], declared_at="2026-10-07T00:00:00+00:00",
                  expires_at="2026-10-09T00:00:00+00:00")
    fields.update(overrides)
    return build_route_declaration(**fields)


class ClassifyRouteTests(unittest.TestCase):
    def test_subscription_declaration_is_confirmed(self):
        self.assertEqual(classify_route(declaration(), provider="jules", now=NOW).verdict, SUBSCRIPTION_CONFIRMED)

    def test_paid_routes_map_to_their_verdicts(self):
        for route, verdict in (("api_key", API_KEY_CONFIRMED), ("metered", METERED_CONFIRMED),
                               ("overage", OVERAGE_CONFIRMED), ("unknown", UNKNOWN_BILLING_ROUTE)):
            with self.subTest(route=route):
                self.assertEqual(classify_route(declaration(billing_route=route), provider="jules", now=NOW).verdict,
                                 verdict)

    def test_api_key_authentication_is_never_subscription(self):
        verdict = classify_route(declaration(auth_method="api_key"), provider="jules", now=NOW)
        self.assertEqual(verdict.verdict, API_KEY_CONFIRMED)

    def test_missing_expired_future_or_foreign_declaration_is_unknown(self):
        cases = {
            "missing": (None, NOW),
            "expired": (declaration(), "2026-10-09T00:00:00+00:00"),
            "not yet valid": (declaration(), "2026-10-06T23:59:59+00:00"),
            "other provider": (declaration(provider="other"), NOW),
        }
        for name, (decl, now) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(classify_route(decl, provider="jules", now=now).verdict, UNKNOWN_BILLING_ROUTE)

    def test_tampered_or_malformed_declaration_is_unknown(self):
        tampered = dict(declaration(), billing_route="subscription", auth_method="api_key")
        broken_shape = dict(declaration())
        broken_shape.pop("evidence_refs")
        no_evidence = declaration(evidence_refs=[])
        bad_route = declaration(billing_route="free")
        naive_time = declaration(declared_at="2026-10-07T00:00:00")
        for name, decl in (("tampered", tampered), ("missing key", broken_shape), ("no evidence", no_evidence),
                           ("unrecognised route", bad_route), ("naive timestamp", naive_time), ("not a dict", "x")):
            with self.subTest(name=name):
                self.assertEqual(classify_route(decl, provider="jules", now=NOW).verdict, UNKNOWN_BILLING_ROUTE)

    def test_broken_auth_on_subscription_is_auth_broken_but_paid_stays_paid(self):
        self.assertEqual(classify_route(declaration(auth_state="broken"), provider="jules", now=NOW).verdict,
                         AUTH_BROKEN)
        self.assertEqual(classify_route(declaration(auth_state="broken", billing_route="metered"),
                                        provider="jules", now=NOW).verdict, METERED_CONFIRMED)


class GateTests(unittest.TestCase):
    def route(self, verdict):
        return RouteVerdict(verdict, "test", "jules")

    def test_subscription_allows_provider_work(self):
        for op in (READ_ONLY_LIVE, SUBSCRIPTION_MODEL_WORK):
            with self.subTest(op=op):
                decision = gate(op, self.route(SUBSCRIPTION_CONFIRMED))
                self.assertEqual(decision.decision, ALLOW)
                self.assertTrue(decision.provider_execution_allowed)

    def test_every_paid_or_unknown_route_is_a_hard_stop_for_provider_work(self):
        for verdict in (API_KEY_CONFIRMED, METERED_CONFIRMED, OVERAGE_CONFIRMED, UNKNOWN_BILLING_ROUTE):
            for op in (READ_ONLY_LIVE, SUBSCRIPTION_MODEL_WORK):
                with self.subTest(verdict=verdict, op=op):
                    decision = gate(op, self.route(verdict))
                    self.assertEqual(decision.decision, HARD_STOP)
                    self.assertFalse(decision.provider_execution_allowed)
                    self.assertTrue(decision.requires_human)
                    self.assertTrue(decision.local_safe_work_allowed)

    def test_auth_broken_pauses_provider_only(self):
        decision = gate(SUBSCRIPTION_MODEL_WORK, self.route(AUTH_BROKEN))
        self.assertEqual(decision.decision, STOP_PROVIDER)
        self.assertFalse(decision.provider_execution_allowed)
        self.assertTrue(decision.local_safe_work_allowed)
        self.assertFalse(decision.requires_human)

    def test_local_static_work_continues_under_any_route(self):
        for verdict in (SUBSCRIPTION_CONFIRMED, API_KEY_CONFIRMED, METERED_CONFIRMED, OVERAGE_CONFIRMED,
                        UNKNOWN_BILLING_ROUTE, AUTH_BROKEN, "GARBAGE"):
            with self.subTest(verdict=verdict):
                decision = gate(LOCAL_STATIC, self.route(verdict))
                self.assertEqual(decision.decision, ALLOW)
                self.assertFalse(decision.provider_execution_allowed)
                self.assertTrue(decision.local_safe_work_allowed)

    def test_paid_provider_operation_is_never_automatic_even_on_subscription(self):
        decision = gate(PAID_OR_UNKNOWN_PROVIDER, self.route(SUBSCRIPTION_CONFIRMED))
        self.assertEqual(decision.decision, HARD_STOP)
        self.assertFalse(decision.provider_execution_allowed)

    def test_unknown_operation_or_verdict_fails_closed(self):
        self.assertEqual(gate("SOMETHING_NEW", self.route(SUBSCRIPTION_CONFIRMED)).decision, HARD_STOP)
        self.assertEqual(gate(READ_ONLY_LIVE, self.route("GARBAGE")).decision, HARD_STOP)

    def test_route_drift_is_detected(self):
        self.assertFalse(detect_route_drift(self.route(SUBSCRIPTION_CONFIRMED), self.route(SUBSCRIPTION_CONFIRMED)))
        self.assertTrue(detect_route_drift(self.route(SUBSCRIPTION_CONFIRMED), self.route(API_KEY_CONFIRMED)))
        self.assertTrue(detect_route_drift(self.route(SUBSCRIPTION_CONFIRMED),
                                           RouteVerdict(SUBSCRIPTION_CONFIRMED, "x", "other")))

    def test_current_jules_api_key_route_is_a_billing_boundary(self):
        # The repository's Jules route authenticates with X-Goog-Api-Key; its billing is recorded as
        # PROBABLY_SAFE_BUT_NOT_EXPLICITLY_GUARANTEED (docs/JULES_API_ROUTE_DECISION_20260925.md).
        current = classify_route(declaration(auth_method="api_key", billing_route="unknown"), provider="jules", now=NOW)
        self.assertEqual(gate(READ_ONLY_LIVE, current).decision, HARD_STOP)


if __name__ == "__main__":
    unittest.main()
