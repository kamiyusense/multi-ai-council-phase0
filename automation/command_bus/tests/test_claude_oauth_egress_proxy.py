from __future__ import annotations

import unittest

from automation.command_bus.claude_oauth_egress_proxy import (
    EXPECTED_ALLOWED_CONNECT,
    evaluate_connect_authority,
    open_allowed_tunnel,
    validate_runtime_environment,
)


class ClaudeOAuthEgressProxyTests(unittest.TestCase):
    def test_exact_platform_connect_is_allowed(self):
        decision = evaluate_connect_authority("platform.claude.com:443")
        self.assertTrue(decision.allowed)
        self.assertEqual((decision.host, decision.port), ("platform.claude.com", 443))

    def test_model_api_host_is_denied_before_connector(self):
        calls = []

        def connector(host, port, timeout):
            calls.append((host, port, timeout))
            raise AssertionError("connector must not be called for denied model host")

        decision, upstream = open_allowed_tunnel(
            "api.anthropic.com:443",
            connector=connector,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "host_not_allowlisted")
        self.assertIsNone(upstream)
        self.assertEqual(calls, [])

    def test_allowed_target_has_one_attempt_and_no_fallback(self):
        calls = []

        def connector(host, port, timeout):
            calls.append((host, port, timeout))
            raise OSError("fixture connect failure")

        decision, upstream = open_allowed_tunnel(
            "platform.claude.com:443",
            connector=connector,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "single_connect_failed")
        self.assertIsNone(upstream)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ("platform.claude.com", 443))

    def test_broad_or_noncanonical_destinations_fail_closed(self):
        denied = (
            None,
            "",
            "PLATFORM.CLAUDE.COM:443",
            "platform.claude.com",
            "platform.claude.com:0443",
            "platform.claude.com:444",
            "platform.claude.com:443/path",
            "user@platform.claude.com:443",
            "platform.claude.com:443?x=1",
            "127.0.0.1:443",
            "*.claude.com:443",
            "claude.com:443",
        )
        for authority in denied:
            with self.subTest(authority=authority):
                self.assertFalse(evaluate_connect_authority(authority).allowed)

    def test_environment_is_exact_and_additional_proxy_contract_keys_fail(self):
        good = {
            "PHASE0_OAUTH_PROXY_BIND": "172.29.247.3",
            "PHASE0_OAUTH_PROXY_PORT": "8081",
            "PHASE0_OAUTH_PROXY_ALLOWED_CONNECT": EXPECTED_ALLOWED_CONNECT,
        }
        self.assertEqual(validate_runtime_environment(good)["status"], "PASS")

        for mutate in (
            lambda env: env.update(PHASE0_OAUTH_PROXY_ALLOWED_CONNECT="api.anthropic.com:443"),
            lambda env: env.update(PHASE0_OAUTH_PROXY_PORT="8082"),
            lambda env: env.update(PHASE0_OAUTH_PROXY_EXTRA_HOST="example.com:443"),
        ):
            bad = dict(good)
            mutate(bad)
            self.assertEqual(validate_runtime_environment(bad)["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
