import json
import tempfile
import unittest

from providers.policy import ProviderPolicy
from relay.acp_client import ACPClient
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
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as f:
                json.dump(payload, f)
                f.flush()
                client = ACPClient(init_fixture_path=f.name, policy=make_policy())
                with self.assertRaisesRegex(ValueError, message):
                    client.initialize("test")

    def test_initialize_rejects_live_process_claim(self):
        payload = {
            "protocol_version": 1,
            "live_process_started": True,
            "auth": {"kind": "account"},
            "capabilities": {},
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as f:
            json.dump(payload, f)
            f.flush()
            client = ACPClient(init_fixture_path=f.name, policy=make_policy())
            with self.assertRaisesRegex(ValueError, "live_process_started must be false"):
                client.initialize("test")

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


if __name__ == "__main__":
    unittest.main()
