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

        self.assertIn("curl", self.workflow_text)
        self.assertIn("--retry 0", self.workflow_text)

        # We also need to check for retry>0 logic elsewhere.
        self.assertNotIn("--retry 1", self.workflow_text)
        self.assertNotIn("--retry 2", self.workflow_text)
        self.assertNotIn("--retry 3", self.workflow_text)

    def test_workflow_has_expected_command_logic(self):
        self.assertIn("494b7296f32dce1c173a7699e4bd2d87f70d31a9", self.workflow_text)
        self.assertIn("PYTHONPATH=relay/src python relay/tests/relay/core_pr3_overlay_runner.py --core-root core --relay-root relay --core-head", self.workflow_text)

    def test_workflow_github_token(self):
        self.assertIn("github.token", self.workflow_text.lower())

    def test_workflow_enforces_append_only(self):
        self.assertIn(".status == \"added\"", self.workflow_text)
        self.assertIn(".filename | test(\"^automation/command_bus/relay_overlay_validation_requests/", self.workflow_text)

    def test_workflow_enforces_parent_binding(self):
        self.assertIn(".parents | length", self.workflow_text)
        self.assertIn(".parents[0].sha", self.workflow_text)

if __name__ == "__main__":
    unittest.main()
