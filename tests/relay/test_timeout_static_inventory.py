import ast
import inspect
import os
import textwrap
import unittest
from dataclasses import fields

from src.providers.base import ProviderStaticProfile
from src.providers.factory import create_core_adapter
from src.providers.policy import (
    ANTIGRAVITY_POLICY,
    CLAUDE_POLICY,
    CODEX_POLICY,
    ProviderPolicy,
    claude_session_meta,
)
from src.providers.preflight import validate_provider_static
from src.relay.acp_client import ACPClient
from src.relay.dispatcher import DuplicateConflictGuard, RelayDispatcher
from src.relay.duplicate_guard import DuplicateGuard
from src.relay.envelope import DispatchEnvelope, DispatchSlot, validate_timeout
from src.relay.lifecycle import RelayLifecycle
from src.relay.mock_transport import MockTransport
from src.relay.transport import RelayTransport


class _CaptureAdapter:
    def __init__(self) -> None:
        self.prepared = None

    def prepare(self, context):
        self.prepared = dict(context)
        return dict(context)

    def preflight(self, prepared):
        return {"ok": False, "live_ready": False}

    def dispatch(self, prepared):
        raise AssertionError("dispatch must not run after blocked preflight")

    def collect(self, handle):
        raise AssertionError("collect must not run")

    def abort(self, handle):
        raise AssertionError("abort must not run")

    def classify(self, raw):
        raise AssertionError("classify must not run")


class TestTimeoutStaticInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = os.path.join(os.path.dirname(__file__), "..", "..", "docs")
        inventory_path = os.path.join(base, "RELAY_TIMEOUT_STATIC_INVENTORY.md")
        checkpoint_path = os.path.join(base, "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(inventory_path):
            raise AssertionError("timeout inventory document is missing")
        if not os.path.isfile(checkpoint_path):
            raise AssertionError("static checkpoint document is missing")
        with open(inventory_path, "r", encoding="utf-8") as stream:
            cls.inventory = stream.read()
        with open(checkpoint_path, "r", encoding="utf-8") as stream:
            cls.checkpoint = stream.read()
        cls.rows = cls._parse_inventory(cls.inventory)

    @staticmethod
    def _parse_inventory(content: str) -> dict[str, dict[str, str]]:
        headers = [
            "surface_id",
            "canonical_source",
            "current_static_contract",
            "exact_value_or_default",
            "evidence_kind",
            "live_meaning",
            "state",
        ]
        lines = content.splitlines()
        header_index = None
        for index, line in enumerate(lines):
            if line.startswith("| surface_id |"):
                header_index = index
                actual = [cell.strip() for cell in line.strip("|").split("|")]
                if actual != headers:
                    raise AssertionError(f"unexpected inventory headers: {actual}")
                break
        if header_index is None:
            raise AssertionError("inventory table header is missing")

        rows = {}
        for line in lines[header_index + 2 :]:
            if not line.startswith("| "):
                break
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != len(headers):
                raise AssertionError(f"malformed inventory row: {line}")
            row = dict(zip(headers, cells))
            surface_id = row["surface_id"]
            if surface_id in rows:
                raise AssertionError(f"duplicate surface_id: {surface_id}")
            rows[surface_id] = row
        return rows

    def test_validate_timeout_contract(self) -> None:
        validate_timeout(None)
        validate_timeout(1)
        validate_timeout(30)

        for value in (True, False, 0, -1, 1.5, "30", [30], {"timeout": 30}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_timeout(value)

    def test_dispatch_envelope_timeout_defaults_are_none(self) -> None:
        field = DispatchEnvelope.__dataclass_fields__["timeout_seconds"]
        self.assertIsNone(field.default)
        sig = inspect.signature(DispatchEnvelope.build)
        self.assertIsNone(sig.parameters["timeout_seconds"].default)

        envelope = DispatchEnvelope.build(
            slot=DispatchSlot(case_id="case", provider_id="openai", sequence=0),
            correlation_id="corr",
            payload={},
        )
        self.assertIsNone(envelope.timeout_seconds)

    def test_transport_and_acp_mock_timeout_defaults_are_none(self) -> None:
        transport_sig = inspect.signature(RelayTransport.prompt)
        self.assertIsNone(transport_sig.parameters["timeout_seconds"].default)

        acp_sig = inspect.signature(ACPClient.prompt)
        self.assertIsNone(acp_sig.parameters["timeout_seconds"].default)

        tree = ast.parse(textwrap.dedent(inspect.getsource(ACPClient.prompt)))
        timeout_name_uses = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id == "timeout_seconds"
        ]
        self.assertEqual(timeout_name_uses, [])

    def test_dispatcher_forwards_exact_timeout_to_prepare(self) -> None:
        adapter = _CaptureAdapter()
        dispatcher = RelayDispatcher(adapter=adapter, guard=DuplicateConflictGuard())
        result = dispatcher.dispatch(
            "slot",
            {
                "provider_id": "openai",
                "session_id": "session",
                "correlation_id": "corr",
                "timeout_seconds": 17,
                "payload": {},
            },
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "preflight_not_ok")
        self.assertEqual(adapter.prepared["timeout_seconds"], 17)

    def test_lifecycle_forwards_timeout_once(self) -> None:
        transport = MockTransport()
        lifecycle = RelayLifecycle(
            transport=transport,
            duplicate_guard=DuplicateGuard(),
        )
        envelope = DispatchEnvelope.build(
            slot=DispatchSlot(case_id="case", provider_id="openai", sequence=1),
            correlation_id="corr",
            payload={},
            timeout_seconds=42,
        )

        result = lifecycle.dispatch_mock(envelope, cwd="/tmp")

        self.assertEqual(result.prompt_attempts, 1)
        self.assertEqual(transport.prompt_counts["openai"], 1)
        self.assertEqual(transport.prompt_timeouts["openai"], 42)
        self.assertEqual(transport.cancelled, [])
        self.assertEqual(len(transport.closed), 1)

    def test_lifecycle_timeout_cancels_once_closes_once_and_never_retries(self) -> None:
        transport = MockTransport(timeout_providers={"openai"})
        lifecycle = RelayLifecycle(
            transport=transport,
            duplicate_guard=DuplicateGuard(),
        )
        envelope = DispatchEnvelope.build(
            slot=DispatchSlot(case_id="case", provider_id="openai", sequence=2),
            correlation_id="corr",
            payload={},
            timeout_seconds=42,
        )

        result = lifecycle.dispatch_mock(envelope, cwd="/tmp")

        self.assertEqual(result.state.value, "TIMEOUT")
        self.assertEqual(result.prompt_attempts, 1)
        self.assertEqual(transport.prompt_counts["openai"], 1)
        self.assertEqual(transport.prompt_timeouts["openai"], 42)
        self.assertEqual(len(transport.cancelled), 1)
        self.assertEqual(len(transport.closed), 1)
        self.assertEqual(transport.cancelled[0], transport.closed[0])

    def test_provider_policy_and_profile_have_no_timeout_field(self) -> None:
        self.assertNotIn("timeout_seconds", {field.name for field in fields(ProviderPolicy)})
        self.assertNotIn(
            "timeout_seconds",
            {field.name for field in fields(ProviderStaticProfile)},
        )
        for policy in (CODEX_POLICY, CLAUDE_POLICY, ANTIGRAVITY_POLICY):
            self.assertFalse(hasattr(policy, "timeout_seconds"))

    def test_provider_preflight_does_not_establish_timeout_for_any_provider(self) -> None:
        cases = {
            "openai": {
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "custom_model_provider_configured": False,
                    "arbitrary_codex_config_present": False,
                },
            },
            "anthropic": {
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "dangerous_permission_bypass": False,
                    "hide_claude_auth": False,
                },
                "provider_meta": claude_session_meta(),
            },
            "google": {
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "cloud_billing_selected": False,
                    "overages_enabled": False,
                    "adc_present": False,
                    "vertex_selected": False,
                },
                "platform": "linux",
                "architecture": "x86_64",
            },
        }
        self.assertNotIn(
            "timeout",
            inspect.signature(validate_provider_static).parameters,
        )
        self.assertNotIn(
            "timeout_seconds",
            inspect.signature(validate_provider_static).parameters,
        )
        for provider_id, kwargs in cases.items():
            with self.subTest(provider_id=provider_id):
                result = validate_provider_static(provider_id=provider_id, **kwargs)
                self.assertEqual(result["static_configuration_status"], "PASS")
                self.assertFalse(any("timeout" in key.lower() for key in result))

    def test_factory_does_not_establish_dedicated_provider_timeout(self) -> None:
        self.assertNotIn(
            "timeout",
            inspect.signature(create_core_adapter).parameters,
        )
        source = inspect.getsource(create_core_adapter)
        self.assertNotIn("timeout_seconds", source)

    def test_inventory_has_exact_required_surfaces_and_conservative_states(self) -> None:
        required = {
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
            "provider_factory",
        }
        self.assertEqual(set(self.rows), required)

        for surface in (
            "provider_policy_openai",
            "provider_policy_anthropic",
            "provider_policy_google",
            "provider_preflight",
            "provider_factory",
        ):
            with self.subTest(surface=surface):
                self.assertEqual(self.rows[surface]["state"], "UNKNOWN_LIVE")

        self.assertEqual(
            self.rows["mock_transport_observation"]["state"],
            "STATIC_OBSERVED",
        )
        self.assertEqual(self.rows["acp_client_mock"]["state"], "STATIC_OBSERVED")

    def test_inventory_never_promotes_mock_or_optional_none_to_live_proof(self) -> None:
        self.assertIn(
            "does not prove a real provider process enforces the timeout",
            self.rows["lifecycle_forwarding"]["live_meaning"],
        )
        self.assertIn(
            "does not impose a finite provider live timeout",
            self.rows["transport_protocol"]["live_meaning"],
        )
        self.assertIn(
            "real provider timeout enforcement remains unknown",
            self.rows["acp_client_mock"]["live_meaning"],
        )

    def test_inventory_excludes_unrelated_controller_timeout_values(self) -> None:
        forbidden = (
            "timeout-minutes",
            "--connect-timeout",
            "--max-time",
            "CLIENT_HELLO_TIMEOUT_MS",
            "API_TIMEOUT_MS",
        )
        for token in forbidden:
            self.assertNotIn(token, self.inventory)

    def test_inventory_and_checkpoint_preserve_unresolved_live_boundary(self) -> None:
        for phrase in (
            "zero live execution",
            "does not choose or authorize any timeout value",
            "does not resolve `common_timeout`",
            "Provider-specific exact finite live timeout values remain **UNKNOWN**",
            "first real provider/model turn remains separately human-approved",
        ):
            self.assertIn(phrase, self.inventory)

        checkpoint_section = self.checkpoint.split(
            "## Timeout Static Inventory Checkpoint",
            1,
        )[1]
        for phrase in (
            "PREPARED/static timeout-inventory status only",
            "No live execution",
            "provider-specific exact finite live timeout values remain UNKNOWN",
        ):
            self.assertIn(phrase, checkpoint_section)
