import unittest
import inspect
from typing import Any
import re
from pathlib import Path

from src.relay.envelope import validate_timeout, DispatchEnvelope, DispatchSlot
from src.relay.transport import RelayTransport
from src.relay.mock_transport import MockTransport
from src.relay.lifecycle import RelayLifecycle
from src.relay.duplicate_guard import DuplicateGuard
from src.providers.policy import CODEX_POLICY, CLAUDE_POLICY, ANTIGRAVITY_POLICY
from src.providers.preflight import validate_provider_static

class TestTimeoutStaticInventory(unittest.TestCase):
    def test_validate_timeout_accepts_none(self):
        validate_timeout(None) # Should not raise

    def test_validate_timeout_accepts_positive_int(self):
        validate_timeout(30) # Should not raise

    def test_validate_timeout_rejects_bool(self):
        with self.assertRaises(ValueError):
            validate_timeout(True)
        with self.assertRaises(ValueError):
            validate_timeout(False)

    def test_validate_timeout_rejects_zero_and_negative(self):
        with self.assertRaises(ValueError):
            validate_timeout(0)
        with self.assertRaises(ValueError):
            validate_timeout(-1)

    def test_validate_timeout_rejects_other_types(self):
        with self.assertRaises(ValueError):
            validate_timeout(30.5)
        with self.assertRaises(ValueError):
            validate_timeout("30")
        with self.assertRaises(ValueError):
            validate_timeout([30])
        with self.assertRaises(ValueError):
            validate_timeout({"timeout": 30})

    def test_dispatch_envelope_default_timeout(self):
        slot = DispatchSlot(case_id="case1", provider_id="provider1", sequence=1)
        envelope = DispatchEnvelope.build(
            slot=slot,
            correlation_id="corr1",
            payload={}
        )
        self.assertIsNone(envelope.timeout_seconds)

    def test_relay_transport_prompt_default_timeout(self):
        sig = inspect.signature(RelayTransport.prompt)
        param = sig.parameters.get("timeout_seconds")
        self.assertIsNotNone(param)
        self.assertEqual(param.default, None)

    def test_lifecycle_forwards_timeout_and_makes_one_prompt(self):
        transport = MockTransport()
        guard = DuplicateGuard()
        lifecycle = RelayLifecycle(transport=transport, duplicate_guard=guard)

        slot = DispatchSlot(case_id="case1", provider_id="openai", sequence=1)
        envelope = DispatchEnvelope.build(
            slot=slot,
            correlation_id="corr1",
            payload={},
            timeout_seconds=42
        )

        lifecycle.dispatch_mock(envelope, cwd="/tmp")

        self.assertEqual(transport.prompt_counts.get("openai"), 1)
        self.assertEqual(transport.prompt_timeouts.get("openai"), 42)

    def test_lifecycle_timeout_cancels_and_closes_once(self):
        transport = MockTransport(timeout_providers={"openai"})
        guard = DuplicateGuard()
        lifecycle = RelayLifecycle(transport=transport, duplicate_guard=guard)

        slot = DispatchSlot(case_id="case1", provider_id="openai", sequence=1)
        envelope = DispatchEnvelope.build(
            slot=slot,
            correlation_id="corr1",
            payload={},
            timeout_seconds=42
        )

        result = lifecycle.dispatch_mock(envelope, cwd="/tmp")

        self.assertEqual(result.state.value, "TIMEOUT")
        self.assertEqual(transport.prompt_counts.get("openai"), 1)
        self.assertEqual(len(transport.cancelled), 1)
        self.assertEqual(transport.cancelled[0][0], "openai")
        self.assertEqual(len(transport.closed), 1)
        self.assertEqual(transport.closed[0][0], "openai")

    def test_provider_policies_do_not_expose_timeout(self):
        for policy in [CODEX_POLICY, CLAUDE_POLICY, ANTIGRAVITY_POLICY]:
            self.assertFalse(hasattr(policy, "timeout_seconds"))

    def test_provider_preflight_does_not_expose_timeout(self):
        res = validate_provider_static(
            provider_id="openai",
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "custom_model_provider_configured": False,
                "arbitrary_codex_config_present": False
            }
        )
        self.assertNotIn("timeout_seconds", res)

    def test_inventory_table_content(self):
        docs_path = Path("docs/RELAY_TIMEOUT_STATIC_INVENTORY.md")
        if not docs_path.exists():
            return

        content = docs_path.read_text()

        # Test required surface IDs
        required_surfaces = [
            "timeout_validator",
            "dispatch_envelope",
            "dispatcher_forwarding",
            "lifecycle_forwarding",
            "transport_protocol",
            "mock_transport_observation",
            "acp_client_mock",
            "provider_policy_openai",
            "provider_policy_anthropic",
            "provider_policy_google",
            "provider_preflight",
            "provider_factory"
        ]
        for surface in required_surfaces:
            self.assertIn(surface, content)

        # Test exact UNKNOWN_LIVE states for providers
        self.assertRegex(content, r"provider_policy_openai.*UNKNOWN_LIVE")
        self.assertRegex(content, r"provider_policy_anthropic.*UNKNOWN_LIVE")
        self.assertRegex(content, r"provider_policy_google.*UNKNOWN_LIVE")

        # Test required textual claims
        self.assertIn("zero live execution", content)
        self.assertIn("does not choose timeout values", content)
        self.assertIn("does not resolve common_timeout", content)
        self.assertIn("provider-specific exact finite live timeout values remain UNKNOWN", content)
        self.assertIn("first live provider turn remains separately human-approved", content)

    def test_checkpoint_content(self):
        checkpoint_path = Path("docs/RELAY_STATIC_CHECKPOINT.md")
        if not checkpoint_path.exists():
            return

        content = checkpoint_path.read_text()
        self.assertIn("## Timeout Static Inventory Checkpoint", content)
        self.assertIn("PREPARED", content)
        self.assertIn("static", content)
        self.assertIn("timeout-inventory", content)
