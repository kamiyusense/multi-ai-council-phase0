import unittest
from copy import deepcopy

from relay.envelope import validate_payload, DispatchEnvelope, DispatchSlot, compute_intent_hash
from relay.bridge import RelayProviderAdapterBridge


class TestSensitiveFanoutInventoryPart1(unittest.TestCase):

    def test_validate_payload_rejects_overrides(self):
        """validate_payload rejects only the listed top-level control-plane override keys."""
        blocked_keys = [
            "model", "modelProvider", "serviceTier", "reasoning", "effort", "thinking",
            "approvalPolicy", "approvalsReviewer", "sandbox", "sandboxPolicy", "cwd",
            "config", "base", "developer", "general instructions", "plugin disabling",
            "billing", "auth route", "timeout_seconds"
        ]
        for key in blocked_keys:
            with self.assertRaises(ValueError, msg=f"Should reject {key}"):
                validate_payload({key: "value"})

    def test_validate_payload_accepts_synthetic_marker(self):
        """
        Tests must directly prove clearly synthetic keys/values such as
        {"secret":"synthetic-secret-marker"} and nested synthetic private markers are
        accepted/preserved by validate_payload. This demonstrates generic sensitive filtering is absent.
        """
        payload = {
            "secret": "synthetic-secret-marker",
            "nested": {"private": "synthetic-private-marker"}
        }
        # Should not raise exception
        validate_payload(payload)

    def test_dispatch_envelope_copy_preserves_marker(self):
        """
        tests must prove DispatchEnvelope deep-copies input payload by mutating source
        after build and showing envelope payload/hash remain stable, and preserves marker.
        """
        original_payload = {
            "secret": "synthetic-secret-marker",
            "nested": {"private": "synthetic-private-marker"}
        }
        slot = DispatchSlot(case_id="case1", provider_id="provider1", sequence=0)

        envelope = DispatchEnvelope.build(
            slot=slot,
            correlation_id="corr1",
            payload=original_payload,
            timeout_seconds=30
        )

        # Verify marker preserved in envelope
        self.assertEqual(envelope.payload["secret"], "synthetic-secret-marker")
        self.assertEqual(envelope.payload["nested"]["private"], "synthetic-private-marker")

        original_payload["secret"] = "mutated-secret"
        original_payload["nested"]["private"] = "mutated-private"

        # Verify envelope is unaffected by source mutation
        self.assertEqual(envelope.payload["secret"], "synthetic-secret-marker")
        self.assertEqual(envelope.payload["nested"]["private"], "synthetic-private-marker")

    def test_intent_hash_binding(self):
        """
        tests must independently recompute/compare intent hash behavior enough to show
        payload identity binding is not redaction.
        """
        payload = {"secret": "synthetic-secret-marker"}
        timeout = 30

        hash1 = compute_intent_hash(payload, timeout)

        # Independent recompute matching relay/envelope.py logic
        import json
        import hashlib
        intent = {"payload": payload, "timeout_seconds": timeout}
        encoded = json.dumps(intent, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        hash2 = hashlib.sha256(encoded).hexdigest()

        self.assertEqual(hash1, hash2)
        # The payload was used directly in the hash without any redaction step
        self.assertTrue(b"synthetic-secret-marker" in encoded)

    def test_bridge_prepare_copy_preserves_marker(self):
        """
        tests must prove RelayProviderAdapterBridge.prepare returns an independent
        copied payload while preserving synthetic marker content.
        """
        bridge = RelayProviderAdapterBridge()

        original_payload = {
            "secret": "synthetic-secret-marker"
        }

        case_context = {
            "provider_id": "provider1",
            "session_id": "session1",
            "correlation_id": "corr1",
            "payload": original_payload,
            "timeout_seconds": 30
        }

        prepared = bridge.prepare(case_context)

        self.assertIn("payload", prepared)
        self.assertEqual(prepared["payload"]["secret"], "synthetic-secret-marker")

        # Mutate original to prove isolation
        original_payload["secret"] = "mutated-secret"
        self.assertEqual(prepared["payload"]["secret"], "synthetic-secret-marker")

from relay.lifecycle import RelayLifecycle
from relay.mock_transport import MockTransport
from relay.duplicate_guard import DuplicateGuard
from relay.dispatcher import RelayDispatcher, DuplicateConflictGuard


class TestSensitiveFanoutInventoryPart2(unittest.TestCase):

    def test_lifecycle_prompt_forwards_payload(self):
        """
        use a tests-only capture transport/adapter where needed to prove RelayLifecycle
        forwards the prepared synthetic payload to prompt unchanged in the mock path
        with exactly one prompt attempt;
        """
        transport = MockTransport()
        guard = DuplicateGuard()
        lifecycle = RelayLifecycle(transport=transport, duplicate_guard=guard)

        payload = {"secret": "synthetic-secret-marker"}
        slot = DispatchSlot(case_id="case1", provider_id="provider1", sequence=0)
        envelope = DispatchEnvelope.build(
            slot=slot,
            correlation_id="corr1",
            payload=payload,
            timeout_seconds=30
        )

        # We must track the exact arguments passed to transport.prompt.
        # MockTransport does not natively store the prompted payload, so we patch it or wrap it.
        # However, MockTransport doesn't store payload, so we subclass it for this capture.
        class CaptureTransport(MockTransport):
            def __init__(self):
                super().__init__()
                self.captured_payloads = []
            def prompt(self, provider_id, session_id, payload, timeout_seconds=None):
                self.captured_payloads.append(payload)
                return super().prompt(provider_id, session_id, payload, timeout_seconds)

        capture_transport = CaptureTransport()
        lifecycle.transport = capture_transport

        result = lifecycle.dispatch_mock(envelope, cwd="/tmp")

        self.assertEqual(result.prompt_attempts, 1)
        self.assertEqual(len(capture_transport.captured_payloads), 1)
        self.assertEqual(capture_transport.captured_payloads[0]["secret"], "synthetic-secret-marker")

    def test_dispatcher_prepared_payload_forwarded(self):
        """
        Tests must prove dispatcher does not redact payload and forwards it to adapter.
        """
        # RelayDispatcher takes an adapter and a DuplicateConflictGuard
        class CaptureBridge(RelayProviderAdapterBridge):
            def __init__(self):
                super().__init__()
                self.captured_prepared = None
            def prepare(self, case_context):
                # Capture the context passed to prepare before passing it to super
                self.captured_prepared = case_context
                return super().prepare(case_context)

        bridge = CaptureBridge()
        guard = DuplicateConflictGuard()
        dispatcher = RelayDispatcher(adapter=bridge, guard=guard)

        payload = {"secret": "synthetic-secret-marker"}
        context = {
            "correlation_id": "corr1",
            "payload": payload,
            "timeout_seconds": 30
        }

        result = dispatcher.dispatch("provider1", context)

        self.assertIsNotNone(bridge.captured_prepared)
        self.assertEqual(bridge.captured_prepared["payload"]["secret"], "synthetic-secret-marker")

import json
from relay.core_adapter import RelayCoreAdapter
from relay.acp_client import ACPClient
from providers.policy import ProviderPolicy


class TestSensitiveFanoutInventoryPart3(unittest.TestCase):

    def test_core_adapter_raw_response_handling(self):
        """
        tests must prove no claim that CoreAdapter raw-response handling redacts arbitrary
        synthetic content; use only synthetic markers.
        """
        bridge = RelayProviderAdapterBridge()
        adapter = RelayCoreAdapter("provider1", bridge)

        # We simulate a raw response containing our synthetic marker
        mock_response = {
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "SUCCESS",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "Here is a secret: synthetic-secret-marker"
        }
        raw_bytes = json.dumps(mock_response).encode("utf-8")

        # Test classify behavior - it validates structure but does not redact raw bytes
        classification = adapter.classify(raw_bytes)

        self.assertEqual(classification["execution_state"], "COMPLETE")
        # Prove the raw bytes still contain the marker
        self.assertIn(b"synthetic-secret-marker", raw_bytes)

    def test_acp_client_mock_response(self):
        """
        tests must prove no claim that ACPClient raw-response handling redacts arbitrary synthetic content.
        """
        # ACPClient configuration for tests
        policy = ProviderPolicy(provider_id="provider1", external_agent="test", pinned_version="v1")
        # Ensure we have a dummy fixture to load
        client = ACPClient(init_fixture_path="fixtures/relay/acp_initialize_account.json", policy=policy)

        # Setup mock response
        mock_response_dict = {"content": "synthetic-secret-marker"}
        mock_response_bytes = json.dumps(mock_response_dict).encode("utf-8")

        # We manually patch _sessions and configured_responses to bypass open_session/initialize requirements for unit testing just prompt
        client._sessions["session1"] = {
            "provider_id": "provider1",
            "cwd": "/tmp",
            "state": "open",
            "prompted": False,
            "evidence": []
        }
        client.configured_responses["session1"] = mock_response_bytes

        # Perform prompt
        response = client.prompt("provider1", "session1", {"secret": "synthetic-secret-marker"})

        self.assertEqual(response, mock_response_bytes)
        self.assertIn(b"synthetic-secret-marker", response)

    def test_markdown_inventory_surfaces(self):
        """
        tests must parse the inventory table and assert the exact required surface_id set.
        tests must assert whole_path_sensitive_fanout_policy = MISSING_STATIC_EVIDENCE / BLOCKED_UNKNOWN.
        tests must assert no real secret/PII fixture marker pattern is present; all markers must be explicitly synthetic.
        """
        with open("docs/RELAY_SENSITIVE_FANOUT_STATIC_INVENTORY.md", "r", encoding="utf-8") as f:
            content = f.read()

        required_surfaces = {
            "payload_type_gate",
            "payload_control_plane_override_gate",
            "dispatch_envelope_copy",
            "intent_hash_binding",
            "bridge_prepare_copy",
            "dispatcher_prepared_payload",
            "lifecycle_prompt_payload",
            "mock_transport_payload_boundary",
            "core_adapter_raw_response",
            "relay_result_raw_bytes",
            "acp_client_mock_response",
            "whole_path_sensitive_fanout_policy"
        }

        found_surfaces = set()
        whole_path_row = None
        for line in content.splitlines():
            if line.startswith("|") and not line.startswith("| surface_id |") and not line.startswith("| ---"):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) > 1 and parts[1] != "":
                    surface_id = parts[1]
                    found_surfaces.add(surface_id)
                    if surface_id == "whole_path_sensitive_fanout_policy":
                        whole_path_row = parts

        self.assertEqual(required_surfaces, found_surfaces)

        self.assertIsNotNone(whole_path_row)
        # whole_path_row indexes: 0:empty, 1:surface_id, 2:canonical_source, 3:behavior, 4:meaning, 5:evidence, 6:missing, 7:state
        self.assertEqual(whole_path_row[5], "MISSING_STATIC_EVIDENCE")
        self.assertEqual(whole_path_row[7], "BLOCKED_UNKNOWN")

        # Check no real secret markers
        lower_content = content.lower()
        self.assertNotIn("real-secret", lower_content)
        self.assertNotIn("real-pii", lower_content)

    def test_static_checkpoint_text(self):
        """
        tests must assert docs/checkpoint say no real sensitive data, no external evidence,
        no provider send, no production filter, no blocker resolution.
        """
        with open("docs/RELAY_STATIC_CHECKPOINT.md", "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("No real sensitive data is used.", content)
        self.assertIn("no external evidence, no provider send, no production filter, no blocker resolution.", content.lower())
        self.assertIn("common_sensitive_fanout remains MISSING_STATIC_EVIDENCE / BLOCKED_UNKNOWN.", content)
