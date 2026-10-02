import unittest

from automation.command_bus.jules_result_lineage import verify_result_lineage
from automation.command_bus.work_closed_loop_prepare import prepare_static_cycle
from .closed_loop_fixtures import snapshot, NOW


class SourceBoundaryRegressions(unittest.TestCase):
    def test_captured_json_cannot_prepare_successor_without_authentication(self):
        value = snapshot()
        value['source_mode'] = 'CAPTURED'
        value['source_authentication'] = 'VERIFIED'
        result = prepare_static_cycle(value, now=NOW)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertNotIn('next_task', result)
        self.assertNotIn('wake', result)

    def test_lineage_rejects_one_nanosecond_create_time_difference(self):
        value = snapshot()['source']
        value['acceptance']['createTime'] = '2026-10-01T10:01:00.123456781Z'
        value['session_readback']['createTime'] = '2026-10-01T10:01:00.123456782Z'
        result = verify_result_lineage(lane='blue', **value, now=NOW)
        self.assertEqual(result.status, 'UNKNOWN')

    def test_non_pr_extra_output_does_not_establish_unique_session_result(self):
        value = snapshot()['source']
        value['session_readback']['outputs'].append({})
        self.assertEqual(verify_result_lineage(lane='blue', **value, now=NOW).status, 'UNKNOWN')

    def test_malformed_command_changed_file_is_unknown_not_exception(self):
        value = snapshot()['source']
        value['command_commit']['files'] = [None]
        self.assertEqual(verify_result_lineage(lane='blue', **value, now=NOW).status, 'UNKNOWN')

    def test_review_cannot_cite_its_own_response_as_success_evidence(self):
        value = snapshot()
        response = value['review']['records']['responses'][0]
        reference = 'review-response:' + response['response_id']
        response['evidence_refs'] = [reference]
        for check in value['review']['checks']:
            check['evidence_ref'] = reference
        result = prepare_static_cycle(value, now=NOW)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertNotIn('next_task', result)
