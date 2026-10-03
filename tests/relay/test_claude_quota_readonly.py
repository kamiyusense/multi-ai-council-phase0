import json
import unittest
from datetime import datetime, timezone

from relay.claude_quota_readonly import summarize_claude_rate_limit_info as rate, summarize_claude_usage_response as usage

# SYNTHETIC shapes (SDKRateLimitInfo / `/usage` response of claude-agent-sdk 0.3.286); no real account data.
INFO = {"status": "allowed_warning", "resetsAt": 1790000000, "rateLimitType": "five_hour", "utilization": 83.5,
        "overageStatus": "rejected", "overageDisabledReason": "out_of_credits", "canUserPurchaseCredits": True,
        "hasChargeableSavedPaymentMethod": True}
USAGE = {"session": {"total_cost_usd": 1.23, "model_usage": {"m": {"inputTokens": 1}}}, "subscription_type": "max",
         "rate_limits_available": True,
         "rate_limits": {"five_hour": {"utilization": 12, "resets_at": "2026-10-04T00:00:00Z"},
                         "seven_day": {"utilization": 40.5, "resets_at": None},
                         "extra_usage": {"is_enabled": True, "monthly_limit": 100, "used_credits": 5, "currency": "USD"}}}


class TestClaudeQuotaReadonly(unittest.TestCase):
    def test_rate_limit_info(self):
        r = rate(INFO)
        self.assertEqual((r["status"], r["limit_type"], r["used_percent"], r["resets_at_epoch"], r["side_effects"]),
                         ("allowed_warning", "five_hour", 83.5, 1790000000, 0))

    def test_billing_and_credit_fields_are_never_copied(self):
        blob = json.dumps(rate(INFO)) + json.dumps(usage(USAGE))
        for leaked in ("out_of_credits", "overage", "credits", "currency", "USD", "total_cost", "max", "inputTokens", "monthly_limit"):
            self.assertNotIn(leaked, blob)

    def test_usage_response_windows(self):
        u = usage(USAGE)
        self.assertEqual(u["rate_limits_available"], True)
        self.assertEqual(u["five_hour"], {"used_percent": 12, "resets_at_epoch": int(datetime(2026, 10, 4, tzinfo=timezone.utc).timestamp())})
        self.assertEqual(u["seven_day"], {"used_percent": 40.5, "resets_at_epoch": "UNKNOWN"})

    def test_malformed_is_unknown_never_ok(self):
        for bad in (None, [], "x", {}, {"status": "fine", "rateLimitType": "hourly", "utilization": 101, "resetsAt": -1},
                    {"utilization": True}, {"utilization": "5"}):
            with self.subTest(bad=bad):
                r = rate(bad)
                self.assertEqual((r["status"], r["limit_type"], r["used_percent"], r["resets_at_epoch"]), ("UNKNOWN",) * 4)
        for bad in (None, [], {}, {"rate_limits": []}, {"rate_limits": {"five_hour": {"utilization": 150}}}):
            with self.subTest(bad=bad):
                u = usage(bad)
                self.assertEqual((u["five_hour"], u["seven_day"]), ("UNKNOWN", "UNKNOWN"))


if __name__ == "__main__":
    unittest.main()
