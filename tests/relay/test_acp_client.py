import unittest
from src.relay.acp_client import ACPClient
from src.relay.lifecycle import RelayLifecycle
from src.relay.envelope import DispatchEnvelope, DispatchSlot
from src.relay.duplicate_guard import DuplicateGuard

class TestACPClient(unittest.TestCase):
    def setUp(self):
        self.client = ACPClient()

    def test_initialize_success(self):
        result = self.client.initialize("test")
        self.assertEqual(result, {"live_process_started": False})

    def test_initialize_unsupported(self):
        client = ACPClient(init_fixture_path="fixtures/relay/acp_initialize_unsupported.json")
        with self.assertRaises(ValueError):
            client.initialize("test")

    def test_deterministic_session_ids(self):
        s1 = self.client.open_session("prov1", cwd="/")
        s2 = self.client.open_session("prov1", cwd="/")
        self.assertEqual(s1, "acp-mock:prov1:1")
        self.assertEqual(s2, "acp-mock:prov1:2")

    def test_exact_raw_terminal_bytes(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.configured_responses[s1] = b"raw_bytes"
        result = self.client.prompt("p", s1, {})
        self.assertEqual(result, b"raw_bytes")

    def test_missing_terminal(self):
        s1 = self.client.open_session("p", cwd="/")
        with self.assertRaises(ValueError):
            self.client.prompt("p", s1, {})

    def test_malformed_terminal(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.configured_responses[s1] = "string" # type: ignore
        with self.assertRaises(ValueError):
            self.client.prompt("p", s1, {})

    def test_timeout_error_raising(self):
        s1 = self.client.open_session("p", cwd="/")
        with self.assertRaises(TimeoutError):
            self.client.prompt("p", s1, {"timeout": True})

        s2 = self.client.open_session("p", cwd="/")
        with self.assertRaises(RuntimeError):
            self.client.prompt("p", s2, {"error": True})

    def test_evidence_deepcopy(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.configured_responses[s1] = b"ok"
        update = {"k": "v"}
        self.client.configured_updates[s1] = [update]
        self.client.prompt("p", s1, {})

        evidence = self.client.get_evidence(s1)
        self.assertEqual(evidence, [{"k": "v"}])
        update["k"] = "v2"
        self.assertEqual(evidence, [{"k": "v"}]) # Original unchanged

    def test_malformed_update_rejection(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.configured_updates[s1] = ["not_a_dict"] # type: ignore
        with self.assertRaises(ValueError):
            self.client.prompt("p", s1, {})

    def test_safety_callbacks(self):
        self.assertFalse(self.client.permission_callback({"a": 1}))
        self.assertEqual(self.client.permission_calls, [{"a": 1}])

        self.assertFalse(self.client.file_read_callback({"b": 1}))
        self.assertEqual(self.client.file_read_calls, [{"b": 1}])

        self.assertFalse(self.client.file_write_callback({"c": 1}))
        self.assertEqual(self.client.file_write_calls, [{"c": 1}])

        self.assertFalse(self.client.terminal_request_callback({"d": 1}))
        self.assertEqual(self.client.terminal_request_calls, [{"d": 1}])

        self.assertFalse(self.client.elicitation_callback({"e": 1}))
        self.assertEqual(self.client.elicitation_calls, [{"e": 1}])

        self.assertFalse(self.client.unknown_extension_callback({"f": 1}))
        self.assertEqual(self.client.unknown_extension_calls, [{"f": 1}])

    def test_wrong_provider(self):
        s1 = self.client.open_session("p1", cwd="/")
        with self.assertRaises(ValueError):
            self.client.prompt("p2", s1, {})

    def test_second_prompt(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.configured_responses[s1] = b"ok"
        self.client.prompt("p", s1, {})
        with self.assertRaises(ValueError):
            self.client.prompt("p", s1, {})

    def test_prompt_after_cancel(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.cancel("p", s1)
        with self.assertRaises(ValueError):
            self.client.prompt("p", s1, {})

    def test_prompt_after_close(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.close("p", s1)
        with self.assertRaises(ValueError):
            self.client.prompt("p", s1, {})

    def test_second_cancel(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.cancel("p", s1)
        with self.assertRaises(ValueError):
            self.client.cancel("p", s1)

    def test_second_close(self):
        s1 = self.client.open_session("p", cwd="/")
        self.client.close("p", s1)
        with self.assertRaises(ValueError):
            self.client.close("p", s1)

class DummyGuard(DuplicateGuard):
    def __init__(self):
        self.reserved = set()
    def reserve(self, envelope: DispatchEnvelope):
        from src.relay.duplicate_guard import DuplicateDecision
        if envelope.correlation_id in self.reserved:
            return DuplicateDecision.SAME_REQUEST
        self.reserved.add(envelope.correlation_id)
        return DuplicateDecision.RESERVED

class TestIntegration(unittest.TestCase):
    def test_integration(self):
        class WrappedClient(ACPClient):
            def __init__(self):
                super().__init__()
                self.cancelled_calls = []
                self.closed_calls = []
            def cancel(self, p, s):
                self.cancelled_calls.append((p, s))
                super().cancel(p, s)
            def close(self, p, s):
                self.closed_calls.append((p, s))
                super().close(p, s)

        client = WrappedClient()
        lifecycle = RelayLifecycle(client, DummyGuard())

        # Test stop before dispatch
        lifecycle.request_stop()
        env1 = DispatchEnvelope(slot=DispatchSlot("case1", "p1", 1), correlation_id="c1", payload={"timeout": True}, packet_sha256="sha")
        res1 = lifecycle.dispatch_mock(env1, cwd="/")
        self.assertEqual(res1.state.name, "BLOCKED")
        self.assertEqual(len(client._sessions), 0)

        # New lifecycle for other tests
        lifecycle = RelayLifecycle(client, DummyGuard())

        # Test timeout -> 1 cancel, 1 close
        env2 = DispatchEnvelope(slot=DispatchSlot("case2", "p2", 1), correlation_id="c2", payload={"timeout": True}, packet_sha256="sha2")
        res2 = lifecycle.dispatch_mock(env2, cwd="/")
        self.assertEqual(res2.state.name, "TIMEOUT")
        s2 = res2.session_id
        self.assertIsNotNone(s2)
        self.assertEqual(client.cancelled_calls.count(("p2", s2)), 1)
        self.assertEqual(client.closed_calls.count(("p2", s2)), 1)

        # Test duplicate -> no second prompt
        env3 = DispatchEnvelope(slot=DispatchSlot("case2", "p2", 1), correlation_id="c2", payload={"timeout": True}, packet_sha256="sha2")
        res3 = lifecycle.dispatch_mock(env3, cwd="/")
        self.assertEqual(res3.state.name, "BLOCKED")
