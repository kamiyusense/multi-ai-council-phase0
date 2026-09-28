from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/jules-chat-semiauto.yml")


class JulesSemiAutoWorkflowIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_jules_payload_starts_from_isolated_work_branch(self):
        self.assertIn('--arg starting_branch "${WORK_BRANCH}"', self.text)
        self.assertNotIn('--arg starting_branch "${TARGET_BRANCH}"', self.text)
        self.assertIn(
            "EXPECTED_BRANCH: ${{ steps.validate.outputs.work_branch }}",
            self.text,
        )

    def test_workflow_verifies_both_target_and_work_snapshots(self):
        self.assertIn(
            'target_head="$(read_branch_head "${TARGET_BRANCH}")"',
            self.text,
        )
        self.assertIn(
            'work_head="$(read_branch_head "${WORK_BRANCH}")"',
            self.text,
        )
        self.assertIn(
            'if [[ "${target_head}" != "${EXPECTED_HEAD}" ]]',
            self.text,
        )
        self.assertIn(
            'if [[ "${work_head}" != "${EXPECTED_HEAD}" ]]',
            self.text,
        )
        self.assertIn(
            'if [[ "${target_tree}" != "${EXPECTED_TREE}" ]]',
            self.text,
        )
        self.assertIn(
            'if [[ "${work_tree}" != "${EXPECTED_TREE}" ]]',
            self.text,
        )

    def test_workflow_remains_read_only_and_retry_zero(self):
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertIn("curl --silent --show-error --fail-with-body --retry 0", self.text)
        self.assertNotIn("git push", self.text)
        self.assertNotIn("force: true", self.text)


if __name__ == "__main__":
    unittest.main()
