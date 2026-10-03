"""One-shot proof fault tests; all network, posting and worker activity faked."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from automation.command_bus import blue_work_wake_proof as proof
from automation.command_bus.blue_work_reconcile_prepare import assess_cloud_review
from automation.command_bus.github_readonly import ReadResponse

NOW = datetime(2026, 10, 2, 21, 25, tzinfo=timezone.utc)
HEAD, TREE, CARRIER = 'a' * 40, 'b' * 40, 'c' * 40
CTX = {'run_id': 11, 'run_attempt': 1, 'workflow_commit': 'd' * 40, 'workflow_blob': 'e' * 40}
TARGET = {'pr': 172, 'branch': 'cloud-work/replacement-proof-v1', 'head': HEAD, 'tree': TREE}
SNAPSHOT = {'main_head': CTX['workflow_commit'], 'main_tree': 'f' * 40, 'workflow_blob': CTX['workflow_blob'],
            'carrier': {'pr': 167, 'branch': 'cloud-work/carrier-blue-v1', 'head': CARRIER, 'tree': '1' * 40},
            'target': TARGET, 'worker_generation': 1, 'protocol_sha256': '2' * 64,
            'worker_state': {'active_generation': 1}}


def authorization():
    root = Path(__file__).resolve().parents[3]
    value = json.loads((root / proof.AUTHORIZATION).read_text())
    value['target'] = deepcopy(TARGET)
    return value


def attempt():
    value = authorization()
    command, body = proof.make_command(value, SNAPSHOT, (NOW + timedelta(minutes=30)).isoformat())
    return dict(CTX, schema_version=1, proof_id=value['proof_id'], status='ATTEMPTING', job_id=22,
                snapshot=deepcopy(SNAPSHOT), command=command, review_body=body,
                review_body_sha256=proof.hashlib.sha256(body.encode()).hexdigest(), approved_principal=proof.PRINCIPAL,
                created_at=NOW.isoformat(), retry=0, fallback='disabled', limits=value['limits'])


def review(value):
    return {'id': 33, 'state': 'COMMENTED', 'body': value['review_body'], 'commit_id': CARRIER,
            'user': deepcopy(proof.PRINCIPAL), 'submitted_at': (NOW + timedelta(seconds=1)).isoformat()}


def receipt(value):
    body = dict(protocol_version=1, command_id=value['proof_id'], proof_id=value['proof_id'], lane='blue',
                worker_generation=1, trigger_review_id=33, carrier_pr=167, carrier_branch='cloud-work/carrier-blue-v1',
                carrier_head=CARRIER, target_repository=proof.EXPECTED_REPOSITORY, target_pr=172,
                target_branch=TARGET['branch'], expected_target_head=HEAD, target_head_before=HEAD,
                target_head_after=HEAD, target_tree=TREE, target_tree_before=TREE, target_tree_after=TREE,
                terminal=True, verification=['fresh repository/target and review GET URLs'], status='PASS',
                timestamp=(NOW + timedelta(seconds=2)).isoformat())
    return {'id': 44, 'body': proof.RECEIPT_PREFIX + '\n' + json.dumps(body),
            'user': {'id': 20355232, 'login': 'kamiyusense', 'type': 'User'},
            'created_at': (NOW + timedelta(seconds=3)).isoformat()}


class ProofTests(unittest.TestCase):
    def test_sealed_authorization_and_budget(self):
        root = Path(__file__).resolve().parents[3]
        value = proof.load_authorization(root / proof.AUTHORIZATION, NOW)
        self.assertEqual(value['target_pr'], 172)
        self.assertNotIn(value['target_pr'], {217, 227})
        self.assertEqual(set(proof.ZERO.values()), {0})
        self.assertEqual(value['limits']['review_post'], 1)
        expiry = datetime.fromisoformat(value['approval_expires_at'].replace('Z', '+00:00'))
        with self.assertRaises(ValueError):
            proof.load_authorization(root / proof.AUTHORIZATION, expiry + timedelta(seconds=1))

    def test_context_negative_events_refs_actor_attempt_and_id(self):
        a = authorization()
        env = dict(GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/main',
                   GITHUB_REPOSITORY=proof.EXPECTED_REPOSITORY, GITHUB_RUN_ATTEMPT='1',
                   GITHUB_ACTOR='kamiyusense', PROOF_ID=a['proof_id'], APPROVED_MAIN=CTX['workflow_commit'],
                   APPROVED_WORKFLOW_BLOB=CTX['workflow_blob'], GITHUB_SHA=CTX['workflow_commit'], GITHUB_RUN_ID='11')
        self.assertEqual(proof.context(env, a), CTX)
        for key, bad in [('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_REF', 'refs/heads/evil'),
                         ('GITHUB_REPOSITORY', 'wrong/repo'), ('GITHUB_RUN_ATTEMPT', '2'),
                         ('GITHUB_ACTOR', 'another-user'), ('PROOF_ID', a['proof_id'] + '-retry'),
                         ('APPROVED_MAIN', HEAD), ('APPROVED_WORKFLOW_BLOB', ''), ('GITHUB_RUN_ID', '-1')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                proof.context(dict(env, **{key: bad}), a)

    def test_command_readonly_and_target_separate_from_carrier(self):
        value = attempt()
        command = value['command']
        self.assertEqual(command['expected_target_head'], HEAD)
        self.assertNotEqual(command['expected_target_head'], CARRIER)
        self.assertEqual(command['allowed_paths'], [])
        self.assertIs(command['live_provider_or_model_allowed'], False)
        self.assertEqual(command['retry'], 0)
        self.assertEqual(command['fallback'], 'disabled')
        self.assertIn(TREE, command['task'])

    def test_existing_worker_contract_fresh_read_duplicates_and_staleness(self):
        value = attempt()
        args = dict(body=value['review_body'], active_generation=1, fixed_generation=1,
                    current_target=dict(target_repository=proof.EXPECTED_REPOSITORY, target_pr=172,
                                        target_branch=TARGET['branch'], expected_target_head=HEAD),
                    reviews=[review(value)], comments=[], records_complete=True, now=NOW)
        self.assertEqual(assess_cloud_review(**args).status, 'VALIDATED')
        self.assertEqual(assess_cloud_review(**dict(args, fixed_generation=2)).status, 'NO_OP')
        self.assertEqual(assess_cloud_review(**dict(args, active_generation=2, fixed_generation=2)).status, 'STALE')
        self.assertEqual(assess_cloud_review(**dict(args, now=NOW + timedelta(hours=1))).status, 'STALE')
        self.assertEqual(assess_cloud_review(**dict(args, current_target=dict(args['current_target'], expected_target_head=CARRIER))).status, 'STALE')
        self.assertEqual(assess_cloud_review(**dict(args, reviews=[review(value), dict(review(value), id=34)])).status, 'UNKNOWN')
        self.assertEqual(assess_cloud_review(**dict(args, comments=[receipt(value)])).status, 'NO_OP')

    def test_review_exact_readback_and_negative_metadata(self):
        value = attempt()
        row = review(value)
        self.assertEqual(proof.verify_review([row], value)['id'], 33)
        for key, bad in [('state', 'PENDING'), ('body', value['review_body'] + ' '),
                         ('commit_id', HEAD), ('user', {'id': 1, 'login': 'github-actions[bot]', 'type': 'Bot'}),
                         ('submitted_at', (NOW + timedelta(hours=2)).isoformat())]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                proof.verify_review([dict(row, **{key: bad})], value)
        for rows in ([], [row, dict(row, id=34)]):
            with self.assertRaises(ValueError):
                proof.verify_review(rows, value)

    def test_receipt_missing_never_promoted_and_valid_binding_is_not_wake_authority(self):
        value = attempt()
        args = (value, review(value), TARGET, NOW + timedelta(minutes=1), receipt(value)['user'])
        self.assertEqual(proof.inspect_receipt([], *args)['status'], 'UNKNOWN')
        result = proof.inspect_receipt([receipt(value)], *args)
        self.assertEqual(result['status'], 'RECEIPT_BINDING_VALIDATED')
        self.assertIsNone(result['successor'])
        self.assertEqual(result['work_wake_origin'], 'REQUIRES_INDEPENDENT_READBACK')

    def test_receipt_wrong_lane_trigger_generation_target_tree_terminal_and_late(self):
        value = attempt()
        row = receipt(value)
        body = proof._body(row['body'], proof.RECEIPT_PREFIX)
        for key, bad in [('lane', 'red'), ('trigger_review_id', 34), ('worker_generation', 2),
                         ('carrier_pr', 171), ('carrier_head', HEAD), ('target_pr', 227),
                         ('target_branch', 'wrong'), ('target_tree', CARRIER), ('target_head_after', CARRIER),
                         ('terminal', False), ('timestamp', (NOW + timedelta(hours=2)).isoformat())]:
            changed = dict(row, body=proof.RECEIPT_PREFIX + '\n' + json.dumps(dict(body, **{key: bad})))
            with self.subTest(key=key), self.assertRaises(ValueError):
                proof.inspect_receipt([changed], value, review(value), TARGET, NOW + timedelta(minutes=1), row['user'])
        for rows in ([row, dict(row, id=45)], [dict(row, created_at=(NOW + timedelta(hours=2)).isoformat())]):
            with self.assertRaises(ValueError):
                proof.inspect_receipt(rows, value, review(value), TARGET, NOW + timedelta(hours=3), row['user'])
        with self.assertRaises(ValueError):
            proof.inspect_receipt([row], value, review(value), dict(TARGET, head=CARRIER), NOW + timedelta(minutes=1), row['user'])

    def test_nonpass_terminal_cannot_produce_successor(self):
        value = attempt()
        row = receipt(value)
        body = proof._body(row['body'], proof.RECEIPT_PREFIX)
        for status in ['FAIL', 'UNKNOWN', 'BLOCKED', 'STALE', 'NO_OP']:
            changed = dict(row, body=proof.RECEIPT_PREFIX + '\n' + json.dumps(dict(body, status=status)))
            result = proof.inspect_receipt([changed], value, review(value), TARGET, NOW + timedelta(minutes=1), row['user'])
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['successor'])

    def test_post_client_timeout_consumes_budget_before_network(self):
        with patch.object(proof, 'build_opener') as opener:
            opener.return_value.open.side_effect = TimeoutError('do not serialize token')
            poster = proof.ReviewPostOnce('fake-token')
            with self.assertRaises(TimeoutError):
                poster.post(167, CARRIER, attempt()['review_body'])
            with self.assertRaises(ValueError):
                poster.post(167, CARRIER, attempt()['review_body'])
            self.assertEqual(opener.return_value.open.call_count, 1)
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(request.full_url, proof.ROOT + '/pulls/167/reviews')
            self.assertEqual(json.loads(request.data)['event'], 'COMMENT')

    def test_post_stage_ambiguous_http_readback_no_resend_and_restart_marker(self):
        value = attempt()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'attempt.json').write_text(json.dumps(value))
            reader, poster = Mock(), Mock()
            poster.post.side_effect = TimeoutError('sensitive raw error')
            with patch.object(proof, 'verify_artifact', return_value={'id': 55, 'digest': 'sha256:' + 'f' * 64}), \
                 patch.object(proof, 'check_run', return_value=22), \
                 patch.object(proof, 'collect', return_value=SNAPSHOT), \
                 patch.object(proof, 'read_all', return_value=[review(value)]):
                result = proof.submit_once(reader, poster, authorization(), CTX, output, '55', 'f' * 64, NOW)
                self.assertEqual(result['status'], 'REVIEW_VERIFIED_RECEIPT_PENDING')
                self.assertEqual(result['http_outcome'], 'UNKNOWN')
                self.assertEqual(result['review_post_attempts'], 1)
                self.assertNotIn('sensitive', (output / 'post-result.json').read_text())
                with self.assertRaises(FileExistsError):
                    proof.submit_once(reader, poster, authorization(), CTX, output, '55', 'f' * 64, NOW)
            self.assertEqual(poster.post.call_count, 1)

    def test_missing_artifact_or_final_drift_blocks_before_post(self):
        for failure in ('artifact', 'fence', 'expired', 'tampered'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                value = attempt()
                if failure == 'tampered':
                    value['command']['allowed_paths'] = ['anything']
                output = Path(directory)
                (output / 'attempt.json').write_text(json.dumps(value))
                poster = Mock()
                with patch.object(proof, 'verify_artifact', side_effect=ValueError('not durable') if failure == 'artifact' else None,
                                  return_value={'id': 55}), patch.object(proof, 'check_run', return_value=22), \
                     patch.object(proof, 'collect', return_value=dict(SNAPSHOT, main_head=HEAD) if failure == 'fence' else SNAPSHOT):
                    with self.assertRaises(ValueError):
                        proof.submit_once(Mock(), poster, authorization(), CTX, output, '55', 'f' * 64,
                                          NOW + timedelta(hours=1) if failure == 'expired' else NOW)
                poster.post.assert_not_called()

    def test_attempt_is_durable_before_post_and_existing_path_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'attempt'
            with patch.object(proof, 'check_run', return_value=22), patch.object(proof, 'collect', return_value=SNAPSHOT):
                value = proof.create_attempt(Mock(), authorization(), CTX, NOW, output)
                self.assertEqual(json.loads((output / 'attempt.json').read_text()), value)
                self.assertEqual(value['status'], 'ATTEMPTING')
                with self.assertRaises(ValueError):
                    proof.create_attempt(Mock(), authorization(), CTX, NOW, output)

    def test_artifact_origin_exact_run_head_name_digest_required(self):
        value = attempt()
        row = {'id': 55, 'expired': False, 'name': 'bwj4-attempt-' + value['proof_id'],
               'digest': 'sha256:' + 'f' * 64, 'workflow_run': {'id': 11, 'head_sha': CTX['workflow_commit']}}
        reader = Mock()
        reader.get.return_value = ReadResponse(row, {})
        self.assertEqual(proof.verify_artifact(reader, value, '55', 'f' * 64)['id'], 55)
        for key, bad in [('expired', True), ('digest', 'sha256:' + 'e' * 64), ('name', 'wrong'),
                         ('workflow_run', {'id': 12, 'head_sha': CTX['workflow_commit']})]:
            reader.get.return_value = ReadResponse(dict(row, **{key: bad}), {})
            with self.subTest(key=key), self.assertRaises(ValueError):
                proof.verify_artifact(reader, value, '55', 'f' * 64)

    def test_workflow_dispatch_only_main_code_job_scoped_permissions(self):
        root = Path(__file__).resolve().parents[3]
        text = (root / proof.WORKFLOW).read_text()
        trigger = text.split('\non:\n', 1)[1].split('\npermissions:', 1)[0]
        import re
        self.assertEqual(re.findall(r'^  ([a-z_]+):', trigger, re.MULTILINE), ['workflow_dispatch'])
        self.assertIn('\npermissions: {}\n', text)
        jobs = text.split('\njobs:\n', 1)[1]
        self.assertEqual(re.findall(r'^  ([a-z-]+):', jobs, re.MULTILINE), [proof.JOB])
        permissions = jobs.split('    permissions:\n', 1)[1].split('    env:', 1)[0]
        self.assertEqual(permissions, '      contents: read\n      actions: read\n      pull-requests: write\n')
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertIn('persist-credentials: false', text)
        upload_index = text.index('id: attempt')
        post_index = text.index('run: python -m automation.command_bus.blue_work_wake_proof post')
        self.assertLess(upload_index, post_index)
        self.assertIn('if-no-files-found: error', text[upload_index:post_index])
        self.assertNotIn('pull_request.head', text)
        self.assertNotIn('secrets.', text)
        self.assertNotIn('workflow_call:', text)
        static = (root / '.github/workflows/blue-work-reconcile-static.yml').read_text()
        self.assertNotIn('blue_work_wake_proof post', static)

    def test_run_origin_and_complete_history_reject_prior_or_rerun(self):
        a = authorization()
        run = dict(id=11, run_attempt=1, head_sha=CTX['workflow_commit'], head_branch='main',
                   event='workflow_dispatch', path=proof.WORKFLOW,
                   repository={'full_name': proof.EXPECTED_REPOSITORY},
                   actor={'id': a['approved_actor_id'], 'login': a['approved_actor_login']},
                   triggering_actor={'id': a['approved_actor_id'], 'login': a['approved_actor_login']})
        job = {'id': 22, 'name': proof.JOB, 'head_sha': CTX['workflow_commit'], 'run_attempt': 1, 'status': 'in_progress'}
        reader = Mock()
        reader.get.return_value = ReadResponse(run, {})
        with patch.object(proof, 'read_all', side_effect=[[run], [job]]):
            self.assertEqual(proof.check_run(reader, CTX, a), 22)
        for key, bad in [('event', 'pull_request'), ('head_branch', 'evil'), ('head_sha', HEAD),
                         ('path', 'other.yml'), ('run_attempt', 2),
                         ('actor', {'id': 1, 'login': a['approved_actor_login']})]:
            reader.get.return_value = ReadResponse(dict(run, **{key: bad}), {})
            with self.subTest(key=key), self.assertRaises(ValueError):
                proof.check_run(reader, CTX, a)
        reader.get.return_value = ReadResponse(run, {})
        for history in ([], [run, dict(run, id=12)], [dict(run, run_attempt=2)]):
            with patch.object(proof, 'read_all', return_value=history), self.assertRaises(ValueError):
                proof.check_run(reader, CTX, a)
        for jobs in ([], [job, dict(job, id=23)], [dict(job, status='completed')]):
            with patch.object(proof, 'read_all', side_effect=[[run], jobs]), self.assertRaises(ValueError):
                proof.check_run(reader, CTX, a)

    def test_pr_branch_and_tree_binding_rejects_drift_and_other_repository(self):
        pr = {'number': 172, 'state': 'open', 'merged': False,
              'head': {'sha': HEAD, 'ref': TARGET['branch'], 'repo': {'full_name': proof.EXPECTED_REPOSITORY}}}
        reader = Mock()
        reader.get.side_effect = [ReadResponse({'object': {'sha': HEAD}}, {}),
                                  ReadResponse({'sha': HEAD, 'tree': {'sha': TREE}}, {})]
        self.assertEqual(proof._pr_binding(reader, pr), TARGET)
        reader.get.side_effect = [ReadResponse({'object': {'sha': CARRIER}}, {})]
        with self.assertRaises(ValueError):
            proof._pr_binding(reader, pr)
        changed = deepcopy(pr)
        changed['head']['repo']['full_name'] = 'another/repository'
        with self.assertRaises(ValueError):
            proof._pr_binding(reader, changed)

    def test_post_absent_readback_remains_unknown_with_exactly_one_send(self):
        value = attempt()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'attempt.json').write_text(json.dumps(value))
            poster = Mock()
            with patch.object(proof, 'verify_artifact', return_value={'id': 55}), \
                 patch.object(proof, 'check_run', return_value=22), patch.object(proof, 'collect', return_value=SNAPSHOT), \
                 patch.object(proof, 'read_all', return_value=[]):
                result = proof.submit_once(Mock(), poster, authorization(), CTX, output, '55', 'f' * 64, NOW)
            self.assertEqual(result['status'], 'UNKNOWN')
            self.assertEqual(poster.post.call_count, 1)
            self.assertIsNone(result['receipt'])

    def test_no_redirect_or_credential_forwarding(self):
        with self.assertRaises(ValueError):
            proof._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.example/')

    def test_attempt_collection_drift_never_writes_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new'
            with patch.object(proof, 'check_run', return_value=22), \
                 patch.object(proof, 'collect', side_effect=[SNAPSHOT, dict(SNAPSHOT, worker_generation=2)]), self.assertRaises(ValueError):
                proof.create_attempt(Mock(), authorization(), CTX, NOW, output)
            self.assertFalse(output.exists())

    def test_collect_composes_existing_snapshot_and_rejects_each_fresh_boundary(self):
        for failure in ('none', 'main', 'workflow', 'authorization', 'generation', 'tree', 'duplicate',
                        'cross-lane', 'final-target', 'final-records'):
            with self.subTest(failure=failure):
                a = authorization()
                ctx = dict(CTX, workflow_blob=proof.blob(b'vetted workflow'))
                carrier = {'number': 167, 'state': 'open', 'merged': False,
                           'head': {'sha': CARRIER, 'ref': 'cloud-work/carrier-blue-v1',
                                    'repo': {'full_name': proof.EXPECTED_REPOSITORY}}}
                target = {'number': 172, 'state': 'open', 'merged': False,
                          'head': {'sha': HEAD, 'ref': TARGET['branch'], 'repo': {'full_name': proof.EXPECTED_REPOSITORY}}}
                state = {'active_generation': 2 if failure == 'generation' else 1,
                         'replacement_proof_pr': 172, 'replacement_proof_branch': TARGET['branch']}
                reviews = [review(attempt())] if failure == 'duplicate' else []
                lane = SimpleNamespace(carrier_pr=carrier, result_pr=target, worker_state=state, reviews=reviews, comments=[])
                def get(url):
                    if url.endswith('/git/ref/heads/main'):
                        data = {'object': {'sha': HEAD if failure == 'main' else ctx['workflow_commit']}}
                    elif '/git/ref/heads/' in url:
                        data = {'object': {'sha': HEAD if url.endswith(TARGET['branch']) else CARRIER}}
                    elif '/git/commits/' in url:
                        sha = url.rsplit('/', 1)[1]
                        tree = TREE if sha == HEAD else 'f' * 40
                        data = {'sha': sha, 'tree': {'sha': CARRIER if failure == 'tree' and sha == HEAD else tree}}
                    elif url.endswith('/pulls/172'):
                        data = deepcopy(target)
                        if failure == 'final-target':
                            data['head']['sha'] = CARRIER
                    elif url.endswith('/pulls/167'):
                        data = carrier
                    else:
                        raise AssertionError(url)
                    return ReadResponse(data, {})
                def content(reader, path, ref):
                    if path == proof.WORKFLOW:
                        return 'wrong workflow' if failure == 'workflow' else 'vetted workflow'
                    if path == proof.AUTHORIZATION:
                        return '{}' if failure == 'authorization' else json.dumps(a, indent=2) + '\n'
                    return 'verified existing protocol'
                def all_rows(reader, url, **kwargs):
                    if '/pulls?state=open' in url:
                        return [{'number': n, 'state': 'open', 'merged_at': None, 'labels': [{'name': 'cloud-' + color}]}
                                for n, color in [(167, 'blue'), (165, 'yellow'), (166, 'green'), (171, 'red')]]
                    if failure == 'cross-lane' and '/pulls/166/reviews' in url:
                        return [{'id': 99, 'body': '[CW_GREEN_V1]\n' + json.dumps({'command_id': a['proof_id']})}]
                    if failure == 'final-records' and '/pulls/167/reviews' in url:
                        return [review(attempt())]
                    return []
                reader = Mock()
                reader.get.side_effect = get
                with patch.object(proof, 'collect_lane_snapshot', return_value=lane), \
                     patch.object(proof, 'content_at', side_effect=content), patch.object(proof, 'read_all', side_effect=all_rows):
                    if failure == 'none':
                        result = proof.collect(reader, ctx, a, NOW)
                        self.assertEqual(result['target'], TARGET)
                        self.assertEqual(result['carrier']['head'], CARRIER)
                    else:
                        with self.assertRaises(ValueError):
                            proof.collect(reader, ctx, a, NOW)


if __name__ == '__main__':
    unittest.main()
