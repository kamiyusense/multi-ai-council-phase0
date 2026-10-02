"""BWJ-4 review delivery descriptors and MOCK wake inspection; no transport.

GitHub actor metadata is not proof of a particular Actions run. CAPTURED input
remains BLOCKED; this module cannot authenticate provider origin or send a POST.
The existing bridge/reviewer/receipt contracts remain the only static gates.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from .blue_jules_result_event import EXPECTED_REPOSITORY
from .blue_work_reconcile_prepare import (
    _body, _command, _positive, _sha, _time, assess_cloud_review,
)
from .work_bridge_prepare import prepare_bridge


def _result(status, reason, **details):
    return dict(status=status, reason=reason, execution_mode='PREPARE_ONLY',
                posting_authority=False, external_send_attempted=False,
                model_executed=False, claim_reserved=False, adoption_performed=False,
                retry=0, fallback='disabled', resend_allowed=False, **details)


def _fence(snapshot):
    """Carrier movement and result/canonical-target movement are separate fences."""
    wake = snapshot['wake']
    carrier = wake['carrier_pr']
    return {
        'carrier': {k: carrier[k] for k in ('number', 'state', 'merged', 'head', 'labels')},
        'worker_state': wake['worker_state'], 'protocol': wake['protocol'],
        'source': snapshot['source'], 'captures': snapshot['session_captures'],
        'result': wake['result_pr'], 'review_target': snapshot['review']['current_result'],
        'canonical_target': snapshot['next_snapshot']['target'],
    }


def _fresh_pair(snapshot, final_snapshot, now):
    for value in (snapshot, final_snapshot):
        if isinstance(value, dict) and value.get('source_mode') == 'MOCK':
            request = value['source']['request']
            target = value['next_snapshot']['target']
            required = {'repository': EXPECTED_REPOSITORY, 'branch': request['target_branch'],
                        'head': request['expected_target_head'], 'tree': request['expected_target_tree'],
                        'expected_head': request['expected_target_head'], 'expected_tree': request['expected_target_tree']}
            if any(target.get(k) != v for k, v in required.items()):
                return None, _result('STOP', 'canonical target HEAD/tree/branch stale against formal command')
            if any('mode' in row and row['mode'] not in {'100644', '100755'}
                   for row in value['review']['changed_files']):
                return None, _result('STOP', 'unsafe changed-file mode')
    first = prepare_bridge(snapshot, now=now)
    if first['status'] != 'PREPARED_REVIEW':
        return None, _result('NO_OP' if first['status'] == 'PREPARED_NEXT' else first['status'],
                             'existing bridge refused a new review; never resend')
    final = prepare_bridge(final_snapshot, now=now)
    if final['status'] != 'PREPARED_REVIEW':
        return None, _result('NO_OP' if final['status'] == 'PREPARED_NEXT' else final['status'],
                             'final durable bridge readback refused a new review; never resend')
    before, after = _fence(snapshot), _fence(final_snapshot)
    if before != after or first['review_candidate'] != final['review_candidate']:
        reason = ('carrier changed during preparation' if before['carrier'] != after['carrier']
                  else 'source/target/generation changed during preparation')
        return None, _result('STOP', reason)
    return final, None


def prepare_review_submission(snapshot, final_snapshot, *, now: datetime,
                              submission_state='NOT_ATTEMPTED'):
    """Describe one COMMENT request, with no send function or authority.

    NOT_ATTEMPTED is a MOCK input, not a durable production attempt ledger.
    Ambiguous submission stops even if GitHub has not yet returned a review.
    """
    try:
        if submission_state != 'NOT_ATTEMPTED':
            return _result('UNKNOWN', 'submission attempted/unknown; read back, never resend')
        bridge, refused = _fresh_pair(snapshot, final_snapshot, now)
        if refused:
            return refused
        plan = bridge['review_candidate']
        if plan['lane'] != 'blue':
            return _result('NO_OP', 'Blue-only delivery boundary')
        command = _body(plan['review_body'], '[CW_BLUE_V1]')
        _command(command, 'blue')
        carrier = final_snapshot['wake']['carrier_pr']
        head = carrier['head']['sha']
        tree = final_snapshot['review']['current_result']['tree']
        if not _sha(head) or not _sha(tree):
            raise ValueError('exact HEAD/tree missing')
        endpoint = f'/repos/{EXPECTED_REPOSITORY}/pulls/{carrier["number"]}/reviews'
        return _result('PREPARED', 'MOCK descriptor only; production source and posting NOT_WIRED',
            source_authentication='MOCK_ONLY', live_transport='NOT_WIRED',
            command_id=command['command_id'], worker_generation=command['worker_generation'],
            carrier_pr=carrier['number'], carrier_head=head, carrier_state=carrier['state'],
            target={k: command[k] for k in ('target_repository', 'target_pr', 'target_branch', 'expected_target_head')},
            target_tree=tree, request={'method': 'POST', 'endpoint': endpoint,
                'body': {'event': 'COMMENT', 'commit_id': head, 'body': plan['review_body']}},
            required_permission_candidate={'pull-requests': 'write'}, permission_enabled=False,
            readback={'list_reviews': endpoint, 'get_review': endpoint + '/{fresh_review_id}',
                'match': ['id', 'state=COMMENTED', 'body byte equality', 'commit_id=carrier_head',
                          'user.id/login/type from approved principal slot', 'submitted_at'],
                'origin_run_authentication': 'NOT_WIRED'},
            blockers=['production Session source authentication', 'human posting authorization',
                      'job-scoped permission approval', 'durable attempt record before a POST'])
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return _result('UNKNOWN', 'missing/conflicting delivery snapshot')


def assess_review_wake(event, snapshot, final_snapshot, *, expected_author,
                       fixed_generation, now: datetime):
    """Treat a webhook as a hint, then inspect fresh durable MOCK records.

    expected_author must come from an independently approved activation slot.
    Even matching bot identity cannot prove token type or posting run/job.
    Missing terminal receipt remains UNKNOWN and confers no successor authority.
    """
    try:
        if snapshot.get('source_mode') != 'MOCK' or final_snapshot.get('source_mode') != 'MOCK':
            return _result('BLOCKED', 'production source authentication NOT_WIRED')
        if event.get('event_name') != 'pull_request_review' or event.get('action') != 'submitted':
            return _result('NO_OP', 'only submitted pull_request_review wakes this contract')
        wake = final_snapshot['wake']
        if (event['repository']['full_name'] != EXPECTED_REPOSITORY
                or event['pull_request']['number'] != wake['carrier_pr']['number']):
            return _result('NO_OP', 'wrong repository/carrier')
        row = event['review']
        command = _body(row['body'], '[CW_BLUE_V1]')
        if command is None:
            return _result('NO_OP', 'wrong lane/prefix')
        _command(command, 'blue')
        if command['allowed_paths'] or not command['command_id'].startswith('blue-jules-result-'):
            return _result('BLOCKED', 'BWJ-4 requires the existing read-only result-review task')
        if (not isinstance(expected_author, dict) or set(expected_author) != {'id', 'login', 'type'}
                or not _positive(expected_author['id']) or not expected_author['login']
                or expected_author['type'] not in {'Bot', 'User'}):
            return _result('UNKNOWN', 'approved principal identity unavailable')
        observed_author = {k: row['user'][k] for k in expected_author}
        if observed_author != expected_author:
            return _result('BLOCKED', 'review author differs from approved principal')
        if not _positive(row['id']) or row['state'] != 'COMMENTED':
            return _result('UNKNOWN', 'review is not a submitted COMMENT')
        if row['commit_id'] != wake['carrier_pr']['head']['sha']:
            return _result('STOP', 'review carrier HEAD moved; target staleness is a separate gate')
        submitted = _time(row['submitted_at'])
        if submitted > now or submitted >= _time(command['expires_at']):
            return _result('STOP', 'future/expired submission')
        durable = [r for r in wake['reviews'] if r.get('id') == row['id']]
        fields = ('id', 'body', 'state', 'commit_id', 'submitted_at', 'user')
        if len(durable) != 1 or any(durable[0].get(k) != row[k] for k in fields):
            return _result('UNKNOWN', 'exact triggering review fresh readback missing/conflicting')
        # Re-use source/carrier/target gates without treating the triggering
        # review's mere presence as posting permission or as a receipt.
        unsubmitted = []
        for value in (snapshot, final_snapshot):
            copied = deepcopy(value)
            copied['wake'].update(reviews=[], comments=[])
            unsubmitted.append(copied)
        bridge, refused = _fresh_pair(*unsubmitted, now)
        if refused:
            return refused
        if bridge['review_candidate']['review_body'] != row['body']:
            return _result('STOP', 'event command differs from freshly reconciled result')
        # Existing bridge checks cross-lane collisions and exact terminal/tree binding.
        recovered = prepare_bridge(final_snapshot, now=now)
        gate = assess_cloud_review(body=row['body'],
            active_generation=wake['worker_state']['active_generation'], fixed_generation=fixed_generation,
            current_target={**bridge_target(command), 'expected_target_head': wake['result_pr']['head']['sha']},
            reviews=wake['reviews'], comments=wake['comments'], records_complete=wake['records_complete'],
            now=now, lane='blue')
        if gate.status != 'VALIDATED':
            return _result('STOP' if gate.status == 'STALE' else gate.status, gate.reason)
        # UNKNOWN is expected while the selected worker has no terminal receipt.
        if recovered['status'] != 'UNKNOWN' or recovered.get('recovery', {}).get('status') != 'UNKNOWN':
            return _result('STOP', 'durable recovery conflict; no wake consumption')
        return _result('UNKNOWN', 'MOCK wake preflight valid; terminal receipt missing, never resend',
            source_authentication='MOCK_ONLY', worker_preflight='VALIDATED',
            wake_identity={'lane': 'blue', 'carrier_pr': wake['carrier_pr']['number'],
                'command_id': command['command_id'], 'worker_generation': command['worker_generation'],
                'trigger_review': row['id'], 'target_head': command['expected_target_head'],
                'target_tree': final_snapshot['review']['current_result']['tree']},
            origin_run_authentication='NOT_WIRED')
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return _result('UNKNOWN', 'missing/conflicting wake snapshot')


def bridge_target(command):
    return {k: command[k] for k in ('target_repository', 'target_pr', 'target_branch')}
