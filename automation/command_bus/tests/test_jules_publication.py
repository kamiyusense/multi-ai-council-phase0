import unittest

from automation.command_bus.jules_publication import (
    PublicationState, fast_forward_allowed, validate_jules_publication,
)

HEAD="a"*40
RESULT="b"*40
PATH="tests/relay/test_dispatcher.py"


def valid(**changes):
    values=dict(
        expected_target_head=HEAD,
        current_target_head=HEAD,
        resulting_commit=RESULT,
        parent_shas=[HEAD],
        comparison_base_branch="feature/relay-transport-7070955470193506982",
        expected_base_branch="feature/relay-transport-7070955470193506982",
        changed_paths=[{"path":PATH,"operation":"MODIFY","symlink":False}],
        allowed_paths={PATH},
        tests_passed=True,
        compileall_passed=True,
        diff_check_passed=True,
        retry_count=0,
        fallback_used=False,
        task_submitted=True,
        jules_task_started=True,
        model_started=True,
        github_mutation_uncertainty=False,
        main_direct_write=False,
    )
    values.update(changes)
    return validate_jules_publication(**values)


class JulesPublicationTests(unittest.TestCase):
    def test_valid_one_child_publication_passes(self):
        self.assertEqual(valid().state, PublicationState.PASS)

    def test_parent_must_equal_expected_target_head(self):
        self.assertEqual(valid(parent_shas=["c"*40]).state, PublicationState.BLOCKED)

    def test_merge_commit_is_rejected(self):
        self.assertEqual(valid(parent_shas=[HEAD,"c"*40]).state, PublicationState.BLOCKED)

    def test_stale_target_is_blocked(self):
        self.assertEqual(valid(current_target_head="c"*40).state, PublicationState.BLOCKED)

    def test_wrong_base_is_blocked(self):
        self.assertEqual(valid(comparison_base_branch="main").state, PublicationState.BLOCKED)

    def test_unexpected_path_delete_rename_or_symlink_block(self):
        cases=[
            [{"path":"src/relay/dispatcher.py","operation":"MODIFY","symlink":False}],
            [{"path":PATH,"operation":"DELETE","symlink":False}],
            [{"path":PATH,"operation":"RENAME","symlink":False}],
            [{"path":PATH,"operation":"MODIFY","symlink":True}],
        ]
        for changed in cases:
            with self.subTest(changed=changed):
                self.assertEqual(valid(changed_paths=changed).state, PublicationState.BLOCKED)

    def test_unknown_test_is_unknown(self):
        self.assertEqual(valid(tests_passed=None).state, PublicationState.UNKNOWN)

    def test_retry_or_fallback_blocks(self):
        self.assertEqual(valid(retry_count=1).state, PublicationState.BLOCKED)
        self.assertEqual(valid(fallback_used=True).state, PublicationState.BLOCKED)

    def test_task_model_evidence_must_be_proven(self):
        self.assertEqual(valid(task_submitted=None).state, PublicationState.UNKNOWN)
        self.assertEqual(valid(jules_task_started=False).state, PublicationState.BLOCKED)

    def test_github_mutation_uncertainty_blocks_or_unknown(self):
        self.assertEqual(valid(github_mutation_uncertainty="UNKNOWN").state, PublicationState.UNKNOWN)
        self.assertEqual(valid(github_mutation_uncertainty=True).state, PublicationState.BLOCKED)

    def test_main_direct_write_blocks(self):
        self.assertEqual(valid(main_direct_write=True).state, PublicationState.BLOCKED)

    def test_fast_forward_requires_target_unchanged_and_ancestry(self):
        decision=valid()
        self.assertEqual(fast_forward_allowed(decision,current_target_head=HEAD,expected_target_head=HEAD,resulting_commit=RESULT,ancestry_is_fast_forward=True).state, PublicationState.PASS)
        self.assertEqual(fast_forward_allowed(decision,current_target_head="c"*40,expected_target_head=HEAD,resulting_commit=RESULT,ancestry_is_fast_forward=True).state, PublicationState.BLOCKED)
        self.assertEqual(fast_forward_allowed(decision,current_target_head=HEAD,expected_target_head=HEAD,resulting_commit=RESULT,ancestry_is_fast_forward=False).state, PublicationState.BLOCKED)


if __name__ == "__main__":
    unittest.main()
