from __future__ import annotations

import json
import unittest
from typing import Any

from providers.policy import ProviderPolicy
from relay.acp_client import ACPClient
from relay.duplicate_guard import DuplicateGuard
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.lifecycle import RelayLifecycle
from relay.result import RelayState


class MockACPConnection:
    def __init__(self, init_fixture_path: str) -> None:
        with open(init_fixture_path, "r", encoding="utf-8") as f:
            self._init_data = json.load(f)

        self.session_counts = 0
        self.prompt_counts = 0
        self.cancel_counts = 0
        self.close_counts = 0
        self.simulate_timeout = False
        self.simulate_error = False
        self.updates_to_stream: list[dict[str, Any]] = []
        self.safety_responses: list[Any] = []

    def initialize(self) -> Any:
        return self._init_data

    def new_session(self, cwd: str) -> Any:
        self.session_counts += 1
        return {"session_id": f"sess-{self.session_counts}"}

    def prompt(
        self,
        session_id: str,
        payload: dict[str, Any],
        timeout_seconds: int | None,
        on_update: Any,
        on_permission: Any,
        on_file: Any,
        on_terminal: Any,
        on_elicitation: Any,
        on_extension: Any,
    ) -> Any:
        self.prompt_counts += 1

        if self.simulate_timeout:
            raise TimeoutError("mock timeout")
        if self.simulate_error:
            raise RuntimeError("mock error")

        # Push updates
        for u in self.updates_to_stream:
            on_update(u)

        # Exercise safety handlers to capture their responses
        self.safety_responses.append(on_permission({"type": "permission"}))
        self.safety_responses.append(on_file({"type": "file"}))
        self.safety_responses.append(on_terminal({"type": "terminal"}))
        self.safety_responses.append(on_elicitation({"type": "elicitation"}))
        self.safety_responses.append(on_extension({"type": "extension"}))

        return {"status": "ok"}

    def cancel(self, session_id: str) -> None:
        self.cancel_counts += 1

    def close(self, session_id: str) -> None:
        self.close_counts += 1


class TestACPClient(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ProviderPolicy(
            provider_id="mock",
            external_agent="mock-agent",
            pinned_version="1.0.0",
            required_auth_kind="account",
        )

    def get_envelope(self, correlation: str = "corr-1") -> DispatchEnvelope:
        return DispatchEnvelope.build(
            slot=DispatchSlot("case-1", "mock", 0),
            correlation_id=correlation,
            payload={"packet": "hello"},
        )

    def test_valid_initialize_account_path(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        client = ACPClient(conn, self.policy)

        init = client.initialize("mock")
        self.assertEqual(init["provider_id"], "mock")
        self.assertFalse(init["live_process_started"])
        self.assertIsInstance(init["capabilities"], dict)

        session_id = client.open_session("mock", cwd=".")
        self.assertEqual(session_id, "sess-1")

        client.prompt("mock", session_id, {"msg": "hi"}, None)
        self.assertEqual(conn.prompt_counts, 1)

    def test_unsupported_auth_kind_rejected(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_unsupported.json")
        client = ACPClient(conn, self.policy)
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN: rejected auth_kind api_key"):
            client.initialize("mock")

    def test_malformed_capabilities_rejected(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        conn._init_data["capabilities"] = "invalid_string"
        client = ACPClient(conn, self.policy)
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN: malformed or missing capabilities"):
            client.initialize("mock")

    def test_exactly_one_prompt(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        client = ACPClient(conn, self.policy)
        relay = RelayLifecycle(client, DuplicateGuard())

        res = relay.dispatch_mock(self.get_envelope(), cwd=".")
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertEqual(res.prompt_attempts, 1)
        self.assertEqual(conn.prompt_counts, 1)

    def test_duplicate_does_not_prompt_again(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        client = ACPClient(conn, self.policy)
        relay = RelayLifecycle(client, DuplicateGuard())

        env = self.get_envelope()
        relay.dispatch_mock(env, cwd=".")
        self.assertEqual(conn.prompt_counts, 1)

        env_dup = DispatchEnvelope.build(
            slot=env.slot, correlation_id="dup", payload=env.payload
        )
        res_dup = relay.dispatch_mock(env_dup, cwd=".")
        self.assertEqual(res_dup.state, RelayState.BLOCKED)
        self.assertEqual(conn.prompt_counts, 1)

    def test_prompt_timeout_cancels_once_closes_once(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        conn.simulate_timeout = True
        client = ACPClient(conn, self.policy)
        relay = RelayLifecycle(client, DuplicateGuard())

        res = relay.dispatch_mock(self.get_envelope(), cwd=".")
        self.assertEqual(res.state, RelayState.TIMEOUT)
        self.assertEqual(conn.cancel_counts, 1)
        self.assertEqual(conn.close_counts, 1)

    def test_prompt_error_cancels_once_closes_once(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        conn.simulate_error = True
        client = ACPClient(conn, self.policy)
        relay = RelayLifecycle(client, DuplicateGuard())

        res = relay.dispatch_mock(self.get_envelope(), cwd=".")
        self.assertEqual(res.state, RelayState.UNKNOWN)
        self.assertEqual(conn.cancel_counts, 1)
        self.assertEqual(conn.close_counts, 1)

    def test_pre_session_error_creates_no_session(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_unsupported.json")
        client = ACPClient(conn, self.policy)
        relay = RelayLifecycle(client, DuplicateGuard())

        res = relay.dispatch_mock(self.get_envelope(), cwd=".")
        self.assertEqual(res.state, RelayState.UNKNOWN)
        self.assertEqual(conn.session_counts, 0)
        self.assertEqual(conn.cancel_counts, 0)
        self.assertEqual(conn.close_counts, 0)
        self.assertIsNone(res.session_id)

    def test_stop_before_dispatch_creates_no_session(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        client = ACPClient(conn, self.policy)
        relay = RelayLifecycle(client, DuplicateGuard())

        relay.request_stop()
        res = relay.dispatch_mock(self.get_envelope(), cwd=".")
        self.assertEqual(res.state, RelayState.BLOCKED)
        self.assertEqual(conn.session_counts, 0)

    def test_ordered_raw_session_updates_retained(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        conn.updates_to_stream = [{"id": 1}, {"id": 2}]
        client = ACPClient(conn, self.policy)

        session_id = client.open_session("mock", cwd=".")
        raw = client.prompt("mock", session_id, {"msg": "hi"}, None)

        data = json.loads(raw)
        self.assertEqual(data["_acp_session_updates"], [{"id": 1}, {"id": 2}])

    def test_safety_handlers_explicitly_deny(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        client = ACPClient(conn, self.policy)

        session_id = client.open_session("mock", cwd=".")
        client.prompt("mock", session_id, {"msg": "hi"}, None)

        self.assertEqual(len(conn.safety_responses), 5)
        for r in conn.safety_responses:
            self.assertEqual(r["granted"], False)
            self.assertEqual(r["reason"], "unsupported/denied")

    def test_retry_count_and_fallback_remain_disabled(self):
        conn = MockACPConnection("fixtures/relay/acp_initialize_account.json")
        client = ACPClient(conn, self.policy)

        self.assertEqual(client._retry_count, 0)
        self.assertEqual(client._fallback_enabled, False)
        self.assertEqual(client._live_process_started, False)


if __name__ == "__main__":
    unittest.main()
