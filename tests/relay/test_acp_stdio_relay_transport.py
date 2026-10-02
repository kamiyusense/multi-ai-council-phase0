import sys
import tempfile
import unittest

from providers.antigravity_acp import build_antigravity_profile
from providers.claude_acp import build_claude_profile
from providers.codex_acp import build_codex_profile
from relay.acp_stdio_relay_transport import AcpStdioStaticTransport
from relay.bridge import RelayProviderAdapterBridge
from relay.core_adapter import RelayCoreAdapter
from relay.duplicate_guard import DuplicateGuard
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.lifecycle import RelayLifecycle
from relay.result import RelayState

_FALSE = {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False}
PROFILES = {
    "openai": lambda: build_codex_profile("account", {**_FALSE, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False}),
    "anthropic": lambda: build_claude_profile("account", {**_FALSE, "dangerous_permission_bypass": False, "hide_claude_auth": False}),
    "google": lambda: build_antigravity_profile("account", {**_FALSE, "cloud_billing_selected": False, "overages_enabled": False, "adc_present": False, "vertex_selected": False}, "linux", "x86_64"),
}

HANDSHAKE = (
    "import sys, json\n"
    "def send(o):\n"
    "    sys.stdout.write(json.dumps(o) + '\\n'); sys.stdout.flush()\n"
    "r = json.loads(sys.stdin.readline())\n"
    "send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'protocolVersion': 1}})\n"
    "r = json.loads(sys.stdin.readline())\n"
    "send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'sessionId': 's1'}})\n"
    "r = json.loads(sys.stdin.readline())\n"
)


def fake_agent(tail: str) -> tuple[str, ...]:
    return (sys.executable, "-c", HANDSHAKE + tail)


OK_TAIL = (
    "send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 's1', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake ' + r['params']['prompt'][0]['text']}}}})\n"
    "send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'stopReason': 'end_turn'}})\n"
)


def envelope(provider_id, seq=0, prompt="hi", timeout=5):
    return DispatchEnvelope.build(
        slot=DispatchSlot("case", provider_id, seq),
        correlation_id=f"corr-{provider_id}-{seq}",
        payload={"prompt": prompt},
        timeout_seconds=timeout,
    )


def lifecycle(provider_id, tail=OK_TAIL, guard=None):
    t = AcpStdioStaticTransport(PROFILES[provider_id](), fake_agent(tail))
    return t, RelayLifecycle(transport=t, duplicate_guard=guard or DuplicateGuard())


class TestThreeProviderStaticE2E(unittest.TestCase):
    cwd = tempfile.gettempdir()

    def test_each_provider_success_maps_and_classifies(self):
        for pid, make in PROFILES.items():
            with self.subTest(pid):
                t, lc = lifecycle(pid)
                res = lc.dispatch_mock(envelope(pid), cwd=self.cwd)
                self.assertEqual(res.state, RelayState.SIMULATED)
                self.assertTrue(res.simulated)
                self.assertEqual(res.prompt_attempts, 1)
                self.assertEqual(t.spawn_count, 1)
                adapter = RelayCoreAdapter(pid, RelayProviderAdapterBridge(), make().static_preflight_config)
                self.assertTrue(adapter.classify(res.raw)["success"])
                self.assertIn(b"fake hi", res.raw)

    def test_duplicate_same_request_no_second_spawn_and_conflict_blocked(self):
        t, lc = lifecycle("openai")
        self.assertEqual(lc.dispatch_mock(envelope("openai"), cwd=self.cwd).state, RelayState.SIMULATED)
        dup = lc.dispatch_mock(envelope("openai"), cwd=self.cwd)
        self.assertEqual(dup.state, RelayState.BLOCKED)
        conflict = lc.dispatch_mock(envelope("openai", prompt="other"), cwd=self.cwd)
        self.assertEqual((conflict.state, conflict.error), (RelayState.BLOCKED, "dispatch slot conflict"))
        self.assertEqual(t.spawn_count, 1)

    def test_stop_blocks_without_spawn(self):
        t, lc = lifecycle("anthropic")
        lc.request_stop()
        self.assertEqual(lc.dispatch_mock(envelope("anthropic"), cwd=self.cwd).state, RelayState.BLOCKED)
        self.assertEqual(t.spawn_count, 0)

    def test_timeout_no_retry(self):
        t, lc = lifecycle("google", "import time; time.sleep(30)\n")
        res = lc.dispatch_mock(envelope("google", timeout=1), cwd=self.cwd)
        self.assertEqual(res.state, RelayState.TIMEOUT)
        self.assertEqual((t.spawn_count, res.prompt_attempts), (1, 1))

    def test_malformed_and_non_end_turn_never_success(self):
        for tail in (
            "sys.stdout.write('not json\\n'); sys.stdout.flush()\n",
            "send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'stopReason': 'refusal'}})\n",
            "send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'stopReason': 'end_turn'}})\n",
        ):
            with self.subTest(tail=tail):
                t, lc = lifecycle("openai", tail)
                res = lc.dispatch_mock(envelope("openai"), cwd=self.cwd)
                self.assertEqual(res.state, RelayState.UNKNOWN)
                self.assertIsNone(res.raw)
                self.assertEqual(t.spawn_count, 1)

    def test_provider_isolation(self):
        t, _ = lifecycle("openai")
        with self.assertRaises(ValueError):
            t.initialize("anthropic")
        sid = t.open_session("openai", cwd=self.cwd)
        with self.assertRaises(ValueError):
            t.prompt("google", sid, {"prompt": "x"})
        self.assertEqual(t.spawn_count, 0)

    def test_second_prompt_rejected(self):
        t, _ = lifecycle("openai")
        sid = t.open_session("openai", cwd=self.cwd)
        t.prompt("openai", sid, {"prompt": "x"}, 5)
        with self.assertRaises(ValueError):
            t.prompt("openai", sid, {"prompt": "x"}, 5)
        self.assertEqual(t.spawn_count, 1)


class TestLiveLaunchRefused(unittest.TestCase):
    def test_official_adapters_refused_for_every_provider(self):
        cmds = [
            ("codex-acp",), ("/usr/bin/claude-agent-acp",), ("agy_acp_server.par",),
            ("C:\\x\\agy_acp_server.exe",), ("npx", "@agentclientprotocol/codex-acp@2.1.0"),
        ]
        for pid, make in PROFILES.items():
            for cmd in cmds:
                with self.subTest(pid=pid, cmd=cmd):
                    with self.assertRaises(ValueError):
                        AcpStdioStaticTransport(make(), cmd)

    def test_bad_inputs(self):
        prof = PROFILES["openai"]()
        for bad in ((), ["python"], ("",)):
            with self.assertRaises(ValueError):
                AcpStdioStaticTransport(prof, bad)
        with self.assertRaises(TypeError):
            AcpStdioStaticTransport(object(), ("python",))

    def test_claude_session_meta_stays_no_bypass(self):
        meta = PROFILES["anthropic"]().session_meta
        self.assertIs(meta["claudeCode"]["options"]["allowDangerouslySkipPermissions"], False)


if __name__ == "__main__":
    unittest.main()
