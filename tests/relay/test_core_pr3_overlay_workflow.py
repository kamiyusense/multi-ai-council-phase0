import re
import unittest
from pathlib import Path

class TestCorePR3OverlayWorkflow(unittest.TestCase):
    def setUp(self):
        self.workflow_path = Path(".github/workflows/relay-core-pr3-overlay-validation.yml")
        self.assertTrue(self.workflow_path.exists(), "Workflow file is missing")
        self.workflow_text = self.workflow_path.read_text()

    def test_workflow_does_not_contain_forbidden_strings(self):
        forbidden = [
            "workflow_dispatch",
            "schedule:",
            "JULES_API_KEY",
            "secrets.",
            "permissions: write",
            "contents: write",
            "actions/upload-artifact",
            "api.openai.com",
            "api.anthropic.com",
            "generativelanguage.googleapis.com"
        ]

        for f in forbidden:
            self.assertNotIn(f, self.workflow_text, f"Forbidden string found: {f}")

    def test_workflow_has_required_configurations(self):
        self.assertIn("permissions:\n  contents: read", self.workflow_text)
        self.assertIn("feature/relay-transport-7070955470193506982", self.workflow_text)
        self.assertIn("automation/command_bus/relay_overlay_validation_requests/*.json", self.workflow_text)
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", self.workflow_text)

        checkout_count = self.workflow_text.count("uses: actions/checkout")
        pinned_checkout_count = self.workflow_text.count("uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262")
        self.assertEqual(checkout_count, pinned_checkout_count, "All checkouts must be pinned.")

        persist_count = self.workflow_text.count("persist-credentials: false")
        self.assertEqual(checkout_count, persist_count, "persist-credentials: false must be present for all checkouts.")

        self.assertIn("curl --silent --show-error --fail-with-body --retry 0", self.workflow_text)
        self.assertNotRegex(self.workflow_text, r"--retry\\s+[1-9][0-9]*")
        self.assertIn("Checkout exact triggering commit", self.workflow_text)

    def test_workflow_has_expected_command_logic(self):
        self.assertIn("494b7296f32dce1c173a7699e4bd2d87f70d31a9", self.workflow_text)
        self.assertIn("PYTHONPATH=relay/src python relay/tests/relay/core_pr3_overlay_runner.py", self.workflow_text)
        self.assertIn("--core-root core", self.workflow_text)
        self.assertIn("--relay-root relay", self.workflow_text)
        self.assertIn("--core-head", self.workflow_text)

    def test_workflow_github_token(self):
        self.assertIn("github.token", self.workflow_text.lower())

    def test_workflow_enforces_append_only(self):
        self.assertIn("jq '.files | length'", self.workflow_text)
        self.assertIn('== "1"', self.workflow_text)
        self.assertIn("'.files[0].status'", self.workflow_text)
        self.assertIn('== "added"', self.workflow_text)
        self.assertIn("^automation/command_bus/relay_overlay_validation_requests/", self.workflow_text)
        self.assertIn('.purpose | select(type == "string" and length > 0)', self.workflow_text)

    def test_workflow_enforces_parent_binding(self):
        self.assertIn("jq '.parents | length'", self.workflow_text)
        self.assertIn("'.parents[0].sha'", self.workflow_text)
        self.assertIn("relay_sha must equal the triggering commit's sole parent", self.workflow_text)

    def test_overlay_result_contract_matches_runner_output(self):
        required = (
            '.dispatch_counts == {"openai": 1, "anthropic": 1, "google": 1}',
            '.collect_counts == {"openai": 1, "anthropic": 1, "google": 1}',
            '.abort_counts == {"openai": 0, "anthropic": 0, "google": 0}',
            ".report_contains_human_final == true",
            '.relay_compatibility == "PASS"',
            '.provider_order == ["openai", "anthropic", "google"]',
            ".participant_count == 3",
            ".agreement_count == 3",
            ".formal_consensus == false",
            ".human_required == true",
            '"live_turn_executed": false',
            '"retry_count": 0',
            '"fallback_state": "disabled"',
            '"fail_count": 0',
            '"unknown_count": 0',
        )
        for fragment in required:
            self.assertIn(fragment, self.workflow_text)
        for obsolete in (".each_dispatch_count",):
            self.assertNotIn(obsolete, self.workflow_text)
        self.assertNotIn("jq -r '.collect_count'", self.workflow_text)
        self.assertNotIn("jq -r '.abort_count'", self.workflow_text)

    def test_no_live_provider_or_secret_surface(self):
        for value in (
            "jules.googleapis.com",
            "JULES_API_KEY",
            "secrets.",
            "contents: write",
            "permissions: write",
            "workflow_dispatch",
            "schedule:",
        ):
            self.assertNotIn(value, self.workflow_text)
        self.assertNotRegex(
            self.workflow_text,
            re.compile(r"\\b(curl|wget)\\b.*(?:openai|anthropic|jules|googleapis)", re.I),
        )

if __name__ == "__main__":
    unittest.main()
