"""One approved BWJ-4 transport proof. No provider, target write or retry route.

Only the dispatch-only, main-pinned proof job invokes the single POST. Tests
inject GET/POST fakes. A submitted review never proves a Work wake by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, build_opener

from .blue_jules_result_event import EXPECTED_REPOSITORY
from .blue_work_reconcile_prepare import PREFIX, RECEIPT_PREFIX, _body, _command, _pairs, _records, _sha, _time
from .cloud_work_lanes import LANES, lane_identity
from .cloud_work_snapshot import collect_lane_snapshot, discover_carrier
from .github_readonly import ROOT, GitHubGetReader, _NoRedirect, content_at, read_all

WORKFLOW = '.github/workflows/blue-work-wake-proof.yml'
JOB = 'one-shot-readonly-wake-proof'
AUTHORIZATION = 'docs/BLUE_BWJ4_PROOF_AUTHORIZATION.json'
PRINCIPAL = {'id': 41898282, 'login': 'github-actions[bot]', 'type': 'Bot'}
ZERO = {'provider_create': 0, 'provider_get': 0, 'provider_model_execution': 0,
        'jules_submit': 0, 'jules_get': 0, 'claim_reservation': 0,
        'next_command_publication': 0, 'target_mutation': 0, 'adoption': 0,
        'retry': 0}


def blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def required(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def load_authorization(path: Path, now: datetime) -> dict:
    value = json.loads(path.read_text(), object_pairs_hook=_pairs)
    required(value.get('schema_version') == 1 and value.get('purpose') == 'BWJ-4_TRANSPORT_ONLY', 'authorization scope')
    required(value.get('approved') is True and value.get('retry') == 0 and value.get('fallback') == 'disabled', 'authorization policy')
    required(value.get('repository') == EXPECTED_REPOSITORY and value.get('limits') == dict(ZERO, proof_activation=1,
             workflow_run=1, review_post=1, logical_blue_wake=1, terminal_receipt=1)
             and all(type(v) is int for v in value['limits'].values()), 'budget scope')
    proof_id = value.get('proof_id')
    required(isinstance(proof_id, str) and re.fullmatch(r'blue-bwj4-[0-9]{8}T[0-9]{6}Z-transport-proof-01', proof_id) is not None,
             'new proof identity')
    required(now < _time(value['approval_expires_at']), 'approval expired')
    return value


def context(env: dict, authorization: dict) -> dict:
    required(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and env.get('GITHUB_REF') == 'refs/heads/main', 'main dispatch only')
    required(env.get('GITHUB_REPOSITORY') == EXPECTED_REPOSITORY and env.get('GITHUB_RUN_ATTEMPT') == '1', 'repository/attempt fence')
    required(env.get('GITHUB_ACTOR') == authorization['approved_actor_login'], 'approved actor')
    required(env.get('PROOF_ID') == authorization['proof_id'], 'sealed proof identity')
    head, workflow_blob = env.get('APPROVED_MAIN'), env.get('APPROVED_WORKFLOW_BLOB')
    required(_sha(head) and _sha(workflow_blob) and head == env.get('GITHUB_SHA'), 'approved code identity')
    run_id = env.get('GITHUB_RUN_ID', '')
    required(run_id.isdigit() and int(run_id) > 0, 'run identity')
    return {'run_id': int(run_id), 'run_attempt': 1, 'workflow_commit': head, 'workflow_blob': workflow_blob}


def _pr_binding(reader, pr: dict) -> dict:
    required(pr.get('state') == 'open' and pr.get('merged') is False
             and pr.get('head', {}).get('repo', {}).get('full_name') == EXPECTED_REPOSITORY, 'open same-repository PR')
    head, branch = pr['head']['sha'], pr['head']['ref']
    required(_sha(head) and branch not in {'main', 'master'} and '..' not in branch, 'non-default target')
    ref = reader.get(ROOT + '/git/ref/heads/' + branch).data
    required(ref.get('object', {}).get('sha') == head, 'branch/PR drift')
    commit = reader.get(ROOT + '/git/commits/' + head).data
    required(commit.get('sha') == head and _sha(commit.get('tree', {}).get('sha')), 'commit/tree binding')
    return {'pr': pr['number'], 'branch': branch, 'head': head, 'tree': commit['tree']['sha']}


def check_run(reader, ctx: dict, authorization: dict) -> int:
    run = reader.get(ROOT + f"/actions/runs/{ctx['run_id']}").data
    required(run.get('id') == ctx['run_id'] and run.get('run_attempt') == 1
             and run.get('head_sha') == ctx['workflow_commit'] and run.get('head_branch') == 'main'
             and run.get('event') == 'workflow_dispatch' and run.get('path') == WORKFLOW
             and run.get('repository', {}).get('full_name') == EXPECTED_REPOSITORY, 'trusted run binding')
    for field in ('actor', 'triggering_actor'):
        required(run.get(field, {}).get('login') == authorization['approved_actor_login']
                 and run.get(field, {}).get('id') == authorization['approved_actor_id'], 'run actor binding')
    # Run history is durable replay protection even after artifacts expire. A
    # prior blocked/cancelled/ambiguous run consumes this workflow activation.
    runs = read_all(reader, ROOT + '/actions/workflows/blue-work-wake-proof.yml/runs?per_page=100', array_key='workflow_runs')
    required(len(runs) == 1 and runs[0].get('id') == ctx['run_id'] and runs[0].get('run_attempt') == 1, 'one run budget already consumed')
    jobs = read_all(reader, ROOT + f"/actions/runs/{ctx['run_id']}/jobs?per_page=100", array_key='jobs')
    selected = [j for j in jobs if j.get('name') == JOB]
    required(len(selected) == 1 and selected[0].get('head_sha') == ctx['workflow_commit']
             and selected[0].get('run_attempt') == 1 and selected[0].get('status') == 'in_progress', 'exact running proof job')
    return selected[0]['id']


def collect(reader, ctx: dict, authorization: dict, now: datetime) -> dict:
    required(now < _time(authorization['approval_expires_at']), 'approval expired')
    main = reader.get(ROOT + '/git/ref/heads/main').data['object']['sha']
    required(main == ctx['workflow_commit'], 'current main drift')
    main_commit = reader.get(ROOT + '/git/commits/' + main).data
    workflow = content_at(reader, WORKFLOW, main)
    required(blob(workflow.encode()) == ctx['workflow_blob'], 'workflow blob drift')
    required(content_at(reader, AUTHORIZATION, main) == json.dumps(authorization, indent=2) + '\n', 'authorization content drift')
    lane = collect_lane_snapshot(reader, lane='blue', result_number=authorization['target_pr'])
    carrier, target = _pr_binding(reader, lane.carrier_pr), _pr_binding(reader, lane.result_pr)
    required(target['pr'] not in {217, 227} and target['pr'] != carrier['pr'], 'forbidden historical target')
    required(lane.worker_state.get('replacement_proof_pr') == target['pr']
             and lane.worker_state.get('replacement_proof_branch') == target['branch'], 'existing safe transport fixture')
    required(target == authorization['target'], 'sealed fixture drift')
    required(lane.worker_state['active_generation'] == authorization['worker_generation'], 'worker generation drift')
    identities, terminals = _records(lane.reviews, lane.comments, True)
    required(authorization['proof_id'] not in identities | terminals, 'existing Blue command/receipt')
    # A same-ID record on another lane must not be repurposed as this proof.
    open_prs = read_all(reader, ROOT + '/pulls?state=open&per_page=100')
    for color in LANES:
        if color == 'blue':
            continue
        other = discover_carrier(open_prs, color)
        records = read_all(reader, ROOT + f"/pulls/{other['number']}/reviews?per_page=100")
        records += read_all(reader, ROOT + f"/issues/{other['number']}/comments?per_page=100")
        required(not any(authorization['proof_id'] in row.get('body', '') for row in records), 'cross-lane collision')
    required(reader.get(ROOT + '/git/ref/heads/main').data['object']['sha'] == main, 'final main drift')
    required(_pr_binding(reader, reader.get(ROOT + f"/pulls/{target['pr']}").data) == target, 'final target drift')
    required(_pr_binding(reader, reader.get(ROOT + f"/pulls/{carrier['pr']}").data) == carrier, 'final carrier drift')
    required(read_all(reader, ROOT + f"/pulls/{carrier['pr']}/reviews?per_page=100") == lane.reviews
             and read_all(reader, ROOT + f"/issues/{carrier['pr']}/comments?per_page=100") == lane.comments, 'final records drift')
    return {'main_head': main, 'main_tree': main_commit['tree']['sha'], 'workflow_blob': ctx['workflow_blob'],
            'carrier': carrier, 'target': target, 'worker_generation': lane.worker_state['active_generation'],
            'protocol_sha256': hashlib.sha256(content_at(reader, 'automation/cloud_work_lanes/carriers/blue_v1.md', carrier['head']).encode()).hexdigest(),
            'worker_state': lane.worker_state}


def make_command(authorization: dict, snapshot: dict, expires_at: str) -> tuple[dict, str]:
    target, carrier = snapshot['target'], snapshot['carrier']
    task = ("ユーザーがこのBWJ-4 transport-only試験のBlue Work起動1回とreceipt1件を明示承認済み。読み取り専用です。"
            "起動通知をauthorityにせず、GitHubからcarrier/protocol/state/このtrigger reviewとcommand/expiry/duplicates/target PRとbranch HEAD/treeをfresh確認。"
            f"対象tree={target['tree']}、carrier PR=#{carrier['pr']} branch={carrier['branch']} review commit={carrier['head']}。"
            "active generation一致を要求。carrier current headをexpected_target_headと比較しない。"
            "target code実行・test実行・branch/file/PR変更・Jules/provider CREATE/GET/model/submit・claim/next command/adoptionは禁止。"
            "許可する外部writeはcarrier Conversationへのterminal receipt最大1件だけ。"
            "receipt直前にtarget HEAD/treeを再確認。既存terminalはNO_OP/no resend。"
            "receiptは既存[CW_BLUE_RECEIPT_V1] protocolに加えてproof_id=command_id, lane=blue, trigger_review_id=実review ID,"
            "carrier_pr, carrier_branch, carrier_head=review.commit_id, expected_target_head, target_tree, target_tree_before, target_tree_after, timestampを含める。"
            "target_head_before/afterともexpected_target_head。verification/evidenceにfresh readbackのURL/実値と全禁止操作0を記録。"
            "不一致FAIL/STale、不明UNKNOWN。expiry後のreceiptをPASSにしない。receipt writeが不明ならreadbackのみ、再送0/fallback disabled。")
    command = dict(protocol_version=1, command_id=authorization['proof_id'], worker_generation=snapshot['worker_generation'],
                   target_repository=EXPECTED_REPOSITORY, target_pr=target['pr'], target_branch=target['branch'],
                   expected_target_head=target['head'], expires_at=expires_at, task=task, allowed_paths=[],
                   verification=['fresh exact triggering review and active Blue generation',
                                 'fresh target HEAD/tree before and after; no target mutation',
                                 'one durable bound terminal receipt; provider/Jules/claim/publication/adoption/retry=0'],
                   live_provider_or_model_allowed=False, retry=0, fallback='disabled')
    _command(command)
    return command, PREFIX + '\n' + json.dumps(command, ensure_ascii=False, indent=2)


def create_attempt(reader, authorization: dict, ctx: dict, now: datetime, output: Path) -> dict:
    required(not output.exists(), 'attempt path already exists; no overwrite')
    job_id = check_run(reader, ctx, authorization)
    first, second = collect(reader, ctx, authorization, now), collect(reader, ctx, authorization, now)
    required(first == second, 'preflight changed during event')
    expiry = min(now + timedelta(minutes=30), _time(authorization['approval_expires_at'])).isoformat()
    command, body = make_command(authorization, second, expiry)
    attempt = dict(ctx, schema_version=1, proof_id=authorization['proof_id'], status='ATTEMPTING',
                   job_id=job_id, snapshot=second, command=command, review_body=body,
                   review_body_sha256=hashlib.sha256(body.encode()).hexdigest(), approved_principal=PRINCIPAL,
                   created_at=now.isoformat(), retry=0, fallback='disabled', limits=authorization['limits'])
    output.mkdir()
    with (output / 'attempt.json').open('x') as handle:
        json.dump(attempt, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({'proof_id': attempt['proof_id'], 'status': 'ATTEMPTING', 'run_id': ctx['run_id'], 'job_id': job_id}))
    return attempt


def verify_artifact(reader, attempt: dict, artifact_id: str, digest: str) -> dict:
    required(artifact_id.isdigit() and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest), 'durable artifact unavailable')
    row = reader.get(ROOT + '/actions/artifacts/' + artifact_id).data
    required(row.get('id') == int(artifact_id) and row.get('expired') is False
             and row.get('name') == 'bwj4-attempt-' + attempt['proof_id'] and row.get('digest') == 'sha256:' + digest
             and row.get('workflow_run', {}).get('id') == attempt['run_id']
             and row.get('workflow_run', {}).get('head_sha') == attempt['workflow_commit'], 'attempt artifact origin mismatch')
    return {'id': row['id'], 'digest': row['digest']}


class ReviewPostOnce:
    """Only one fixed COMMENT-review endpoint. No redirects, retries or fallback."""
    def __init__(self, token: str):
        required(bool(token) and '\n' not in token and '\r' not in token, 'existing GITHUB_TOKEN unavailable')
        self._token, self._used = token, False
        self._opener = build_opener(_NoRedirect())

    def post(self, carrier_pr: int, carrier_head: str, body: str) -> dict:
        required(not self._used, 'POST budget consumed')
        required(type(carrier_pr) is int and carrier_pr > 0 and _sha(carrier_head) and body.startswith(PREFIX + '\n'), 'fixed review endpoint/action')
        self._used = True  # Consume BEFORE touching the network, including timeout.
        request = Request(ROOT + f'/pulls/{carrier_pr}/reviews', method='POST',
                          data=json.dumps({'event': 'COMMENT', 'commit_id': carrier_head, 'body': body}).encode(),
                          headers={'Authorization': 'Bearer ' + self._token, 'Accept': 'application/vnd.github+json',
                                   'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
        with self._opener.open(request, timeout=30) as response:
            required(response.status == 200, 'POST outcome not confirmed')
            raw = response.read(1024 * 1024 + 1)
            required(len(raw) <= 1024 * 1024, 'POST readback size')
            return json.loads(raw, object_pairs_hook=_pairs)


def verify_review(rows: list, attempt: dict) -> dict:
    identity = attempt['proof_id']
    found = [r for r in rows if identity in r.get('body', '')]
    required(len(found) == 1, 'review outcome UNKNOWN/duplicate; never resend')
    row = found[0]
    required(row.get('state') == 'COMMENTED' and row.get('body') == attempt['review_body']
             and row.get('commit_id') == attempt['snapshot']['carrier']['head'], 'review binding')
    required(all(row.get('user', {}).get(k) == v for k, v in attempt['approved_principal'].items()), 'review principal')
    required(type(row.get('id')) is int and _time(attempt['created_at']) <= _time(row['submitted_at'])
             <= _time(attempt['command']['expires_at']), 'review timestamp/identity')
    return {key: row[key] for key in ('id', 'state', 'body', 'commit_id', 'user', 'submitted_at')}


def submit_once(reader, poster, authorization: dict, ctx: dict, output: Path,
                artifact_id: str, digest: str, now: datetime) -> dict:
    attempt = json.loads((output / 'attempt.json').read_text(), object_pairs_hook=_pairs)
    required(all(attempt.get(k) == v for k, v in ctx.items()) and attempt.get('proof_id') == authorization['proof_id'], 'attempt/run binding')
    required(attempt.get('status') == 'ATTEMPTING' and attempt.get('retry') == 0 and attempt.get('fallback') == 'disabled', 'attempt policy')
    required(now < _time(attempt['command']['expires_at']), 'command expired')
    required(attempt.get('review_body_sha256') == hashlib.sha256(attempt['review_body'].encode()).hexdigest(), 'body hash')
    required(_body(attempt['review_body'], PREFIX) == attempt['command'], 'body exact command')
    required(make_command(authorization, attempt['snapshot'], attempt['command']['expires_at']) == (attempt['command'], attempt['review_body']), 'bounded command')
    artifact = verify_artifact(reader, attempt, artifact_id, digest)
    required(check_run(reader, ctx, authorization) == attempt['job_id'], 'job drift')
    required(collect(reader, ctx, authorization, now) == attempt['snapshot'], 'final pre-POST fence')
    # Exclusive local marker additionally prevents calling this step twice in
    # the same job. Cross-job/run replay is stopped by complete run history.
    with (output / 'post-consumed.json').open('x') as handle:
        json.dump({'proof_id': attempt['proof_id'], 'artifact': artifact, 'status': 'POST_BUDGET_CONSUMED'}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    result = {'status': 'UNKNOWN', 'review_post_attempts': 1, 'retry': 0, 'fallback': 'disabled',
              'attempt_artifact': artifact, 'review': None, 'receipt': None, **ZERO}
    # Any POST error is uncertainty. Always perform independent GET; no send retry.
    try:
        poster.post(attempt['snapshot']['carrier']['pr'], attempt['snapshot']['carrier']['head'], attempt['review_body'])
        result['http_outcome'] = 'RESPONSE_RECEIVED'
    except Exception:
        result['http_outcome'] = 'UNKNOWN'  # Never serialize exceptions/token/raw bodies.
    try:
        url = ROOT + f"/pulls/{attempt['snapshot']['carrier']['pr']}/reviews?per_page=100"
        result['review'] = verify_review(read_all(reader, url), attempt)
        result['status'] = 'REVIEW_VERIFIED_RECEIPT_PENDING'
    except Exception:
        result['readback_outcome'] = 'UNKNOWN'
    with (output / 'post-result.json').open('x') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    return result


def inspect_receipt(comments: list, attempt: dict, review: dict, current_target: dict,
                    now: datetime, receipt_author: dict) -> dict:
    """Binding validation only; controller must separately prove intended Work."""
    found = []
    for row in comments:
        receipt = _body(row.get('body'), RECEIPT_PREFIX)
        if receipt and receipt.get('command_id') == attempt['proof_id']:
            found.append((row, receipt))
    if not found:
        return {'status': 'UNKNOWN', 'reason': 'receipt missing; STOP/no resend'}
    required(len(found) == 1, 'duplicate terminal')
    row, receipt = found[0]
    target, carrier = attempt['snapshot']['target'], attempt['snapshot']['carrier']
    expected = dict(protocol_version=1, command_id=attempt['proof_id'], proof_id=attempt['proof_id'], lane='blue',
                    worker_generation=attempt['snapshot']['worker_generation'], trigger_review_id=review['id'],
                    carrier_pr=carrier['pr'], carrier_branch=carrier['branch'], carrier_head=carrier['head'],
                    target_repository=EXPECTED_REPOSITORY, target_pr=target['pr'], target_branch=target['branch'],
                    expected_target_head=target['head'], target_head_before=target['head'], target_head_after=target['head'],
                    target_tree=target['tree'], target_tree_before=target['tree'], target_tree_after=target['tree'], terminal=True)
    required(all(type(receipt.get(k)) is type(v) and receipt.get(k) == v for k, v in expected.items()), 'terminal binding mismatch')
    required(all(row.get('user', {}).get(k) == v for k, v in receipt_author.items()), 'independent receipt author')
    required(current_target == target and _time(review['submitted_at']) <= _time(receipt['timestamp'])
             <= _time(row['created_at']) <= _time(attempt['command']['expires_at']), 'late receipt/target drift')
    required(_time(row['created_at']) <= now and isinstance(receipt.get('verification'), list)
             and bool(receipt['verification']), 'terminal evidence unavailable')
    if receipt.get('status') != 'PASS':
        return {'status': receipt.get('status', 'UNKNOWN'), 'receipt_id': row['id'], 'successor': None}
    return {'status': 'RECEIPT_BINDING_VALIDATED', 'receipt_id': row['id'],
            'work_wake_origin': 'REQUIRES_INDEPENDENT_READBACK', 'successor': None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['prepare', 'post'])
    parser.add_argument('--output', default='bwj4-proof')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    authorization = load_authorization(Path(AUTHORIZATION), now)
    ctx = context(os.environ, authorization)
    reader = GitHubGetReader(os.environ.get('GITHUB_TOKEN', ''))
    if args.stage == 'prepare':
        create_attempt(reader, authorization, ctx, now, Path(args.output))
    else:
        result = submit_once(reader, ReviewPostOnce(os.environ.get('GITHUB_TOKEN', '')), authorization, ctx,
                             Path(args.output), os.environ.get('ATTEMPT_ARTIFACT_ID', ''),
                             os.environ.get('ATTEMPT_ARTIFACT_DIGEST', ''), now)
        print(json.dumps({k: v for k, v in result.items() if k != 'review'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
