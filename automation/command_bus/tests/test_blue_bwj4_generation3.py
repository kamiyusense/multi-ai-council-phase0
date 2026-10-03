"""Third separately approved proof: exact consumed history and offline faults."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from automation.command_bus import blue_work_wake_proof as proof
from automation.command_bus.github_readonly import ReadResponse
from .test_blue_work_wake_proof import authorization, review, receipt, CTX, NOW, SNAPSHOT, TARGET

ROOT_DIR = Path(__file__).resolve().parents[3]
CANDIDATE = 'docs/BLUE_BWJ4_GEN3_AUTHORIZATION_CANDIDATE.json'


def generation3():
    value = json.loads((ROOT_DIR / CANDIDATE).read_text())
    value.update(approved=True, approval_expires_at='2026-10-04T03:50:00Z', target=deepcopy(TARGET))
    return value


class Generation3Tests(unittest.TestCase):
    def setUp(self):
        self.auth = generation3()
        self.prior = [proof.CONSUMED_PROOF, proof.CONSUMED_PROOF_2]
        self.workflow = (ROOT_DIR / proof.WORKFLOW).read_text()
        self.runs, self.jobs = {}, {}
        for p in self.prior:
            self.runs[p['run_id']] = dict(id=p['run_id'], head_sha=p['head_sha'], run_attempt=1,
                path=proof.WORKFLOW, event='workflow_dispatch', head_branch='main', status='completed',
                conclusion='failure', repository={'full_name': proof.EXPECTED_REPOSITORY},
                actor={'id': 20355232, 'login': 'kamiyusense'},
                triggering_actor={'id': 20355232, 'login': 'kamiyusense'})
            steps = {'Fresh gates and secret-free ATTEMPTING record': 'failure',
                     'Make attempt durable BEFORE the single review POST': 'skipped',
                     'Verify artifact and final reread fence, POST at most once, GET readback': 'skipped'}
            self.jobs[p['run_id']] = dict(id=p['job_id'], run_id=p['run_id'], head_sha=p['head_sha'],
                run_attempt=1, name=proof.JOB, status='completed', conclusion='failure',
                steps=[dict(name=k, status='completed', conclusion=v) for k, v in steps.items()])
        self.current = dict(id=CTX['run_id'], run_attempt=1)
        self.history = list(self.runs.values()) + [self.current]
        self.reader = Mock()
        self.reader.get.side_effect = lambda url: ReadResponse(self.runs[int(url.rsplit('/', 1)[1])], {})

    def content(self, reader, path, ref):
        p = next(p for p in self.prior if p['head_sha'] == ref)
        if path == proof.WORKFLOW:
            return self.workflow
        old_auth = dict(proof_id=p['proof_id'])
        if p['proof_generation'] == 2:
            old_auth.update(proof_generation=2, prior_terminal_runs=[proof.CONSUMED_PROOF])
        return json.dumps(old_auth)

    def pages(self, reader, url, **kwargs):
        run_id = int(url.split('/runs/', 1)[1].split('/', 1)[0])
        return [self.jobs[run_id]] if '/jobs?' in url else []

    def check(self, history=None):
        with patch.object(proof, 'content_at', side_effect=self.content), \
             patch.object(proof, 'read_all', side_effect=self.pages):
            proof.check_activation_history(self.reader, self.history if history is None else history, CTX, self.auth)

    def test_disabled_candidate_is_not_dispatch_authority(self):
        candidate = json.loads((ROOT_DIR / CANDIDATE).read_text())
        self.assertIs(candidate['approved'], False)
        self.assertIsNone(candidate['approval_expires_at'])
        self.assertEqual((candidate['proof_generation'], candidate['worker_generation']), (3, 1))
        with self.assertRaises(ValueError):
            proof.load_authorization(ROOT_DIR / CANDIDATE, NOW)

    def test_exact_two_consumed_failures_retained_distinct_from_new_identity(self):
        self.check()
        self.assertEqual(self.auth['prior_terminal_runs'], self.prior)
        self.assertTrue(all(p['activation_consumed'] for p in self.prior))
        self.assertNotIn(self.auth['proof_id'], {p['proof_id'] for p in self.prior})
        self.assertEqual(self.reader.get.call_count, 2)

    def test_missing_duplicate_extra_rerun_and_new_replay_history_rejected(self):
        variants = [self.history[1:], self.history[:-1], [self.history[0], self.history[0], self.current],
                    self.history + [dict(self.current, id=99)],
                    [dict(r, run_attempt=2) if r['id'] == self.prior[1]['run_id'] else r for r in self.history],
                    [dict(r, run_attempt=2) if r['id'] == CTX['run_id'] else r for r in self.history]]
        for history in variants:
            with self.subTest(history=history), self.assertRaises(ValueError):
                self.check(history)

    def test_old_identity_or_incomplete_changed_consumed_lineage_rejected(self):
        for changes in ({'proof_id': p['proof_id']} for p in self.prior):
            self.auth = dict(generation3(), **changes)
            with self.assertRaises(ValueError):
                self.check()
        for changes in ({'prior_terminal_runs': self.prior[:1]}, {'prior_terminal_runs': self.prior[::-1]},
                        {'prior_terminal_runs': [self.prior[0], dict(self.prior[1], activation_consumed=False)]},
                        {'proof_generation': True}, {'proof_generation': 4}, {'approved': False}):
            self.auth = dict(generation3(), **changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.check()

    def test_each_old_run_origin_terminal_head_or_actor_drift_rejected(self):
        for p in self.prior:
            original = deepcopy(self.runs[p['run_id']])
            for key, bad in [('conclusion', 'success'), ('head_sha', 'a'*40), ('run_attempt', 2),
                             ('event', 'push'), ('repository', {'full_name': 'wrong/repo'}),
                             ('triggering_actor', {'id': 1, 'login': 'kamiyusense'})]:
                self.runs[p['run_id']] = dict(original, **{key: bad})
                with self.subTest(proof=p['proof_generation'], key=key), self.assertRaises(ValueError):
                    self.check()
            self.runs[p['run_id']] = original

    def test_each_old_job_or_post_step_uncertainty_rejected(self):
        for p in self.prior:
            original = deepcopy(self.jobs[p['run_id']])
            for changed in (dict(original, id=1), dict(original, run_attempt=2), dict(original, steps=[]),
                            dict(original, steps=[dict(s, conclusion='success') for s in original['steps']])):
                self.jobs[p['run_id']] = changed
                with self.assertRaises(ValueError):
                    self.check()
            self.jobs[p['run_id']] = original

    def test_old_generation2_authorization_cannot_erase_generation1(self):
        def wrong(reader, path, ref):
            value = self.content(reader, path, ref)
            return json.dumps({'proof_id': proof.CONSUMED_PROOF_2['proof_id'], 'proof_generation': 2,
                               'prior_terminal_runs': []}) if path == proof.AUTHORIZATION and ref == self.prior[1]['head_sha'] else value
        with patch.object(proof, 'content_at', side_effect=wrong), \
             patch.object(proof, 'read_all', side_effect=self.pages), self.assertRaisesRegex(ValueError, 'lineage drift'):
            proof.check_activation_history(self.reader, self.history, CTX, self.auth)

    def collect_with(self, main_reads=None, target=None, carrier=None, generation=1, records=None):
        ctx = dict(CTX, workflow_blob=proof.blob(self.workflow.encode()))
        main = main_reads or [ctx['workflow_commit'], ctx['workflow_commit']]
        reader = Mock()
        reader.get.side_effect = [ReadResponse({'object': {'sha': main[0]}}, {}),
                                 ReadResponse({'tree': {'sha': SNAPSHOT['main_tree']}}, {}),
                                 ReadResponse({'object': {'sha': main[1]}}, {}), ReadResponse({}, {}), ReadResponse({}, {})]
        state = dict(active_generation=generation, replacement_proof_pr=172, replacement_proof_branch=TARGET['branch'])
        lane = SimpleNamespace(carrier_pr={}, result_pr={}, worker_state=state, reviews=[], comments=[])
        def content(reader, path, ref):
            return self.workflow if path == proof.WORKFLOW else json.dumps(self.auth, indent=2)+'\n' if path == proof.AUTHORIZATION else 'protocol'
        bindings = [SNAPSHOT['carrier'], TARGET, target or TARGET, carrier or SNAPSHOT['carrier']]
        with patch.object(proof, 'content_at', side_effect=content), patch.object(proof, 'collect_lane_snapshot', return_value=lane), \
             patch.object(proof, '_pr_binding', side_effect=bindings), patch.object(proof, 'discover_carrier', return_value={'number': 999}), \
             patch.object(proof, 'read_all', return_value=[]), patch.object(proof, '_records', return_value=(records or set(), set())):
            return proof.collect(reader, ctx, self.auth, NOW)

    def test_exact_generation2_final_main_drift_failure_fixture_still_stops(self):
        self.assertEqual(self.collect_with()['worker_generation'], 1)
        with self.assertRaisesRegex(ValueError, 'final main drift'):
            self.collect_with(main_reads=[CTX['workflow_commit'], '9'*40])

    def test_initial_main_target_carrier_worker_and_old_record_drift_stop(self):
        variants = [dict(main_reads=['9'*40, '9'*40]), dict(target=dict(TARGET, head='9'*40)),
                    dict(carrier=dict(SNAPSHOT['carrier'], head='9'*40)), dict(generation=2)]
        variants += [dict(records={p['proof_id']}) for p in self.prior]
        variants += [dict(records={self.auth['proof_id']})]
        for kwargs in variants:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.collect_with(**kwargs)

    def test_preflight_failure_or_between_snapshot_main_drift_creates_no_attempt_and_no_post(self):
        for snapshots in ([ValueError('current main drift')], [SNAPSHOT, ValueError('final main drift')],
                          [SNAPSHOT, dict(SNAPSHOT, main_head='9'*40)]):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory)/'attempt'
                poster = Mock()
                with patch.object(proof, 'check_run', return_value=22), patch.object(proof, 'collect', side_effect=snapshots), \
                     patch.object(proof, 'ReviewPostOnce', return_value=poster), self.assertRaises(ValueError):
                    proof.create_attempt(Mock(), self.auth, CTX, NOW, output)
                self.assertFalse(output.exists())
                poster.post.assert_not_called()

    def test_mock_durable_attempt_fake_review_wake_receipt_and_no_replay(self):
        self.check()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'attempt'
            with patch.object(proof, 'check_run', return_value=22), patch.object(proof, 'collect', return_value=SNAPSHOT):
                value = proof.create_attempt(Mock(), self.auth, CTX, NOW, output)
            self.assertEqual((value['proof_generation'], value['snapshot']['worker_generation']), (3, 1))
            self.assertEqual(value['prior_terminal_runs'], self.prior)
            poster = Mock()
            with patch.object(proof, 'verify_artifact', return_value={'id': 55}), patch.object(proof, 'check_run', return_value=22), \
                 patch.object(proof, 'collect', return_value=SNAPSHOT), patch.object(proof, 'read_all', return_value=[review(value)]):
                result = proof.submit_once(Mock(), poster, self.auth, CTX, output, '55', 'f'*64, NOW)
                self.assertEqual(result['status'], 'REVIEW_VERIFIED_RECEIPT_PENDING')
                with self.assertRaises(FileExistsError):
                    proof.submit_once(Mock(), poster, self.auth, CTX, output, '55', 'f'*64, NOW)
            self.assertEqual(poster.post.call_count, 1)  # FAKE only.
            self.assertEqual({result[k] for k in proof.ZERO}, {0})
            terminal = receipt(value)
            args = (value, review(value), TARGET, NOW.replace(minute=26), terminal['user'])
            self.assertEqual(proof.inspect_receipt([], *args)['status'], 'UNKNOWN')
            self.assertEqual(proof.inspect_receipt([terminal], *args)['status'], 'RECEIPT_BINDING_VALIDATED')
            with self.assertRaises(ValueError):
                proof.inspect_receipt([terminal, dict(terminal, id=45)], *args)
            with self.assertRaises(ValueError):
                proof.verify_review([review(value), dict(review(value), id=34)], value)

    def test_attempt_history_tamper_or_final_drift_makes_zero_fake_post_calls(self):
        for failure in ('history', 'main'):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory)/'attempt'
                with patch.object(proof, 'check_run', return_value=22), patch.object(proof, 'collect', return_value=SNAPSHOT):
                    value = proof.create_attempt(Mock(), self.auth, CTX, NOW, output)
                if failure == 'history':
                    value['prior_terminal_runs'] = self.prior[:1]
                    (output/'attempt.json').write_text(json.dumps(value))
                poster = Mock()
                with patch.object(proof, 'verify_artifact', return_value={'id': 55}), patch.object(proof, 'check_run', return_value=22), \
                     patch.object(proof, 'collect', side_effect=ValueError('final main drift')), self.assertRaises(ValueError):
                    proof.submit_once(Mock(), poster, self.auth, CTX, output, '55', 'f'*64, NOW)
                poster.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
