# 使用停止中・実行禁止（規約上の理由、2026-10）
# SUSPENDED - DO NOT RUN (Antigravity terms, 2026-10). Archived from the Relay; see archive/antigravity_launch/README.md.
"""Antigravity STATIC dispatch: route admission on the settings snapshot, then the existing lifecycle (fake agent only)."""
import tempfile
import unittest

from providers import build_antigravity_profile, build_claude_profile
from providers.policy import antigravity_route_admission
from relay.antigravity_dispatch import MODES, AntigravityStaticDispatcher
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.result import RelayState
from tests.relay.test_claude_route_admission import _FALSE as _BASE, FakeAgent, profile as claude_profile

_FALSE = {**_BASE, "cloud_billing_selected": False, "overages_enabled": False, "adc_present": False, "vertex_selected": False}
GOOD = {"auth": {"type": "oauth-personal"}}


def agy_profile():
    return build_antigravity_profile("account", dict(_FALSE), "linux", "x86_64")


def env(provider="google", cid="c1"):
    return DispatchEnvelope.build(slot=DispatchSlot("case", provider, 0), correlation_id=cid, payload={"prompt": "hi"}, timeout_seconds=10)


class TestPolicy(unittest.TestCase):
    def test_only_personal_oauth_is_admitted(self):
        self.assertEqual(antigravity_route_admission(GOOD), (True, "OK"))
        for bad in ({"auth": {"type": "gemini-api-key"}}, {"auth": {"type": "agent-platform"}}, {"auth": {"type": "oauth-business"}},
                    {"auth": {"type": ""}}, {"auth": {"type": 5}}, {"auth": {}}, {"auth": "oauth-personal"}, {}, None, [], "x"):
            self.assertFalse(antigravity_route_admission(bad)[0], bad)
        self.assertEqual(antigravity_route_admission({"auth": {"type": "gemini-api-key"}})[1], "ROUTE_gemini-api-key")
        self.assertEqual(antigravity_route_admission({})[1], "NO_AUTH_SELECTION")


class TestDispatch(unittest.TestCase):
    def test_personal_oauth_completes_one_mock_lifecycle(self):
        a = FakeAgent()
        d = AntigravityStaticDispatcher(agy_profile(), a.command)
        r = d.dispatch(env(), settings=GOOD, cwd=tempfile.gettempdir())
        self.assertEqual(r.state, RelayState.SIMULATED)
        self.assertEqual(a.methods().count("session/prompt"), 1)

    def test_every_other_selection_is_blocked_before_any_process(self):
        for bad in ({"auth": {"type": "gemini-api-key"}}, {"auth": {"type": "agent-platform"}}, {"auth": {"type": "oauth-business"}},
                    {}, None, {"auth": {"type": None}}):
            a = FakeAgent()
            d = AntigravityStaticDispatcher(agy_profile(), a.command)
            r = d.dispatch(env(), settings=bad, cwd=tempfile.gettempdir())
            self.assertEqual(r.state, RelayState.BLOCKED, bad)
            self.assertIsNone(d.last_transport)
            self.assertEqual(a.methods(), [])

    def test_session_auth_error_is_plain_failure_no_prompt_no_retry(self):
        a = FakeAgent(session_error=True)
        d = AntigravityStaticDispatcher(agy_profile(), a.command)
        r = d.dispatch(env(), settings=GOOD, cwd=tempfile.gettempdir())
        self.assertNotEqual(r.state, RelayState.SIMULATED)
        self.assertEqual(a.methods().count("session/prompt"), 0)
        self.assertEqual(a.methods().count("initialize"), 1)
        self.assertEqual(a.methods().count("session/new"), 1)

    def test_monitor_only_records_but_does_not_block(self):
        a = FakeAgent()
        d = AntigravityStaticDispatcher(agy_profile(), a.command, mode="monitor_only")
        r = d.dispatch(env(), settings={"auth": {"type": "gemini-api-key"}}, cwd=tempfile.gettempdir())
        self.assertEqual(r.state, RelayState.SIMULATED)
        self.assertEqual(d.observed[0][1], (False, "ROUTE_gemini-api-key"))

    def test_no_off_mode_and_profile_scope(self):
        for m in ("off", "none", "", "ENFORCE", None):
            with self.assertRaises(ValueError):
                AntigravityStaticDispatcher(agy_profile(), ("x",), mode=m)
        self.assertEqual(MODES, ("enforce", "monitor_only"))
        with self.assertRaises(ValueError):
            AntigravityStaticDispatcher(claude_profile(), ("x",))
        d = AntigravityStaticDispatcher(agy_profile(), FakeAgent().command)
        self.assertEqual(d.dispatch(env("anthropic"), settings=GOOD, cwd=tempfile.gettempdir()).state, RelayState.BLOCKED)

    def test_duplicate_request_runs_once(self):
        a = FakeAgent()
        d = AntigravityStaticDispatcher(agy_profile(), a.command)
        e = env()
        d.dispatch(e, settings=GOOD, cwd=tempfile.gettempdir())
        r2 = d.dispatch(e, settings=GOOD, cwd=tempfile.gettempdir())
        self.assertEqual(r2.state, RelayState.BLOCKED)
        self.assertEqual(a.methods().count("initialize"), 1)


if __name__ == "__main__":
    unittest.main()
