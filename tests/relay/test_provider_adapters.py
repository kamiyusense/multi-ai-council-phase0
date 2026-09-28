import unittest
import ast
from pathlib import Path
from providers import build_codex_profile, build_claude_profile, build_antigravity_profile, ProviderStaticProfile
from providers.policy import CODEX_POLICY, CLAUDE_POLICY, ANTIGRAVITY_POLICY, claude_session_meta, antigravity_binary_name

class TestProviderAdapters(unittest.TestCase):
    def test_codex_profile_pass(self):
        evidence = {
            "api_key_present": False,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "custom_model_provider_configured": False,
            "arbitrary_codex_config_present": False,
        }
        profile = build_codex_profile("account", evidence)
        self.assertEqual(profile.provider_id, CODEX_POLICY.provider_id)
        self.assertEqual(profile.external_agent, CODEX_POLICY.external_agent)
        self.assertEqual(profile.pinned_version, CODEX_POLICY.pinned_version)
        self.assertEqual(profile.retry_count, 0)
        self.assertEqual(profile.fallback_state, 'disabled')
        self.assertFalse(profile.live_ready)
        self.assertEqual(profile.live_readiness, 'BLOCKED')

    def test_claude_profile_pass(self):
        evidence = {
            "api_key_present": False,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "dangerous_permission_bypass": False,
            "hide_claude_auth": False,
        }
        profile = build_claude_profile("account", evidence)
        self.assertEqual(profile.provider_id, CLAUDE_POLICY.provider_id)
        self.assertEqual(profile.session_meta, claude_session_meta())

        # Claude meta exact false
        self.assertFalse(profile.session_meta["claudeCode"]["options"]["allowDangerouslySkipPermissions"])

    def test_antigravity_profile_pass(self):
        evidence = {
            "api_key_present": False,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "cloud_billing_selected": False,
            "overages_enabled": False,
            "adc_present": False,
            "vertex_selected": False,
        }
        profile = build_antigravity_profile("account", evidence, "windows", "x86_64")
        self.assertEqual(profile.provider_id, ANTIGRAVITY_POLICY.provider_id)
        self.assertEqual(profile.binary_name, "agy_acp_server.exe")

    def test_mutation_resistance(self):
        evidence = {
            "api_key_present": False,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "custom_model_provider_configured": False,
            "arbitrary_codex_config_present": False,
        }
        profile = build_codex_profile("account", evidence)
        config = profile.get_static_preflight_config()
        config["new_key"] = "hacked"
        self.assertNotIn("new_key", profile.get_static_preflight_config())

        with self.assertRaises(Exception): # frozen dataclass
            profile.provider_id = "hacked"
    def test_claude_meta_exact_false_failure(self):
        evidence = {
            "api_key_present": False,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "dangerous_permission_bypass": False,
            "hide_claude_auth": False,
        }
        bad_meta = {"claudeCode": {"options": {"allowDangerouslySkipPermissions": True}}}
        with self.assertRaises(ValueError):
            build_claude_profile("account", evidence, bad_meta)

    def test_antigravity_unsupported_arch(self):
        evidence = {
            "api_key_present": False,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "cloud_billing_selected": False,
            "overages_enabled": False,
            "adc_present": False,
            "vertex_selected": False,
        }
        with self.assertRaises(ValueError):
            build_antigravity_profile("account", evidence, "mac", "x86_64")

    def test_wrong_auth_failure(self):
        evidence = {
            "api_key_present": False,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "custom_model_provider_configured": False,
            "arbitrary_codex_config_present": False,
        }
        with self.assertRaises(ValueError):
            build_codex_profile("apikey", evidence)

    def test_malformed_evidence_failure(self):
        with self.assertRaises(Exception):
            build_codex_profile("account", ["not_a_dict"])

    def test_ast_no_os_subprocess_import(self):
        # Ensure no os/subprocess imported
        files_to_check = [
            Path("src/providers/codex_acp.py"),
            Path("src/providers/claude_acp.py"),
            Path("src/providers/antigravity_acp.py"),
        ]
        for path in files_to_check:
            with open(path, "r") as f:
                tree = ast.parse(f.read(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name, ("os", "subprocess"))
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn(node.module, ("os", "subprocess"))

    def test_no_duplicate_version_literals(self):
        files_to_check = [
            Path("src/providers/codex_acp.py"),
            Path("src/providers/claude_acp.py"),
            Path("src/providers/antigravity_acp.py"),
        ]
        for path in files_to_check:
            with open(path, "r") as f:
                content = f.read()
                self.assertNotIn("1.12.0", content)
                self.assertNotIn("0.79.0", content)
                self.assertNotIn("1.1.1", content)
                self.assertNotIn("@agentclientprotocol/codex-acp", content)
                self.assertNotIn("@agentclientprotocol/claude-agent-acp", content)
                self.assertNotIn("antigravity-acp", content)


    def test_missing_or_true_evidence_failure(self):
        # true evidence fail
        evidence_true = {
            "api_key_present": True,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "custom_model_provider_configured": False,
            "arbitrary_codex_config_present": False,
        }
        with self.assertRaises(ValueError):
            build_codex_profile("account", evidence_true)

        # missing evidence fail
        evidence_missing = {
            "api_key_present": False,
            # gateway_configured is missing
            "external_cloud_configured": False,
            "custom_model_provider_configured": False,
            "arbitrary_codex_config_present": False,
        }
        with self.assertRaises(ValueError):
            build_codex_profile("account", evidence_missing)

if __name__ == "__main__":
    unittest.main()
