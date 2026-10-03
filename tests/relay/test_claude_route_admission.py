"""M3/M8 (STATIC): refuse a non-subscription Claude route before `session/new` / any prompt.

The Claude adapter's identity push is classified by the transport (observation only); the one policy is
``providers.policy.claude_route_admission``, injected into the transport. Fake ACP agents (NOT the official
adapter) reproduce the push ordering; nothing real is started.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

from pathlib import Path

from providers.antigravity_acp import build_antigravity_profile
from providers.claude_acp import build_claude_profile
from providers.codex_acp import build_codex_profile
from providers.policy import claude_route_admission
from relay.acp_client import _acp_await_auth_status, _acp_initialize, _acp_new_session
from relay.acp_stdio_relay_transport import AcpStdioStaticTransport
from relay.acp_stdio_transport import spawn_stdio_transport
from relay.claude_auth_readonly import AUTH_STATUS_UPDATE_METHOD
from relay.duplicate_guard import DuplicateGuard
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.lifecycle import RelayLifecycle
from relay.result import RelayState

_FALSE = {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False}
SUB = {"kind": "account", "label": "Claude Pro", "account": {"plan": "pro", "email": "synthetic@example.invalid"}}
API_KEY = {"kind": "api_key", "label": "Anthropic API key", "detail": "apiKeyHelper"}
GATEWAY = {"kind": "gateway", "label": "Custom model gateway"}
EXTERNAL = {"kind": "external", "label": "AWS Bedrock"}
NONE = {"kind": "none", "label": "Not logged in"}


def push(auth_status):
    return {"jsonrpc": "2.0", "method": AUTH_STATUS_UPDATE_METHOD, "params": {"authStatus": auth_status}}


def profile():
    return build_claude_profile("account", {**_FALSE, "dangerous_permission_bypass": False, "hide_claude_auth": False})


class FakeAgent:
    """Programmable fake ACP agent; logs the methods it receives and its pid."""

    def __init__(self, after_init=(), before_session_reply=(), after_session=(), in_prompt=(), session_error=False):
        self.dir = tempfile.mkdtemp()
        self.log, self.pidfile = os.path.join(self.dir, "methods.log"), os.path.join(self.dir, "pid")
        code = (
            "import sys, json, os\n"
            "def send(o):\n    sys.stdout.write(json.dumps(o) + '\\n'); sys.stdout.flush()\n"
            f"open({self.pidfile!r}, 'w').write(str(os.getpid()))\n"
            "while True:\n"
            "    line = sys.stdin.readline()\n"
            "    if not line: break\n"
            "    r = json.loads(line)\n"
            f"    open({self.log!r}, 'a').write(r.get('method', '?') + '\\n')\n"
            "    m = r.get('method')\n"
            "    if m == 'initialize':\n"
            "        send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'protocolVersion': 1}})\n"
            f"        [send(f) for f in {list(after_init)!r}]\n"
            "    elif m == 'session/new':\n"
            f"        [send(f) for f in {list(before_session_reply)!r}]\n"
            f"        if {session_error!r}:\n"
            "            send({'jsonrpc': '2.0', 'id': r['id'], 'error': {'code': -1, 'message': 'x'}})\n"
            "        else:\n"
            "            send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'sessionId': 's1'}})\n"
            f"            [send(f) for f in {list(after_session)!r}]\n"
            "    elif m == 'session/prompt':\n"
            f"        [send(f) for f in {list(in_prompt)!r}]\n"
            "        send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 's1', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'synthetic reply'}}}})\n"
            "        send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'stopReason': 'end_turn'}})\n"
        )
        self.command = (sys.executable, "-c", code)

    def methods(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return fh.read().split()

    def alive(self):
        if os.name == "nt":  # os.kill(pid, 0) would terminate the process on Windows; liveness is checked on POSIX only
            return False
        deadline = time.monotonic() + 3.0
        with open(self.pidfile, encoding="utf-8") as fh:
            pid = int(fh.read())
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            time.sleep(0.05)
        return True


def dispatch(agent, admission=claude_route_admission, wait=0.5, prof=None):
    t = AcpStdioStaticTransport(prof or profile(), agent.command, route_admission=admission, route_admission_wait_seconds=wait)
    env = DispatchEnvelope.build(slot=DispatchSlot("case", "anthropic", 0), correlation_id="corr-route", payload={"prompt": "hi"}, timeout_seconds=10)
    return t, RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(env, cwd=tempfile.gettempdir())


class TestPolicy(unittest.TestCase):
    def test_only_all_subscription_observations_are_admitted(self):
        sub = {"auth_state": "CLAUDE_SUBSCRIPTION_ACCOUNT"}
        self.assertEqual(claude_route_admission([sub]), (True, "OK"))
        self.assertEqual(claude_route_admission([sub, sub]), (True, "OK"))
        self.assertEqual(claude_route_admission([]), (False, "NO_AUTH_STATUS_OBSERVED"))
        for state in ("API_KEY_ROUTE_VIOLATION", "EXTERNAL_ROUTE_VIOLATION", "NOT_AUTHENTICATED", "UNKNOWN"):
            with self.subTest(state=state):
                self.assertEqual(claude_route_admission([sub, {"auth_state": state}]), (False, f"ROUTE_{state}"))
        for bad in ({}, {"auth_state": None}, {"auth_state": 3}, "x", None):
            with self.subTest(bad=bad):
                self.assertEqual(claude_route_admission([bad]), (False, "ROUTE_UNKNOWN"))


class TestAdmissionBeforeAnyPrompt(unittest.TestCase):
    def test_subscription_is_admitted_and_the_turn_runs(self):
        agent = FakeAgent(after_init=[push(SUB)])
        t, res = dispatch(agent)
        self.assertEqual(res.state, RelayState.SIMULATED, res.error)
        self.assertEqual(agent.methods(), ["initialize", "session/new", "session/prompt"])
        self.assertEqual(t.route_admission_decisions, [(True, "OK"), (True, "OK")])

    def test_every_other_route_is_refused_before_session_new_and_the_child_is_stopped(self):
        for status, reason in ((API_KEY, "ROUTE_API_KEY_ROUTE_VIOLATION"), (GATEWAY, "ROUTE_EXTERNAL_ROUTE_VIOLATION"),
                               (EXTERNAL, "ROUTE_EXTERNAL_ROUTE_VIOLATION"), (NONE, "ROUTE_NOT_AUTHENTICATED"),
                               ({"kind": "future_kind"}, "ROUTE_UNKNOWN")):
            with self.subTest(kind=status["kind"]):
                agent = FakeAgent(after_init=[push(status)])
                t, res = dispatch(agent)
                self.assertEqual((res.state, res.prompt_attempts, res.raw), (RelayState.BLOCKED, 0, None))
                self.assertIn(reason, res.error)
                self.assertEqual(agent.methods(), ["initialize"])  # no session/new, no prompt: nothing generated
                self.assertEqual((t.spawn_count, t.prompt_count), (1, 0))
                self.assertFalse(agent.alive())

    def test_no_identity_push_is_refused_fail_closed(self):
        agent = FakeAgent()
        t, res = dispatch(agent, wait=0.3)
        self.assertEqual((res.state, res.prompt_attempts), (RelayState.BLOCKED, 0))
        self.assertIn("NO_AUTH_STATUS_OBSERVED", res.error)
        self.assertEqual(agent.methods(), ["initialize"])
        self.assertFalse(agent.alive())

    def test_violation_seen_while_session_new_is_answered_blocks_the_prompt(self):
        agent = FakeAgent(after_init=[push(SUB)], before_session_reply=[push(API_KEY)])
        t, res = dispatch(agent)
        self.assertEqual((res.state, res.prompt_attempts), (RelayState.BLOCKED, 0))
        self.assertEqual(agent.methods(), ["initialize", "session/new"])  # session made, prompt never sent
        self.assertFalse(agent.alive())

    def test_late_pushes_are_observability_only_not_a_pre_generation_gate(self):
        """TIMING LIMIT: a push that follows the session/new reply or arrives at prompt start can land after
        generation has begun, so it is recorded but cannot gate (docs: OBSERVABILITY_ONLY)."""
        for kwargs in ({"after_session": [push(API_KEY)]}, {"in_prompt": [push(API_KEY)]}):
            with self.subTest(kwargs=list(kwargs)):
                agent = FakeAgent(after_init=[push(SUB)], **kwargs)
                t, res = dispatch(agent)
                self.assertEqual(res.state, RelayState.SIMULATED)
                self.assertEqual(agent.methods()[-1], "session/prompt")
                self.assertEqual(t.auth_status_evidence[-1]["auth_state"], "API_KEY_ROUTE_VIOLATION")
                self.assertEqual(t.route_admission_decisions, [(True, "OK"), (True, "OK")])  # decided before the late push

    def test_transport_owns_no_policy_it_only_calls_the_injected_one(self):
        agent = FakeAgent(after_init=[push(API_KEY)])
        _t, res = dispatch(agent, admission=lambda evidence: (True, "TEST_ALLOW"))
        self.assertEqual(res.state, RelayState.SIMULATED)  # transport did not second-guess the injected policy
        agent = FakeAgent(after_init=[push(SUB)])
        _t, res = dispatch(agent, admission=lambda evidence: (False, "TEST_DENY"))
        self.assertEqual((res.state, res.prompt_attempts), (RelayState.BLOCKED, 0))
        self.assertIn("TEST_DENY", res.error)

    def test_without_an_injected_policy_behavior_is_unchanged_observation_only(self):
        agent = FakeAgent(after_init=[push(API_KEY)])
        t = AcpStdioStaticTransport(profile(), agent.command)
        env = DispatchEnvelope.build(slot=DispatchSlot("case", "anthropic", 0), correlation_id="c", payload={"prompt": "hi"}, timeout_seconds=10)
        res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(env, cwd=tempfile.gettempdir())
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertEqual(t.auth_status_evidence[0]["auth_state"], "API_KEY_ROUTE_VIOLATION")
        self.assertEqual(t.route_admission_decisions, [])

    def test_only_the_claude_profile_may_use_the_extension(self):
        codex = build_codex_profile("account", {**_FALSE, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False})
        with self.assertRaises(ValueError):
            AcpStdioStaticTransport(codex, FakeAgent().command, route_admission=claude_route_admission)

    def test_refusal_keeps_raw_account_data_out_of_the_result(self):
        agent = FakeAgent(after_init=[push({**API_KEY, "account": {"email": "synthetic@example.invalid"}})])
        t, res = dispatch(agent)
        blob = repr(res) + json.dumps(t.auth_status_evidence) + json.dumps(t.route_admission_decisions)
        for secret in ("synthetic@example.invalid", "apiKeyHelper", "Anthropic API key"):
            self.assertNotIn(secret, blob)


class TestSessionNewFailureStopsTheChild(unittest.TestCase):
    """M10 (observed): when session/new failed, the lifecycle had no session id to close and the adapter child kept running."""

    def test_child_is_stopped_after_a_session_new_error(self):
        agent = FakeAgent(after_init=[push(SUB)], session_error=True)
        t = AcpStdioStaticTransport(profile(), agent.command)
        env = DispatchEnvelope.build(slot=DispatchSlot("case", "anthropic", 0), correlation_id="c", payload={"prompt": "hi"}, timeout_seconds=10)
        res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(env, cwd=tempfile.gettempdir())
        self.assertEqual((res.state, res.prompt_attempts), (RelayState.UNKNOWN, 0))
        self.assertEqual(agent.methods(), ["initialize", "session/new"])
        self.assertFalse(agent.alive())


class TestM7ProviderScope(unittest.TestCase):
    """Common Relay contract across providers; the Claude identity push stays Claude-only (UNKNOWN stays UNKNOWN)."""

    def profiles(self):
        yield "openai", build_codex_profile("account", {**_FALSE, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False})
        yield "google", build_antigravity_profile("account", {**_FALSE, "cloud_billing_selected": False, "overages_enabled": False, "adc_present": False, "vertex_selected": False}, "linux", "x86_64")
        yield "anthropic", profile()

    def run_one(self, provider_id, prof, agent):
        t = AcpStdioStaticTransport(prof, agent.command)
        env = DispatchEnvelope.build(slot=DispatchSlot("case", provider_id, 0), correlation_id=f"c-{provider_id}", payload={"prompt": "hi"}, timeout_seconds=10)
        return t, RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(env, cwd=tempfile.gettempdir())

    def test_all_three_providers_complete_the_same_mock_lifecycle_without_the_extension(self):
        for provider_id, prof in self.profiles():
            with self.subTest(provider=provider_id):
                t, res = self.run_one(provider_id, prof, FakeAgent())
                self.assertEqual((res.state, res.prompt_attempts, res.simulated, t.spawn_count), (RelayState.SIMULATED, 1, True, 1))
                self.assertEqual(t.auth_status_evidence, [])

    def test_the_claude_identity_push_is_not_accepted_for_other_providers(self):
        for provider_id, prof in self.profiles():
            if provider_id == "anthropic":
                continue
            with self.subTest(provider=provider_id):
                t, res = self.run_one(provider_id, prof, FakeAgent(in_prompt=[push(SUB)]))
                self.assertEqual(res.state, RelayState.UNKNOWN)
                self.assertEqual(t.auth_status_evidence, [])


TRIPWIRE = Path(__file__).resolve().parents[2] / "fixtures" / "relay" / "claude_cli_tripwire.py"


@unittest.skipUnless(os.environ.get("RELAY_CLAUDE_ACP_DIR") and shutil.which("node") and os.name != "nt",
                     "RELAY_CLAUDE_ACP_DIR / node / POSIX not available (TEST_ENVIRONMENT_NOT_PREPARED)")
class TestOfficialAdapterOrdering(unittest.TestCase):
    """Official claude-agent-acp + tripwire CLI answering with a SYNTHETIC `auth status --json`.

    Same step order as the transport (initialize -> wait for the identity push -> policy -> session/new),
    driven with the wire helpers because the official-adapter launch seam stays closed for Claude.
    """

    def run_sequence(self, cli_json):
        home = tempfile.mkdtemp()
        log = os.path.join(home, "tripwire.log")
        env = {"HOME": home, "CLAUDE_CODE_EXECUTABLE": str(TRIPWIRE), "RELAY_TRIPWIRE_LOG": log, "RELAY_TRIPWIRE_AUTH_STATUS_JSON": cli_json}
        out = {}

        async def go():
            cm = spawn_stdio_transport("node", os.path.join(os.environ["RELAY_CLAUDE_ACP_DIR"], "dist", "index.js"),
                                       env=env, cwd=home, shutdown_timeout=3)
            stdout, stdin, _p = await cm.__aenter__()
            try:
                sink = []
                await _acp_initialize(stdout, stdin, 30, sink)
                await _acp_await_auth_status(stdout, 10, sink)
                out["decision"] = claude_route_admission(sink)
                if out["decision"][0]:
                    try:
                        await _acp_new_session(stdout, stdin, home, 30, profile().session_meta, sink)
                    except RuntimeError:
                        out["session_new"] = "error (needs a real Claude CLI)"
                    await asyncio.sleep(1.0)
            finally:
                await cm.__aexit__(None, None, None)

        asyncio.run(go())
        with open(log, encoding="utf-8") if os.path.exists(log) else open(os.devnull, encoding="utf-8") as fh:
            out["cli_calls"] = [json.loads(x) for x in fh if x.strip()]
        return out

    def test_non_subscription_routes_are_refused_before_any_cli_session_is_spawned(self):
        for cli, reason in (({"loggedIn": True, "apiProvider": "firstParty", "apiKeySource": "apiKeyHelper"}, "ROUTE_API_KEY_ROUTE_VIOLATION"),
                            ({"loggedIn": False, "apiProvider": "bedrock"}, "ROUTE_EXTERNAL_ROUTE_VIOLATION"),
                            ({"loggedIn": False}, "ROUTE_NOT_AUTHENTICATED")):
            with self.subTest(reason=reason):
                out = self.run_sequence(json.dumps(cli))
                self.assertEqual(out["decision"], (False, reason))
                self.assertEqual(out["cli_calls"], [["auth", "status", "--json"]])  # only the identity probe ran

    def test_subscription_passes_the_gate_and_stops_at_the_cli_live_boundary(self):
        out = self.run_sequence(json.dumps({"loggedIn": True, "apiProvider": "firstParty", "subscriptionType": "pro"}))
        self.assertEqual(out["decision"], (True, "OK"))
        self.assertEqual(out["session_new"], "error (needs a real Claude CLI)")
        self.assertTrue(any("stream-json" in call for call in out["cli_calls"]))  # the session CLI would start only now


if __name__ == "__main__":
    unittest.main()
