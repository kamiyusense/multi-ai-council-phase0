import ast
import unittest
from pathlib import Path

from providers.policy import (
    ANTIGRAVITY_POLICY,
    CLAUDE_POLICY,
    CODEX_POLICY,
    claude_session_meta,
)
from providers.preflight import validate_provider_static


def common():
    return {
        "api_key_present": False,
        "gateway_configured": False,
        "external_cloud_configured": False,
    }


class TestProviderPreflight(unittest.TestCase):
    def test_no_environ_or_subprocess_used(self):
        source = Path("src/providers/preflight.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    self.assertNotIn(alias.name, ["os", "subprocess", "sys"])
            if isinstance(node, ast.Attribute) and node.attr == "environ":
                self.fail("os.environ read detected")
            if isinstance(node, ast.Call):
                if hasattr(node.func, "id") and node.func.id in ["eval", "exec", "open"]:
                    self.fail(f"forbidden builtin {node.func.id} used")

    def test_unknown_provider_fails_closed(self):
        res = validate_provider_static("unknown", "account", common())
        self.assertEqual(res["static_configuration_status"], "UNKNOWN")
        self.assertEqual(res["provider_id"], "UNKNOWN")
        self.assertEqual(res["live_readiness"], "BLOCKED")

    def test_openai_pass_uses_policy_metadata(self):
        flags = common() | {
            "custom_model_provider_configured": False,
            "arbitrary_codex_config_present": False,
        }
        res = validate_provider_static("openai", "account", flags)
        self.assertEqual(res["static_configuration_status"], "PASS")
        self.assertEqual(res["provider_id"], CODEX_POLICY.provider_id)
        self.assertEqual(res["external_agent"], CODEX_POLICY.external_agent)
        self.assertEqual(res["pinned_version"], CODEX_POLICY.pinned_version)
        self.assertEqual(res["retry_count"], 0)
        self.assertEqual(res["fallback_state"], "disabled")
        self.assertFalse(res["live_ready"])
        self.assertIn("provider-internal retry proof remains UNKNOWN", res["reasons"])

    def test_common_route_flags_missing_true_or_malformed_fail_closed(self):
        for provider in ("openai", "anthropic", "google"):
            for key in ("api_key_present", "gateway_configured", "external_cloud_configured"):
                for value in (True, None, 0, "false"):
                    flags = common()
                    flags[key] = value
                    res = validate_provider_static(provider, "account", flags)
                    self.assertEqual(
                        res["static_configuration_status"],
                        "UNKNOWN",
                        (provider, key, value, res),
                    )

    def test_route_evidence_itself_must_be_mapping(self):
        for bad in (None, [], "nope", 1):
            res = validate_provider_static("openai", "account", bad)
            self.assertEqual(res["static_configuration_status"], "UNKNOWN")
            self.assertEqual(res["provider_id"], "openai")

    def test_invalid_auth_kind_fails_closed(self):
        flags = common() | {
            "custom_model_provider_configured": False,
            "arbitrary_codex_config_present": False,
        }
        for auth in (None, "api_key", "", 1):
            res = validate_provider_static("openai", auth, flags)  # type: ignore[arg-type]
            self.assertEqual(res["static_configuration_status"], "UNKNOWN")
            self.assertEqual(res["provider_id"], "openai")

    def test_openai_specific_flags_fail_closed(self):
        base = common() | {
            "custom_model_provider_configured": False,
            "arbitrary_codex_config_present": False,
        }
        for key in ("custom_model_provider_configured", "arbitrary_codex_config_present"):
            for mode in ("missing", True, None, "false"):
                flags = dict(base)
                if mode == "missing":
                    flags.pop(key)
                else:
                    flags[key] = mode
                res = validate_provider_static("openai", "account", flags)
                self.assertEqual(res["static_configuration_status"], "UNKNOWN")

    def test_anthropic_pass_requires_exact_session_meta(self):
        flags = common() | {
            "dangerous_permission_bypass": False,
            "hide_claude_auth": False,
        }
        res = validate_provider_static(
            "anthropic",
            "account",
            flags,
            provider_meta=claude_session_meta(),
        )
        self.assertEqual(res["static_configuration_status"], "PASS")
        self.assertEqual(res["provider_id"], CLAUDE_POLICY.provider_id)
        self.assertIn("provider/SDK retry/fallback proof remains UNKNOWN", res["reasons"])
        self.assertFalse(
            claude_session_meta()["claudeCode"]["options"]["allowDangerouslySkipPermissions"]
        )

    def test_anthropic_meta_must_match_exactly(self):
        flags = common() | {
            "dangerous_permission_bypass": False,
            "hide_claude_auth": False,
        }
        bad_values = (
            None,
            [],
            "bad",
            {"claudeCode": {"options": {"allowDangerouslySkipPermissions": True}}},
            {
                "claudeCode": {
                    "options": {
                        "allowDangerouslySkipPermissions": False,
                        "extra": True,
                    }
                }
            },
        )
        for bad in bad_values:
            res = validate_provider_static(
                "anthropic",
                "account",
                flags,
                provider_meta=bad,  # type: ignore[arg-type]
            )
            self.assertEqual(res["static_configuration_status"], "UNKNOWN")
            self.assertEqual(res["provider_id"], "anthropic")

    def test_anthropic_specific_flags_fail_closed(self):
        base = common() | {
            "dangerous_permission_bypass": False,
            "hide_claude_auth": False,
        }
        for key in ("dangerous_permission_bypass", "hide_claude_auth"):
            for mode in ("missing", True, None, "false"):
                flags = dict(base)
                if mode == "missing":
                    flags.pop(key)
                else:
                    flags[key] = mode
                res = validate_provider_static(
                    "anthropic",
                    "account",
                    flags,
                    provider_meta=claude_session_meta(),
                )
                self.assertEqual(res["static_configuration_status"], "UNKNOWN")

    def test_google_pass_and_policy_metadata(self):
        flags = common() | {
            "cloud_billing_selected": False,
            "overages_enabled": False,
            "adc_present": False,
            "vertex_selected": False,
        }
        res = validate_provider_static(
            "google",
            "account",
            flags,
            platform="linux",
            architecture="x86_64",
        )
        self.assertEqual(res["static_configuration_status"], "PASS")
        self.assertEqual(res["provider_id"], ANTIGRAVITY_POLICY.provider_id)
        self.assertEqual(res["external_agent"], ANTIGRAVITY_POLICY.external_agent)
        self.assertEqual(res["pinned_version"], ANTIGRAVITY_POLICY.pinned_version)
        self.assertIn(
            "internal retry/fallback and executed-model proof remain UNKNOWN",
            res["reasons"],
        )

    def test_google_specific_route_flags_fail_closed(self):
        base = common() | {
            "cloud_billing_selected": False,
            "overages_enabled": False,
            "adc_present": False,
            "vertex_selected": False,
        }
        for key in ("cloud_billing_selected", "overages_enabled", "adc_present", "vertex_selected"):
            for mode in ("missing", True, None, "false"):
                flags = dict(base)
                if mode == "missing":
                    flags.pop(key)
                else:
                    flags[key] = mode
                res = validate_provider_static(
                    "google",
                    "account",
                    flags,
                    platform="linux",
                    architecture="x86_64",
                )
                self.assertEqual(res["static_configuration_status"], "UNKNOWN")

    def test_google_platform_architecture_fail_closed(self):
        flags = common() | {
            "cloud_billing_selected": False,
            "overages_enabled": False,
            "adc_present": False,
            "vertex_selected": False,
        }
        for platform, arch in (
            (None, "x86_64"),
            ("linux", None),
            (1, "x86_64"),
            ("linux", []),
            ("unknownOS", "x86_64"),
        ):
            res = validate_provider_static(
                "google",
                "account",
                flags,
                platform=platform,  # type: ignore[arg-type]
                architecture=arch,  # type: ignore[arg-type]
            )
            self.assertEqual(res["static_configuration_status"], "UNKNOWN")
            self.assertEqual(res["provider_id"], "google")

    def test_static_pass_never_means_live_ready(self):
        cases = [
            (
                "openai",
                common() | {
                    "custom_model_provider_configured": False,
                    "arbitrary_codex_config_present": False,
                },
                {},
            ),
            (
                "anthropic",
                common() | {
                    "dangerous_permission_bypass": False,
                    "hide_claude_auth": False,
                },
                {"provider_meta": claude_session_meta()},
            ),
            (
                "google",
                common() | {
                    "cloud_billing_selected": False,
                    "overages_enabled": False,
                    "adc_present": False,
                    "vertex_selected": False,
                },
                {"platform": "linux", "architecture": "x86_64"},
            ),
        ]
        for provider, flags, kwargs in cases:
            res = validate_provider_static(provider, "account", flags, **kwargs)
            self.assertEqual(res["static_configuration_status"], "PASS")
            self.assertEqual(res["live_readiness"], "BLOCKED")
            self.assertFalse(res["live_ready"])
            self.assertEqual(res["retry_count"], 0)
            self.assertEqual(res["fallback_state"], "disabled")


if __name__ == "__main__":
    unittest.main()
