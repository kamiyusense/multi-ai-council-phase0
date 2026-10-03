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
        epoch = int(datetime(2026, 10, 4, tzinfo=timezone.utc).timestamp())
        self.assertEqual(u["five_hour"], {"used_percent": 12, "resets_at_epoch": epoch, "stale": "UNKNOWN"})
        self.assertEqual(u["seven_day"], {"used_percent": 40.5, "resets_at_epoch": "UNKNOWN", "stale": "UNKNOWN"})

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

    def test_non_finite_and_absurd_numbers_are_unknown_not_a_crash(self):
        """Observed defect: Python's json accepts Infinity/NaN and int(inf) raised OverflowError."""
        for text in ('{"status": "allowed", "resetsAt": Infinity, "utilization": 5}',
                     '{"status": "allowed", "resetsAt": 1e400, "utilization": NaN}',
                     '{"status": "allowed", "resetsAt": -Infinity, "utilization": Infinity}',
                     '{"resetsAt": 99999999999999999999}'):
            with self.subTest(text=text):
                r = rate(json.loads(text))
                self.assertEqual(r["resets_at_epoch"], "UNKNOWN")
                if "NaN" in text or "utilization\": Infinity" in text:
                    self.assertEqual(r["used_percent"], "UNKNOWN")
        u = usage(json.loads('{"rate_limits": {"five_hour": {"utilization": 5, "resets_at": "9999999999999999-01-01"}, "seven_day": {"utilization": Infinity}}}'))
        self.assertEqual(u["five_hour"]["resets_at_epoch"], "UNKNOWN")
        self.assertEqual(u["seven_day"], "UNKNOWN")

    def test_stale_window_needs_a_clock_and_conflicting_status_is_flagged(self):
        self.assertEqual(rate(INFO)["stale"], "UNKNOWN")  # no clock supplied
        self.assertIs(rate(INFO, now_epoch=1790000001)["stale"], True)   # reset time already passed
        self.assertIs(rate(INFO, now_epoch=1789999999)["stale"], False)
        self.assertIs(rate({**INFO, "status": "rejected", "utilization": 10})["conflict"], True)
        self.assertIs(rate({**INFO, "status": "allowed", "utilization": 100})["conflict"], True)
        self.assertIs(rate({**INFO, "status": "rejected", "utilization": 100})["conflict"], False)
        self.assertIs(rate({**INFO, "status": "allowed_warning", "utilization": 99})["conflict"], False)
        self.assertEqual(rate({"status": "allowed"})["conflict"], "UNKNOWN")  # partial data: not judged
        self.assertIs(usage(USAGE, now_epoch=2000000000)["five_hour"]["stale"], True)

    def test_partial_and_unknown_schema_keep_only_what_is_safe(self):
        r = rate({"status": "allowed", "someNewField": {"secret": "x"}, "rateLimitType": "five_hour"})
        self.assertEqual((r["status"], r["limit_type"], r["used_percent"]), ("allowed", "five_hour", "UNKNOWN"))
        self.assertNotIn("someNewField", json.dumps(r))
        self.assertEqual(usage({"rate_limits": {"five_hour": {"utilization": 5}}})["five_hour"]["resets_at_epoch"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
