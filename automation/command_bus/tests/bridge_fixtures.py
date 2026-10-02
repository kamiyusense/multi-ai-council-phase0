"""Entirely synthetic source captures, fake submission and receipt; no I/O."""
from copy import deepcopy
import hashlib
import json

from automation.command_bus.cloud_work_lanes import lane_identity
from automation.command_bus.jules_session_evidence import capture_session_evidence
from automation.command_bus.work_closed_loop_prepare import prepare_static_cycle
from .closed_loop_fixtures import snapshot, NOW


def bridge_snapshot(lane='blue', *, submitted=False, terminal=False, virtual_index=0):
    value = snapshot(lane)
    if virtual_index:
        number = 2000 + 2 * virtual_index
        head = hashlib.sha1(('MOCK-only-' + str(virtual_index)).encode()).hexdigest()
        encoded = json.dumps(value).replace('relay-dev-loop-900-', f'relay-dev-loop-{number}-')
        encoded = encoded.replace('/900.json', f'/{number}.json').replace('"loop_number": 900', f'"loop_number": {number}')
        encoded = encoded.replace('"loop_id": "900"', f'"loop_id": "{number}"')
        encoded = encoded.replace('a' * 40, head).replace('pr42-', f'pr{42 + virtual_index}-')
        encoded = encoded.replace('sessions/12345', f'sessions/{100000 + virtual_index}')
        encoded = encoded.replace('/pull/42"', f'/pull/{42 + virtual_index}"')
        encoded = encoded.replace('"number": 42', f'"number": {42 + virtual_index}')
        value = json.loads(encoded)
    source = value['source']
    accepted = dict(source['acceptance'], state='QUEUED')
    value['session_captures'] = {}
    for label, provider, kind in (('accepted', accepted, 'JULES_CREATE_RESPONSE'),
                                  ('completed', source['session_readback'], 'JULES_GET_RESPONSE')):
        value['session_captures'][label] = capture_session_evidence(provider, request=source['request'], claim=source['claim'],
            dispatch_run=source['dispatch_run'], dispatch_job=source['dispatch_job'], source_kind=kind,
            captured_at=source['acceptance']['createTime'] if label == 'accepted' else NOW.isoformat(), now=NOW)
    if submitted or terminal:
        body = prepare_static_cycle(value, now=NOW)['wake']['review_body']
        command = json.loads(body.split('\n', 1)[1])
        value['wake']['reviews'] = [{'id': 101, 'state': 'COMMENTED', 'body': body, 'submitted_at': NOW.isoformat()}]
        if terminal:
            receipt = {k: command[k] for k in ('protocol_version', 'command_id', 'worker_generation', 'target_repository', 'target_pr', 'target_branch')}
            receipt.update(status='PASS', terminal=True, target_head_before=command['expected_target_head'],
                           target_head_after=command['expected_target_head'], verification=['fixture://independent-review'])
            value['wake']['comments'] = [{'id': 102, 'body': lane_identity(lane)['receipt_prefix'] + '\n' + json.dumps(receipt), 'created_at': NOW.isoformat()}]
            value['terminal_binding'] = {'command_id': command['command_id'], 'carrier_pr': value['wake']['carrier_pr']['number'],
                'worker_generation': command['worker_generation'], 'target_pr': command['target_pr'],
                'target_branch': command['target_branch'], 'target_head': command['expected_target_head'],
                'target_tree': source['result_commit']['tree']['sha'], 'trigger_review': 101, 'receipt_comment': 102}
    return value


def replace_record(row, prefix, **changes):
    record = json.loads(row['body'].split('\n', 1)[1])
    record.update(changes)
    row['body'] = prefix + '\n' + json.dumps(record)


def unsafe_cases():
    """Each mutation must prevent any unreserved successor candidate."""
    return {
        'receipt_before_command': lambda x: x['wake'].update(reviews=[]),
        'missing_command': lambda x: x['wake'].update(reviews=[]),
        'missing_receipt': lambda x: x['wake'].update(comments=[]),
        'duplicate_command': lambda x: x['wake']['reviews'].append(deepcopy(x['wake']['reviews'][0])),
        'duplicate_terminal': lambda x: x['wake']['comments'].append(dict(x['wake']['comments'][0], id=103)),
        'stale_generation': lambda x: (x['wake']['worker_state'].update(active_generation=2), x['wake']['protocol'].update(worker_generation=2)),
        'wrong_lane': lambda x: x.update(lane='red' if x['lane'] != 'red' else 'blue'),
        'wrong_carrier': lambda x: x['wake']['worker_state'].update(carrier_pr=999),
        'wrong_branch': lambda x: x['source']['session_readback']['sourceContext']['githubRepoContext'].update(startingBranch='jules-work/other'),
        'wrong_pr': lambda x: x['wake']['result_pr'].update(number=999),
        'wrong_tree': lambda x: x['review']['current_result'].update(tree='b' * 40),
        'stale_event_head': lambda x: x['wake']['event']['pull_request']['head'].update(sha='b' * 40),
        'stale_target_head': lambda x: x['next_snapshot']['target'].update(head='b' * 40),
        'stale_result_head': lambda x: x['source']['result_pr']['head'].update(sha='b' * 40),
        'source_missing': lambda x: x.pop('session_captures'),
        'source_conflict': lambda x: x['session_captures']['completed'].update(session_id='99999'),
        'untrusted_capture': lambda x: x.update(source_mode='CAPTURED', source_authentication='VERIFIED'),
        'partial_pagination': lambda x: x['wake'].update(records_complete=False),
        'partial_files': lambda x: x['review'].update(files_complete=False),
        'partial_ancestry': lambda x: x['source']['comparison'].update(total_commits=2),
        'retry_attempt': lambda x: x.update(attempt=2),
        'output_zero': lambda x: x['source']['session_readback'].update(outputs=[]),
        'output_two': lambda x: x['source']['session_readback']['outputs'].append(deepcopy(x['source']['session_readback']['outputs'][0])),
        'self_review': lambda x: x['review'].update(implementer_id='mock-independent-work'),
        'green_tests_without_review': lambda x: x['review'].update(records=None),
        'unexpected_path': lambda x: x['review']['changed_files'][0].update(filename='docs/unrelated.md'),
        'symlink': lambda x: x['review']['changed_files'][0].update(symlink=True),
        'delete': lambda x: x['review']['changed_files'][0].update(status='removed'),
        'rename': lambda x: x['review']['changed_files'][0].update(status='renamed'),
        'fork': lambda x: x['source']['result_pr']['head']['repo'].update(full_name='other/repo'),
        'reservation_collision': lambda x: x.update(reservation_preflight=dict(deepcopy(x['next_snapshot']), tree_entries=x['next_snapshot']['tree_entries'] + [{'path': 'automation/command_bus/loop_id_claims/901.json', 'type': 'blob'}])),
        'malformed_body': lambda x: x['wake']['comments'][0].update(body=lane_identity(x['lane'])['receipt_prefix'] + '\n{"secret":"must-not-appear",'),
        'late_terminal': lambda x: x['wake']['comments'][0].update(created_at=x['wake']['expires_at']),
        'wrong_receipt_tree': lambda x: x['terminal_binding'].update(target_tree='b' * 40),
        'wrong_trigger_review': lambda x: x['terminal_binding'].update(trigger_review=999),
        'wrong_terminal_pr': lambda x: replace_record(x['wake']['comments'][0], lane_identity(x['lane'])['receipt_prefix'], target_pr=999),
        'wrong_terminal_generation': lambda x: replace_record(x['wake']['comments'][0], lane_identity(x['lane'])['receipt_prefix'], worker_generation=2),
        'wrong_terminal_head': lambda x: replace_record(x['wake']['comments'][0], lane_identity(x['lane'])['receipt_prefix'], target_head_after='b' * 40),
        'different_terminal_color': lambda x: x['wake']['comments'][0].update(body=x['wake']['comments'][0]['body'].replace(lane_identity(x['lane'])['receipt_prefix'], lane_identity('red' if x['lane'] != 'red' else 'blue')['receipt_prefix'], 1)),
        'circular_review_evidence': lambda x: x['review']['records']['responses'][0].update(evidence_refs=['review-response:mock-review-response']),
    }
