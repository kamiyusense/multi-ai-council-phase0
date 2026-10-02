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
        self.assertEqual(t.spawn_count, 0)
        t.initialize("openai")
        sid = t.open_session("openai", cwd=self.cwd)
        with self.assertRaises(ValueError):
            t.prompt("google", sid, {"prompt": "x"})
        t.close("openai", sid)

    def test_second_prompt_rejected(self):
        t, _ = lifecycle("openai")
        t.initialize("openai")
        sid = t.open_session("openai", cwd=self.cwd)
        t.prompt("openai", sid, {"prompt": "x"}, 5)
        with self.assertRaises(ValueError):
            t.prompt("openai", sid, {"prompt": "x"}, 5)
        t.close("openai", sid)
        self.assertEqual((t.spawn_count, t.prompt_count), (1, 1))


class TestLifecycleMapping(unittest.TestCase):
    """Relay calls map one-to-one onto ACP calls over ONE persistent child."""

    def _agent(self, logfile, tail_after_prompt):
        script = (
            "import sys, json\n"
            f"LOG = {logfile!r}\n"
            "def note(m):\n"
            "    open(LOG, 'a').write(m + '\\n')\n"
            "def send(o):\n"
            "    sys.stdout.write(json.dumps(o) + '\\n'); sys.stdout.flush()\n"
            "for line in sys.stdin:\n"
            "    r = json.loads(line); m = r['method']; note(m)\n"
            "    if m == 'initialize':\n"
            "        send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'protocolVersion': 1, 'agentCapabilities': {'sessionCapabilities': {'close': {}}}}})\n"
            "    elif m == 'session/new':\n"
            "        send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'sessionId': 's1'}})\n"
            "    elif m == 'session/prompt':\n"
            + tail_after_prompt +
            "    elif m == 'session/close':\n"
            "        send({'jsonrpc': '2.0', 'id': r['id'], 'result': {}})\n"
        )
        return (sys.executable, "-c", script)

    def _methods(self, logfile):
        with open(logfile) as fh:
            return fh.read().split()

    def test_success_order_and_close_request(self):
        import os
        log = os.path.join(tempfile.mkdtemp(), "m.log")
        tail = (
            "        send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 's1', 'update': {'sessionUpdate': 'available_commands_update', 'availableCommands': []}}})\n"
            "        send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 's1', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'ok'}}}})\n"
            "        send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'stopReason': 'end_turn'}})\n"
        )
        t = AcpStdioStaticTransport(PROFILES["openai"](), self._agent(log, tail))
        res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(envelope("openai"), cwd=tempfile.gettempdir())
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertEqual(self._methods(log), ["initialize", "session/new", "session/prompt", "session/close"])
        self.assertEqual((t.spawn_count, t.close_requests, t.cancel_sent), (1, 1, 0))

    def test_timeout_sends_cancel_then_closes_and_no_retry(self):
        import os
        log = os.path.join(tempfile.mkdtemp(), "m.log")
        t = AcpStdioStaticTransport(PROFILES["anthropic"](), self._agent(log, "        pass\n"))
        res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(envelope("anthropic", timeout=1), cwd=tempfile.gettempdir())
        self.assertEqual(res.state, RelayState.TIMEOUT)
        self.assertEqual(self._methods(log), ["initialize", "session/new", "session/prompt", "session/cancel"])
        self.assertEqual((t.spawn_count, t.prompt_count, t.cancel_sent), (1, 1, 1))

    def test_tool_call_update_and_agent_request_fail_closed(self):
        import os
        for tail in (
            "        send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 's1', 'update': {'sessionUpdate': 'tool_call', 'toolCallId': 'x'}}})\n",
            "        send({'jsonrpc': '2.0', 'id': 99, 'method': 'session/request_permission', 'params': {'sessionId': 's1'}})\n",
        ):
            with self.subTest(tail=tail):
                log = os.path.join(tempfile.mkdtemp(), "m.log")
                t = AcpStdioStaticTransport(PROFILES["google"](), self._agent(log, tail))
                res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(envelope("google"), cwd=tempfile.gettempdir())
                self.assertEqual(res.state, RelayState.UNKNOWN)
                self.assertIsNone(res.raw)
                self.assertNotIn("permission", " ".join(self._methods(log)))


class TestOfficialAdapterLaunchGuards(unittest.TestCase):
    def _launch(self, pid, **over):
        from pathlib import Path
        from relay.acp_stdio_relay_transport import OfficialAdapterLaunch
        root = Path(__file__).resolve().parents[2] / "fixtures" / "relay"
        gate = Path(__file__).resolve().parents[2] / "src" / "relay" / "codex_turn_gate.py"
        env = {"CODEX_PATH": str(gate), "RELAY_GATE_BACKEND": str(root / "fake_codex_app_server.py")}
        env.update(over.pop("env", {}))
        return OfficialAdapterLaunch(over.pop("command", ("node", "x/codex-acp/dist/index.js")), env, over.pop("root", root))

    def test_openai_official_launch_accepted_with_fixture_backend(self):
        AcpStdioStaticTransport(PROFILES["openai"](), official=self._launch("openai"))

    def test_claude_and_antigravity_have_no_verified_seam(self):
        for pid, cmd in (("anthropic", ("node", "claude-agent-acp/dist/index.js")), ("google", ("./agy_acp_server.par",))):
            with self.subTest(pid):
                with self.assertRaisesRegex(ValueError, "UNKNOWN / LIVE_BOUNDARY"):
                    AcpStdioStaticTransport(PROFILES[pid](), official=self._launch(pid, command=cmd))

    def test_backend_outside_fixture_root_or_credentials_refused(self):
        with self.assertRaises(ValueError):
            AcpStdioStaticTransport(PROFILES["openai"](), official=self._launch("openai", env={"RELAY_GATE_BACKEND": "/usr/bin/env"}))
        # un-gated launch (backend wired directly as CODEX_PATH) is refused
        with self.assertRaisesRegex(ValueError, "one-generation gate"):
            AcpStdioStaticTransport(PROFILES["openai"](), official=self._launch(
                "openai", env={"CODEX_PATH": self._launch("openai").env["RELAY_GATE_BACKEND"]}))
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "MODEL_PROVIDER", "CODEX_CONFIG"):
            with self.subTest(key):
                with self.assertRaises(ValueError):
                    AcpStdioStaticTransport(PROFILES["openai"](), official=self._launch("openai", env={key: "x"}))

    def test_command_and_official_are_exclusive(self):
        with self.assertRaises(ValueError):
            AcpStdioStaticTransport(PROFILES["openai"](), ("python",), official=self._launch("openai"))
        with self.assertRaises(ValueError):
            AcpStdioStaticTransport(PROFILES["openai"]())


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


class TestOfficialCodexAdapterWithFixtureBackend(unittest.TestCase):
    """Real official codex-acp + fixture app-server. Skipped unless RELAY_CODEX_ACP_DIR is set.

    RELAY_CODEX_ACP_DIR = .../node_modules/@agentclientprotocol/codex-acp (npm install
    --ignore-scripts --omit=optional). The adapter's backend is the fixture via CODEX_PATH,
    so the bundled Codex is never executed and no provider/model is reachable.
    """

    def setUp(self):
        import os
        import shutil
        self.dir = os.environ.get("RELAY_CODEX_ACP_DIR")
        if not self.dir or not shutil.which("node"):
            self.skipTest("RELAY_CODEX_ACP_DIR / node not available (TEST_ENVIRONMENT_NOT_PREPARED)")

    def test_lifecycle_through_official_adapter(self):
        import os
        from pathlib import Path
        from relay.acp_stdio_relay_transport import OfficialAdapterLaunch
        root = Path(__file__).resolve().parents[2] / "fixtures" / "relay"
        home = tempfile.mkdtemp()
        log = os.path.join(home, "backend.log")
        env = {
            "HOME": home, "CODEX_HOME": home, "APP_SERVER_LOGS": home, "FAKE_CODEX_LOG": log,
            "CODEX_PATH": str(root.parents[1] / "src" / "relay" / "codex_turn_gate.py"),
            "RELAY_GATE_BACKEND": str(root / "fake_codex_app_server.py"),
            "RELAY_GATE_LOG": os.path.join(home, "gate.log"),
        }
        launch = OfficialAdapterLaunch(("node", os.path.join(self.dir, "dist", "index.js")), env, root)
        t = AcpStdioStaticTransport(PROFILES["openai"](), official=launch)
        res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(
            envelope("openai", timeout=20), cwd=home
        )
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertIn(b"fake codex reply", res.raw)
        with open(log) as fh:
            methods = fh.read().split()
        self.assertEqual(methods[0], "initialize")
        # One Relay request -> exactly one generation reaches the backend; any
        # upstream-initiated extra turn (title generation) is stopped by the gate.
        self.assertEqual(methods.count("turn/start"), 1)
        self.assertEqual((t.spawn_count, t.prompt_count), (1, 1))
        adapter = RelayCoreAdapter("openai", RelayProviderAdapterBridge(), PROFILES["openai"]().static_preflight_config)
        self.assertTrue(adapter.classify(res.raw)["success"])


class TestOfficialTckFixtureAgentThroughLifecycle(unittest.TestCase):
    """acp-tck's bundled conforming v1 fixture agent (offline, stdlib, no provider).

    Skipped unless RELAY_ACP_TCK_FIXTURE points at tests/fixtures/agents/v1/conforming.py.
    This is an ACP-conformant fixture, NOT the official Claude/Antigravity adapter.
    """

    def setUp(self):
        import os
        self.fixture = os.environ.get("RELAY_ACP_TCK_FIXTURE")
        if not self.fixture:
            self.skipTest("RELAY_ACP_TCK_FIXTURE not set (TEST_ENVIRONMENT_NOT_PREPARED)")

    def test_three_profiles_success_cancel_isolation(self):
        for pid in PROFILES:
            with self.subTest(pid):
                t = AcpStdioStaticTransport(PROFILES[pid](), (sys.executable, self.fixture))
                res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(
                    envelope(pid), cwd=tempfile.gettempdir()
                )
                self.assertEqual(res.state, RelayState.SIMULATED)
                self.assertEqual((t.spawn_count, t.prompt_count, t.cancel_sent), (1, 1, 0))
                adapter = RelayCoreAdapter(pid, RelayProviderAdapterBridge(), PROFILES[pid]().static_preflight_config)
                self.assertTrue(adapter.classify(res.raw)["success"])


class TestCodexAdapterContract(unittest.TestCase):
    """Relay<->ACP contract against official codex-acp + gate + fixture backend.

    Skipped unless RELAY_CODEX_ACP_DIR is set. Backend log = what reached the fixture.
    """

    def setUp(self):
        import os
        import shutil
        self.dir = os.environ.get("RELAY_CODEX_ACP_DIR")
        if not self.dir or not shutil.which("node"):
            self.skipTest("RELAY_CODEX_ACP_DIR / node not available (TEST_ENVIRONMENT_NOT_PREPARED)")
        self.home = tempfile.mkdtemp()

    def _env(self, gated=True, **extra):
        import os
        from pathlib import Path
        repo = Path(__file__).resolve().parents[2]
        fake = str(repo / "fixtures" / "relay" / "fake_codex_app_server.py")
        env = {
            "HOME": self.home, "CODEX_HOME": self.home, "APP_SERVER_LOGS": self.home,
            "FAKE_CODEX_LOG": os.path.join(self.home, "backend.log"),
            "RELAY_GATE_LOG": os.path.join(self.home, "gate.log"),
            "RELAY_GATE_BACKEND": fake,
            "CODEX_PATH": str(repo / "src" / "relay" / "codex_turn_gate.py") if gated else fake,
        }
        env.update(extra)
        return env

    def _adapter(self):
        import os
        return ("node", os.path.join(self.dir, "dist", "index.js"))

    def _transport(self, **extra):
        from pathlib import Path
        from relay.acp_stdio_relay_transport import OfficialAdapterLaunch
        root = Path(__file__).resolve().parents[2] / "fixtures" / "relay"
        launch = OfficialAdapterLaunch(self._adapter(), self._env(**extra), root)
        return AcpStdioStaticTransport(PROFILES["openai"](), official=launch)

    def _backend(self, name="backend.log"):
        import os
        path = os.path.join(self.home, name)
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            return fh.read().split()

    @staticmethod
    def _read(path):
        with open(path) as fh:
            return fh.read()

    def _wait_for(self, predicate, seconds=5.0):
        import time
        end = time.time() + seconds
        while time.time() < end:
            if predicate():
                return True
            time.sleep(0.05)
        return predicate()

    def test_upstream_title_second_turn_is_reproduced_without_gate(self):
        """Canary: documents upstream behavior. If this fails, upstream changed; re-audit."""
        import asyncio
        from relay.acp_client import acp_mock_text_update_wire
        asyncio.run(acp_mock_text_update_wire(
            *self._adapter(), cwd=self.home, prompt_text="hi", timeout=20.0, env=self._env(gated=False)))
        self.assertTrue(self._wait_for(lambda: self._backend().count("turn/start") >= 2),
                        "BLOCKED_TITLE_GENERATION_SECOND_TURN canary: second turn/start no longer observed")

    def test_gate_limits_backend_to_one_generation_and_blocks_title_turn(self):
        import asyncio
        import json
        import os
        from relay.acp_client import acp_mock_text_update_wire
        asyncio.run(acp_mock_text_update_wire(
            *self._adapter(), cwd=self.home, prompt_text="hi", timeout=20.0, env=self._env()))
        gate_log = os.path.join(self.home, "gate.log")
        self.assertTrue(self._wait_for(lambda: os.path.exists(gate_log) and "blocked" in self._read(gate_log)))
        with open(gate_log) as fh:
            decisions = [json.loads(line)["decision"] for line in fh if line.strip()]
        self.assertEqual(decisions, ["allowed", "blocked"])
        self.assertEqual(self._backend().count("turn/start"), 1)

    def test_initialize_and_session_new_start_no_generation(self):
        t = self._transport()
        t.initialize("openai")
        sid = t.open_session("openai", cwd=self.home)
        methods = self._backend()
        for gen in ("turn/start", "review/start", "thread/compact/start", "turn/steer", "thread/goal/set"):
            self.assertNotIn(gen, methods)
        self.assertEqual(t.prompt_count, 0)
        t.close("openai", sid)

    def test_cancel_and_close_are_bounded_and_do_not_relaunch(self):
        import time
        t = self._transport(FAKE_CODEX_NO_COMPLETE="1")
        t.initialize("openai")
        sid = t.open_session("openai", cwd=self.home)
        started = time.time()
        t.cancel("openai", sid)
        t.close("openai", sid)
        self.assertLess(time.time() - started, 10)
        self.assertEqual((t.spawn_count, self._backend().count("initialize")), (1, 1))

    def test_timeout_cancels_without_relaunch_or_retry(self):
        t = self._transport(FAKE_CODEX_NO_COMPLETE="1")
        res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(
            envelope("openai", timeout=2), cwd=self.home)
        self.assertEqual(res.state, RelayState.TIMEOUT)
        self.assertEqual((t.spawn_count, t.prompt_count, t.cancel_sent), (1, 1, 1))
        methods = self._backend()
        self.assertEqual((methods.count("initialize"), methods.count("turn/start")), (1, 1))
        self.assertIn("turn/interrupt", methods)

    def test_duplicate_and_conflict_start_no_new_process_or_generation(self):
        t = self._transport()
        lc = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard())
        self.assertEqual(lc.dispatch_mock(envelope("openai", timeout=20), cwd=self.home).state, RelayState.SIMULATED)
        dup = lc.dispatch_mock(envelope("openai", timeout=20), cwd=self.home)
        conflict = lc.dispatch_mock(envelope("openai", prompt="different", timeout=20), cwd=self.home)
        self.assertEqual((dup.state, conflict.state), (RelayState.BLOCKED, RelayState.BLOCKED))
        methods = self._backend()
        self.assertEqual((t.spawn_count, methods.count("initialize"), methods.count("turn/start")), (1, 1, 1))
