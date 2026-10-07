import unittest

from automation.command_bus.symphony_result_adoption import AdoptionAction, decide_result_adoption


class ResultAdoptionTests(unittest.TestCase):
    def decide(self, **changes):
        arguments = dict(expected_head="h1", canonical_head="h1", canonical_trustworthy=True,
                         task_still_valid=True, mutation_operations=("ADD", "MODIFY"))
        arguments.update(changes)
        return decide_result_adoption(**arguments)

    def test_current_add_modify_result_can_be_adopted(self):
        self.assertEqual(self.decide().action, AdoptionAction.ADOPT)

    def test_old_head_is_replanned_even_if_task_was_valid(self):
        self.assertEqual(self.decide(canonical_head="h2").action, AdoptionAction.STALE_REPLAN)

    def test_invalid_task_and_destructive_or_unknown_mutation_are_isolated(self):
        self.assertEqual(self.decide(task_still_valid=False).action, AdoptionAction.ISOLATE_TASK)
        for operation in ("DELETE", "FORCE_PUSH", "DEFAULT_BRANCH_WRITE", "RENAME", "UNCLASSIFIED"):
            with self.subTest(operation=operation):
                self.assertEqual(self.decide(mutation_operations=(operation,)).action,
                                 AdoptionAction.ISOLATE_TASK)

    def test_untrustworthy_canonical_lineage_holds_authority(self):
        self.assertEqual(self.decide(canonical_trustworthy=False).action, AdoptionAction.HOLD_AUTHORITY)
        self.assertEqual(self.decide(canonical_head=None).action, AdoptionAction.HOLD_AUTHORITY)
