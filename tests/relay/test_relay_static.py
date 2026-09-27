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
from relay.envelope import DispatchEnvelope, DispatchSlot, compute_intent_hash
from relay.lifecycle import RelayLifecycle
from relay.mock_transport import MockTransport
from relay.result import RelayState


class EnvelopeTests(unittest.TestCase):
    def envelope(self, payload=None, correlation="corr-1", timeout_seconds=None, include_timeout=False):
        kwargs = {
            "slot": DispatchSlot("case-1", "openai", 0),
            "correlation_id": correlation,
            "payload": payload or {"packet": "hello"},
        }
        if timeout_seconds is not None or include_timeout:
            kwargs["timeout_seconds"] = timeout_seconds
        return DispatchEnvelope.build(**kwargs)

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

    def test_hash_is_deterministic_across_equivalent_nested_payloads(self):
        a = self.envelope({"nested": {"x": 1, "y": 2}, "list": [1, 2]})
        b = self.envelope({"list": [1, 2], "nested": {"y": 2, "x": 1}})
        self.assertEqual(a.packet_sha256, b.packet_sha256)

    def test_payload_mutation_after_build_does_not_affect_envelope(self):
        payload = {"packet": "hello", "nested": {"x": 1}, "list": [1, 2]}
        envelope = self.envelope(payload, correlation="corr-mutation")

        expected_sha256 = envelope.packet_sha256

        # Mutate caller payload
        payload["packet"] = "mutated"
        payload["nested"]["x"] = 99
        payload["list"].append(3)

        # Envelope payload should remain unchanged
        self.assertEqual(envelope.payload, {"packet": "hello", "nested": {"x": 1}, "list": [1, 2]})
        self.assertEqual(envelope.packet_sha256, expected_sha256)

    def test_omitted_timeout_and_explicit_none_are_same_request(self):
        guard = DuplicateGuard()
        a = self.envelope()
        b = self.envelope(include_timeout=True, timeout_seconds=None)
        self.assertEqual(a.packet_sha256, b.packet_sha256)
        self.assertEqual(guard.reserve(a), DuplicateDecision.RESERVED)
        self.assertEqual(guard.reserve(b), DuplicateDecision.SAME_REQUEST)

    def test_same_slot_same_payload_same_finite_timeout_are_same_request(self):
        guard = DuplicateGuard()
        a = self.envelope(timeout_seconds=30)
        b = self.envelope(timeout_seconds=30)
        self.assertEqual(guard.reserve(a), DuplicateDecision.RESERVED)
        self.assertEqual(guard.reserve(b), DuplicateDecision.SAME_REQUEST)

    def test_same_slot_same_payload_different_timeout_are_conflict(self):
        guard = DuplicateGuard()
        self.assertEqual(guard.reserve(self.envelope(timeout_seconds=30)), DuplicateDecision.RESERVED)
        self.assertEqual(guard.reserve(self.envelope(timeout_seconds=60)), DuplicateDecision.CONFLICT)

    def test_omitted_or_none_versus_finite_timeout_are_conflict(self):
        guard = DuplicateGuard()
        self.assertEqual(guard.reserve(self.envelope(timeout_seconds=None)), DuplicateDecision.RESERVED)
        self.assertEqual(guard.reserve(self.envelope(timeout_seconds=30)), DuplicateDecision.CONFLICT)

    def test_dispatch_slot_invalid_types(self):
        invalid_strings = [None, "", False, True, 123, [], {}]
        for val in invalid_strings:
            with self.assertRaises(ValueError):
                DispatchSlot(val, "prov", 1).key()
            with self.assertRaises(ValueError):
                DispatchSlot("case", val, 1).key()

    def test_dispatch_slot_invalid_sequences(self):
        invalid_seqs = [None, False, True, -1, -99, 1.5, "1", [], {}]
        for val in invalid_seqs:
            with self.assertRaises(ValueError):
                DispatchSlot("case", "prov", val).key()

    def test_dispatch_slot_valid_sequence_0(self):
        slot = DispatchSlot("case", "prov", 0)
        self.assertEqual(slot.key(), "case:prov:0")

    def test_dispatch_envelope_build_invalid_correlation_ids(self):
        invalid_corrs = [None, "", False, True, 123, [], {}]
        slot = DispatchSlot("case", "prov", 1)
        for val in invalid_corrs:
            with self.assertRaises(ValueError):
                DispatchEnvelope.build(slot=slot, correlation_id=val, payload={})

    def test_dispatch_envelope_build_invalid_slot(self):
        invalid_slot = DispatchSlot("", "prov", 1)
        with self.assertRaises(ValueError):
            DispatchEnvelope.build(slot=invalid_slot, correlation_id="c", payload={})

    def test_dispatch_envelope_build_invalid_timeouts(self):
        invalid_timeouts = [False, True, 3.14, 0, -1, "10", [10], {"t": 10}]
        slot = DispatchSlot("case", "prov", 1)
        for invalid_val in invalid_timeouts:
            with self.assertRaises(ValueError):
                DispatchEnvelope.build(slot=slot, correlation_id="c", payload={}, timeout_seconds=invalid_val)

    def test_dispatch_envelope_build_none_timeout_is_accepted(self):
        slot = DispatchSlot("case", "prov", 1)
        env = DispatchEnvelope.build(slot=slot, correlation_id="c", payload={}, timeout_seconds=None)
        self.assertIsNone(env.timeout_seconds)

    def test_same_slot_same_hash_is_same_request(self):
        guard = DuplicateGuard()
        self.assertEqual(guard.reserve(self.envelope(correlation="corr-a")), DuplicateDecision.RESERVED)
        self.assertEqual(guard.reserve(self.envelope(correlation="corr-b")), DuplicateDecision.SAME_REQUEST)

    def test_same_slot_different_hash_is_conflict(self):
        guard = DuplicateGuard()
        self.assertEqual(guard.reserve(self.envelope({"x": 1})), DuplicateDecision.RESERVED)
        self.assertEqual(guard.reserve(self.envelope({"x": 2})), DuplicateDecision.CONFLICT)


class IntentHashTests(unittest.TestCase):
    def test_key_order_determinism(self):
        a = compute_intent_hash({"a": 1, "b": 2}, None)
        b = compute_intent_hash({"b": 2, "a": 1}, None)
        self.assertEqual(a, b)

    def test_nested_key_order_determinism(self):
        a = compute_intent_hash({"x": {"a": 1, "b": 2}}, None)
        b = compute_intent_hash({"x": {"b": 2, "a": 1}}, None)
        self.assertEqual(a, b)

    def test_timeout_differences(self):
        a = compute_intent_hash({}, None)
        b = compute_intent_hash({}, 10)
        self.assertNotEqual(a, b)

    def test_invalid_timeouts_rejected(self):
        invalid_timeouts = [False, True, 3.14, 0, -1, "10", [10], {"t": 10}]
        for invalid_val in invalid_timeouts:
            with self.assertRaises(ValueError):
                compute_intent_hash({}, invalid_val)


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
        self.assertEqual(result.packet_sha256, self.envelope().packet_sha256)
        self.assertIsNotNone(result.session_id)
        self.assertEqual(result.prompt_attempts, 1)

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
        second_result = relay.dispatch_mock(second, cwd="snapshot")
        self.assertEqual(second_result.state, RelayState.BLOCKED)
        self.assertEqual(second_result.prompt_attempts, 0)
        self.assertEqual(second_result.packet_sha256, second.packet_sha256)
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
        conflict_result = relay.dispatch_mock(conflict, cwd="snapshot")
        self.assertEqual(conflict_result.state, RelayState.BLOCKED)
        self.assertEqual(conflict_result.prompt_attempts, 0)
        self.assertEqual(conflict_result.packet_sha256, conflict.packet_sha256)
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

    def test_timeout_cancels_and_closes_session(self):
        transport = MockTransport(timeout_providers={"openai"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        result = relay.dispatch_mock(self.envelope(), cwd="snapshot")
        self.assertEqual(result.state, RelayState.TIMEOUT)
        self.assertEqual(transport.prompt_counts["openai"], 1)
        self.assertEqual(len(transport.cancelled), 1)
        self.assertEqual(transport.cancelled[0][0], "openai")
        self.assertEqual(len(transport.closed), 1)
        self.assertEqual(transport.closed[0][0], "openai")
        self.assertEqual(result.packet_sha256, self.envelope().packet_sha256)
        self.assertIsNotNone(result.session_id)
        self.assertEqual(result.prompt_attempts, 1)

    def test_error_cancels_and_closes_session(self):
        transport = MockTransport(error_providers={"openai"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        result = relay.dispatch_mock(self.envelope(), cwd="snapshot")
        self.assertEqual(result.state, RelayState.UNKNOWN)
        self.assertEqual(transport.prompt_counts["openai"], 1)
        self.assertEqual(len(transport.cancelled), 1)
        self.assertEqual(transport.cancelled[0][0], "openai")
        self.assertEqual(len(transport.closed), 1)
        self.assertEqual(transport.closed[0][0], "openai")
        self.assertEqual(result.packet_sha256, self.envelope().packet_sha256)
        self.assertIsNotNone(result.session_id)
        self.assertEqual(result.prompt_attempts, 1)

    def test_finite_timeout_reaches_mock_prompt_unchanged(self):
        transport = MockTransport(responses={"openai": b"{}"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        envelope = DispatchEnvelope.build(
            slot=DispatchSlot("case-1", "openai", 0),
            correlation_id="corr-to",
            payload={"packet": "hello"},
            timeout_seconds=42,
        )
        relay.dispatch_mock(envelope, cwd="snapshot")
        self.assertEqual(transport.prompt_timeouts["openai"], 42)

    def test_omitted_or_none_timeout_remains_deterministic_and_accepted(self):
        transport = MockTransport(responses={"openai": b"{}"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        envelope = self.envelope()
        relay.dispatch_mock(envelope, cwd="snapshot")
        self.assertIn("openai", transport.prompt_timeouts)
        self.assertIsNone(transport.prompt_timeouts["openai"])

    def test_timeout_failure_still_causes_exactly_one_prompt_attempt_then_cancel_and_close(self):
        transport = MockTransport(timeout_providers={"openai"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        envelope = DispatchEnvelope.build(
            slot=DispatchSlot("case-1", "openai", 0),
            correlation_id="corr-to-fail",
            payload={"packet": "hello"},
            timeout_seconds=10,
        )
        result = relay.dispatch_mock(envelope, cwd="snapshot")
        self.assertEqual(result.state, RelayState.TIMEOUT)
        self.assertEqual(transport.prompt_counts["openai"], 1)
        self.assertEqual(transport.prompt_timeouts["openai"], 10)
        self.assertEqual(len(transport.cancelled), 1)
        self.assertEqual(transport.cancelled[0][0], "openai")
        self.assertEqual(len(transport.closed), 1)
        self.assertEqual(transport.closed[0][0], "openai")
        self.assertEqual(result.prompt_attempts, 1)

    def test_different_providers_different_timeouts_no_cross_contamination(self):
        transport = MockTransport(
            responses={"openai": b"openai", "anthropic": b"anthropic"}
        )
        relay = RelayLifecycle(transport, DuplicateGuard())
        env_openai = DispatchEnvelope.build(
            slot=DispatchSlot("case-1", "openai", 0),
            correlation_id="corr-openai",
            payload={"packet": "hello"},
            timeout_seconds=15,
        )
        env_anthropic = DispatchEnvelope.build(
            slot=DispatchSlot("case-1", "anthropic", 0),
            correlation_id="corr-anthropic",
            payload={"packet": "hello"},
            timeout_seconds=30,
        )

        relay.dispatch_mock(env_openai, cwd="openai-snapshot")
        relay.dispatch_mock(env_anthropic, cwd="anthropic-snapshot")

        self.assertEqual(transport.prompt_timeouts["openai"], 15)
        self.assertEqual(transport.prompt_timeouts["anthropic"], 30)

    def test_duplicate_after_error_does_not_prompt(self):
        transport = MockTransport(error_providers={"openai"})
        relay = RelayLifecycle(transport, DuplicateGuard())
        first_envelope = self.envelope()

        # First dispatch produces error
        first_result = relay.dispatch_mock(first_envelope, cwd="snapshot")
        self.assertEqual(first_result.state, RelayState.UNKNOWN)
        self.assertEqual(transport.prompt_counts["openai"], 1)

        # Second dispatch is identical
        second_envelope = DispatchEnvelope.build(
            slot=first_envelope.slot,
            correlation_id="corr-dup",
            payload=first_envelope.payload,
        )
        second_result = relay.dispatch_mock(second_envelope, cwd="snapshot")
        self.assertEqual(second_result.state, RelayState.BLOCKED)
        self.assertEqual(second_result.prompt_attempts, 0)
        self.assertEqual(transport.prompt_counts["openai"], 1)

    def test_request_stop_blocks_new_dispatch_without_reserving_slot(self):
        transport = MockTransport(responses={"openai": b"{}"})
        guard = DuplicateGuard()
        relay = RelayLifecycle(transport, guard)
        relay.request_stop()

        envelope = self.envelope()
        result = relay.dispatch_mock(envelope, cwd="snapshot")
        self.assertEqual(result.state, RelayState.BLOCKED)
        self.assertEqual(result.error, "stop requested")
        self.assertEqual(result.packet_sha256, envelope.packet_sha256)
        self.assertIsNone(result.session_id)
        self.assertEqual(result.prompt_attempts, 0)

        # Verify no transport activity occurred
        self.assertEqual(transport.prompt_counts.get("openai", 0), 0)
        self.assertFalse(transport.live_process_started)

        # Verify duplicate slot was not reserved by doing fresh dispatch
        fresh_relay = RelayLifecycle(MockTransport(responses={"openai": b"{}"}), guard)
        fresh_result = fresh_relay.dispatch_mock(envelope, cwd="snapshot")
        self.assertEqual(fresh_result.state, RelayState.SIMULATED)


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
