import unittest

from automation.command_bus.claude_jules_budget_summary import summarize_budget_slots

class TestBudgetSummary(unittest.TestCase):
    def test_summary_exact_values_empty(self):
        result = summarize_budget_slots([])
        self.assertEqual(result, {'used': 0, 'cap': 10, 'remaining': 10, 'command_ids': []})

    def test_summary_exact_values_in_order(self):
        slots = [
            {'slot': 1, 'command_id': 'cmd-1'},
            {'slot': 2, 'command_id': 'cmd-2'}
        ]
        result = summarize_budget_slots(slots)
        self.assertEqual(result, {'used': 2, 'cap': 10, 'remaining': 8, 'command_ids': ['cmd-1', 'cmd-2']})

    def test_summary_exact_values_out_of_order(self):
        slots = [
            {'slot': 2, 'command_id': 'cmd-2'},
            {'slot': 1, 'command_id': 'cmd-1'}
        ]
        result = summarize_budget_slots(slots)
        self.assertEqual(result, {'used': 2, 'cap': 10, 'remaining': 8, 'command_ids': ['cmd-1', 'cmd-2']})

    def test_invalid_slots_rejected_out_of_order(self):
        slots = [
            {'slot': 1, 'command_id': 'cmd-1'},
            {'slot': 3, 'command_id': 'cmd-3'}
        ]
        with self.assertRaises(ValueError):
            summarize_budget_slots(slots)

    def test_invalid_slots_rejected_repeated_command_id(self):
        slots = [
            {'slot': 1, 'command_id': 'cmd-1'},
            {'slot': 2, 'command_id': 'cmd-1'}
        ]
        with self.assertRaises(ValueError):
            summarize_budget_slots(slots)

    def test_invalid_slots_rejected_too_many_slots(self):
        slots = [{'slot': i, 'command_id': f'cmd-{i}'} for i in range(1, 12)]
        with self.assertRaises(ValueError):
            summarize_budget_slots(slots)

    def test_invalid_slots_rejected_bool(self):
        slots = [
            {'slot': True, 'command_id': 'cmd-1'}
        ]
        with self.assertRaises(ValueError):
            summarize_budget_slots(slots)

if __name__ == '__main__':
    unittest.main()
