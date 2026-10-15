"""Provider / billing route guard: auth and billing judged separately; only provider execution is stopped."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import unittest

from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_provider_route import (
    ACCOUNT_OAUTH, ACCOUNT_OAUTH_CONFIRMED, ALLOW, AUTH_BROKEN, BILLING_UNKNOWN, HARD_STOP, LOCAL_STATIC,
    METERED_CONFIRMED, OVERAGE_CONFIRMED, PAID_OR_UNKNOWN_PROVIDER, READ_ONLY_LIVE, REST_API_KEY, STOP_PROVIDER,
    SUBSCRIPTION_CONFIRMED, SUBSCRIPTION_MODEL_WORK, UNKNOWN_ROUTE, RouteVerdict, build_route_declaration,
    classify_route, detect_route_drift, gate, route_resolver,
)
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    CARRIER, DATA, LOOP, NOW, FakeFacts, FakeGitHub, FakeJules, owner_event, policy, roadmap, seed_owner, task_spec,
)

AT = "2026-10-08T00:00:00+00:00"
COMMANDS = "automation/command_bus/jules_api_requests/"
BUDGET = "automation/command_bus/evidence/claude-auto-live-budget/"


def declaration(**overrides):
    fields = dict(provider="jules", transport="jules-tools-cli", auth_method="account_oauth",
                  billing_route="subscription", auth_state="ok", declared_by="user", evidence_refs=["docs/route.md"],
                  declared_at="2026-10-01T00:00:00+00:00", expires_at="2026-10-31T00:00:00+00:00")
    fields.update(overrides)
    return build_route_declaration(**fields)


def classify(decl, *, now=AT, transport="jules-tools-cli"):
    return classify_route(decl, provider="jules", transport=transport, now=now)


class ClassifyRouteTests(unittest.TestCase):
    def test_account_login_with_subscription_evidence(self):
        v = classify(declaration())
        self.assertEqual((v.verdict, v.auth_class, v.billing_class),
                         (ACCOUNT_OAUTH_CONFIRMED, ACCOUNT_OAUTH, SUBSCRIPTION_CONFIRMED))

    def test_account_login_does_not_imply_subscription_billing(self):
        v = classify(declaration(billing_route="unknown"))
        self.assertEqual((v.verdict, v.billing_class), (ACCOUNT_OAUTH_CONFIRMED, BILLING_UNKNOWN))

    def test_api_key_is_its_own_auth_class_and_not_assumed_metered(self):
        v = classify(declaration(auth_method="api_key", billing_route="unknown"))
        self.assertEqual((v.verdict, v.auth_class, v.billing_class), (REST_API_KEY, REST_API_KEY, BILLING_UNKNOWN))

    def test_owner_time_boxed_api_key_exception_is_narrow(self):
        carrier = dict(transport="carrier-rest-api-key", auth_method="api_key", declared_by="owner",
                       declared_at="2026-10-15T00:00:00+00:00", expires_at="2026-10-15T04:00:00+00:00")
        now = "2026-10-15T01:00:00+00:00"
        ok = classify(declaration(**carrier), now=now, transport="carrier-rest-api-key")
        self.assertEqual((ok.verdict, ok.billing_class, ok.owner_time_boxed), (REST_API_KEY, SUBSCRIPTION_CONFIRMED, True))
        too_long = dict(carrier, expires_at="2026-10-15T04:00:01+00:00")
        for name, changes in {"over four hours": too_long, "not the owner": dict(carrier, declared_by="user"),
                              "billing unknown": dict(carrier, billing_route="unknown"),
                              "auth broken": dict(carrier, auth_state="broken")}.items():
            with self.subTest(name):
                v = classify(declaration(**changes), now=now, transport="carrier-rest-api-key")
                self.assertFalse(v.owner_time_boxed)
        other = classify(declaration(**dict(carrier, transport="jules-tools-cli")), now=now, transport="jules-tools-cli")
        self.assertFalse(other.owner_time_boxed)
        expired = classify(declaration(**carrier), now="2026-10-15T04:00:00+00:00", transport="carrier-rest-api-key")
        self.assertEqual(expired.verdict, UNKNOWN_ROUTE)

    def test_confirmed_paid_billing_wins_over_auth(self):
        for route, verdict in (("metered", METERED_CONFIRMED), ("overage", OVERAGE_CONFIRMED)):
            for auth in ("account_oauth", "api_key"):
                with self.subTest(route=route, auth=auth):
                    self.assertEqual(classify(declaration(billing_route=route, auth_method=auth)).verdict, verdict)

    def test_broken_login_is_auth_broken(self):
        self.assertEqual(classify(declaration(auth_state="broken")).verdict, AUTH_BROKEN)

    def test_unknown_auth_method_is_unknown_route(self):
        self.assertEqual(classify(declaration(auth_method="unknown")).verdict, UNKNOWN_ROUTE)

    def test_missing_expired_future_or_foreign_declaration_is_unknown(self):
        cases = {
            "missing": (None, AT, "jules-tools-cli"),
            "expired": (declaration(), "2026-10-31T00:00:00+00:00", "jules-tools-cli"),
            "not yet valid": (declaration(), "2026-09-30T23:59:59+00:00", "jules-tools-cli"),
            "other provider": (declaration(provider="other"), AT, "jules-tools-cli"),
            "other transport": (declaration(), AT, "carrier-rest-api-key"),
        }
        for name, (decl, now, transport) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(classify(decl, now=now, transport=transport).verdict, UNKNOWN_ROUTE)

    def test_tampered_or_malformed_declaration_is_unknown(self):
        tampered = dict(declaration(auth_method="api_key"), auth_method="account_oauth")
        missing = dict(declaration())
        missing.pop("transport")
        for name, decl in (("tampered", tampered), ("missing key", missing),
                           ("no evidence", declaration(evidence_refs=[])),
                           ("unrecognised billing", declaration(billing_route="free")),
                           ("naive timestamp", declaration(declared_at="2026-10-01T00:00:00")),
                           ("not a dict", "x")):
            with self.subTest(name=name):
                self.assertEqual(classify(decl).verdict, UNKNOWN_ROUTE)

    def test_route_drift_is_detected(self):
        base = classify(declaration())
        self.assertFalse(detect_route_drift(base, classify(declaration())))
        self.assertTrue(detect_route_drift(base, classify(declaration(billing_route="unknown"))))
        self.assertTrue(detect_route_drift(base, classify(declaration(auth_method="api_key"))))


class GateTests(unittest.TestCase):
    def route(self, verdict, billing=BILLING_UNKNOWN):
        return RouteVerdict(verdict, "test", "jules", "t", billing_class=billing)

    def test_account_route_reads_existing_sessions_without_billing_proof(self):
        decision = gate(READ_ONLY_LIVE, self.route(ACCOUNT_OAUTH_CONFIRMED))
        self.assertEqual(decision.decision, ALLOW)
        self.assertTrue(decision.provider_execution_allowed)

    def test_account_route_needs_subscription_evidence_for_new_model_work(self):
        self.assertEqual(gate(SUBSCRIPTION_MODEL_WORK, self.route(ACCOUNT_OAUTH_CONFIRMED)).decision, STOP_PROVIDER)
        self.assertEqual(gate(SUBSCRIPTION_MODEL_WORK,
                              self.route(ACCOUNT_OAUTH_CONFIRMED, SUBSCRIPTION_CONFIRMED)).decision, ALLOW)

    def test_rest_api_key_metered_and_overage_are_hard_stops(self):
        for verdict in (REST_API_KEY, METERED_CONFIRMED, OVERAGE_CONFIRMED):
            for op in (READ_ONLY_LIVE, SUBSCRIPTION_MODEL_WORK):
                with self.subTest(verdict=verdict, op=op):
                    decision = gate(op, self.route(verdict, SUBSCRIPTION_CONFIRMED))
                    self.assertEqual(decision.decision, HARD_STOP)
                    self.assertFalse(decision.provider_execution_allowed)
                    self.assertTrue(decision.local_safe_work_allowed)
                    self.assertTrue(decision.requires_human)

    def test_owner_time_boxed_api_key_allows_only_new_model_work(self):
        route = RouteVerdict(REST_API_KEY, "r", "jules", "carrier-rest-api-key", REST_API_KEY, SUBSCRIPTION_CONFIRMED, True)
        allowed = gate(SUBSCRIPTION_MODEL_WORK, route)
        self.assertEqual((allowed.decision, allowed.provider_execution_allowed, allowed.requires_human), (ALLOW, True, False))
        self.assertEqual(gate(READ_ONLY_LIVE, route).decision, HARD_STOP)
        self.assertEqual(gate(PAID_OR_UNKNOWN_PROVIDER, route).decision, HARD_STOP)
        no_billing = RouteVerdict(REST_API_KEY, "r", "jules", "carrier-rest-api-key", REST_API_KEY, BILLING_UNKNOWN, True)
        self.assertEqual(gate(SUBSCRIPTION_MODEL_WORK, no_billing).decision, HARD_STOP)

    def test_auth_broken_and_unknown_route_pause_provider_only(self):
        for verdict in (AUTH_BROKEN, UNKNOWN_ROUTE):
            with self.subTest(verdict=verdict):
                decision = gate(READ_ONLY_LIVE, self.route(verdict))
                self.assertEqual(decision.decision, STOP_PROVIDER)
                self.assertFalse(decision.provider_execution_allowed)
                self.assertTrue(decision.local_safe_work_allowed)

    def test_local_static_work_continues_under_any_route(self):
        for verdict in (*(ACCOUNT_OAUTH_CONFIRMED, REST_API_KEY, METERED_CONFIRMED, OVERAGE_CONFIRMED, AUTH_BROKEN,
                          UNKNOWN_ROUTE), "GARBAGE"):
            with self.subTest(verdict=verdict):
                decision = gate(LOCAL_STATIC, self.route(verdict))
                self.assertEqual(decision.decision, ALLOW)
                self.assertFalse(decision.provider_execution_allowed)
                self.assertTrue(decision.local_safe_work_allowed)

    def test_paid_provider_operation_is_never_automatic(self):
        self.assertEqual(gate(PAID_OR_UNKNOWN_PROVIDER, self.route(ACCOUNT_OAUTH_CONFIRMED,
                                                                   SUBSCRIPTION_CONFIRMED)).decision, HARD_STOP)

    def test_unknown_operation_or_verdict_fails_closed(self):
        self.assertEqual(gate("SOMETHING_NEW", self.route(ACCOUNT_OAUTH_CONFIRMED)).decision, HARD_STOP)
        self.assertEqual(gate(READ_ONLY_LIVE, self.route("GARBAGE")).decision, HARD_STOP)

    def test_current_rest_dispatch_route_is_a_billing_boundary(self):
        # User decision D1 (2026-10-08): the JULES_API_KEY REST route is not approved.
        current = classify(declaration(transport="carrier-rest-api-key", auth_method="api_key",
                                       billing_route="unknown"), transport="carrier-rest-api-key")
        for op in (READ_ONLY_LIVE, SUBSCRIPTION_MODEL_WORK):
            self.assertEqual(gate(op, current).decision, HARD_STOP)


class DispatchWiringTests(unittest.TestCase):
    """The gate sits in the real dispatch path: a blocked route writes nothing irreversible."""

    def controller(self, github, facts, route):
        return ClaudeJulesAutoLoop(
            client=github, refs=github, policy=policy(), owner_reader=LoopOwnerGitHubBackend(github, branch=DATA),
            roadmap=roadmap(task_spec("alpha-helper")), facts=facts, origin_loop_id=LOOP, lane_id="J-BLUE",
            provider_route=route)

    def world(self):
        github = FakeGitHub()
        jules = FakeJules(github)
        seed_owner(github, owner_event())
        return github, FakeFacts(github, jules)

    def test_unknown_route_stops_dispatch_before_any_carrier_or_budget_write(self):
        github, facts = self.world()
        result = self.controller(github, facts, route_resolver(None, provider="jules",
                                                               transport="carrier-rest-api-key")).step(now=NOW)
        self.assertEqual(result.status, "PREPARED_NOT_AUTHORIZED", result.reason)
        self.assertIn("provider route", result.reason)
        self.assertEqual(github.list(COMMANDS, CARRIER), [])
        self.assertEqual(github.list(BUDGET, DATA), [])

    def test_rest_api_key_route_stops_dispatch(self):
        github, facts = self.world()
        decl = declaration(transport="carrier-rest-api-key", auth_method="api_key", billing_route="unknown",
                           declared_at="2026-09-01T00:00:00+00:00", expires_at="2026-12-01T00:00:00+00:00")
        result = self.controller(github, facts, route_resolver(decl, provider="jules",
                                                               transport="carrier-rest-api-key")).step(now=NOW)
        self.assertEqual(result.status, "PREPARED_NOT_AUTHORIZED")
        self.assertIn("HARD_STOP", result.reason)
        self.assertEqual(github.list(COMMANDS, CARRIER), [])

    def test_confirmed_subscription_route_dispatches_normally(self):
        github, facts = self.world()
        decl = declaration(transport="t", declared_at="2026-09-01T00:00:00+00:00",
                           expires_at="2026-12-01T00:00:00+00:00")
        result = self.controller(github, facts, route_resolver(decl, provider="jules", transport="t")).step(now=NOW)
        self.assertEqual(result.status, "DISPATCHED", result.reason)
        self.assertEqual(len(github.list(COMMANDS, CARRIER)), 1)

    def test_route_change_right_before_the_trigger_blocks_the_command_and_budget(self):
        github, facts = self.world()
        good = declaration(transport="t", declared_at="2026-09-01T00:00:00+00:00",
                           expires_at="2026-12-01T00:00:00+00:00")
        calls = []

        def drifting(now):
            calls.append(now)
            # preflight sees the subscription route; the re-check before the irreversible write does not
            return classify_route(good if len(calls) == 1 else None, provider="jules", transport="t", now=now)
        result = self.controller(github, facts, drifting).step(now=NOW)
        self.assertEqual(result.status, "PREPARED_NOT_AUTHORIZED", result.reason)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(github.list(COMMANDS, CARRIER), [])
        self.assertEqual(github.list(BUDGET, DATA), [])

    def test_route_resolver_error_is_never_a_pass(self):
        github, facts = self.world()

        def broken(now):
            raise RuntimeError("route store unreadable")
        result = self.controller(github, facts, broken).step(now=NOW)
        self.assertEqual(result.status, "PREPARED_NOT_AUTHORIZED")
        self.assertIn("unverifiable", result.reason)
        self.assertEqual(github.list(COMMANDS, CARRIER), [])

    def test_live_entry_point_always_installs_the_gate(self):
        from automation.command_bus import claude_jules_live as live
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name, value in (("policy", policy()), ("roadmap", roadmap(task_spec("alpha-helper")))):
                paths[name] = os.path.join(tmp, f"{name}.json")
                with open(paths[name], "w", encoding="utf-8") as fh:
                    json.dump(value, fh)
            args = argparse.Namespace(policy=paths["policy"], roadmap=paths["roadmap"], campaign_policy=None,
                                      provider_route=None, repo_dir=tmp, trailer="", scratch=tmp,
                                      origin_loop_id=LOOP, lane_id="J-BLUE", recovery_policy=None)
            loop, *_ = live.build_live(args)
        route = loop.dispatcher.provider_route
        self.assertIsNotNone(route)
        self.assertEqual(route(NOW).verdict, UNKNOWN_ROUTE)
        self.assertEqual(route(NOW).transport, live.LIVE_DISPATCH_TRANSPORT)


if __name__ == "__main__":
    unittest.main()
