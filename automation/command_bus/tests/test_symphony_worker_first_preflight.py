"""Bounded worker-only preflight; never uses a model, network or GitHub writer."""
import os
from pathlib import Path
import tempfile
import json
import sys
import unittest
from unittest.mock import patch

from ..scripts import symphony_worker_first_preflight as subject

HEAD = 'a' * 40
BRANCH = 'codex/symphony-worker-proof-issue-9999'
GOOD = {'status': 'DONE', 'thread_starts': 0, 'model_dispatch': 0,
        'route': {'subscription_route_compatible': True,
                  'provenance': 'SAME_PROCESS_FRESH_READ_ONLY_NOT_ADMISSION'}}


class WorkerOnlyPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.work = base / 'work'; self.work.mkdir()
        self.scratch = base / 'scratch'; self.scratch.mkdir(mode=0o700)
        self.auth = base / 'auth'; self.auth.mkdir(mode=0o700)
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.auth),
                                          'OPENAI_API_KEY': ''}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        os.environ.pop('OPENAI_API_KEY')
        self.git = patch.object(subject, '_git', side_effect=[BRANCH, HEAD, '', BRANCH, HEAD, ''])
        self.fs = patch.object(subject, '_native_linux_state', return_value=True)
        self.probe = patch.object(subject, '_codex_readonly_probe', return_value=GOOD)
        self.git_mock = self.git.start(); self.addCleanup(self.git.stop)
        self.fs.start(); self.addCleanup(self.fs.stop)
        self.probe_mock = self.probe.start(); self.addCleanup(self.probe.stop)

    def check(self, **kwargs):
        return subject.preflight(workspace=kwargs.get('workspace', self.work),
                                 expected_head=kwargs.get('expected_head', HEAD),
                                 scratch_parent=kwargs.get('scratch_parent', self.scratch),
                                 executable=kwargs.get('executable', 'codex'))

    def test_clean_worker_proof_without_github_permissions(self):
        result = self.check()
        self.assertEqual(result['status'], 'PASS_READONLY_NOT_ADMISSION')
        self.assertFalse(result['worker_only_readonly_requires_branch_protection'])
        self.assertEqual(result['publication_rules_status'], 'NOT_EVALUATED')
        self.assertFalse(result['live_authorized'])
        self.assertEqual(result['model_turns'], 0)
        self.assertEqual(result['github_writes'], 0)
        self.assertEqual(result['thread_starts'], 0)
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(self.probe_mock.call_count, 1)

    def test_github_branch_rules_403_is_not_queried_or_needed_for_preflight(self):
        result = self.check()
        self.assertEqual(result['status'], 'PASS_READONLY_NOT_ADMISSION')
        self.assertNotIn('rules_complete', result)
        self.assertEqual(self.git_mock.call_count, 6)

    def test_blocks_wrong_head_before_codex(self):
        self.git_mock.side_effect = [BRANCH, 'b'*40]
        self.assertEqual(self.check()['status'], 'BLOCKED')
        self.probe_mock.assert_not_called()

    def test_blocks_main_and_dirty_workspace(self):
        for observations in [('main',), (BRANCH, HEAD, ' M README.md')]:
            self.git_mock.reset_mock(side_effect=True)
            self.git_mock.side_effect = observations
            self.assertEqual(self.check()['status'], 'BLOCKED')
        self.probe_mock.assert_not_called()

    def test_blocks_metered_parent_env(self):
        os.environ['OPENAI_API_KEY'] = 'STATIC_NOT_A_CREDENTIAL'
        self.assertEqual(self.check()['status'], 'BLOCKED')
        self.probe_mock.assert_not_called()

    def test_blocks_overlap_and_symlink(self):
        self.assertEqual(self.check(scratch_parent=self.work)['status'], 'BLOCKED')
        link = self.scratch.parent / 'linked'
        link.symlink_to(self.scratch, target_is_directory=True)
        self.assertEqual(self.check(scratch_parent=link)['status'], 'BLOCKED')
        self.probe_mock.assert_not_called()

    def test_blocks_insecure_scratch(self):
        self.scratch.chmod(0o755)
        self.assertEqual(self.check()['status'], 'BLOCKED')
        self.probe_mock.assert_not_called()

    def test_native_storage_unknown_fails_closed(self):
        self.fs.stop()
        with patch.object(subject, '_native_linux_state', return_value=False):
            self.assertEqual(self.check()['status'], 'BLOCKED')
        self.probe_mock.assert_not_called()

    def test_no_false_pass_when_readonly_probe_fails_or_misreports_start(self):
        for reply in ({'status': 'BLOCKED'}, {**GOOD, 'model_dispatch': 1},
                      {**GOOD, 'route': {'subscription_route_compatible': False}},
                      {**GOOD, 'thread_starts': 1}):
            self.git_mock.side_effect = [BRANCH, HEAD, '']
            self.probe_mock.return_value = reply
            self.assertEqual(self.check()['status'], 'BLOCKED')

    def test_workspace_changes_during_probe_never_report_fresh_pass(self):
        for after in (('main',), (BRANCH, 'b' * 40),
                      (BRANCH, HEAD, '?? arrived-during-probe.txt')):
            self.git_mock.reset_mock(side_effect=True)
            self.git_mock.side_effect = [BRANCH, HEAD, '', *after]
            self.probe_mock.reset_mock()
            result = self.check()
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertFalse(result['local_branch_verified'])
            self.probe_mock.assert_called_once()
            self.assertEqual(result['model_turns'], 0)
            self.assertEqual(result['thread_starts'], 0)
            self.assertEqual(list(self.scratch.iterdir()), [])

    def test_parent_metered_selector_added_during_probe_blocks_readonly_pass(self):
        def rebind(**unused):
            os.environ['OPENAI_API_KEY'] = 'STATIC_NOT_A_CREDENTIAL'
            return GOOD
        self.probe_mock.side_effect = rebind
        result = self.check()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(result['local_branch_verified'])
        self.assertEqual(self.git_mock.call_count, 3)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_auth_or_storage_rebound_during_probe_blocks_readonly_pass(self):
        other = self.auth.parent / 'other-auth'
        other.mkdir(mode=0o700)
        def rebind(**unused):
            os.environ['CODEX_HOME'] = str(other)
            return GOOD
        self.probe_mock.side_effect = rebind
        self.assertEqual(self.check()['status'], 'BLOCKED')
        self.assertEqual(self.git_mock.call_count, 3)
        os.environ['CODEX_HOME'] = str(self.auth)
        self.probe_mock.side_effect = None
        self.git_mock.reset_mock(side_effect=True)
        self.git_mock.side_effect = [BRANCH, HEAD, '']
        with patch.object(subject, '_native_linux_state', side_effect=[True, False]):
            result = self.check()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(result['local_branch_verified'])
        self.assertEqual(self.git_mock.call_count, 3)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_invalid_sha_and_executable_not_executed(self):
        for arguments in ({'expected_head': 'main'}, {'executable': 'curl'}, {'executable': 'codex.exe'}):
            self.assertEqual(self.check(**arguments)['status'], 'BLOCKED')
        self.git_mock.assert_not_called()
        self.probe_mock.assert_not_called()

    def test_actual_disposable_child_creates_private_files_without_shared_selectors(self):
        # Real JSONL subprocess, fake account only. No installed Codex is used.
        self.probe.stop()
        binary = self.auth.parent/'codex'
        binary.write_text('#!'+sys.executable+'\n'+'''import sys,json,os,pathlib
root=pathlib.Path(json.loads(sys.argv[sys.argv.index('-c')+1].split('=',1)[1]))
(root/'fixture-created').write_text('STATIC_ONLY')
blocked=['GH_TOKEN','CODEX_SQLITE_HOME','SYMPHONY_G5_OBSERVER_KEY_HEX']
(root/'child-env.json').write_text(json.dumps([k for k in blocked if k in os.environ]))
for line in sys.stdin:
 r=json.loads(line); method=r.get('method')
 with (root/'methods.jsonl').open('a') as out:out.write(json.dumps({'method':method})+'\\n')
 if 'id' not in r:continue
 result={'requiresOpenaiAuth':True,'account':{'type':'chatgpt'}} if method=='account/read' else {'config':{'model_provider':'openai'}} if method=='config/read' else {}
 print(json.dumps({'id':r['id'],'result':result}),flush=True)
''')
        binary.chmod(0o700)
        with patch.dict(os.environ,{'GH_TOKEN':'STATIC_AUTHORITY','CODEX_SQLITE_HOME':'STATIC_SHARED'}):
            reply=subject._codex_readonly_probe(workspace=self.work,sqlite_home=self.scratch,executable=str(binary))
        self.assertEqual(reply['status'],'DONE')
        self.assertEqual(json.loads((self.scratch/'child-env.json').read_text()),[])
        methods=[json.loads(s)['method'] for s in (self.scratch/'methods.jsonl').read_text().splitlines()]
        self.assertEqual(methods,['initialize','initialized','account/read','config/read'])
        self.assertTrue(all(p.stat().st_mode&0o777==0o600 for p in self.scratch.iterdir()))


if __name__ == '__main__':
    unittest.main()
