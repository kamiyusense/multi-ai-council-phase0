import unittest
from automation.command_bus.claude_jules_budget_summary import summarize_budget_slots

class TestClaudeJulesBudgetSummary(unittest.TestCase):
    def test_summarize_budget_slots_empty(self):
        result = summarize_budget_slots([])
        self.assertEqual(result, {'used': 0, 'cap': 10, 'remaining': 10, 'command_ids': []})

    def test_summarize_budget_slots_ordered(self):
        slots = [{'slot': 2, 'command_id': 'cmd-2'}, {'slot': 1, 'command_id': 'cmd-1'}]
        result = summarize_budget_slots(slots)
        self.assertEqual(result, {'used': 2, 'cap': 10, 'remaining': 8, 'command_ids': ['cmd-1', 'cmd-2']})

    def test_summarize_budget_slots_non_int_slot(self):
        with self.assertRaises(ValueError):
            summarize_budget_slots([{'slot': 1, 'command_id': 'cmd-1'}, {'slot': '2', 'command_id': 'cmd-2'}])

    def test_summarize_budget_slots_none_slot(self):
        with self.assertRaises(ValueError):
            summarize_budget_slots([{'slot': 1, 'command_id': 'cmd-1'}, {'slot': None, 'command_id': 'cmd-2'}])

    def test_summarize_budget_slots_bool_slot(self):
        with self.assertRaises(ValueError):
            summarize_budget_slots([{'slot': True, 'command_id': 'cmd-1'}])

    def test_summarize_budget_slots_missing_slot(self):
        with self.assertRaises(ValueError):
            summarize_budget_slots([{'slot': 1, 'command_id': 'cmd-1'}, {'slot': 3, 'command_id': 'cmd-3'}])

    def test_summarize_budget_slots_repeated_command_id(self):
        with self.assertRaises(ValueError):
            summarize_budget_slots([{'slot': 1, 'command_id': 'cmd-1'}, {'slot': 2, 'command_id': 'cmd-1'}])

    def test_summarize_budget_slots_exceeding_cap(self):
        slots = [{'slot': i, 'command_id': f'cmd-{i}'} for i in range(1, 12)]
        with self.assertRaises(ValueError):
            summarize_budget_slots(slots)
