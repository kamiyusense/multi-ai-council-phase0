from __future__ import annotations

import unittest

from providers.policy import (
    ANTIGRAVITY_POLICY,
    CLAUDE_POLICY,
    CODEX_POLICY,
    antigravity_binary_name,
    claude_session_meta,
)
from relay.duplicate_guard import DuplicateDecision, DuplicateGuard
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.lifecycle import RelayLifecycle
from relay.mock_transport import MockTransport
from relay.result import RelayState


class EnvelopeTests(unittest.TestCase):
    def envelope(self, payload=None, correlation="corr-1"):
        return DispatchEnvelope.build(
            slot=DispatchSlot("case-1", "openai", 0),
            correlation_id=correlation,
            payload=payload or {"packet": "hello"},
        )

    def test_payload_and_correlation_are_preserved(self):
        payload = {"packet": "hello", "nested": {"x": 1}}
        envelope = self.envelope(payload, correlation="corr-preserved")
        self.assertEqual(envelope.payload, payload)
        self.assertIsNot(envelope.payload, payload)
        self.assertEqual(envelope.correlation_id, "corr-preserved")

    def test_hash_is_deterministic_across_key_order(self):
        a = self.envelope({"a": 1, "b": 2})
        b = self.envelope({"b": 2, "a": 1})
        self.assertEqual(a.packet_sha256, b.packet_sha256)

    def test_same_slot_same_hash_is_same_request(self):
        guard = DuplicateGuard()
        self.assertEqual(guard.reserve(self.envelope(correlation="corr-a")), DuplicateDecision.RESERVED)
        self.assertEqual(guard.reserve(self.envelope(correlation="corr-b")), DuplicateDecision.SAME_REQUEST)

    def test_same_slot_different_hash_is_conflict(self):
        guard = DuplicateGuard()
        self.assertEqual(guard.reserve(self.envelope({"x": 1})), DuplicateDecision.RESERVED)
        self.assertEqual(guard.reserve(self.envelope({"x": 2})), DuplicateDecision.CONFLICT)


class LifecycleTests(unittest.TestCase):
    def envelope(self, provider="openai", seq=0):
        return DispatchEnvelope.build(
            slot=DispatchSlot("case-1", provider, seq),
            correlation_id=f"corr-{provider}-{seq}",
            payload={"packet": "hello"},
        )

    def test_mock_dispatch_is_simulated_and_one_prompt(self):
        transport = MockTransport(responses={"openai": b'{"ok":true}'})
        relay = RelayLifecycle(transport, DuplicateGuard())
        result = relay.dispatch_mock(self.envelope(), cwd="snapshot")
        self.assertEqual(result.state, RelayState.SIMULATED)
        self.assertTrue(result.simulated)
        self.assertEqual(result.raw, b'{"ok":true}')
        self.assertEqual(transport.prompt_counts["openai"], 1)
        self.assertFalse(transport.live_process_started)
        self.assertEqual(result.correlation_id, "corr-openai-0")
        self.assertEqual(result.provider_id, "openai")

    def test_duplicate_does_not_prompt_twice(self):
        transport = MockTransport(responses={"openai": b"{}"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        first = self.envelope()
        second = DispatchEnvelope.build(
            slot=first.slot,
            correlation_id="different-correlation",
            payload=first.payload,
        )
        self.assertEqual(relay.dispatch_mock(first, cwd="snapshot").state, RelayState.SIMULATED)
        self.assertEqual(relay.dispatch_mock(second, cwd="snapshot").state, RelayState.BLOCKED)
        self.assertEqual(transport.prompt_counts["openai"], 1)

    def test_conflict_does_not_prompt_again(self):
        transport = MockTransport(responses={"openai": b"{}"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        relay.dispatch_mock(self.envelope(), cwd="snapshot")
        conflict = DispatchEnvelope.build(
            slot=DispatchSlot("case-1", "openai", 0),
            correlation_id="corr-conflict",
            payload={"packet": "changed"},
        )
        self.assertEqual(relay.dispatch_mock(conflict, cwd="snapshot").state, RelayState.BLOCKED)
        self.assertEqual(transport.prompt_counts["openai"], 1)

    def test_provider_identity_isolated(self):
        transport = MockTransport(
            responses={"openai": b"openai", "anthropic": b"anthropic"}
        )
        relay = RelayLifecycle(transport, DuplicateGuard())
        a = relay.dispatch_mock(self.envelope("openai", 0), cwd="openai-snapshot")
        b = relay.dispatch_mock(self.envelope("anthropic", 0), cwd="anthropic-snapshot")
        self.assertEqual(a.raw, b"openai")
        self.assertEqual(b.raw, b"anthropic")
        self.assertEqual(transport.prompt_counts, {"openai": 1, "anthropic": 1})

    def test_session_closed_without_restart(self):
        transport = MockTransport(responses={"openai": b"{}"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        relay.dispatch_mock(self.envelope(), cwd="snapshot")
        self.assertEqual(len(transport.closed), 1)
        self.assertEqual(transport.prompt_counts["openai"], 1)


class ProviderPolicyTests(unittest.TestCase):
    def test_all_policies_are_subscription_only_and_live_blocked(self):
        for policy in (CODEX_POLICY, CLAUDE_POLICY, ANTIGRAVITY_POLICY):
            policy.assert_static_safety()
            self.assertTrue(policy.validate_auth_kind("account"))
            for rejected in ("api_key", "gateway", "external", "none", None):
                self.assertFalse(policy.validate_auth_kind(rejected))
            self.assertFalse(policy.live_ready)

    def test_claude_bypass_explicitly_false(self):
        self.assertIs(
            claude_session_meta()["claudeCode"]["options"]["allowDangerouslySkipPermissions"],
            False,
        )

    def test_antigravity_windows_binary_selection(self):
        self.assertEqual(
            antigravity_binary_name("windows", "x86_64"),
            "agy_acp_server.exe",
        )
        self.assertEqual(
            antigravity_binary_name("windows", "aarch64"),
            "agy_acp_server.exe",
        )

    def test_antigravity_unknown_platform_rejected(self):
        with self.assertRaises(ValueError):
            antigravity_binary_name("plan9", "x86_64")


if __name__ == "__main__":
    unittest.main()
