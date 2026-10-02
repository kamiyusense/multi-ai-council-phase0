"""Finite four-lane result bridge/recovery replay. No transport or authority.

MOCK exercises the future authenticated boundary. CAPTURED JSON always stops
before a posting candidate. GitHub is the restart source, not process memory.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from .blue_work_reconcile_prepare import (_body, _command, _positive, _records, _time,
    prepare_reconciled_wake, prepare_result_review_request)
from .blue_work_wake_prepare import CarrierSnapshot
from .cloud_work_lanes import LANES, lane_identity
from .jules_result_lineage import verify_result_lineage
from .jules_session_evidence import validate_capture_pair, evidence_fingerprint
from .next_jules_prepare import prepare_next_jules, recheck_next_jules
from .work_result_review import assess_result_review


def recover_result_command(*, wake: dict, plan, target_tree: str, now: datetime,
                           terminal_binding: Any = None) -> dict:
    """Reconcile submitted commands/receipts; never decides to resend.

    A missing receipt after a submitted review is UNKNOWN, including expiry.
    An expired record cannot yield successor preparation. Tree/trigger/time
    evidence supplements, and does not change, the existing carrier protocol.
    """
    lane = plan.lane
    metadata = lane_identity(lane)
    expected = _body(plan.review_body, metadata['command_prefix'])
    _command(expected, lane)
    reviews, comments = wake['reviews'], wake['comments']
    if wake['records_complete'] is not True:
        raise ValueError('complete durable carrier records required')
    for row in reviews + comments:
        for other in LANES:
            if other == lane:
                continue
            for prefix in (lane_identity(other)['command_prefix'], lane_identity(other)['receipt_prefix']):
                foreign = _body(row['body'], prefix)
                if foreign is not None and foreign.get('command_id') == expected['command_id']:
                    raise ValueError('foreign lane record conflicts with command identity')
    matching = [r for r in reviews if (c := _body(r['body'], metadata['command_prefix'])) is not None
                and c.get('command_id') == expected['command_id']]
    # Stale workers never acquire authority from an earlier review.
    if len(matching) == 1:
        command = _body(matching[0]['body'], metadata['command_prefix'])
        _command(command, lane)
        if command['worker_generation'] != wake['worker_state']['active_generation']:
            return {'status': 'STOP', 'reason': 'stale worker generation', 'resend_allowed': False}
    seen, terminals = _records(reviews, comments, True, focus_command=expected, lane=lane)
    if expected['command_id'] not in seen:
        if now >= _time(expected['expires_at']):
            return {'status': 'STOP', 'reason': 'expired candidate', 'resend_allowed': False}
        return {'status': 'NOT_SUBMITTED', 'resend_allowed': False}
    if len(matching) != 1:
        raise ValueError('submitted command identity ambiguous')
    review = matching[0]
    command = _body(review['body'], metadata['command_prefix'])
    if command != expected:
        raise ValueError('full submitted command differs from fixed candidate')
    if command['command_id'] not in terminals:
        return {'status': 'UNKNOWN', 'reason': 'submitted command without terminal receipt; never resend', 'resend_allowed': False}
    receipt_rows = [r for r in comments if (c := _body(r['body'], metadata['receipt_prefix'])) is not None
                    and c.get('command_id') == command['command_id']]
    receipt_row = receipt_rows[0]  # _records required exactly one terminal.
    receipt = _body(receipt_row['body'], metadata['receipt_prefix'])
    if (not _positive(review.get('id')) or not _positive(receipt_row.get('id'))
            or not isinstance(terminal_binding, dict)):
        raise ValueError('terminal trigger/tree evidence unavailable')
    binding = {'command_id': command['command_id'], 'carrier_pr': wake['carrier_pr']['number'],
               'worker_generation': command['worker_generation'], 'target_pr': command['target_pr'],
               'target_branch': command['target_branch'], 'target_head': command['expected_target_head'],
               'target_tree': target_tree, 'trigger_review': review['id'], 'receipt_comment': receipt_row['id']}
    if terminal_binding != binding:
        raise ValueError('terminal trigger/tree binding conflict')
    submitted, completed = _time(review['submitted_at']), _time(receipt_row['created_at'])
    if not submitted <= completed <= now or submitted >= _time(command['expires_at']):
        raise ValueError('terminal chronology unavailable/inconsistent')
    if completed >= _time(command['expires_at']):
        return {'status': 'STOP', 'reason': 'late terminal receipt; no automatic PASS promotion',
                'terminal_status': receipt['status'], 'resend_allowed': False}
    return {'status': 'TERMINAL', 'terminal_status': receipt['status'],
            'trigger_review': review['id'], 'receipt_comment': receipt_row['id'], 'resend_allowed': False}


def prepare_bridge(snapshot: Any, *, now: datetime) -> dict:
    result = {'execution_mode': 'PREPARE_ONLY', 'external_send_attempted': False,
              'model_executed': False, 'adoption_performed': False, 'claim_reserved': False,
              'posting_authority': False, 'source_authentication': 'NOT_WIRED',
              'retry': 0, 'fallback': 'disabled'}
    try:
        if not isinstance(snapshot, dict) or snapshot.get('source_mode') not in {'MOCK', 'CAPTURED'}:
            raise ValueError('explicit source mode required')
        result['source_mode'] = snapshot['source_mode']
        if snapshot['source_mode'] != 'MOCK':
            result.update(status='BLOCKED', reason='production source authentication NOT_WIRED; captured JSON confers no posting authority')
            return result
        if type(snapshot.get('attempt', 1)) is not int or snapshot.get('attempt', 1) != 1:
            return dict(result, status='STOP', reason='retry/replay attempt refused')
        source = snapshot['source']
        lane = next(l for l in LANES if lane_identity(l)['jules_lane'] == source['claim']['lane_id'])
        if lane != snapshot['lane']:
            raise ValueError('source claim and selected lane disagree')
        validate_capture_pair(snapshot['session_captures']['accepted'], snapshot['session_captures']['completed'], source=source, now=now)
        result['source_authentication'] = 'MOCK_ONLY'
        result['capture_fingerprint'] = evidence_fingerprint(snapshot['session_captures']['completed'])
        lineage = verify_result_lineage(lane=lane, **source, now=now)
        if lineage.status != 'VERIFIED_SNAPSHOT':
            return dict(result, status='UNKNOWN', reason='formal source/result lineage unavailable')
        wake = dict(snapshot['wake'])
        if wake['result_pr'] != source['result_pr']:
            raise ValueError('wake and source result readbacks differ')
        wake['lineage'] = lineage.lineage
        wake['protocol'] = CarrierSnapshot(**wake['protocol'])
        if now >= _time(wake['expires_at']):
            return dict(result, status='STOP', reason='expired command; preserve durable records and never resend')
        # Derive the fixed identity without treating any submitted command as
        # permission to send. Recovery below reads the real durable record lists.
        plan = prepare_reconciled_wake(**dict(wake, reviews=[], comments=[]), lane=lane, now=now)
        if plan.status != 'PREPARED':
            return dict(result, status='STOP' if plan.status == 'STALE' else plan.status, reason='event/carrier/target preflight refused')
        review_input = snapshot['review']
        current = review_input['current_result']
        if current != {'head': lineage.result_head, 'tree': lineage.result_tree}:
            return dict(result, status='STOP', reason='result HEAD/tree moved')
        if review_input['files_complete'] is not True or not review_input['changed_files']:
            raise ValueError('complete nonempty result file list required')
        seen_paths = set()
        for row in review_input['changed_files']:
            if (row.get('filename') not in lineage.allowed_paths or row['filename'] in seen_paths
                    or row.get('status') not in {'added', 'modified'} or row.get('symlink') is not False):
                return dict(result, status='STOP', reason='result scope/file mode unsafe')
            seen_paths.add(row['filename'])
        recovery = recover_result_command(wake=wake, plan=plan, target_tree=lineage.result_tree, now=now,
                                          terminal_binding=snapshot.get('terminal_binding'))
        result['recovery'] = recovery
        if recovery['status'] == 'NOT_SUBMITTED':
            result['review_candidate'] = asdict(plan)
            result['posting_blockers'] = ['production source authentication', 'explicit posting authorization', 'pull-requests:write', 'fresh final readback']
            return dict(result, status='PREPARED_REVIEW', reason='MOCK artifact only; no send method')
        if recovery['status'] != 'TERMINAL':
            return dict(result, status=recovery['status'])
        if recovery['terminal_status'] != 'PASS':
            return dict(result, status='NO_OP', reason='terminal non-PASS command cannot propose successor')
        request = prepare_result_review_request(plan, target_tree=lineage.result_tree,
                                               evidence_refs=review_input['evidence_refs'], expires_at=wake['expires_at'], now=now)
        if review_input.get('records') is None:
            return dict(result, status='BLOCKED', reason='independent review record missing')
        reviewed = assess_result_review(lineage=lineage, request=request, reviewer_records=review_input['records'],
                    current_result=current, changed_files=review_input['changed_files'], files_complete=True,
                    allowed_paths=source['request']['allowed_paths'], checks=review_input['checks'],
                    implementer_id=review_input['implementer_id'], now=now)
        result['review'] = asdict(reviewed)
        if reviewed.status != 'VALIDATED' or reviewed.decision != 'PASS':
            return dict(result, status=reviewed.status if reviewed.status != 'VALIDATED' else 'BLOCKED')
        proposal = reviewed.response['next_command_proposal']
        if proposal is None:
            return dict(result, status='NO_OP', reason='no useful next task')
        target = snapshot['next_snapshot']['target']
        if target['branch'] != source['request']['target_branch']:
            return dict(result, status='STOP', reason='next canonical branch differs from source mission')
        next_plan = prepare_next_jules(lane=lane, **proposal, **snapshot['next_snapshot'], review_decision='PASS', now=now)
        if next_plan.status == 'PREPARED':
            final = snapshot.get('reservation_preflight', snapshot['next_snapshot'])
            next_plan = recheck_next_jules(next_plan, **final, now=now)
        result['next_task'] = asdict(next_plan)
        return dict(result, status='PREPARED_NEXT' if next_plan.status == 'PREPARED' else next_plan.status,
                    reason='STOP before reservation or dispatch')
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, StopIteration):
        # Untrusted inputs/errors never become log contents or arbitrary labels.
        return dict(result, status='UNKNOWN', reason='bridge snapshot missing/malformed/conflicting; retry=0')
