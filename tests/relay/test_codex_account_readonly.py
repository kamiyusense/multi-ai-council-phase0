import unittest

from relay.codex_account_readonly import (
    READ_ONLY_METHODS, assert_read_only, read_only_requests, summarize_account_evidence,
)

OK_ACCOUNT = {"account": {"type": "chatgpt", "email": "private@example.invalid", "planType": "plus"}, "requiresOpenaiAuth": False}
OK_LIMITS = {
    "ordinaryUsageAllowed": True, "accountId": "acct-private",
    "rateLimits": {
        "primary": {"usedPercent": 12.5, "windowDurationMins": 300, "resetsAt": 1760000000},
        "secondary": {"usedPercent": 3, "windowDurationMins": 10080, "resetsAt": 1760500000},
        "credits": {"hasCredits": True, "unlimited": False, "balance": "99"},
        "spendControlReached": False, "rateLimitReachedType": None, "planType": "plus",
    },
}


class TestCodexAccountReadonly(unittest.TestCase):
    def test_only_two_requests_and_no_token_refresh(self):
        reqs = read_only_requests()
        self.assertEqual({r["method"] for r in reqs}, set(READ_ONLY_METHODS))
        self.assertIs(reqs[0]["params"]["refreshToken"], False)
        for bad in ("account/login/start", "account/logout", "account/login/cancel", "turn/start"):
            with self.assertRaises(ValueError):
                assert_read_only(bad)

    def test_happy_path_and_private_fields_not_copied(self):
        ev = summarize_account_evidence(OK_ACCOUNT, OK_LIMITS)
        self.assertEqual((ev["auth_state"], ev["plan_type"], ev["ordinary_usage_allowed"]), ("CHATGPT_ACCOUNT", "plus", True))
        self.assertEqual(ev["primary_window"]["used_percent"], 12.5)
        self.assertIsNone(ev["rate_limit_reached_type"])
        self.assertEqual(ev["side_effects"], 0)
        blob = str(ev)
        for private in ("private@example.invalid", "acct-private", "99"):
            self.assertNotIn(private, blob)

    def test_missing_or_malformed_is_unknown(self):
        for acct, lim in ((None, None), ({}, {}), ("x", [1]), ({"account": None, "requiresOpenaiAuth": "yes"}, OK_LIMITS)):
            with self.subTest(acct=acct):
                ev = summarize_account_evidence(acct, lim)
                self.assertEqual(ev["auth_state"], "UNKNOWN")
                self.assertEqual(ev["ordinary_usage_allowed"], "UNKNOWN")

    def test_not_authenticated_never_reports_usage_allowed(self):
        ev = summarize_account_evidence({"account": None, "requiresOpenaiAuth": True}, OK_LIMITS)
        self.assertEqual((ev["auth_state"], ev["ordinary_usage_allowed"]), ("NOT_AUTHENTICATED", "UNKNOWN"))

    def test_api_key_route_flagged(self):
        ev = summarize_account_evidence({"account": {"type": "apiKey"}, "requiresOpenaiAuth": False}, OK_LIMITS)
        self.assertEqual(ev["auth_state"], "API_KEY_ROUTE_VIOLATION")

    def test_null_values_are_unknown_not_ok(self):
        lim = {"ordinaryUsageAllowed": None, "rateLimits": {"primary": None, "spendControlReached": None}}
        ev = summarize_account_evidence(OK_ACCOUNT, lim)
        self.assertEqual((ev["ordinary_usage_allowed"], ev["primary_window"], ev["spend_control_reached"]), ("UNKNOWN",) * 3)


if __name__ == "__main__":
    unittest.main()
