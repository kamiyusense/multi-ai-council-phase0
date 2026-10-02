"""Deterministic finite MOCK E2E/soak artifact. Never calls external services."""
from copy import deepcopy
import json
from datetime import timedelta

from automation.command_bus.cloud_work_lanes import LANES, lane_identity
from automation.command_bus.blue_work_reconcile_prepare import assess_cloud_review
from automation.command_bus.work_bridge_prepare import prepare_bridge
from .bridge_fixtures import bridge_snapshot, unsafe_cases
from .closed_loop_fixtures import NOW


def run_simulation(loops_per_lane=8):
    if type(loops_per_lane) is not int or not 5 <= loops_per_lane <= 10:
        raise ValueError('bounded 5–10 MOCK loops per lane')
    invariants = {key: 0 for key in ('global_loop_collision', 'cross_color_consumption', 'foreign_receipt_adoption',
        'duplicate_dispatch', 'terminal_replay', 'stale_generation_execution', 'unauthenticated_adoption',
        'target_mismatch_adoption', 'merge', 'force', 'external_send', 'claim_reservation')}
    rows, seen_numbers, submissions = [], set(), set()
    fault_count = 0
    for round_number in range(loops_per_lane):
        # A reproducible permutation changes interleaving, not lane identity.
        ordered = LANES[round_number % 4:] + LANES[:round_number % 4]
        for lane in ordered:
            index = round_number * 4 + LANES.index(lane) + 1
            pending = bridge_snapshot(lane, virtual_index=index)
            prepared = prepare_bridge(pending, now=NOW)
            assert prepared['status'] == 'PREPARED_REVIEW', prepared
            body = prepared['review_candidate']['review_body']
            command = json.loads(body.split('\n', 1)[1])
            # Duplicate wake before submit/crash can regenerate the SAME
            # candidate only. One fake submission is recorded durably below.
            assert prepare_bridge(json.loads(json.dumps(pending)), now=NOW) == prepared
            identity = command['command_id']
            assert identity not in submissions
            submissions.add(identity)
            waiting = bridge_snapshot(lane, submitted=True, virtual_index=index)
            for action in ('synchronize', 'opened', 'synchronize'):
                waiting['wake']['event']['action'] = action
                output = prepare_bridge(json.loads(json.dumps(waiting)), now=NOW)
                assert output['status'] == 'UNKNOWN' and 'review_candidate' not in output and 'next_task' not in output
            terminal = bridge_snapshot(lane, terminal=True, virtual_index=index)
            terminal['wake']['carrier_pr']['head']['sha'] = 'b' * 40  # carrier is not fixed target.
            complete = prepare_bridge(json.loads(json.dumps(terminal)), now=NOW)
            assert complete['status'] == 'PREPARED_NEXT', complete
            number = complete['next_task']['claim']['loop_number']
            assert number not in seen_numbers
            seen_numbers.add(number)
            assert complete['next_task']['claim']['lane_id'] == lane_identity(lane)['jules_lane']
            assert complete['next_task']['claim']['schema_version'] == 3
            assert complete['next_task']['reservation_state'] == 'NOT_RESERVED'
            for key in ('external_send_attempted', 'model_executed', 'adoption_performed', 'claim_reserved', 'posting_authority'):
                assert complete[key] is False
            # Simulated durable review consumption, then fresh process/JSON.
            terminal['review']['records'] = complete['review']['recovered_records']
            recovered = prepare_bridge(json.loads(json.dumps(terminal)), now=NOW)
            assert recovered['status'] == 'NO_OP' and 'next_task' not in recovered
            # Every foreign worker must ignore this lane's command.
            args = dict(body=body, active_generation=1, fixed_generation=1,
                current_target={k: command[k] for k in ('target_repository', 'target_pr', 'target_branch', 'expected_target_head')},
                reviews=[{'id': 101, 'state': 'COMMENTED', 'body': body}], comments=[], records_complete=True, now=NOW)
            for other in LANES:
                gate = assess_cloud_review(**args, lane=other)
                assert gate.status == ('VALIDATED' if other == lane else 'NO_OP')
            # Each fault is observed from a fresh synthetic durable snapshot.
            for name, mutate in unsafe_cases().items():
                faulty = bridge_snapshot(lane, terminal=True)
                mutate(faulty)
                outcome = prepare_bridge(faulty, now=NOW + (timedelta(hours=1) if name == 'late_terminal' else timedelta()))
                assert outcome['status'] != 'PREPARED_NEXT' and not outcome.get('next_task', {}).get('claim'), (lane, name, outcome)
                fault_count += 1
            rows.append({'lane': lane, 'virtual_round': round_number + 1, 'command_id': identity,
                         'candidate_loop': number, 'restart_status': recovered['status']})
    return {'source_mode': 'MOCK', 'execution_mode': 'PREPARE_ONLY', 'virtual_loops': len(rows),
            'loops_per_lane': loops_per_lane, 'fault_observations': fault_count, 'fake_submissions': len(submissions),
            'unreserved_next_candidates': len(seen_numbers), 'invariant_violations': invariants,
            'external_execution': 0, 'records': rows,
            'limitations': ['Assertions cover deterministic fixture cases only.', 'No provider/source authentication or live wake proven.',
                           'Concurrent unreserved candidates may collide; formal reservation recheck must BLOCK, never retry.']}


if __name__ == '__main__':
    print(json.dumps(run_simulation(), sort_keys=True, indent=2))
