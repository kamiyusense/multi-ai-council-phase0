"""Synthetic BWJ-4 delivery proof plus the existing BWJ-5/6 bridge."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from automation.command_bus.blue_jules_result_event import classify_jules_result_event, EventDecision
from automation.command_bus.blue_review_delivery_prepare import prepare_review_submission, assess_review_wake
from automation.command_bus.work_bridge_prepare import prepare_bridge
from automation.command_bus.jules_result_lineage import verify_result_lineage
from .bridge_fixtures import bridge_snapshot, replace_record, unsafe_cases
from .closed_loop_fixtures import NOW

AUTHOR = {'id': 999999, 'login': 'MOCK-only-principal', 'type': 'Bot'}


def submitted_snapshot():
    value = bridge_snapshot(submitted=True)
    row = value['wake']['reviews'][0]
    row.update(user=deepcopy(AUTHOR), commit_id=value['wake']['carrier_pr']['head']['sha'])
    event = {'event_name': 'pull_request_review', 'action': 'submitted',
        'repository': {'full_name': 'kamiyusense/multi-ai-council-phase0'},
        'pull_request': {'number': value['wake']['carrier_pr']['number']}, 'review': deepcopy(row)}
    return value, event


def inspect(value, event, *, final=None, author=AUTHOR, generation=1, now=NOW):
    return assess_review_wake(event, value, value if final is None else final,
                             expected_author=author, fixed_generation=generation, now=now)


def run_delivery_replay():
    """Finite existing-fixture replay; production authentication is not asserted."""
    with patch('urllib.request.urlopen', side_effect=AssertionError('network prohibited')) as network, \
            patch('subprocess.Popen', side_effect=AssertionError('execution prohibited')) as execution:
        pending = bridge_snapshot()
        post = prepare_review_submission(pending, deepcopy(pending), now=NOW)
        assert post['status'] == 'PREPARED', post
        assert post['request']['body']['event'] == 'COMMENT'
        submitted, event = submitted_snapshot()
        wake = inspect(submitted, event)
        assert wake['worker_preflight'] == 'VALIDATED' and wake['status'] == 'UNKNOWN', wake
        # No receipt is a stop for the controller, not a reason to post again.
        missing = prepare_review_submission(submitted, submitted, now=NOW)
        assert missing['status'] == 'UNKNOWN' and not missing.get('request')
        lineage = verify_result_lineage(lane='blue', **submitted['source'], now=NOW)
        duplicate = classify_jules_result_event(submitted['wake']['event'], lineage.lineage,
                                                [post['command_id']], lane='blue')
        assert duplicate.decision == EventDecision.IGNORE
        terminal = bridge_snapshot(terminal=True)
        next_task = prepare_bridge(terminal, now=NOW)
        assert next_task['status'] == 'PREPARED_NEXT'
        assert next_task['next_task']['claim']['schema_version'] == 3
        assert next_task['next_task']['reservation_state'] == 'NOT_RESERVED'
        terminal['review']['records'] = next_task['review']['recovered_records']
        assert prepare_bridge(json.loads(json.dumps(terminal)), now=NOW)['status'] == 'NO_OP'
        assert network.call_count == execution.call_count == 0
    return {'status': 'PASS', 'source_mode': 'MOCK', 'source_authentication': 'MOCK_ONLY',
        'production_source_authentication': 'NOT_WIRED', 'execution_mode': 'PREPARE_ONLY',
        'review_candidate': post, 'wake_inspection': wake,
        'terminal_review': next_task['review']['decision'],
        'next_claim_schema': next_task['next_task']['claim']['schema_version'],
        'reservation_state': 'NOT_RESERVED', 'duplicate_result': 'NO_OP', 'restart': 'NO_OP',
        'provider_execution': 0, 'model_execution': 0, 'github_review_post': 0,
        'work_wake_execution': 0, 'claim_reservation': 0, 'jules_dispatch': 0,
        'external_execution': 0, 'permission_change': 0, 'adoption': 0,
        'network_calls': 0, 'process_calls': 0, 'retry': 0, 'fallback': 'disabled'}


class DeliveryTests(unittest.TestCase):
    def assert_closed(self, result):
        for key in ('posting_authority', 'external_send_attempted', 'model_executed',
                    'claim_reserved', 'adoption_performed', 'resend_allowed'):
            self.assertIs(result[key], False, result)

    def test_exact_request_is_only_a_descriptor(self):
        value = bridge_snapshot()
        before = deepcopy(value)
        result = prepare_review_submission(value, deepcopy(value), now=NOW)
        self.assertEqual(result['status'], 'PREPARED', result)
        self.assertEqual(result['request']['endpoint'], '/repos/kamiyusense/multi-ai-council-phase0/pulls/167/reviews')
        self.assertEqual(result['request']['body']['commit_id'], value['wake']['carrier_pr']['head']['sha'])
        self.assertEqual(result['target_tree'], value['review']['current_result']['tree'])
        self.assertFalse(result['permission_enabled'])
        self.assertEqual(value, before)
        self.assert_closed(result)

    def test_unknown_submission_stops_without_candidate(self):
        for state in ('UNKNOWN', 'SUBMITTED', 'FAILED', None):
            result = prepare_review_submission(bridge_snapshot(), bridge_snapshot(), now=NOW, submission_state=state)
            self.assertEqual(result['status'], 'UNKNOWN')
            self.assertNotIn('request', result)
            self.assert_closed(result)

    def test_submitted_missing_receipt_is_unknown_no_resend(self):
        value, event = submitted_snapshot()
        result = inspect(value, event)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(result['worker_preflight'], 'VALIDATED')
        self.assert_closed(result)
        self.assertEqual(prepare_review_submission(value, value, now=NOW)['status'], 'UNKNOWN')

    def test_captured_json_and_auth_label_cannot_unlock(self):
        for auth in ('VERIFIED', 'AUTHENTICATED', 'AUTHENTICATED_CANDIDATE', 'MOCK_ONLY'):
            value, event = submitted_snapshot()
            value.update(source_mode='CAPTURED', source_authentication=auth, posting_authority=True)
            self.assertEqual(inspect(value, event)['status'], 'BLOCKED')
            result = prepare_review_submission(value, value, now=NOW)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertNotIn('request', result)

    def test_final_carrier_movement_stops_separately_from_target(self):
        value = bridge_snapshot()
        final = deepcopy(value)
        final['wake']['carrier_pr']['head']['sha'] = 'b' * 40
        result = prepare_review_submission(value, final, now=NOW)
        self.assertEqual(result['status'], 'STOP', result)
        self.assertIn('carrier', result['reason'])
        self.assertNotIn('request', result)

    def test_already_stale_canonical_target_and_unsafe_modes_refuse_candidate(self):
        for field in ('head', 'tree', 'branch', 'repository', 'expected_head', 'expected_tree'):
            value = bridge_snapshot()
            value['next_snapshot']['target'][field] = 'b' * 40 if 'head' in field or 'tree' in field else 'other'
            result = prepare_review_submission(value, value, now=NOW)
            self.assertEqual(result['status'], 'STOP', result)
            self.assertNotIn('request', result)
        for mode in ('120000', '160000', '100600', None):
            value = bridge_snapshot()
            value['review']['changed_files'][0]['mode'] = mode
            self.assertEqual(prepare_review_submission(value, value, now=NOW)['status'], 'STOP')

    def test_new_same_pr_head_has_new_candidate_identity(self):
        first = prepare_review_submission(bridge_snapshot(), bridge_snapshot(), now=NOW)
        other = json.loads(json.dumps(bridge_snapshot()).replace('a' * 40, 'b' * 40))
        second = prepare_review_submission(other, other, now=NOW)
        self.assertEqual(second['status'], 'PREPARED', second)
        self.assertNotEqual(first['command_id'], second['command_id'])

    def test_all_existing_faults_refuse_posting_candidate(self):
        for name, mutate in unsafe_cases().items():
            with self.subTest(fault=name):
                value = bridge_snapshot(terminal=True)
                mutate(value)
                result = prepare_review_submission(value, value, now=NOW)
                self.assertNotIn('request', result)
                self.assert_closed(result)

    def test_only_review_submission_is_a_trigger(self):
        for name, action in (('issue_comment', 'created'), ('pull_request_review_comment', 'created'),
                             ('pull_request_review', 'edited'), ('pull_request_review', 'dismissed')):
            value, event = submitted_snapshot()
            event.update(event_name=name, action=action)
            self.assertEqual(inspect(value, event)['status'], 'NO_OP')

    def test_wrong_lane_repository_carrier_are_noop(self):
        for field in ('lane', 'repository', 'carrier'):
            value, event = submitted_snapshot()
            if field == 'lane':event['review']['body'] = event['review']['body'].replace('[CW_BLUE_V1]', '[CW_RED_V1]')
            elif field == 'repository':event['repository']['full_name'] = 'other/repo'
            else:event['pull_request']['number'] = 999
            self.assertEqual(inspect(value, event)['status'], 'NO_OP')

    def test_author_identity_must_be_explicit_and_exact(self):
        for field, changed in (('id', 1), ('login', 'github-actions[bot]'), ('type', 'User')):
            value, event = submitted_snapshot()
            event['review']['user'][field] = changed
            self.assertEqual(inspect(value, event)['status'], 'BLOCKED')
        value, event = submitted_snapshot()
        self.assertEqual(inspect(value, event, author=None)['status'], 'UNKNOWN')
        result = inspect(value, event)
        self.assertEqual(result['origin_run_authentication'], 'NOT_WIRED')

    def test_exact_fresh_review_readback_required(self):
        for field, changed in (('body', '[CW_BLUE_V1]\n{}'), ('commit_id', 'b' * 40),
                               ('submitted_at', (NOW - timedelta(seconds=1)).isoformat()), ('id', 103)):
            value, event = submitted_snapshot()
            value['wake']['reviews'][0][field] = changed
            self.assertEqual(inspect(value, event)['status'], 'UNKNOWN')

    def test_pending_approval_review_and_future_event_refused(self):
        for state in ('PENDING', 'APPROVED', 'CHANGES_REQUESTED'):
            value, event = submitted_snapshot()
            event['review']['state'] = state
            self.assertEqual(inspect(value, event)['status'], 'UNKNOWN')
        value, event = submitted_snapshot()
        event['review']['submitted_at'] = (NOW + timedelta(seconds=1)).isoformat()
        self.assertEqual(inspect(value, event)['status'], 'STOP')

    def test_stale_worker_silently_noops_and_new_generation_stops(self):
        value, event = submitted_snapshot()
        self.assertEqual(inspect(value, event, generation=2)['status'], 'NO_OP')
        final = deepcopy(value)
        final['wake']['worker_state']['active_generation'] = 2
        final['wake']['protocol']['worker_generation'] = 2
        self.assertNotIn('worker_preflight', inspect(value, event, final=final))

    def test_expired_command_stops(self):
        value, event = submitted_snapshot()
        self.assertEqual(inspect(value, event, now=NOW + timedelta(hours=2))['status'], 'STOP')

    def test_result_head_branch_tree_and_canonical_target_drift_stop(self):
        for field in ('head', 'tree', 'branch', 'canonical'):
            value, event = submitted_snapshot()
            final = deepcopy(value)
            if field == 'head':final['wake']['result_pr']['head']['sha'] = 'b' * 40
            elif field == 'tree':final['review']['current_result']['tree'] = 'b' * 40
            elif field == 'branch':final['wake']['result_pr']['head']['ref'] = 'other/result'
            else:final['next_snapshot']['target']['head'] = 'b' * 40
            result = inspect(value, event, final=final)
            self.assertNotIn('worker_preflight', result)
            self.assert_closed(result)

    def test_duplicate_submitted_and_cross_lane_collision_cannot_consume(self):
        value, event = submitted_snapshot()
        value['wake']['reviews'].append(deepcopy(value['wake']['reviews'][0]))
        self.assertNotIn('worker_preflight', inspect(value, event))
        value, event = submitted_snapshot()
        foreign = dict(value['wake']['reviews'][0], id=105,
                       body=value['wake']['reviews'][0]['body'].replace('[CW_BLUE_V1]', '[CW_RED_V1]'))
        value['wake']['reviews'].append(foreign)
        self.assertNotIn('worker_preflight', inspect(value, event))

    def test_terminal_replay_and_duplicate_terminal_refused(self):
        terminal = bridge_snapshot(terminal=True)
        row = terminal['wake']['reviews'][0]
        row.update(user=deepcopy(AUTHOR), commit_id=terminal['wake']['carrier_pr']['head']['sha'])
        event = submitted_snapshot()[1]
        event['review'] = deepcopy(row)
        self.assertEqual(inspect(terminal, event)['status'], 'NO_OP')
        terminal['wake']['comments'].append(dict(terminal['wake']['comments'][0], id=103))
        self.assertNotIn('worker_preflight', inspect(terminal, event))

    def test_late_terminal_cannot_be_promoted(self):
        terminal = bridge_snapshot(terminal=True)
        terminal['wake']['comments'][0]['created_at'] = (NOW + timedelta(hours=1)).isoformat()
        result = prepare_bridge(terminal, now=NOW + timedelta(hours=2))
        self.assertNotEqual(result['status'], 'PREPARED_NEXT')
        self.assertNotIn('next_task', result)

    def test_mock_e2e_and_restart_cannot_execute_anything(self):
        result = run_delivery_replay()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['reservation_state'], 'NOT_RESERVED')
        for key in ('provider_execution', 'model_execution', 'github_review_post', 'work_wake_execution',
                    'claim_reservation', 'jules_dispatch', 'external_execution', 'permission_change', 'adoption'):
            self.assertEqual(result[key], 0)

    def test_activation_package_is_disabled_with_fresh_slots_and_separate_budget(self):
        root = Path(__file__).resolve().parents[3]
        plan = json.loads((root / 'docs/BLUE_BWJ4_ONE_SHOT_ACTIVATION.json').read_text())
        self.assertIs(plan['enabled'], False)
        self.assertEqual(plan['activation_state'], 'NOT_APPROVED')
        self.assertEqual(set(plan['slots_at_activation'].values()), {None})
        budget = plan['proposed_live_budget_maximum']
        for key in ('provider_session_create', 'provider_completion_get', 'target_mutation',
                    'next_claim_reservation', 'work_branch_publication', 'jules_command_publication',
                    'jules_submit', 'adoption', 'merge'):
            self.assertEqual(budget[key], 0)
        for key in ('proof_activations', 'posting_workflow_run', 'carrier_comment_review_post',
                    'blue_work_logical_wake', 'work_terminal_receipt_comment'):
            self.assertEqual(budget[key], 1)
        self.assertEqual(plan['retry'], 0)
        self.assertEqual(plan['fallback'], 'disabled')
        self.assertFalse(plan['event_filter']['exactly_once_physical_delivery_guaranteed'])
        # The historical disabled proposal remains evidence. A separate,
        # explicitly approved dispatch-only proof now supplies its transport.
        proof = (root / plan['proposed_future_workflow']['path']).read_text()
        self.assertIn('workflow_dispatch:', proof)
        self.assertNotIn('pull_request_review:', proof)
        self.assertIn('permissions: {}', proof)

    def test_default_static_workflow_keeps_read_permissions_and_only_mock_delivery(self):
        root = Path(__file__).resolve().parents[3]
        workflow = (root / '.github/workflows/blue-work-reconcile-static.yml').read_text()
        permissions = workflow.split('permissions:\n', 1)[1].split('\nconcurrency:', 1)[0]
        self.assertEqual(permissions.strip(), 'contents: read\n  pull-requests: read\n  actions: read')
        self.assertNotIn('pull_request_review:', workflow)
        self.assertNotIn('createReview', workflow)
        self.assertIn('python -m automation.command_bus.tests.test_blue_review_delivery_prepare', workflow)


    def test_exact_blue_prefix_must_start_at_byte_zero(self):
        value, event = submitted_snapshot()
        accepted = inspect(value, event)
        self.assertEqual(accepted.get('worker_preflight'), 'VALIDATED')
        self.assert_closed(accepted)

        exact = event['review']['body']
        malformed = (
            ' ' + exact,
            '[CW_BLUE_VI]' + exact[len('[CW_BLUE_V1]'):],
            'context ' + exact,
            'context\\n' + exact,
            exact.replace('[CW_BLUE_V1]', '[CW_RED_V1]', 1),
        )
        for body in malformed:
            with self.subTest(body=body[:32]):
                value, event = submitted_snapshot()
                event['review']['body'] = body
                result = inspect(value, event)
                self.assertNotEqual(result.get('worker_preflight'), 'VALIDATED')
                self.assert_closed(result)

    def test_review_wake_requires_current_cloud_blue_carrier_label(self):
        for labels in ([], [{'name': 'cloud-red'}]):
            with self.subTest(labels=labels):
                value, event = submitted_snapshot()
                value['wake']['carrier_pr']['labels'] = labels
                final = deepcopy(value)
                result = inspect(value, event, final=final)
                self.assertNotEqual(result.get('worker_preflight'), 'VALIDATED')
                self.assert_closed(result)


if __name__ == '__main__':
    print(json.dumps(run_delivery_replay(), indent=2, sort_keys=True))
