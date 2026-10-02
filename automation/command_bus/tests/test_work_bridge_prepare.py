import json
import unittest
from datetime import timedelta

from automation.command_bus.cloud_work_lanes import LANES
from automation.command_bus.work_bridge_prepare import prepare_bridge
from .bridge_fixtures import bridge_snapshot, unsafe_cases
from .closed_loop_fixtures import NOW


class BridgeTests(unittest.TestCase):
    def test_full_mock_pre_submit_then_terminal_independent_review_next_claim(self):
        for lane in LANES:
            first = prepare_bridge(bridge_snapshot(lane), now=NOW)
            self.assertEqual(first['status'], 'PREPARED_REVIEW', first)
            self.assertEqual(first['review_candidate']['lane'], lane)
            result = prepare_bridge(bridge_snapshot(lane, terminal=True), now=NOW)
            self.assertEqual(result['status'], 'PREPARED_NEXT', result)
            self.assertEqual(result['next_task']['claim']['schema_version'], 3)
            self.assertEqual(result['next_task']['reservation_state'], 'NOT_RESERVED')
            self.assertIs(result['posting_authority'], False)
            for key in ('external_send_attempted', 'model_executed', 'adoption_performed', 'claim_reserved'):
                self.assertIs(result[key], False)

    def test_all_faults_stop_successor_across_four_lanes(self):
        for lane in LANES:
            for name, mutate in unsafe_cases().items():
                with self.subTest(lane=lane, fault=name):
                    value = bridge_snapshot(lane, terminal=True)
                    mutate(value)
                    result = prepare_bridge(value, now=NOW + (timedelta(hours=1) if name == 'late_terminal' else timedelta()))
                    self.assertNotEqual(result['status'], 'PREPARED_NEXT', result)
                    self.assertFalse(result.get('next_task', {}).get('claim'), result)
                    self.assertNotIn('must-not-appear', json.dumps(result))

    def test_carrier_head_refresh_is_not_target_staleness(self):
        value = bridge_snapshot(terminal=True)
        first = prepare_bridge(value, now=NOW)
        value['wake']['carrier_pr']['head']['sha'] = 'b' * 40
        self.assertEqual(prepare_bridge(value, now=NOW), first)

    def test_submitted_missing_receipt_unknown_and_never_resend(self):
        for now in (NOW, NOW + timedelta(hours=2)):
            value = bridge_snapshot(submitted=True)
            result = prepare_bridge(value, now=now)
            self.assertNotIn('review_candidate', result)
            self.assertNotIn('next_task', result)
            self.assertIn(result['status'], {'UNKNOWN', 'STOP'})

    def test_nonpass_terminal_noop(self):
        from .bridge_fixtures import replace_record
        for status in ('FAIL', 'UNKNOWN', 'BLOCKED', 'NO_OP', 'STALE'):
            value = bridge_snapshot(terminal=True)
            replace_record(value['wake']['comments'][0], '[CW_BLUE_RECEIPT_V1]', status=status)
            self.assertEqual(prepare_bridge(value, now=NOW)['status'], 'NO_OP')

    def test_restart_after_review_consumption_no_successor_replay(self):
        value = bridge_snapshot(terminal=True)
        first = prepare_bridge(value, now=NOW)
        value['review']['records'] = first['review']['recovered_records']
        restarted = json.loads(json.dumps(value))
        second = prepare_bridge(restarted, now=NOW)
        self.assertEqual(second['status'], 'NO_OP')
        self.assertNotIn('next_task', second)
        self.assertEqual(restarted, value)

    def test_duplicate_event_and_event_order_do_not_change_fixed_candidate(self):
        value = bridge_snapshot()
        opened = prepare_bridge(value, now=NOW)
        value['wake']['event']['action'] = 'synchronize'
        self.assertEqual(prepare_bridge(value, now=NOW), opened)
        value = bridge_snapshot(submitted=True)
        self.assertEqual(prepare_bridge(value, now=NOW)['status'], 'UNKNOWN')
        value['wake']['event']['action'] = 'opened'
        self.assertEqual(prepare_bridge(value, now=NOW)['status'], 'UNKNOWN')

    def test_expired_candidate_is_stop(self):
        self.assertEqual(prepare_bridge(bridge_snapshot(), now=NOW + timedelta(hours=1))['status'], 'STOP')

    def test_untrusted_auth_label_never_unlocks_pipeline(self):
        value = bridge_snapshot(terminal=True)
        value.update(source_mode='CAPTURED', source_authentication='VERIFIED', posting_authority=True)
        result = prepare_bridge(value, now=NOW)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIs(result['posting_authority'], False)
        self.assertNotIn('next_task', result)

    def test_malformed_input_fixed_error_no_leaked_body(self):
        for value in (None, [], {}, {'source_mode': 'MOCK', 'source': 'secret'}):
            self.assertEqual(prepare_bridge(value, now=NOW)['status'], 'UNKNOWN')
