"""Generation-2 STATIC proof; reuse existing fakes, never a live sender."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from automation.command_bus import blue_work_wake_proof as proof
from automation.command_bus import github_readonly as github
from automation.command_bus.cloud_work_snapshot import collect_lane_snapshot
from .test_cloud_work_snapshot import SnapshotReader
from .test_blue_work_wake_proof import authorization, attempt, review, receipt, CTX, NOW, SNAPSHOT, TARGET

ROOT_DIR = Path(__file__).resolve().parents[3]
CANDIDATE = 'docs/BLUE_BWJ4_FOLLOWUP_AUTHORIZATION_CANDIDATE.json'


def followup():
    value = json.loads((ROOT_DIR / CANDIDATE).read_text())
    value['approved'] = True  # Test-only simulation, not repository authorization.
    return value


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.auth = followup()
        old = proof.CONSUMED_PROOF
        self.old = dict(id=old['run_id'], head_sha=old['head_sha'], run_attempt=1, path=proof.WORKFLOW,
                        event='workflow_dispatch', head_branch='main', status='completed', conclusion='failure',
                        repository={'full_name': proof.EXPECTED_REPOSITORY},
                        actor={'id': 20355232, 'login': 'kamiyusense'},
                        triggering_actor={'id': 20355232, 'login': 'kamiyusense'})
        self.current = dict(self.old, id=CTX['run_id'], head_sha=CTX['workflow_commit'], status='in_progress', conclusion=None)
        expected = {'Fresh gates and secret-free ATTEMPTING record': 'failure',
                    'Make attempt durable BEFORE the single review POST': 'skipped',
                    'Verify artifact and final reread fence, POST at most once, GET readback': 'skipped'}
        self.job = dict(id=old['job_id'], run_id=old['run_id'], run_attempt=1, head_sha=old['head_sha'],
                        name=proof.JOB, status='completed', conclusion='failure',
                        steps=[dict(name=k, status='completed', conclusion=v) for k, v in expected.items()])
        self.reader = Mock()
        self.reader.get.return_value = github.ReadResponse(self.old, {})
        self.workflow = (ROOT_DIR / proof.WORKFLOW).read_text()

    def content(self, reader, path, ref):
        self.assertEqual(ref, proof.CONSUMED_PROOF['head_sha'])
        return self.workflow if path == proof.WORKFLOW else json.dumps({'proof_id': proof.CONSUMED_PROOF['proof_id']})

    def check(self, history=None, jobs=None, artifacts=None):
        with patch.object(proof, 'content_at', side_effect=self.content), \
             patch.object(proof, 'read_all', side_effect=[jobs if jobs is not None else [self.job],
                                                        artifacts if artifacts is not None else []]):
            return proof.check_activation_history(self.reader, history or [self.old, self.current], CTX, self.auth)

    def test_candidate_is_disabled_and_cannot_be_loaded_as_authorization(self):
        candidate = json.loads((ROOT_DIR / CANDIDATE).read_text())
        self.assertIs(candidate['approved'], False)
        self.assertIsNone(candidate['approval_expires_at'])
        self.assertEqual(candidate['worker_generation'], 1)
        self.assertEqual(candidate['proof_generation'], 2)
        with self.assertRaises(ValueError):
            proof.load_authorization(ROOT_DIR / CANDIDATE, NOW)

    def test_exact_consumed_failure_is_preserved_for_separate_generation(self):
        self.check()
        self.assertNotEqual(self.auth['proof_id'], proof.CONSUMED_PROOF['proof_id'])
        self.assertIs(proof.CONSUMED_PROOF['activation_consumed'], True)

    def test_full_check_run_uses_retained_failure_and_exact_running_new_job(self):
        current_job = dict(id=22, name=proof.JOB, run_attempt=1, head_sha=CTX['workflow_commit'], status='in_progress')
        self.reader.get.side_effect = [github.ReadResponse(self.current, {}), github.ReadResponse(self.old, {})]
        with patch.object(proof, 'content_at', side_effect=self.content), \
             patch.object(proof, 'read_all', side_effect=[[self.old, self.current], [self.job], [], [current_job]]):
            self.assertEqual(proof.check_run(self.reader, CTX, self.auth), 22)

    def test_old_default_authorization_still_blocks_two_runs(self):
        with self.assertRaises(ValueError):
            proof.check_activation_history(self.reader, [self.old, self.current], CTX, authorization())

    def test_same_id_unapproved_wrong_generation_or_altered_history_cannot_bypass(self):
        for changes in ({'proof_id': proof.CONSUMED_PROOF['proof_id']}, {'proof_id': None}, {'approved': False},
                        {'proof_generation': True}, {'proof_generation': 3}, {'prior_terminal_runs': []},
                        {'prior_terminal_runs': [dict(proof.CONSUMED_PROOF, activation_consumed=False)]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.auth = dict(followup(), **changes)
                self.check()

    def test_missing_unknown_duplicate_extra_or_rerun_history_stops(self):
        for rows in ([self.current], [self.old], [self.old, self.current, dict(self.current, id=99)],
                     [self.old, dict(self.old)], [dict(self.old, run_attempt=2), self.current]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.check(history=rows)

    def test_old_run_terminal_origin_actor_head_or_repository_drift_stops(self):
        for key, value in [('conclusion', 'success'), ('status', 'in_progress'), ('run_attempt', 2),
                           ('head_sha', 'a'*40), ('head_branch', 'other'), ('event', 'push'),
                           ('path', 'other.yml'), ('repository', {'full_name': 'wrong/repo'}),
                           ('actor', {'id': 1, 'login': 'kamiyusense'})]:
            self.reader.get.return_value = github.ReadResponse(dict(self.old, **{key: value}), {})
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check()

    def test_old_job_post_or_artifact_uncertainty_stops(self):
        for changed in (dict(self.job, id=1), dict(self.job, run_attempt=2), dict(self.job, steps=[]),
                        dict(self.job, steps=[dict(x, conclusion='success') for x in self.job['steps']])):
            with self.assertRaises(ValueError):
                self.check(jobs=[changed])
        with self.assertRaises(ValueError):
            self.check(artifacts=[{'id': 99}])

    def test_old_auth_identity_and_workflow_blob_cannot_be_substituted(self):
        for content in ('{}', 'changed code'):
            with patch.object(proof, 'content_at', return_value=content), \
                 patch.object(proof, 'read_all'), self.assertRaises(ValueError):
                proof.check_activation_history(self.reader, [self.old, self.current], CTX, self.auth)

    def test_live_failure_shape_old_guard_rejects_new_guard_collects_snapshot(self):
        fixture = json.loads((ROOT_DIR / 'automation/command_bus/tests/fixtures/blue_bwj4_canonical_pagination.json').read_text())
        def reader():
            r = SnapshotReader()
            r.pages[fixture['first_url']] = github.ReadResponse([], {'Link': fixture['link']})
            r.pages[fixture['next_url']] = github.ReadResponse([r.carrier], {})
            return r
        old = reader()
        with patch.object(github, 'REPOSITORY_PATH_PREFIXES', (proof.ROOT.split('api.github.com')[1]+'/',)), \
             self.assertRaisesRegex(ValueError, 'scope violation'):
            collect_lane_snapshot(old, lane='blue', result_number=42)
        self.assertEqual(old.calls, [fixture['first_url']])
        new = reader()
        value = collect_lane_snapshot(new, lane='blue', result_number=42)
        self.assertEqual(value.worker_state['active_generation'], 1)
        self.assertEqual(new.calls.count(fixture['next_url']), 2)  # Complete discovery + final fence.

    def test_canonical_endpoint_filter_host_scheme_credentials_and_encoded_path_drift(self):
        first = proof.ROOT + '/pulls?state=open&per_page=100'
        canonical = 'https://api.github.com/repositories/1378815294/pulls?state=open&per_page=100&page=2'
        for bad in (canonical.replace('/pulls?', '/issues?'), canonical.replace('state=open', 'state=closed'),
                    canonical.replace('1378815294', '1'), canonical.replace('https:', 'http:'),
                    canonical.replace('api.github.com', 'token@api.github.com'),
                    canonical.replace('api.github.com', 'evil.example'), canonical.replace('/pulls?', '/%70ulls?')):
            r = SnapshotReader()
            r.pages[first] = github.ReadResponse([], {'link': f'<{bad}>; rel="next"'})
            with self.subTest(url=bad), self.assertRaises(ValueError):
                github.read_all(r, first)
            self.assertEqual(r.calls, [first])

    def test_fake_full_handoff_receipt_missing_late_and_terminal_are_not_wake_authority(self):
        self.check()
        value = attempt()
        value['proof_id'] = self.auth['proof_id']
        a = dict(authorization(), proof_id=self.auth['proof_id'], proof_generation=2,
                 prior_terminal_runs=deepcopy(proof.CONSUMED_PROOF))
        a['prior_terminal_runs'] = [a['prior_terminal_runs']]
        value.update(proof_generation=2, prior_terminal_runs=a['prior_terminal_runs'])
        command, body = proof.make_command(a, SNAPSHOT, value['command']['expires_at'])
        value.update(command=command, review_body=body, review_body_sha256=proof.hashlib.sha256(body.encode()).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / 'attempt.json').write_text(json.dumps(value))
            poster = Mock()
            bad = dict(value, proof_generation=1)
            (output / 'attempt.json').write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, 'generation/history'):
                proof.submit_once(Mock(), poster, a, CTX, output, '55', 'f'*64, NOW)
            poster.post.assert_not_called()
            (output / 'attempt.json').write_text(json.dumps(value))
            with patch.object(proof, 'verify_artifact', return_value={'id': 55}), \
                 patch.object(proof, 'check_run', return_value=22), patch.object(proof, 'collect', return_value=SNAPSHOT), \
                 patch.object(proof, 'read_all', return_value=[review(value)]):
                result = proof.submit_once(Mock(), poster, a, CTX, output, '55', 'f'*64, NOW)
                self.assertEqual(result['status'], 'REVIEW_VERIFIED_RECEIPT_PENDING')
                self.assertEqual(poster.post.call_count, 1)  # FAKE only; no HTTP sender constructed.
                with self.assertRaises(FileExistsError):
                    proof.submit_once(Mock(), poster, a, CTX, output, '55', 'f'*64, NOW)
                self.assertEqual(poster.post.call_count, 1)
            self.assertEqual(set(result[k] for k in proof.ZERO), {0})
            self.assertEqual(proof.inspect_receipt([], value, review(value), TARGET, NOW, receipt(value)['user'])['status'], 'UNKNOWN')
            terminal = receipt(value)
            self.assertEqual(proof.inspect_receipt([terminal], value, review(value), TARGET, NOW.replace(minute=26), terminal['user'])['status'], 'RECEIPT_BINDING_VALIDATED')
            with self.assertRaises(ValueError):
                proof.inspect_receipt([terminal, dict(terminal, id=45)], value, review(value), TARGET, NOW.replace(minute=26), terminal['user'])


if __name__ == '__main__':
    unittest.main()
