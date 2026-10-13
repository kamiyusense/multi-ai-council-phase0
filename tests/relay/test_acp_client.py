import json
import os
import sys
import tempfile
import unittest

from providers.policy import ProviderPolicy
from relay.acp_client import ACPClient, acp_initialize_wire
from relay.duplicate_guard import DuplicateGuard
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.lifecycle import RelayLifecycle


def make_policy(provider_id: str = "test") -> ProviderPolicy:
    return ProviderPolicy(
        provider_id=provider_id,
        external_agent="test-agent",
        pinned_version="1.0.0",
        required_auth_kind="account",
    )


class TestACPClient(unittest.TestCase):
    def setUp(self):
        self.client = ACPClient(policy=make_policy())

    def test_initialize_success(self):
        result = self.client.initialize("test")
        self.assertEqual(
            result,
            {
                "protocol_version": 1,
                "provider_id": "test",
                "mode": "acp_mock",
                "live_process_started": False,
            },
        )

    def test_initialize_requires_policy(self):
        with self.assertRaisesRegex(ValueError, "ProviderPolicy is required"):
            ACPClient().initialize("test")

    def test_initialize_rejects_provider_policy_mismatch(self):
        with self.assertRaisesRegex(ValueError, "provider_id does not match ProviderPolicy"):
            self.client.initialize("other")

    def test_initialize_rejects_non_account_auth(self):
        client = ACPClient(
            init_fixture_path="fixtures/relay/acp_initialize_unsupported.json",
            policy=make_policy(),
        )
        with self.assertRaisesRegex(ValueError, "unsupported auth kind"):
            client.initialize("test")

    def test_initialize_rejects_wrong_protocol_and_bad_capability(self):
        for payload, message in (
            (
                {
                    "protocol_version": 2,
                    "live_process_started": False,
                    "auth": {"kind": "account"},
                    "capabilities": {},
                },
                "Protocol version must be 1",
            ),
            (
                {
                    "protocol_version": 1,
                    "live_process_started": False,
                    "auth": {"kind": "account"},
                    "capabilities": {"terminal": []},
                },
                "Unsupported capability shape",
            ),
        ):
            with tempfile.TemporaryDirectory() as tmp_dir:
                fixture_path = os.path.join(tmp_dir, "init.json")
                with open(fixture_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                client = ACPClient(init_fixture_path=fixture_path, policy=make_policy())
                with self.assertRaisesRegex(ValueError, message):
                    client.initialize("test")

    def test_initialize_rejects_live_process_claim(self):
        payload = {
            "protocol_version": 1,
            "live_process_started": True,
            "auth": {"kind": "account"},
            "capabilities": {},
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            fixture_path = os.path.join(tmp_dir, "init.json")
            with open(fixture_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            client = ACPClient(init_fixture_path=fixture_path, policy=make_policy())
            with self.assertRaisesRegex(ValueError, "live_process_started must be false"):
                client.initialize("test")

    def test_no_named_temporary_file_without_delete_false(self):
        import ast
        with open(__file__, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=__file__)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name == "NamedTemporaryFile":
                    has_delete_false = any(
                        kw.arg == "delete"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value is False
                        for kw in node.keywords
                    )
                    self.assertTrue(
                        has_delete_false,
                        "NamedTemporaryFile calls in test_acp_client.py must pass delete=False",
                    )

    def test_deterministic_session_ids(self):
        s1 = self.client.open_session("test", cwd="/")
        s2 = self.client.open_session("test", cwd="/")
        self.assertEqual(s1, "acp-mock:test:1")
        self.assertEqual(s2, "acp-mock:test:2")

    def test_exact_raw_terminal_bytes(self):
        s1 = self.client.open_session("test", cwd="/")
        self.client.configured_responses[s1] = b"raw_bytes"
        self.assertEqual(self.client.prompt("test", s1, {}), b"raw_bytes")

    def test_missing_or_malformed_terminal_fails_closed(self):
        s1 = self.client.open_session("test", cwd="/")
        with self.assertRaisesRegex(ValueError, "Terminal response"):
            self.client.prompt("test", s1, {})

        malformed_values = [None, "text", 1, ["x"], {"x": 1}]
        for value in malformed_values:
            client = ACPClient(policy=make_policy())
            sid = client.open_session("test", cwd="/")
            client.configured_responses[sid] = value  # type: ignore[assignment]
            with self.assertRaisesRegex(ValueError, "Terminal response"):
                client.prompt("test", sid, {})

    def test_timeout_and_error_raise(self):
        s1 = self.client.open_session("test", cwd="/")
        with self.assertRaises(TimeoutError):
            self.client.prompt("test", s1, {"timeout": True})

        s2 = self.client.open_session("test", cwd="/")
        with self.assertRaises(RuntimeError):
            self.client.prompt("test", s2, {"error": True})

    def test_evidence_is_separate_and_deepcopied(self):
        s1 = self.client.open_session("test", cwd="/")
        terminal = b'{"answer":"raw"}'
        update = {"event": "start", "data": {"k": "v"}}
        self.client.configured_responses[s1] = terminal
        self.client.configured_updates[s1] = [update]

        returned = self.client.prompt("test", s1, {})
        self.assertEqual(returned, terminal)
        self.assertEqual(self.client.get_evidence(s1), [update])

        update["data"]["k"] = "changed"
        evidence = self.client.get_evidence(s1)
        self.assertEqual(evidence[0]["data"]["k"], "v")
        evidence[0]["data"]["k"] = "local-change"
        self.assertEqual(self.client.get_evidence(s1)[0]["data"]["k"], "v")

    def test_malformed_update_rejected_before_success(self):
        s1 = self.client.open_session("test", cwd="/")
        self.client.configured_responses[s1] = b"ok"
        self.client.configured_updates[s1] = ["not-a-dict"]  # type: ignore[list-item]
        with self.assertRaisesRegex(ValueError, "Malformed update"):
            self.client.prompt("test", s1, {})

    def test_each_safety_callback_denies_and_snapshots(self):
        cases = (
            ("permission_callback", "permission_calls"),
            ("file_read_callback", "file_read_calls"),
            ("file_write_callback", "file_write_calls"),
            ("terminal_request_callback", "terminal_request_calls"),
            ("elicitation_callback", "elicitation_calls"),
            ("unknown_extension_callback", "unknown_extension_calls"),
        )
        for method_name, storage_name in cases:
            req = {"nested": {"v": 1}}
            self.assertFalse(getattr(self.client, method_name)(req))
            req["nested"]["v"] = 2
            self.assertEqual(getattr(self.client, storage_name)[0]["nested"]["v"], 1)

    def test_wrong_provider_and_terminal_states(self):
        s1 = self.client.open_session("test", cwd="/")
        with self.assertRaisesRegex(ValueError, "Wrong provider"):
            self.client.prompt("other", s1, {})

        self.client.cancel("test", s1)
        with self.assertRaisesRegex(ValueError, "Session is not open"):
            self.client.prompt("test", s1, {})
        with self.assertRaisesRegex(ValueError, "already closed/cancelled"):
            self.client.cancel("test", s1)

        self.client.close("test", s1)
        with self.assertRaisesRegex(ValueError, "Session is not open"):
            self.client.prompt("test", s1, {})
        with self.assertRaisesRegex(ValueError, "Session already closed"):
            self.client.close("test", s1)

    def test_second_prompt_rejected(self):
        s1 = self.client.open_session("test", cwd="/")
        self.client.configured_responses[s1] = b"ok"
        self.client.prompt("test", s1, {})
        with self.assertRaisesRegex(ValueError, "Session already prompted"):
            self.client.prompt("test", s1, {})


class RecordingACPClient(ACPClient):
    def __init__(self):
        super().__init__(policy=make_policy())
        self.cancel_calls: list[tuple[str, str]] = []
        self.close_calls: list[tuple[str, str]] = []

    def cancel(self, provider_id: str, session_id: str) -> None:
        self.cancel_calls.append((provider_id, session_id))
        super().cancel(provider_id, session_id)

    def close(self, provider_id: str, session_id: str) -> None:
        self.close_calls.append((provider_id, session_id))
        super().close(provider_id, session_id)


class TestRelayLifecycleIntegration(unittest.TestCase):
    @staticmethod
    def envelope(payload: dict, sequence: int = 0) -> DispatchEnvelope:
        return DispatchEnvelope.build(
            slot=DispatchSlot("case", "test", sequence),
            correlation_id=f"corr-{sequence}",
            payload=payload,
        )

    def test_timeout_after_session_cancels_once_and_closes_once(self):
        client = RecordingACPClient()
        lifecycle = RelayLifecycle(client, DuplicateGuard())
        result = lifecycle.dispatch_mock(self.envelope({"timeout": True}), cwd="/")
        self.assertEqual(result.state.name, "TIMEOUT")
        self.assertIsNotNone(result.session_id)
        self.assertEqual(client.cancel_calls, [("test", result.session_id)])
        self.assertEqual(client.close_calls, [("test", result.session_id)])

    def test_error_after_session_cancels_once_and_closes_once(self):
        client = RecordingACPClient()
        lifecycle = RelayLifecycle(client, DuplicateGuard())
        result = lifecycle.dispatch_mock(self.envelope({"error": True}), cwd="/")
        self.assertEqual(result.state.name, "UNKNOWN")
        self.assertIsNotNone(result.session_id)
        self.assertEqual(client.cancel_calls, [("test", result.session_id)])
        self.assertEqual(client.close_calls, [("test", result.session_id)])

    def test_stop_before_dispatch_creates_no_session(self):
        client = RecordingACPClient()
        lifecycle = RelayLifecycle(client, DuplicateGuard())
        lifecycle.request_stop()
        result = lifecycle.dispatch_mock(self.envelope({}), cwd="/")
        self.assertEqual(result.state.name, "BLOCKED")
        self.assertEqual(client._session_count, 0)

    def test_duplicate_same_envelope_creates_no_second_session_or_prompt(self):
        client = RecordingACPClient()
        lifecycle = RelayLifecycle(client, DuplicateGuard())
        env = self.envelope({})
        client.configured_responses["acp-mock:test:1"] = b"ok"

        first = lifecycle.dispatch_mock(env, cwd="/")
        self.assertEqual(first.state.name, "SIMULATED")
        self.assertEqual(client._session_count, 1)
        prompted_before = sum(1 for item in client._sessions.values() if item["prompted"])
        self.assertEqual(prompted_before, 1)

        second = lifecycle.dispatch_mock(env, cwd="/")
        self.assertEqual(second.state.name, "BLOCKED")
        self.assertEqual(client._session_count, 1)
        prompted_after = sum(1 for item in client._sessions.values() if item["prompted"])
        self.assertEqual(prompted_after, 1)


class TestACPInitializeWire(unittest.IsolatedAsyncioTestCase):
    async def test_success_roundtrip(self):
        # A mock child process that reads one line and returns a valid initialize response
        script = (
            "import sys, json\n"
            "req = json.loads(sys.stdin.readline())\n"
            "assert req == {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': "
            "{'protocolVersion': 1, 'clientCapabilities': {}, "
            "'clientInfo': {'name': 'relay', 'version': '0.1.0'}}}, req\n"
            "resp = {'jsonrpc': '2.0', 'id': req['id'], 'result': {'protocolVersion': 1, 'capabilities': {}}}\n"
            "sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        result = await acp_initialize_wire(sys.executable, "-c", script)
        self.assertEqual(result, {'protocolVersion': 1, 'capabilities': {}})

    async def test_timeout_fails_closed(self):
        script = "import time\ntime.sleep(10)\n"
        with self.assertRaisesRegex(TimeoutError, "Timeout reading ACP initialize response"):
            await acp_initialize_wire(sys.executable, "-c", script, timeout=0.1)

    async def test_eof_fails_closed(self):
        script = "import sys\nsys.exit(0)\n"
        with self.assertRaisesRegex(EOFError, "Unexpected EOF reading ACP initialize response"):
            await acp_initialize_wire(sys.executable, "-c", script)

    async def test_malformed_json_fails_closed(self):
        script = "import sys\nsys.stdout.write('not json\\n')\nsys.stdout.flush()\n"
        with self.assertRaisesRegex(ValueError, "Malformed JSON"):
            await acp_initialize_wire(sys.executable, "-c", script)

    async def test_wrong_jsonrpc_version(self):
        script = (
            "import sys, json\n"
            "resp = {'jsonrpc': '1.0', 'id': 0, 'result': {'protocolVersion': 1}}\n"
            "sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(ValueError, "must have jsonrpc='2.0'"):
            await acp_initialize_wire(sys.executable, "-c", script)

    async def test_wrong_id(self):
        script = (
            "import sys, json\n"
            "resp = {'jsonrpc': '2.0', 'id': 1, 'result': {'protocolVersion': 1}}\n"
            "sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            await acp_initialize_wire(sys.executable, "-c", script)

    async def test_error_response_raises(self):
        script = (
            "import sys, json\n"
            "resp = {'jsonrpc': '2.0', 'id': 0, 'error': {'code': -32000, 'message': 'test error'}}\n"
            "sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(RuntimeError, "returned error"):
            await acp_initialize_wire(sys.executable, "-c", script)

    async def test_missing_result(self):
        script = (
            "import sys, json\n"
            "resp = {'jsonrpc': '2.0', 'id': 0}\n"
            "sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(ValueError, "missing valid result object"):
            await acp_initialize_wire(sys.executable, "-c", script)

    async def test_boolean_id_is_not_accepted(self):
        script = (
            "import sys, json\n"
            "sys.stdin.readline()\n"
            "resp = {'jsonrpc': '2.0', 'id': False, 'result': {'protocolVersion': 1}}\n"
            "sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            await acp_initialize_wire(sys.executable, "-c", script)

    async def test_string_protocol_version_is_not_accepted(self):
        script = (
            "import sys, json\n"
            "resp = {'jsonrpc': '2.0', 'id': 0, 'result': {'protocolVersion': '1'}}\n"
            "sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(ValueError, "unsupported protocol version"):
            await acp_initialize_wire(sys.executable, "-c", script)


class TestACPMockPromptWire(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.handshake_script = (
            "import sys, json\n"
            "req1 = json.loads(sys.stdin.readline())\n"
            "assert req1 == {\'jsonrpc\': \'2.0\', \'id\': 0, \'method\': \'initialize\', \'params\': {\'protocolVersion\': 1, \'clientCapabilities\': {}, \'clientInfo\': {\'name\': \'relay\', \'version\': \'0.1.0\'}}}, req1\n"
            "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'result': {'protocolVersion': 1, 'capabilities': {}}}\n"
            "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
            "sys.stdout.flush()\n"
            "req2 = json.loads(sys.stdin.readline())\n"
            "assert req2['method'] == 'session/new'\n"
            "assert req2['id'] == 1\n"
            f"assert req2['params']['cwd'] == {tempfile.gettempdir()!r}\n"
            "assert req2['params']['mcpServers'] == []\n"
            "resp2 = {'jsonrpc': '2.0', 'id': req2['id'], 'result': {'sessionId': 'session-123'}}\n"
            "sys.stdout.write(json.dumps(resp2) + '\\n')\n"
            "sys.stdout.flush()\n"
        )

    async def test_success_roundtrip(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "assert req3['params']['sessionId'] == 'session-123'\n"
            "assert req3['params']['prompt'] == [{'type': 'text', 'text': 'hello fake'}]\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        result = await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")
        self.assertEqual(result, "end_turn")

    async def test_missing_stop_reason(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(ValueError, "missing valid stopReason"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_blank_stop_reason(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': '   '}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(ValueError, "missing valid stopReason"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_wrong_id(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': 99, 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_error_response_raises(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'error': {'code': -1, 'message': 'prompt error'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(RuntimeError, "returned error"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_timeout_fails_closed(self):
        script = self.handshake_script + (
            "import time\n"
            "time.sleep(10)\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(TimeoutError, "Timeout reading ACP session/prompt response"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake", timeout=0.1)

    async def test_initialize_failure_prevents_prompt(self):
        script = (
            "import sys, json\n"
            "req1 = json.loads(sys.stdin.readline())\n"
            "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'error': {'code': -1, 'message': 'init error'}}\n"
            "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
            "sys.stdout.flush()\n"
            "req2 = sys.stdin.readline()\n"
            "if req2:\n"
            "    sys.exit(1)\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(RuntimeError, "ACP initialize returned error"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")


    async def test_bool_prompt_response_id_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': True, 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_missing_prompt_result_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id']}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(ValueError, "missing valid result object"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_invalid_session_never_sends_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, "unexpected-prompt")
            script = (
                "import sys, json\n"
                "req1 = json.loads(sys.stdin.readline())\n"
                "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'result': {'protocolVersion': 1}}\n"
                "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
                "sys.stdout.flush()\n"
                "req2 = json.loads(sys.stdin.readline())\n"
                "resp2 = {'jsonrpc': '2.0', 'id': req2['id'], 'result': {'sessionId': ' '}}\n"
                "sys.stdout.write(json.dumps(resp2) + '\\n')\n"
                "sys.stdout.flush()\n"
                "req3 = sys.stdin.readline()\n"
                f"if req3: open({marker!r}, 'w').write(req3)\n"
            )
            from src.relay.acp_client import acp_mock_prompt_wire
            with self.assertRaisesRegex(ValueError, "missing valid sessionId"):
                await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tmp, prompt_text="hello fake")
            self.assertFalse(os.path.exists(marker), "session/prompt was sent after failed session/new")



    async def test_invalid_stop_reason_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'endTurn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_prompt_wire
        with self.assertRaisesRegex(ValueError, "missing valid stopReason"):
            await acp_mock_prompt_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

class TestACPOpenSessionWire(unittest.IsolatedAsyncioTestCase):
    async def test_success_roundtrip(self):
        script = (
            "import sys, json\n"
            "req1 = json.loads(sys.stdin.readline())\n"
            "assert req1 == {\'jsonrpc\': \'2.0\', \'id\': 0, \'method\': \'initialize\', \'params\': {\'protocolVersion\': 1, \'clientCapabilities\': {}, \'clientInfo\': {\'name\': \'relay\', \'version\': \'0.1.0\'}}}, req1\n"
            "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'result': {'protocolVersion': 1, 'capabilities': {}}}\n"
            "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
            "sys.stdout.flush()\n"
            "req2 = json.loads(sys.stdin.readline())\n"
            "assert req2['method'] == 'session/new'\n"
            "assert req2['id'] == 1\n"
            f"assert req2['params']['cwd'] == {tempfile.gettempdir()!r}\n"
            "assert req2['params']['mcpServers'] == []\n"
            "resp2 = {'jsonrpc': '2.0', 'id': req2['id'], 'result': {'sessionId': 'session-123'}}\n"
            "sys.stdout.write(json.dumps(resp2) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_open_session_wire
        result = await acp_open_session_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir())
        self.assertEqual(result, "session-123")

    async def test_missing_session_id(self):
        script = (
            "import sys, json\n"
            "req1 = json.loads(sys.stdin.readline())\n"
            "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'result': {'protocolVersion': 1, 'capabilities': {}}}\n"
            "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
            "sys.stdout.flush()\n"
            "req2 = json.loads(sys.stdin.readline())\n"
            "resp2 = {'jsonrpc': '2.0', 'id': req2['id'], 'result': {}}\n"
            "sys.stdout.write(json.dumps(resp2) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_open_session_wire
        with self.assertRaisesRegex(ValueError, "missing valid sessionId"):
            await acp_open_session_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir())

    async def test_blank_session_id(self):
        script = (
            "import sys, json\n"
            "req1 = json.loads(sys.stdin.readline())\n"
            "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'result': {'protocolVersion': 1, 'capabilities': {}}}\n"
            "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
            "sys.stdout.flush()\n"
            "req2 = json.loads(sys.stdin.readline())\n"
            "resp2 = {'jsonrpc': '2.0', 'id': req2['id'], 'result': {'sessionId': '   '}}\n"
            "sys.stdout.write(json.dumps(resp2) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_open_session_wire
        with self.assertRaisesRegex(ValueError, "missing valid sessionId"):
            await acp_open_session_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir())

    async def test_session_new_timeout(self):
        script = (
            "import sys, json, time\n"
            "req1 = json.loads(sys.stdin.readline())\n"
            "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'result': {'protocolVersion': 1, 'capabilities': {}}}\n"
            "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
            "sys.stdout.flush()\n"
            "time.sleep(10)\n"
        )
        from src.relay.acp_client import acp_open_session_wire
        with self.assertRaisesRegex(TimeoutError, "Timeout reading ACP session/new response"):
            await acp_open_session_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), timeout=0.1)

    async def test_initialize_failure_aborts_early(self):
        script = (
            "import sys, json\n"
            "req1 = json.loads(sys.stdin.readline())\n"
            "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'error': {'code': -1, 'message': 'init error'}}\n"
            "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
            "sys.stdout.flush()\n"
            "req2 = sys.stdin.readline()\n"
            "if req2:\n"
            "    sys.exit(1)\n"
        )
        from src.relay.acp_client import acp_open_session_wire
        with self.assertRaisesRegex(RuntimeError, "ACP initialize returned error"):
            await acp_open_session_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir())

    async def test_wrong_protocol_version(self):
        script = (
            "import sys, json\n"
            "resp = {'jsonrpc': '2.0', 'id': 0, 'result': {'protocolVersion': '2'}}\n"
            "sys.stdout.write(json.dumps(resp) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(ValueError, "unsupported protocol version"):
            await acp_initialize_wire(sys.executable, "-c", script)


class TestACPMockTextUpdateWire(unittest.IsolatedAsyncioTestCase):
    handshake_script = (
        "import sys, json\n"
        "req1 = json.loads(sys.stdin.readline())\n"
        "assert req1 == {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'protocolVersion': 1, 'clientCapabilities': {}, 'clientInfo': {'name': 'relay', 'version': '0.1.0'}}}, req1\n"
        "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'result': {'protocolVersion': 1, 'capabilities': {}}}\n"
        "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
        "sys.stdout.flush()\n"
        "req2 = json.loads(sys.stdin.readline())\n"
        "assert req2['method'] == 'session/new' and req2['id'] == 1, req2\n"
        f"assert req2['params'] == {{'cwd': {tempfile.gettempdir()!r}, 'mcpServers': []}}, req2\n"
        "resp2 = {'jsonrpc': '2.0', 'id': req2['id'], 'result': {'sessionId': 'session-123'}}\n"
        "sys.stdout.write(json.dumps(resp2) + '\\n')\n"
        "sys.stdout.flush()\n"
    )

    async def test_success_roundtrip(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "assert req3['params']['sessionId'] == 'session-123'\n"
            "assert req3['params']['prompt'] == [{'type': 'text', 'text': 'hello fake'}]\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake result'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        result = await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")
        self.assertEqual(result, {"text": "fake result", "stopReason": "end_turn"})

    async def test_wrong_session_id(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'wrong-id', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake result'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(ValueError, "sessionId mismatch"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_invalid_content(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'image'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(ValueError, "content type must be 'text'"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_wrong_terminal_id(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake result'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': 99, 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_timeout_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake result'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "sys.stdout.flush()\n"
            "import time\n"
            "time.sleep(10)\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(TimeoutError, "Timeout reading ACP session/prompt response"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake", timeout=0.1)

    async def test_eof_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake result'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(EOFError, "Unexpected EOF reading ACP session/prompt response"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_early_terminal_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(ValueError, "must not have an id field"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_invalid_stop_reason(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake result'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'endTurn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(ValueError, "missing valid stopReason"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_bad_notification_shapes_fail_closed(self):
        from src.relay.acp_client import acp_mock_text_update_wire

        base = {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "session-123",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "fake result"},
                },
            },
        }
        for case, expected in (
            ("notification_has_id", "must not have an id field"),
            ("wrong_method", "notification method"),
            ("wrong_update_kind", "notification sessionUpdate"),
            ("missing_text", "missing valid text string"),
        ):
            with self.subTest(case=case):
                notif = json.loads(json.dumps(base))
                if case == "notification_has_id":
                    notif["id"] = None
                elif case == "wrong_method":
                    notif["method"] = "session/other"
                elif case == "wrong_update_kind":
                    notif["params"]["update"]["sessionUpdate"] = "tool_call"
                else:
                    del notif["params"]["update"]["content"]["text"]
                script = self.handshake_script + (
                    "req3 = json.loads(sys.stdin.readline())\n"
                    f"notif = {notif!r}\n"
                    "sys.stdout.write(json.dumps(notif) + '\\n')\n"
                    "sys.stdout.flush()\n"
                )
                with self.assertRaisesRegex(ValueError, expected):
                    await acp_mock_text_update_wire(
                        sys.executable, "-c", script,
                        cwd=tempfile.gettempdir(), prompt_text="hello fake",
                    )

    async def test_bool_terminal_response_id_fails_closed(self):
        from src.relay.acp_client import acp_mock_text_update_wire
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake result'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': True, 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(ValueError, "id mismatch"):
            await acp_mock_text_update_wire(
                sys.executable, "-c", script,
                cwd=tempfile.gettempdir(), prompt_text="hello fake",
            )



    async def test_success_2_chunks(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake '}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "notif2 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'result'}}}}\n"
            "sys.stdout.write(json.dumps(notif2) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        result = await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")
        self.assertEqual(result, {"text": "fake result", "stopReason": "end_turn"})

    async def test_success_3_chunks(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake '}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "notif2 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 're'}}}}\n"
            "sys.stdout.write(json.dumps(notif2) + '\\n')\n"
            "notif3 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'sult'}}}}\n"
            "sys.stdout.write(json.dumps(notif3) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        result = await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")
        self.assertEqual(result, {"text": "fake result", "stopReason": "end_turn"})

    async def test_fourth_chunk_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': '1'}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(ValueError, "Maximum of 3 text updates exceeded"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_missing_chunk_early_terminal_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(ValueError, "must not have an id field"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")

    async def test_valid_first_chunk_then_malformed_fails_closed(self):
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'fake '}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "notif2 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'image'}}}}\n"
            "sys.stdout.write(json.dumps(notif2) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        from src.relay.acp_client import acp_mock_text_update_wire
        with self.assertRaisesRegex(ValueError, "content type must be 'text'"):
            await acp_mock_text_update_wire(sys.executable, "-c", script, cwd=tempfile.gettempdir(), prompt_text="hello fake")


    async def test_second_chunk_wrong_session_fails_closed(self):
        from src.relay.acp_client import acp_mock_text_update_wire
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'valid first'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "notif['params']['sessionId'] = 'other-session'\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(ValueError, "sessionId mismatch"):
            await acp_mock_text_update_wire(
                sys.executable, "-c", script,
                cwd=tempfile.gettempdir(), prompt_text="hello fake",
            )

    async def test_eof_after_two_valid_chunks_fails_closed(self):
        from src.relay.acp_client import acp_mock_text_update_wire
        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'valid first'}}}}\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "notif['params']['update']['content']['text'] = 'valid second'\n"
            "sys.stdout.write(json.dumps(notif) + '\\n')\n"
            "sys.stdout.flush()\n"
        )
        with self.assertRaisesRegex(EOFError, "Unexpected EOF reading ACP session/prompt response"):
            await acp_mock_text_update_wire(
                sys.executable, "-c", script,
                cwd=tempfile.gettempdir(), prompt_text="hello fake",
            )

class TestACPMockTextToPhase0Raw(unittest.TestCase):
    def test_positive_mapping(self):
        from src.relay.acp_client import acp_mock_text_to_phase0_raw
        import json
        mock_result = {"text": "hello 日本語\nworld", "stopReason": "end_turn"}
        raw_bytes = acp_mock_text_to_phase0_raw(mock_result)

        parsed = json.loads(raw_bytes.decode("utf-8"))
        self.assertEqual(set(parsed), {"schema_version", "answer_state", "conclusion_code", "safety_warning", "safety_reason", "evidence_refs", "marker_echoes", "answer_text"})
        self.assertEqual(parsed["schema_version"], "phase0-response-v1")
        self.assertEqual(parsed["answer_state"], "ANSWER")
        self.assertEqual(parsed["conclusion_code"], "SUCCESS")
        self.assertEqual(parsed["safety_warning"], "UNKNOWN")
        self.assertIsNone(parsed["safety_reason"])
        self.assertEqual(parsed["evidence_refs"], [])
        self.assertEqual(parsed["marker_echoes"], {"head": None, "middle": None, "tail": None})
        self.assertEqual(parsed["answer_text"], "hello 日本語\nworld")

        # Test input dict remains unchanged
        self.assertEqual(mock_result, {"text": "hello 日本語\nworld", "stopReason": "end_turn"})

        # Test deterministic repeated mapping bytes equal
        raw_bytes_2 = acp_mock_text_to_phase0_raw(mock_result)
        self.assertEqual(raw_bytes, raw_bytes_2)

    def test_positive_integration_with_core_adapter(self):
        from src.relay.acp_client import acp_mock_text_to_phase0_raw
        from src.relay.core_adapter import RelayCoreAdapter
        from tests.relay.test_core_adapter import RecordingBridge
        import json

        mock_result = {"text": "integration text", "stopReason": "end_turn"}
        raw_bytes = acp_mock_text_to_phase0_raw(mock_result)

        # Instantiate existing RelayCoreAdapter with a mock bridge
        adapter = RelayCoreAdapter("test_provider", RecordingBridge(), {"auth_kind": "mock"})

        # Call pure classify(raw_bytes)
        classification = adapter.classify(raw_bytes)

        self.assertTrue(classification["success"])
        self.assertEqual(classification["execution_state"], "COMPLETE")
        self.assertEqual(classification["participation_state"], "PARTICIPANT")

    def test_negative_wrong_missing_extra_keys(self):
        from src.relay.acp_client import acp_mock_text_to_phase0_raw

        with self.assertRaises(ValueError):
            acp_mock_text_to_phase0_raw({"text": "a"}) # Missing stopReason

        with self.assertRaises(ValueError):
            acp_mock_text_to_phase0_raw({"stopReason": "end_turn"}) # Missing text

        with self.assertRaises(ValueError):
            acp_mock_text_to_phase0_raw({"text": "a", "stopReason": "end_turn", "extra": "b"}) # Extra key

    def test_negative_none_non_dict(self):
        from src.relay.acp_client import acp_mock_text_to_phase0_raw

        with self.assertRaises(TypeError):
            acp_mock_text_to_phase0_raw(None)

        with self.assertRaises(TypeError):
            acp_mock_text_to_phase0_raw(["text", "stopReason"])

    def test_negative_empty_whitespace_text(self):
        from src.relay.acp_client import acp_mock_text_to_phase0_raw

        with self.assertRaises(ValueError):
            acp_mock_text_to_phase0_raw({"text": "", "stopReason": "end_turn"})

        with self.assertRaises(ValueError):
            acp_mock_text_to_phase0_raw({"text": "   \n\t", "stopReason": "end_turn"})

    def test_negative_non_string_text(self):
        from src.relay.acp_client import acp_mock_text_to_phase0_raw

        with self.assertRaises(TypeError):
            acp_mock_text_to_phase0_raw({"text": 123, "stopReason": "end_turn"})

    def test_negative_non_end_turn_stopReason(self):
        from src.relay.acp_client import acp_mock_text_to_phase0_raw

        invalid_reasons = ["refusal", "cancelled", "max_tokens", "max_turn_requests", "endTurn", "unknown"]
        for reason in invalid_reasons:
            with self.subTest(reason=reason):
                with self.assertRaises(ValueError):
                    acp_mock_text_to_phase0_raw({"text": "a", "stopReason": reason})

    def test_negative_non_string_stopReason(self):
        from src.relay.acp_client import acp_mock_text_to_phase0_raw

        with self.assertRaises(TypeError):
            acp_mock_text_to_phase0_raw({"text": "a", "stopReason": True})

class TestACPMockPhase0EndToEnd(unittest.IsolatedAsyncioTestCase):
    handshake_script = (
        "import sys, json\n"
        "req1 = json.loads(sys.stdin.readline())\n"
        "assert req1 == {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'protocolVersion': 1, 'clientCapabilities': {}, 'clientInfo': {'name': 'relay', 'version': '0.1.0'}}}, req1\n"
        "resp1 = {'jsonrpc': '2.0', 'id': req1['id'], 'result': {'protocolVersion': 1, 'capabilities': {}}}\n"
        "sys.stdout.write(json.dumps(resp1) + '\\n')\n"
        "sys.stdout.flush()\n"
        "req2 = json.loads(sys.stdin.readline())\n"
        "assert req2['method'] == 'session/new' and req2['id'] == 1, req2\n"
        f"assert req2['params'] == {{'cwd': {tempfile.gettempdir()!r}, 'mcpServers': []}}, req2\n"
        "resp2 = {'jsonrpc': '2.0', 'id': req2['id'], 'result': {'sessionId': 'session-123'}}\n"
        "sys.stdout.write(json.dumps(resp2) + '\\n')\n"
        "sys.stdout.flush()\n"
    )

    async def test_positive_two_notifications_e2e(self):
        from src.relay.acp_client import acp_mock_text_update_wire, acp_mock_text_to_phase0_raw
        from src.relay.core_adapter import RelayCoreAdapter
        from tests.relay.test_core_adapter import RecordingBridge

        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "assert req3['params']['prompt'][0]['text'] == 'hello end-to-end'\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'こんにちは'}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "notif2 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': '\\nworld'}}}}\n"
            "sys.stdout.write(json.dumps(notif2) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )

        # 1. Fake local child process -> dictionary mock result
        mock_result = await acp_mock_text_update_wire(
            sys.executable, "-c", script,
            cwd=tempfile.gettempdir(), prompt_text="hello end-to-end"
        )

        # Capture copy to ensure unmodified
        mock_result_copy = dict(mock_result)

        self.assertEqual(mock_result, {"text": "こんにちは\nworld", "stopReason": "end_turn"})

        # 2. Map to strict MOCK-only Phase0 response-v1
        raw_bytes = acp_mock_text_to_phase0_raw(mock_result)

        # Verify original dict untouched
        self.assertEqual(mock_result, mock_result_copy)

        parsed = json.loads(raw_bytes.decode("utf-8"))
        self.assertEqual(set(parsed), {"schema_version", "answer_state", "conclusion_code", "safety_warning", "safety_reason", "evidence_refs", "marker_echoes", "answer_text"})
        self.assertEqual(parsed["schema_version"], "phase0-response-v1")
        self.assertEqual(parsed["answer_state"], "ANSWER")
        self.assertEqual(parsed["conclusion_code"], "SUCCESS")
        self.assertEqual(parsed["safety_warning"], "UNKNOWN")
        self.assertIsNone(parsed["safety_reason"])
        self.assertEqual(parsed["evidence_refs"], [])
        self.assertEqual(parsed["marker_echoes"], {"head": None, "middle": None, "tail": None})
        self.assertEqual(parsed["answer_text"], "こんにちは\nworld")

        # 3. Classify with pure core adapter
        adapter = RelayCoreAdapter("test_provider", RecordingBridge(), {"auth_kind": "mock"})
        classification = adapter.classify(raw_bytes)

        self.assertTrue(classification["success"])
        self.assertEqual(classification["execution_state"], "COMPLETE")
        self.assertEqual(classification["participation_state"], "PARTICIPANT")

    async def test_positive_one_notification_e2e(self):
        from src.relay.acp_client import acp_mock_text_update_wire, acp_mock_text_to_phase0_raw
        from src.relay.core_adapter import RelayCoreAdapter
        from tests.relay.test_core_adapter import RecordingBridge

        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'one chunk'}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )

        mock_result = await acp_mock_text_update_wire(
            sys.executable, "-c", script,
            cwd=tempfile.gettempdir(), prompt_text="hello fake"
        )
        self.assertEqual(mock_result, {"text": "one chunk", "stopReason": "end_turn"})

        raw_bytes = acp_mock_text_to_phase0_raw(mock_result)

        adapter = RelayCoreAdapter("test_provider", RecordingBridge(), {"auth_kind": "mock"})
        classification = adapter.classify(raw_bytes)

        self.assertTrue(classification["success"])
        self.assertEqual(classification["execution_state"], "COMPLETE")
        self.assertEqual(classification["participation_state"], "PARTICIPANT")

    async def test_negative_terminal_refusal(self):
        from src.relay.acp_client import acp_mock_text_update_wire, acp_mock_text_to_phase0_raw

        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "assert req3['method'] == 'session/prompt'\n"
            "assert req3['id'] == 2\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'partial '}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'refusal'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )

        mock_result = await acp_mock_text_update_wire(
            sys.executable, "-c", script,
            cwd=tempfile.gettempdir(), prompt_text="hello fake"
        )
        self.assertEqual(mock_result, {"text": "partial ", "stopReason": "refusal"})

        with self.assertRaises(ValueError):
            acp_mock_text_to_phase0_raw(mock_result)

    async def test_negative_terminal_cancelled(self):
        from src.relay.acp_client import acp_mock_text_update_wire, acp_mock_text_to_phase0_raw

        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'partial '}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'cancelled'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )

        mock_result = await acp_mock_text_update_wire(
            sys.executable, "-c", script,
            cwd=tempfile.gettempdir(), prompt_text="hello fake"
        )
        self.assertEqual(mock_result, {"text": "partial ", "stopReason": "cancelled"})

        with self.assertRaises(ValueError):
            acp_mock_text_to_phase0_raw(mock_result)

    async def test_negative_malformed_update_never_calls_downstream(self):
        from src.relay.acp_client import acp_mock_text_update_wire
        from unittest.mock import patch

        script = self.handshake_script + (
            "req3 = json.loads(sys.stdin.readline())\n"
            "notif1 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'valid '}}}}\n"
            "sys.stdout.write(json.dumps(notif1) + '\\n')\n"
            "notif2 = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'session-123', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'image'}}}}\n"
            "sys.stdout.write(json.dumps(notif2) + '\\n')\n"
            "resp3 = {'jsonrpc': '2.0', 'id': req3['id'], 'result': {'stopReason': 'end_turn'}}\n"
            "sys.stdout.write(json.dumps(resp3) + '\\n')\n"
            "sys.stdout.flush()\n"
        )

        with patch("src.relay.acp_client.acp_mock_text_to_phase0_raw") as mock_mapper:
            with patch("src.relay.core_adapter.RelayCoreAdapter.classify") as mock_classifier:
                with self.assertRaises(ValueError):
                    await acp_mock_text_update_wire(
                        sys.executable, "-c", script,
                        cwd=tempfile.gettempdir(), prompt_text="hello fake"
                    )
                mock_mapper.assert_not_called()
                mock_classifier.assert_not_called()
