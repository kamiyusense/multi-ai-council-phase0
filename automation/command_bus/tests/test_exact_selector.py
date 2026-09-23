import unittest

from automation.command_bus.exact_selector import (
    EXPECTED_BRANCH, EXPECTED_REPOSITORY, SelectionState,
    choose_exact, exact_repository_branch_gate, verify_selected_readback,
)


class ExactSelectorTests(unittest.TestCase):
    def test_exact_repository_and_branch_gate_passes(self):
        result=exact_repository_branch_gate(
            repository_candidates=["other/repo", EXPECTED_REPOSITORY],
            repository_readback=EXPECTED_REPOSITORY,
            branch_candidates=["main", EXPECTED_BRANCH],
            branch_readback=EXPECTED_BRANCH,
        )
        self.assertEqual(result["state"], SelectionState.EXACT.value)
        self.assertTrue(result["task_submit_allowed"])

    def test_first_candidate_is_never_implicit_selection(self):
        result=choose_exact(["wrong", EXPECTED_BRANCH], EXPECTED_BRANCH)
        self.assertEqual(result.value, EXPECTED_BRANCH)

    def test_substring_match_is_rejected(self):
        result=choose_exact([EXPECTED_BRANCH+"-copy"], EXPECTED_BRANCH)
        self.assertEqual(result.state, SelectionState.BLOCKED)

    def test_duplicate_exact_matches_are_rejected(self):
        result=choose_exact([EXPECTED_BRANCH, EXPECTED_BRANCH], EXPECTED_BRANCH)
        self.assertEqual(result.state, SelectionState.BLOCKED)

    def test_missing_candidate_list_is_unknown(self):
        self.assertEqual(choose_exact(None, EXPECTED_BRANCH).state, SelectionState.UNKNOWN)

    def test_repository_readback_mismatch_blocks_submit(self):
        result=exact_repository_branch_gate(
            repository_candidates=[EXPECTED_REPOSITORY],
            repository_readback="wrong/repo",
            branch_candidates=[EXPECTED_BRANCH],
            branch_readback=EXPECTED_BRANCH,
        )
        self.assertEqual(result["state"], SelectionState.BLOCKED.value)
        self.assertFalse(result["task_submit_allowed"])

    def test_branch_readback_mismatch_blocks_submit(self):
        result=exact_repository_branch_gate(
            repository_candidates=[EXPECTED_REPOSITORY],
            repository_readback=EXPECTED_REPOSITORY,
            branch_candidates=[EXPECTED_BRANCH],
            branch_readback="main",
        )
        self.assertEqual(result["state"], SelectionState.BLOCKED.value)
        self.assertFalse(result["task_submit_allowed"])

    def test_unavailable_readback_is_unknown(self):
        self.assertEqual(verify_selected_readback(None, EXPECTED_BRANCH).state, SelectionState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
