import ast
import os
import unittest
from pathlib import Path

from providers.preflight import validate_provider_static
from providers.policy import claude_session_meta


class TestProviderPreflight(unittest.TestCase):
    def test_no_environ_or_subprocess_used(self):
        source = Path("src/providers/preflight.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.assertNotIn(alias.name, ["os", "subprocess", "sys"])
            if isinstance(node, ast.Attribute):
                if node.attr == "environ":
                    self.fail("os.environ read detected")
            if isinstance(node, ast.Call):
                if hasattr(node.func, "id") and node.func.id in ["eval", "exec", "open"]:
                    self.fail(f"forbidden builtin {node.func.id} used")

    def test_unknown_provider(self):
        res = validate_provider_static(
            provider_id="unknown",
            auth_kind="account",
            route_evidence={"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False}
        )
        self.assertEqual(res["static_configuration_status"], "UNKNOWN")

    def test_openai_pass(self):
        res = validate_provider_static(
            provider_id="openai",
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "custom_model_provider_configured": False,
                "arbitrary_codex_config_present": False,
            }
        )
        self.assertEqual(res["static_configuration_status"], "PASS")
        self.assertEqual(res["live_readiness"], "BLOCKED")
        self.assertEqual(res["provider_id"], "openai")
        self.assertFalse(res["live_ready"])
        self.assertEqual(res["retry_count"], 0)
        self.assertIn("provider-internal retry proof remains UNKNOWN", res["reasons"])

    def test_openai_fail_missing_evidence(self):
        res = validate_provider_static(
            provider_id="openai",
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "custom_model_provider_configured": False,
                # arbitrary_codex_config_present missing
            }
        )
        self.assertEqual(res["static_configuration_status"], "UNKNOWN")

    def test_anthropic_pass(self):
        res = validate_provider_static(
            provider_id="anthropic",
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "dangerous_permission_bypass": False,
                "hide_claude_auth": False,
            },
            provider_meta=claude_session_meta()
        )
        self.assertEqual(res["static_configuration_status"], "PASS")
        self.assertEqual(res["provider_id"], "anthropic")
        self.assertIn("provider/SDK retry/fallback proof remains UNKNOWN", res["reasons"])

    def test_anthropic_fail_bad_meta(self):
        res = validate_provider_static(
            provider_id="anthropic",
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "dangerous_permission_bypass": False,
                "hide_claude_auth": False,
            },
            provider_meta={"claudeCode": {"options": {"allowDangerouslySkipPermissions": True}}}
        )
        self.assertEqual(res["static_configuration_status"], "UNKNOWN")

    def test_google_pass(self):
        res = validate_provider_static(
            provider_id="google",
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "cloud_billing_selected": False,
                "overages_enabled": False,
                "adc_present": False,
                "vertex_selected": False,
            },
            platform="linux",
            architecture="x86_64"
        )
        self.assertEqual(res["static_configuration_status"], "PASS")
        self.assertEqual(res["provider_id"], "google")
        self.assertIn("internal retry/fallback and executed-model proof remain UNKNOWN", res["reasons"])

    def test_google_fail_bad_platform(self):
        res = validate_provider_static(
            provider_id="google",
            auth_kind="account",
            route_evidence={
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "cloud_billing_selected": False,
                "overages_enabled": False,
                "adc_present": False,
                "vertex_selected": False,
            },
            platform="unknownOS",
            architecture="x86_64"
        )
        self.assertEqual(res["static_configuration_status"], "UNKNOWN")
