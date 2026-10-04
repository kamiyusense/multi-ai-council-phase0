"""Minimal mid-turn rule (STATIC): a CONFIRMED API-key / external route reported during the turn -> existing cancel,
existing stop flag, reason in the result. Unknown / malformed / not-authenticated -> recorded only.
"No monitor-only = no cancel" is one wrapper; there is deliberately no "protection off"."""

import json
import tempfile
import unittest

from providers.policy import claude_route_admission, claude_route_midturn, monitor_only
from relay.acp_stdio_relay_transport import AcpStdioStaticTransport
from relay.duplicate_guard import DuplicateGuard
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.lifecycle import RelayLifecycle
from relay.result import RelayState
from tests.relay.test_claude_route_admission import API_KEY, EXTERNAL, GATEWAY, NONE, SUB, FakeAgent, profile, push


def run(agent, lifecycle=None, slot=0, **kwargs):
    kwargs.setdefault("route_admission", claude_route_admission)
    kwargs.setdefault("route_admission_wait_seconds", 0.5)
    t = AcpStdioStaticTransport(profile(), agent.command, **kwargs)
    lc = lifecycle or RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard())
    lc.transport = t
    env = DispatchEnvelope.build(slot=DispatchSlot("case", "anthropic", slot), correlation_id=f"corr-{slot}", payload={"prompt": "hi"}, timeout_seconds=10)
    return t, lc, lc.dispatch_mock(env, cwd=tempfile.gettempdir())


class TestPolicyPieces(unittest.TestCase):
    def test_midturn_rule_acts_only_on_confirmed_violations(self):
        for state, expected in (("API_KEY_ROUTE_VIOLATION", "ROUTE_API_KEY_ROUTE_VIOLATION"),
                                ("EXTERNAL_ROUTE_VIOLATION", "ROUTE_EXTERNAL_ROUTE_VIOLATION"),
                                ("CLAUDE_SUBSCRIPTION_ACCOUNT", None), ("NOT_AUTHENTICATED", None), ("UNKNOWN", None)):
            with self.subTest(state=state):
                self.assertEqual(claude_route_midturn({"auth_state": state}), expected)
        for bad in ({}, {"auth_state": None}, {"auth_state": 5}, "x", None):
            with self.subTest(bad=bad):
                self.assertIsNone(claude_route_midturn(bad))

    def test_monitor_only_records_the_real_decision_and_always_returns_neutral(self):
        wrapped = monitor_only(claude_route_admission, (True, "MONITOR_ONLY"))
        self.assertEqual(wrapped([{"auth_state": "API_KEY_ROUTE_VIOLATION"}]), (True, "MONITOR_ONLY"))
        self.assertEqual(wrapped.observed[0][1], (False, "ROUTE_API_KEY_ROUTE_VIOLATION"))
        mid = monitor_only(claude_route_midturn, None)
        self.assertIsNone(mid({"auth_state": "EXTERNAL_ROUTE_VIOLATION"}))
        self.assertEqual(mid.observed[0][1], "ROUTE_EXTERNAL_ROUTE_VIOLATION")


class TestMidTurnConfirmedViolation(unittest.TestCase):
    def test_confirmed_violation_cancels_stops_and_names_the_reason(self):
        for status, reason in ((API_KEY, "ROUTE_API_KEY_ROUTE_VIOLATION"), (GATEWAY, "ROUTE_EXTERNAL_ROUTE_VIOLATION"),
                               (EXTERNAL, "ROUTE_EXTERNAL_ROUTE_VIOLATION")):
            with self.subTest(kind=status["kind"]):
                agent = FakeAgent(after_init=[push(SUB)], in_prompt=[push(status)])
                t, lc, res = run(agent, route_midturn=claude_route_midturn)
                self.assertEqual(res.state, RelayState.CANCELLED)
                self.assertIn(reason, res.error)
                self.assertIsNone(res.raw)
                self.assertEqual(agent.methods().count("session/prompt"), 1)  # no second prompt, no retry
                self.assertEqual(agent.methods().count("initialize"), 1)  # no relaunch
                self.assertEqual((t.spawn_count, t.cancel_sent), (1, 1))  # the existing cancel was sent once
                self.assertIn("session/cancel", agent.methods())
                self.assertFalse(agent.alive())
                # existing stop flag: the next dispatch is not started
                again = DispatchEnvelope.build(slot=DispatchSlot("case", "anthropic", 1), correlation_id="next", payload={"prompt": "hi"}, timeout_seconds=10)
                nxt = lc.dispatch_mock(again, cwd=tempfile.gettempdir())
                self.assertEqual((nxt.state, nxt.error), (RelayState.BLOCKED, "stop requested"))

    def test_nothing_private_is_in_the_result_or_the_decisions(self):
        agent = FakeAgent(after_init=[push(SUB)], in_prompt=[push({**API_KEY, "account": {"email": "synthetic@example.invalid"}})])
        t, _lc, res = run(agent, route_midturn=claude_route_midturn)
        blob = repr(res) + json.dumps(t.auth_status_evidence) + json.dumps(t.route_midturn_decisions)
        for secret in ("synthetic@example.invalid", "apiKeyHelper", "Anthropic API key"):
            self.assertNotIn(secret, blob)

    def test_unknown_malformed_and_not_authenticated_are_recorded_only(self):
        frames = [push(NONE), push({"kind": "future_kind"}),
                  {"jsonrpc": "2.0", "method": "_auth/status_update", "params": {"authStatus": "x"}}]
        agent = FakeAgent(after_init=[push(SUB)], in_prompt=frames)
        t, lc, res = run(agent, route_midturn=claude_route_midturn)
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertEqual(t.route_midturn_decisions, [None, None, None])
        self.assertEqual([e["auth_state"] for e in t.auth_status_evidence][1:], ["NOT_AUTHENTICATED", "UNKNOWN", "UNKNOWN"])
        self.assertEqual(t.cancel_sent, 0)
        again = DispatchEnvelope.build(slot=DispatchSlot("case", "anthropic", 1), correlation_id="next", payload={"prompt": "hi"}, timeout_seconds=10)
        self.assertNotEqual(lc.dispatch_mock(again, cwd=tempfile.gettempdir()).error, "stop requested")  # no stop flag

    def test_a_subscription_mid_turn_is_untouched(self):
        t, _lc, res = run(FakeAgent(after_init=[push(SUB)], in_prompt=[push(SUB)]), route_midturn=claude_route_midturn)
        self.assertEqual((res.state, t.route_midturn_decisions), (RelayState.SIMULATED, [None]))

    def test_without_the_rule_behavior_is_unchanged(self):
        t, _lc, res = run(FakeAgent(after_init=[push(SUB)], in_prompt=[push(API_KEY)]))
        self.assertEqual((res.state, t.cancel_sent), (RelayState.SIMULATED, 0))

    def test_only_the_claude_profile_may_set_it(self):
        from providers.codex_acp import build_codex_profile
        codex = build_codex_profile("account", {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False,
                                                "custom_model_provider_configured": False, "arbitrary_codex_config_present": False})
        with self.assertRaises(ValueError):
            AcpStdioStaticTransport(codex, FakeAgent().command, route_midturn=claude_route_midturn)


class TestMonitorOnly(unittest.TestCase):
    def test_monitor_only_records_but_neither_blocks_nor_cancels(self):
        adm = monitor_only(claude_route_admission, (True, "MONITOR_ONLY"))
        mid = monitor_only(claude_route_midturn, None)
        agent = FakeAgent(after_init=[push(API_KEY)], in_prompt=[push(EXTERNAL)])
        t, lc, res = run(agent, route_admission=adm, route_midturn=mid)
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertEqual(agent.methods(), ["initialize", "session/new", "session/prompt"])
        self.assertEqual(adm.observed[0][1], (False, "ROUTE_API_KEY_ROUTE_VIOLATION"))  # the real verdict is kept
        self.assertEqual(mid.observed[0][1], "ROUTE_EXTERNAL_ROUTE_VIOLATION")
        self.assertEqual(t.cancel_sent, 0)


if __name__ == "__main__":
    unittest.main()
