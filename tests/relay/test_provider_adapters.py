import ast
import unittest
from pathlib import Path

from providers import (
    ProviderStaticProfile,
    build_antigravity_profile,
    build_claude_profile,
    build_codex_profile,
)
from providers.policy import (
    ANTIGRAVITY_POLICY,
    CLAUDE_POLICY,
    CODEX_POLICY,
    antigravity_binary_name,
    claude_session_meta,
)
from relay.bridge import RelayProviderAdapterBridge
from relay.core_adapter import RelayCoreAdapter


def codex_evidence():
    return {
        "api_key_present": False,
        "gateway_configured": False,
        "external_cloud_configured": False,
        "custom_model_provider_configured": False,
        "arbitrary_codex_config_present": False,
    }


def claude_evidence():
    return {
        "api_key_present": False,
        "gateway_configured": False,
        "external_cloud_configured": False,
        "dangerous_permission_bypass": False,
        "hide_claude_auth": False,
    }


def google_evidence():
    return {
        "api_key_present": False,
        "gateway_configured": False,
        "external_cloud_configured": False,
        "cloud_billing_selected": False,
        "overages_enabled": False,
        "adc_present": False,
        "vertex_selected": False,
    }


class TestProviderAdapters(unittest.TestCase):
    def assert_profile_invariants(self, profile: ProviderStaticProfile, policy):
        self.assertEqual(profile.provider_id, policy.provider_id)
        self.assertEqual(profile.external_agent, policy.external_agent)
        self.assertEqual(profile.pinned_version, policy.pinned_version)
        self.assertEqual(profile.retry_count, 0)
        self.assertEqual(profile.fallback_state, "disabled")
        self.assertFalse(profile.live_ready)
        self.assertEqual(profile.live_readiness, "BLOCKED")

    def test_codex_profile_pass_and_adapter_compatible_config(self):
        evidence = codex_evidence()
        profile = build_codex_profile("account", evidence)
        self.assert_profile_invariants(profile, CODEX_POLICY)
        self.assertEqual(profile.binary_name, "codex-acp")
        self.assertEqual(
            profile.static_preflight_config,
            {"auth_kind": "account", "route_evidence": evidence},
        )
        adapter = RelayCoreAdapter(
            "openai",
            RelayProviderAdapterBridge(),
            profile.static_preflight_config,
        )
        result = adapter.preflight({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["static_configuration_status"], "PASS")
        self.assertFalse(result["live_ready"])

    def test_claude_profile_pass_and_adapter_compatible_config(self):
        evidence = claude_evidence()
        expected_meta = claude_session_meta()
        profile = build_claude_profile("account", evidence)
        self.assert_profile_invariants(profile, CLAUDE_POLICY)
        self.assertEqual(profile.session_meta, expected_meta)
        self.assertFalse(
            profile.session_meta["claudeCode"]["options"][
                "allowDangerouslySkipPermissions"
            ]
        )
        self.assertEqual(
            profile.static_preflight_config,
            {
                "auth_kind": "account",
                "route_evidence": evidence,
                "provider_meta": expected_meta,
            },
        )
        adapter = RelayCoreAdapter(
            "anthropic",
            RelayProviderAdapterBridge(),
            profile.static_preflight_config,
        )
        self.assertTrue(adapter.preflight({})["ok"])

    def test_antigravity_profile_pass_and_adapter_compatible_config(self):
        evidence = google_evidence()
        profile = build_antigravity_profile(
            "account", evidence, "windows", "x86_64"
        )
        self.assert_profile_invariants(profile, ANTIGRAVITY_POLICY)
        self.assertEqual(
            profile.binary_name,
            antigravity_binary_name("windows", "x86_64"),
        )
        self.assertEqual(
            profile.static_preflight_config,
            {
                "auth_kind": "account",
                "route_evidence": evidence,
                "platform": "windows",
                "architecture": "x86_64",
            },
        )
        adapter = RelayCoreAdapter(
            "google",
            RelayProviderAdapterBridge(),
            profile.static_preflight_config,
        )
        self.assertTrue(adapter.preflight({})["ok"])

    def test_input_and_returned_config_are_deep_copied(self):
        evidence = codex_evidence()
        profile = build_codex_profile("account", evidence)
        evidence["api_key_present"] = True
        self.assertFalse(
            profile.static_preflight_config["route_evidence"]["api_key_present"]
        )

        returned = profile.get_static_preflight_config()
        returned["auth_kind"] = "hacked"
        returned["route_evidence"]["api_key_present"] = True
        fresh = profile.get_static_preflight_config()
        self.assertEqual(fresh["auth_kind"], "account")
        self.assertFalse(fresh["route_evidence"]["api_key_present"])

    def test_claude_meta_is_deep_copied(self):
        evidence = claude_evidence()
        supplied = claude_session_meta()
        profile = build_claude_profile("account", evidence, supplied)
        supplied["claudeCode"]["options"]["allowDangerouslySkipPermissions"] = True
        self.assertFalse(
            profile.static_preflight_config["provider_meta"]["claudeCode"][
                "options"
            ]["allowDangerouslySkipPermissions"]
        )
        returned_meta = profile.session_meta
        returned_meta["claudeCode"]["options"]["allowDangerouslySkipPermissions"] = True
        self.assertFalse(
            profile.session_meta["claudeCode"]["options"][
                "allowDangerouslySkipPermissions"
            ]
        )

    def test_frozen_profile_identity(self):
        profile = build_codex_profile("account", codex_evidence())
        with self.assertRaises(Exception):
            profile.provider_id = "hacked"

    def test_profile_constructor_rejects_unsafe_invariants(self):
        base = {
            "provider_id": "openai",
            "external_agent": "test-agent",
            "pinned_version": "test-version",
            "_static_preflight_config": {
                "auth_kind": "account",
                "route_evidence": codex_evidence(),
            },
        }
        for overrides in (
            {"retry_count": 1},
            {"fallback_state": "enabled"},
            {"live_ready": True},
            {"live_readiness": "READY"},
        ):
            with self.assertRaises(ValueError):
                ProviderStaticProfile(**base, **overrides)

    def test_claude_rejects_noncanonical_meta(self):
        bad_meta = {
            "claudeCode": {
                "options": {"allowDangerouslySkipPermissions": True}
            }
        }
        with self.assertRaises(ValueError):
            build_claude_profile("account", claude_evidence(), bad_meta)

    def test_antigravity_rejects_unsupported_platform_architecture(self):
        with self.assertRaises(ValueError):
            build_antigravity_profile(
                "account", google_evidence(), "mac", "x86_64"
            )

    def test_wrong_auth_fails_closed_for_all_profiles(self):
        cases = (
            lambda: build_codex_profile("api_key", codex_evidence()),
            lambda: build_claude_profile("api_key", claude_evidence()),
            lambda: build_antigravity_profile(
                "api_key", google_evidence(), "windows", "x86_64"
            ),
        )
        for build in cases:
            with self.assertRaises(ValueError):
                build()

    def test_missing_true_and_malformed_route_evidence_fail_closed(self):
        with self.assertRaises(ValueError):
            bad = codex_evidence()
            bad.pop("gateway_configured")
            build_codex_profile("account", bad)

        with self.assertRaises(ValueError):
            bad = claude_evidence()
            bad["dangerous_permission_bypass"] = True
            build_claude_profile("account", bad)

        with self.assertRaises(ValueError):
            bad = google_evidence()
            bad["overages_enabled"] = "false"
            build_antigravity_profile(
                "account", bad, "windows", "x86_64"
            )

        for builder in (
            lambda: build_codex_profile("account", ["not-a-dict"]),
            lambda: build_claude_profile("account", None),
            lambda: build_antigravity_profile(
                "account", "bad", "windows", "x86_64"
            ),
        ):
            with self.assertRaises((TypeError, ValueError, AttributeError)):
                builder()

    def test_static_modules_do_not_import_os_or_subprocess(self):
        files_to_check = [
            Path("src/providers/base.py"),
            Path("src/providers/codex_acp.py"),
            Path("src/providers/claude_acp.py"),
            Path("src/providers/antigravity_acp.py"),
        ]
        for path in files_to_check:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name, ("os", "subprocess"))
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(node.module, ("os", "subprocess"))

    def test_no_duplicate_provider_versions_or_agent_literals(self):
        forbidden = (
            "2.1.0",
            "0.84.0",
            "1.2.1",
            "@agentclientprotocol/codex-acp",
            "@agentclientprotocol/claude-agent-acp",
            "antigravity-acp",
        )
        for path in (
            Path("src/providers/codex_acp.py"),
            Path("src/providers/claude_acp.py"),
            Path("src/providers/antigravity_acp.py"),
        ):
            source = path.read_text(encoding="utf-8")
            for literal in forbidden:
                self.assertNotIn(literal, source)


if __name__ == "__main__":
    unittest.main()
