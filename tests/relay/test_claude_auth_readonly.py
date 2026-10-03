import json
import unittest

from relay.claude_auth_readonly import READ_ONLY_COMMAND, summarize_claude_auth_evidence as summarize


class TestClaudeAuthReadonly(unittest.TestCase):
    def test_only_the_adapters_own_read_only_probe_is_named(self):
        self.assertEqual(READ_ONLY_COMMAND, ("auth", "status", "--json"))

    def test_subscription_login(self):
        r = summarize({"loggedIn": True, "apiProvider": "firstParty", "subscriptionType": "max", "email": "a@b.c", "orgName": "o"})
        self.assertEqual((r["auth_state"], r["plan_type"], r["quota"], r["side_effects"]), ("CLAUDE_SUBSCRIPTION_ACCOUNT", "max", "UNKNOWN", 0))
        self.assertNotIn("a@b.c", json.dumps(r))
        self.assertNotIn('"o"', json.dumps(r))

    def test_route_violations_outrank_a_subscription_login(self):
        both = {"loggedIn": True, "apiProvider": "firstParty", "apiKeySource": "apiKeyHelper", "subscriptionType": "pro"}
        self.assertEqual(summarize(both)["auth_state"], "API_KEY_ROUTE_VIOLATION")
        for provider in ("bedrock", "vertex", "gateway"):
            self.assertEqual(summarize({"loggedIn": False, "apiProvider": provider})["auth_state"], "EXTERNAL_ROUTE_VIOLATION")

    def test_logged_out_and_unknown_never_pass(self):
        self.assertEqual(summarize({"loggedIn": False})["auth_state"], "NOT_AUTHENTICATED")
        for bad in (None, [], {}, {"loggedIn": "yes"}, "not json", b"{", 3):
            with self.subTest(bad=bad):
                self.assertEqual(summarize(bad)["auth_state"], "UNKNOWN")
        # logged in but no identity signal is "no information", not an account
        self.assertEqual(summarize({"loggedIn": True})["auth_state"], "UNKNOWN")

    def test_json_string_input(self):
        self.assertEqual(summarize('{"loggedIn": true, "subscriptionType": "pro"}')["plan_type"], "pro")


if __name__ == "__main__":
    unittest.main()
