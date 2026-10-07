import unittest

from automation.command_bus.symphony_subscription_boundary import assess_new_worker_route


class SubscriptionBoundaryTests(unittest.TestCase):
    def evidence(self, limits=None):
        # Sanitized shape produced by src/relay/codex_account_readonly.py.
        return {"auth_state": "CHATGPT_ACCOUNT", "plan_type": "plus",
                "ordinary_usage_allowed": (limits or {}).get("ordinaryUsageAllowed", "UNKNOWN")}

    def test_chatgpt_route_allows_unknown_quota_without_authorizing_dispatch(self):
        decision = assess_new_worker_route(self.evidence(), worker_environment_keys=("PATH", "HOME"))
        self.assertTrue(decision.new_worker_route_compatible)
        self.assertFalse(decision.dispatch_authorized)

    def test_confirmed_unavailable_usage_defers_new_worker_only(self):
        decision = assess_new_worker_route(
            self.evidence({"ordinaryUsageAllowed": False}), worker_environment_keys=("PATH",),
        )
        self.assertFalse(decision.new_worker_route_compatible)

    def test_api_key_account_and_ambient_metered_env_are_rejected(self):
        key_account = {"auth_state": "API_KEY_ROUTE_VIOLATION", "ordinary_usage_allowed": "UNKNOWN"}
        self.assertFalse(assess_new_worker_route(key_account, worker_environment_keys=()).new_worker_route_compatible)
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
            with self.subTest(key=key):
                self.assertFalse(assess_new_worker_route(
                    self.evidence(), worker_environment_keys=("PATH", key),
                ).new_worker_route_compatible)

    def test_any_paid_fallback_blocks_new_worker_route(self):
        for flag in ("metered_fallback_configured", "paid_provider_fallback_configured",
                     "paid_credit_fallback_configured"):
            with self.subTest(flag=flag):
                self.assertFalse(assess_new_worker_route(
                    self.evidence(), worker_environment_keys=(), **{flag: True},
                ).new_worker_route_compatible)


if __name__ == "__main__":
    unittest.main()
