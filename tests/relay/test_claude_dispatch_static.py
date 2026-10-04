"""STATIC E2E of the Claude dispatch path: Relay envelope -> Admission Gate contract -> route admission -> session
-> one prompt -> mid-turn rule -> terminal. Fake ACP agents only (the real Claude launch seam stays closed)."""

import tempfile
import unittest
import uuid

from automation.command_bus.claude_admission_gate import prepare_transport
from providers.codex_acp import build_codex_profile
from relay.claude_dispatch import ClaudeStaticDispatcher
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.result import RelayState
from tests.relay.test_claude_route_admission import API_KEY, EXTERNAL, GATEWAY, NONE, SUB, FakeAgent, profile, push

GATE_URL = "http://127.0.0.1:18080"
_FALSE = {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False}


def envelope(seq=0, provider="anthropic"):
    return DispatchEnvelope.build(slot=DispatchSlot("case", provider, seq), correlation_id=f"corr-{seq}",
                                  payload={"prompt": "hi"}, timeout_seconds=10)


def gate():
    dispatch_id = str(uuid.uuid4())
    return dispatch_id, prepare_transport(dispatch_id=dispatch_id, gate_base_url=GATE_URL)


def go(agent, seq=0, dispatcher=None, **kw):
    d = dispatcher or ClaudeStaticDispatcher(profile(), agent.command, route_wait_seconds=0.5, **kw)
    dispatch_id, contract = gate()
    return d, d.dispatch(envelope(seq), dispatch_id=dispatch_id, gate_transport=contract, cwd=tempfile.gettempdir())


class TestNormalAndPreStartBlocks(unittest.TestCase):
    def test_subscription_runs_one_prompt_with_no_retry_or_fallback(self):
        agent = FakeAgent(after_init=[push(SUB)])
        d, res = go(agent)
        self.assertEqual((res.state, res.prompt_attempts, res.simulated), (RelayState.SIMULATED, 1, True))
        self.assertEqual(agent.methods(), ["initialize", "session/new", "session/prompt"])
        self.assertEqual((d.last_transport.spawn_count, d.last_transport.prompt_count, d.last_transport.cancel_sent), (1, 1, 0))
        self.assertEqual(d.last_transport.route_admission_decisions, [(True, "OK"), (True, "OK")])

    def test_every_non_subscription_route_is_blocked_before_any_session_or_prompt(self):
        for label, frames in (("api_key", [push(API_KEY)]), ("gateway", [push(GATEWAY)]), ("external", [push(EXTERNAL)]),
                              ("not_authenticated", [push(NONE)]), ("unknown_kind", [push({"kind": "future"})]),
                              ("malformed", [{"jsonrpc": "2.0", "method": "_auth/status_update"}]), ("no_evidence", [])):
            with self.subTest(case=label):
                agent = FakeAgent(after_init=frames)
                d, res = go(agent)
                self.assertEqual((res.state, res.prompt_attempts, res.raw), (RelayState.BLOCKED, 0, None))
                self.assertEqual(agent.methods(), ["initialize"])  # no session/new, no session/prompt: nothing generated
                self.assertEqual(d.last_transport.prompt_count, 0)
                self.assertFalse(agent.alive())


class TestMidTurn(unittest.TestCase):
    def test_confirmed_api_key_or_external_cancels_once_then_the_stop_flag_blocks_the_next_dispatch(self):
        for status in (API_KEY, EXTERNAL, GATEWAY):
            with self.subTest(kind=status["kind"]):
                agent = FakeAgent(after_init=[push(SUB)], in_prompt=[push(status)])
                d, res = go(agent)
                self.assertEqual(res.state, RelayState.CANCELLED)
                self.assertIn("ROUTE_", res.error)
                self.assertEqual((agent.methods().count("session/prompt"), agent.methods().count("initialize")), (1, 1))
                self.assertEqual((d.last_transport.spawn_count, d.last_transport.cancel_sent), (1, 1))
                self.assertFalse(agent.alive())
                _d, nxt = go(FakeAgent(after_init=[push(SUB)]), seq=1, dispatcher=d)
                self.assertEqual((nxt.state, nxt.error), (RelayState.BLOCKED, "stop requested"))

    def test_unknown_malformed_and_not_authenticated_mid_turn_do_not_cancel(self):
        frames = [push(NONE), push({"kind": "future"}), {"jsonrpc": "2.0", "method": "_auth/status_update", "params": {"authStatus": "x"}}]
        agent = FakeAgent(after_init=[push(SUB)], in_prompt=frames)
        d, res = go(agent)
        self.assertEqual((res.state, d.last_transport.cancel_sent), (RelayState.SIMULATED, 0))


class TestMonitorOnly(unittest.TestCase):
    def test_real_decisions_are_observed_but_nothing_is_blocked_or_cancelled(self):
        agent = FakeAgent(after_init=[push(API_KEY)], in_prompt=[push(EXTERNAL)])
        d, res = go(agent, mode="monitor_only")
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertEqual(agent.methods(), ["initialize", "session/new", "session/prompt"])
        admission, midturn = d.observed
        self.assertEqual(admission[0][1], (False, "ROUTE_API_KEY_ROUTE_VIOLATION"))
        self.assertEqual(midturn[0][1], "ROUTE_EXTERNAL_ROUTE_VIOLATION")
        self.assertEqual(d.last_transport.cancel_sent, 0)

    def test_there_is_no_off_mode(self):
        for bad in ("off", "none", "", None, "ENFORCE"):
            with self.subTest(mode=bad):
                with self.assertRaises(ValueError):
                    ClaudeStaticDispatcher(profile(), FakeAgent().command, mode=bad)


class TestGuardsBeforeAnyProcess(unittest.TestCase):
    def blocked_without_process(self, d, dispatch_id, contract, env=None):
        res = d.dispatch(env or envelope(), dispatch_id=dispatch_id, gate_transport=contract, cwd=tempfile.gettempdir())
        self.assertEqual((res.state, res.prompt_attempts), (RelayState.BLOCKED, 0))
        self.assertIsNone(d.last_transport)  # no transport / adapter process was even created
        return res

    def test_gate_contract_must_be_prepared_and_for_this_dispatch(self):
        agent = FakeAgent(after_init=[push(SUB)])
        dispatch_id, contract = gate()
        for label, dispatch, bad in (
            ("not prepared", dispatch_id, {**contract, "status": "BLOCKED"}),
            ("retry", dispatch_id, {**contract, "retry": 1}),
            ("fallback", dispatch_id, {**contract, "fallback": "enabled"}),
            ("live", dispatch_id, {**contract, "live_model": True}),
            ("launch", dispatch_id, {**contract, "launch": True}),
            ("max retries", dispatch_id, {**contract, "env": {**contract["env"], "CLAUDE_CODE_MAX_RETRIES": "3"}}),
            ("other dispatch", str(uuid.uuid4()), contract),
            ("bad id", "not-a-uuid", contract),
            ("missing", dispatch_id, None),
        ):
            with self.subTest(case=label):
                d = ClaudeStaticDispatcher(profile(), agent.command)
                self.blocked_without_process(d, dispatch, bad)
        self.assertEqual(agent.methods(), [])

    def test_a_non_claude_envelope_is_refused(self):
        d = ClaudeStaticDispatcher(profile(), FakeAgent().command)
        dispatch_id, contract = gate()
        res = self.blocked_without_process(d, dispatch_id, contract, envelope(provider="openai"))
        self.assertEqual(res.error, "not a Claude dispatch")

    def test_only_the_claude_profile_is_accepted(self):
        codex = build_codex_profile("account", {**_FALSE, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False})
        with self.assertRaises(ValueError):
            ClaudeStaticDispatcher(codex, FakeAgent().command)

    def test_route_admission_and_the_gate_are_both_required(self):
        # a confirmed subscription route does not replace the gate contract, and a valid gate does not replace the route check
        d = ClaudeStaticDispatcher(profile(), FakeAgent(after_init=[push(SUB)]).command)
        self.blocked_without_process(d, str(uuid.uuid4()), {"status": "BLOCKED"})
        _d, res = go(FakeAgent(after_init=[push(API_KEY)]))
        self.assertEqual(res.state, RelayState.BLOCKED)


class TestDuplicateAndStop(unittest.TestCase):
    def test_the_same_envelope_twice_starts_no_second_process(self):
        agent = FakeAgent(after_init=[push(SUB)])
        d, first = go(agent)
        self.assertEqual(first.state, RelayState.SIMULATED)
        dispatch_id, contract = gate()
        again = d.dispatch(envelope(0), dispatch_id=dispatch_id, gate_transport=contract, cwd=tempfile.gettempdir())
        self.assertEqual((again.state, again.error), (RelayState.BLOCKED, "duplicate request already reserved"))
        self.assertEqual(agent.methods().count("initialize"), 1)


if __name__ == "__main__":
    unittest.main()
