import unittest
from automation.command_bus.next_jules_prepare import NextTaskPlan, recheck_next_jules
from automation.command_bus.work_bridge_prepare import prepare_bridge
from .static_bridge_simulation import run_simulation
from .bridge_fixtures import bridge_snapshot
from .closed_loop_fixtures import NOW


class SoakTests(unittest.TestCase):
    def test_four_colors_eight_virtual_loops_faults_and_restart(self):
        result = run_simulation()
        self.assertEqual(result['virtual_loops'], 32)
        self.assertEqual(result['fake_submissions'], 32)
        self.assertEqual(result['unreserved_next_candidates'], 32)
        self.assertGreaterEqual(result['fault_observations'], 1000)
        self.assertEqual(set(result['invariant_violations'].values()), {0})
        self.assertEqual(result['external_execution'], 0)

    def test_concurrent_unreserved_global_candidates_are_blocked_on_fresh_collision(self):
        plans = [NextTaskPlan(**prepare_bridge(bridge_snapshot(lane, terminal=True), now=NOW)['next_task'])
                 for lane in ('blue', 'yellow', 'green', 'red')]
        self.assertEqual({p.claim['loop_number'] for p in plans}, {901})
        final = bridge_snapshot()['next_snapshot']
        final['tree_entries'].append({'path': 'automation/command_bus/loop_id_claims/901.json', 'type': 'blob'})
        for plan in plans:
            checked = recheck_next_jules(plan, **final, now=NOW)
            self.assertEqual(checked.status, 'BLOCKED')
            self.assertEqual(checked.reservation_state, 'NOT_RESERVED')
            self.assertIs(checked.external_write_attempted, False)
