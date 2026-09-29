import unittest
import os
from providers.policy import ProviderPolicy, claude_session_meta
from providers.preflight import validate_provider_static
from relay.envelope import validate_payload

class TestMinimumPermissionsStaticInventory(unittest.TestCase):
    def test_provider_policy_rejects_mutations(self):
        policy = ProviderPolicy("test", "test", "1.0", automatic_retry=1)
        with self.assertRaises(ValueError):
            policy.assert_static_safety()

        policy = ProviderPolicy("test", "test", "1.0", fallback_enabled=True)
        with self.assertRaises(ValueError):
            policy.assert_static_safety()

        policy = ProviderPolicy("test", "test", "1.0", allow_api_key=True)
        with self.assertRaises(ValueError):
            policy.assert_static_safety()

        policy = ProviderPolicy("test", "test", "1.0", allow_gateway=True)
        with self.assertRaises(ValueError):
            policy.assert_static_safety()

        policy = ProviderPolicy("test", "test", "1.0", allow_external_cloud=True)
        with self.assertRaises(ValueError):
            policy.assert_static_safety()

        policy = ProviderPolicy("test", "test", "1.0", dangerous_permission_bypass=True)
        with self.assertRaises(ValueError):
            policy.assert_static_safety()

        policy = ProviderPolicy("test", "test", "1.0", live_ready=True)
        with self.assertRaises(ValueError):
            policy.assert_static_safety()

    def test_openai_preflight_rejects_flags(self):
        flags = [
            "api_key_present", "gateway_configured", "external_cloud_configured",
            "custom_model_provider_configured", "arbitrary_codex_config_present"
        ]
        for flag in flags:
            route_evidence = {k: False for k in flags}
            route_evidence[flag] = True
            result = validate_provider_static("openai", "account", route_evidence)
            self.assertEqual(result["static_configuration_status"], "UNKNOWN")

    def test_anthropic_preflight_rejects_flags(self):
        flags = [
            "api_key_present", "gateway_configured", "external_cloud_configured",
            "dangerous_permission_bypass", "hide_claude_auth"
        ]
        meta = claude_session_meta()
        for flag in flags:
            route_evidence = {k: False for k in flags}
            route_evidence[flag] = True
            result = validate_provider_static("anthropic", "account", route_evidence, provider_meta=meta)
            self.assertEqual(result["static_configuration_status"], "UNKNOWN")

    def test_claude_session_meta_disallows_dangerous_skip(self):
        meta = claude_session_meta()
        self.assertFalse(meta["claudeCode"]["options"]["allowDangerouslySkipPermissions"])

    def test_anthropic_preflight_rejects_mismatched_meta(self):
        route_evidence = {
            "api_key_present": False, "gateway_configured": False, "external_cloud_configured": False,
            "dangerous_permission_bypass": False, "hide_claude_auth": False
        }
        meta = {"claudeCode": {"options": {"allowDangerouslySkipPermissions": True}}}
        result = validate_provider_static("anthropic", "account", route_evidence, provider_meta=meta)
        self.assertEqual(result["static_configuration_status"], "UNKNOWN")

    def test_google_preflight_rejects_flags(self):
        flags = [
            "api_key_present", "gateway_configured", "external_cloud_configured",
            "cloud_billing_selected", "overages_enabled", "adc_present", "vertex_selected"
        ]
        for flag in flags:
            route_evidence = {k: False for k in flags}
            route_evidence[flag] = True
            result = validate_provider_static("google", "account", route_evidence, platform="linux", architecture="x86_64")
            self.assertEqual(result["static_configuration_status"], "UNKNOWN")

    def test_validate_payload_rejects_overrides_without_claiming_secret_filtering(self):
        blocked_keys = [
            "approvalPolicy", "approvalsReviewer", "sandbox", "sandboxPolicy", "cwd",
            "config", "billing", "auth route"
        ]
        for key in blocked_keys:
            with self.assertRaises(ValueError):
                validate_payload({key: "override"})

        # Must not assert that validate_payload performs secret filtering

    def test_parse_inventory_surfaces_and_disclaimers(self):
        with open("docs/RELAY_MINIMUM_PERMISSIONS_STATIC_INVENTORY.md", "r") as f:
            content = f.read()

        expected_surfaces = [
            "provider_policy_common", "openai_route_controls", "anthropic_route_controls",
            "anthropic_dangerous_permission_bypass", "anthropic_session_meta",
            "google_route_controls", "google_billing_route_controls",
            "relay_payload_control_overrides", "whole_path_minimum_permission_profile"
        ]
        for surface in expected_surfaces:
            self.assertIn(surface, content)

        self.assertIn("| whole_path_minimum_permission_profile", content)
        self.assertIn("BLOCKED_UNKNOWN", content.split("whole_path_minimum_permission_profile")[1])

        self.assertIn("zero permission changes are made", content.lower())
        self.assertIn("zero external/read-only/live evidence is acquired", content.lower())
        self.assertIn("no exact whole-path minimum-permission profile is selected", content.lower())
        self.assertIn("common_min_permissions remains unresolved", content.lower())
        self.assertIn("first live provider/model turn remains separately human-approved", content.lower())

    def test_checkpoint_updated(self):
        with open("docs/RELAY_STATIC_CHECKPOINT.md", "r") as f:
            content = f.read()

        self.assertIn("Minimum Permissions Static Inventory Checkpoint", content)
        self.assertIn("PREPARED/static minimum-permissions-inventory status only", content)
        self.assertIn("No live execution is performed", content)
        self.assertIn("No permission changes are authorized", content)
