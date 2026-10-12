"""Explicit synthetic CLI only. No external inputs, credentials or LIVE factory.

The recover command consumes only this runner's synthetic JSON plus local
records. It rebuilds fake GET context; no pickle/eval/import supplied by data.
"""
import argparse
import base64
import json
import os
from pathlib import Path
from dataclasses import asdict
from ..symphony_g73_host import LocalStaticContents, OperatorStaticHost
from ..symphony_result_manifest import digest


def host(w, events):
    return OperatorStaticHost(w.adapter(), events=events, workspace=w.workspace)


def recover(root):
    from ..tests.test_symphony_g72_runtime import ObservedWorld, KEY
    from ..tests.symphony_g61_github_sim import SimulatedGitHub
    from ..symphony_attempt_store import GitHubAutonomousAttemptStore
    from ..symphony_campaign_store import GitHubCampaignStateStore
    from ..symphony_git_adoption import AppendOnlyAdoptionStore
    from ..symphony_production_observer import SymphonyProductionObserver, ObservedIssue
    from ..symphony_g63_snapshot import StrictWorkspaceSnapshotStore
    from ..tests.test_symphony_g61_production_wiring import NOW
    body = json.loads((root / 'synthetic-restart-context.json').read_text())
    if body['protocol'] != 'SYMPHONY_G73_SYNTHETIC_RESTART_CONTEXT_V1':
        raise ValueError('synthetic context only')
    w = object.__new__(ObservedWorld)
    for name in ('task_id', 'issue_id', 'scope', 'request', 'worker', 'head', 'number',
                 'generation', 'attempt_id', 'snapshot_id', 'external', 'manifest'):
        setattr(w, name, body['world'][name])
    w.tmp = root / 'F'; w.workspace = w.tmp / 'workspace-F'
    w.extra_records = []; w.flow = None
    w.client = LocalStaticContents(root / 'records')
    w.gh = SimulatedGitHub()
    w.gh.refs = body['refs']; w.gh.issues = {int(k): v for k, v in body['issues'].items()}
    w.gh.objects = {oid: (kind, base64.b64decode(raw, validate=True))
                    for oid, (kind, raw) in body['objects'].items()}
    w.attempts = GitHubAutonomousAttemptStore(w.client, write_branch='fixture/attempt-ledger')
    w.campaign_store = GitHubCampaignStateStore(w.client, write_branch='fixture/g72-campaign')
    w.ledger = AppendOnlyAdoptionStore(w.client, write_branch='fixture/g61-ledger')
    w.snapshots = StrictWorkspaceSnapshotStore(str(w.tmp / 'strict-snapshots'))
    w.observer = SymphonyProductionObserver(w.attempts, campaign_id='g61-static', key=KEY,
        issues={w.issue_id: ObservedIssue(w.task_id, w.generation, w.head, w.generation, w.scope)})
    # Strict GET-only context: even accidentally settling instead of recovering
    # cannot dispatch a fake mutation from the recovering process.
    flow = w.wired()
    class RecoveryReads:
        static_only = True
        atomic_expected_head = True
        read_target = flow.transport.read_target
        read_candidate = flow.transport.read_candidate
        def put_candidate(self, *args, **kwargs): raise PermissionError('GET-only recovery')
        def compare_and_swap(self, *args, **kwargs): raise PermissionError('GET-only recovery')
    flow.transport = RecoveryReads(); flow.bridge.transport = flow.transport
    w.flow = flow
    h = host(w, root / 'F.events.jsonl')
    before = h.restore()
    events = h.handle('replay')
    result = h.handle('recover', attempt_id=w.attempt_id, expected_revision=before['revision'], now=NOW)
    after = h.restore()
    assert result['result']['status'] == 'NOOP_DUPLICATE', result
    assert before == after and w.gh.update_refs_requests == 0 and w.gh.object_posts == 0
    assert all(x['status'] in ('NOOP_DUPLICATE', 'READ_ONLY') for x in events['results'])
    return {'protocol': 'SYMPHONY_G73_SYNTHETIC_PROCESS_RECOVERY_V1', 'status': 'PASS',
            'checkpoint_digest': after['checkpoint_digest'], 'receipt': result['result']['status'],
            'event_statuses': [x['status'] for x in events['results']],
            'extra_mock_ref_calls': 0, 'extra_mock_object_posts': 0, 'extra_model_dispatch': 0,
            'actual_candidate_attestation': False}


def run(root):
    from ..tests.test_symphony_g72_runtime import ObservedWorld, signed
    from ..symphony_autonomous_runtime import CampaignState, CampaignTask, TaskStatus
    from ..tests.test_symphony_g61_production_wiring import NOW
    import subprocess, sys
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    client = LocalStaticContents(root / 'records')
    seed = ObservedWorld(root / 'seed', client=client)
    state = CampaignState('g61-static', 1, {n: CampaignTask(n) for n in ('A', 'B', 'E', 'F')})
    assert seed.campaign_store.save(state, expected_revision=0).status == 'ACCEPTED'
    rows = []
    for name in ('A', 'B', 'B::corrective::1', 'E', 'F'):
        w = ObservedWorld(root / name.replace(':', '-'), task_id=name, gh=seed.gh, client=client)
        if name == 'B': w.external['tests'] = 'FAIL'
        events = root / (name.replace(':', '-') + '.events.jsonl')
        events.touch(mode=0o600)
        h = host(w, events)
        revision = h.restore()['revision']
        admitted = h.handle('admission', task_id=name, expected_revision=revision,
                            account_evidence={'auth_state': 'CHATGPT_ACCOUNT'})
        assert admitted['result']['status'] == 'PREPARED_STATIC_ONLY'
        events.write_text(signed(w, 'STARTED') + '\n'); events.chmod(0o600)
        captured = h.handle('replay')['results'][0]
        assert captured['status'] == 'ACCEPTED'
        w.attempt_id = captured['attempt_id']; w.snapshot_id = 'g73-' + digest(w.attempt_id)[:32]
        for _ in range(2):
            with events.open('a') as stream: stream.write(signed(w, 'WORKER_UPDATE') + '\n')
        h.handle('replay')
        snapshot = h.handle('snapshot', attempt_id=w.attempt_id, snapshot_id=w.snapshot_id, captured_at=NOW)
        assert snapshot['result']['close_ready']
        with events.open('a') as stream: stream.write(signed(w, 'TERMINAL') + '\n')
        h.handle('replay')
        rev = h.restore()['revision']
        if name == 'B': result = h.handle('corrective', attempt_id=w.attempt_id, expected_revision=rev)
        else: result = h.handle('settle', attempt_id=w.attempt_id, expected_revision=rev,
                              now=NOW, constraints_known=name != 'E')
        rows.append({'task': name, 'result': result['result'], 'view': result['view'],
                     'signed_updates': 2, 'snapshot_manifest_sha256': w.snapshots.manifest_sha256(w.snapshot_id),
                     'started': w.attempt().started, 'terminal': w.attempt().terminal})
    cp = w.campaign_store.restore('g61-static')
    assert all(cp.state.tasks[n].status is TaskStatus.COMPLETE for n in ('A', 'B', 'F'))
    assert cp.state.tasks['E'].status is TaskStatus.BLOCKED
    assert seed.gh.update_refs_requests == 3
    context = {'protocol': 'SYMPHONY_G73_SYNTHETIC_RESTART_CONTEXT_V1',
               'world': {n: getattr(w, n) for n in ('task_id', 'issue_id', 'scope', 'request', 'worker', 'head',
                   'number', 'generation', 'attempt_id', 'snapshot_id', 'external', 'manifest')},
               'refs': w.gh.refs, 'issues': w.gh.issues,
               'objects': {oid: (kind, base64.b64encode(raw).decode()) for oid, (kind, raw) in w.gh.objects.items()}}
    (root / 'synthetic-restart-context.json').write_text(json.dumps(context))
    # Real independent Python process; only synthetic context and STATIC records.
    process = subprocess.run([sys.executable, '-m', 'automation.command_bus.scripts.symphony_g73_host_fixture', 'recover', str(root)],
                             check=True, capture_output=True, text=True, encoding='utf-8',
                             env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'})
    restart = json.loads(process.stdout)
    assert restart['checkpoint_digest'] == cp.state_digest
    return {'protocol': 'SYMPHONY_G73_HOST_STATIC_EVIDENCE_V1', 'result': 'PASS', 'synthetic': True,
            'host_bound': True, 'disk_durable': True, 'tasks': rows, 'mock_verified_receipts': 3,
            'independent_failed_check_corrective': True, 'blocked_sibling_finished': True,
            'process_restart': restart, 'counts': {'live_worker': 0, 'model': 0,
                'real_git_write': 0, 'actual_result_adoption': 0}, 'operator_approval': 'NONE'}


def main():
    parser = argparse.ArgumentParser(description='Explicit credential-free SYNTHETIC host fixture only')
    parser.add_argument('operation', choices=('run', 'recover'))
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.root) if args.operation == 'run' else recover(args.root), sort_keys=True))


if __name__ == '__main__': main()
