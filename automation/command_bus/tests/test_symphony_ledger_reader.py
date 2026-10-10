import base64
import json
import unittest
from urllib.parse import unquote

from ..symphony_ledger_reader import ReadOnlyLedgerContentsClient
from ..symphony_git_adoption import _git_oid
from ..symphony_attempt_store import GitHubAutonomousAttemptStore
from .test_symphony_attempt_store import intent, store

BRANCH = 'proof/ledger'
HEAD = 'a' * 40


class RecordedGET:
    def __init__(self, files):
        self.files = files
        self.calls = []
        self.bad_sha = False
        self.cap = False
        self.branch_head = HEAD
        self.duplicate = False

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        assert method == 'GET' and body is None
        if path == 'repos/fixture/council':
            return 200, {'full_name':'fixture/council', 'default_branch':'main'}
        if '/git/ref/' in path:
            return 200, {'ref':'refs/heads/'+BRANCH,'object':{'type':'commit','sha':self.branch_head}}
        suffix = path.split('/contents/', 1)[1]
        name, ref = suffix.split('?ref=')
        assert unquote(ref) == HEAD
        name = unquote(name)
        if name in self.files:
            raw = self.files[name].encode('utf-8')
            return 200, {'type':'file','sha':'b'*40 if self.bad_sha else _git_oid('blob',raw),
                         'content':base64.b64encode(raw).decode('ascii')}
        children = sorted({x[len(name)+1:].split('/')[0] for x in self.files if x.startswith(name+'/')})
        result = [{'type':'file' if name+'/'+x in self.files else 'dir','path':name+'/'+x} for x in children]
        if self.cap: result = result * 1000
        if self.duplicate: result = result * 2
        return (200,result) if result else (404,None)


class LedgerReadTests(unittest.TestCase):
    def setup_client(self):
        mem, original = store()
        made = intent(original)
        original.append_started(campaign_id='campaign-1',attempt_id=made.attempt_id,provider_kind='codex',
                                provider_attempt_ref='worker-1',observation_source='LIVE_OBSERVATION')
        self.http = RecordedGET({p:c.text for p,c in mem.files.items()})
        self.client = ReadOnlyLedgerContentsClient(self.http,repository='fixture/council',branch=BRANCH,
                                                   default_branch='main',expected_head=HEAD)
        return made.attempt_id

    def test_original_store_recovers_unicode_start_without_write(self):
        attempt = self.setup_client()
        restored = GitHubAutonomousAttemptStore(self.client,write_branch=BRANCH).restore('campaign-1',attempt)
        self.assertEqual(restored.state,'STARTED_UNRESOLVED')
        self.assertEqual(restored.started['provider_attempt_ref'],'worker-1')
        self.assertTrue(all(m == 'GET' and b is None for m,p,b in self.http.calls))
        p = 'symphony_attempts/unicode.json'; self.http.files[p] = json.dumps({'message':'航海日誌'},ensure_ascii=False)
        self.assertIn('航海日誌',self.client.get(p,BRANCH).text)

    def test_mutations_refused_before_transport(self):
        self.setup_client(); before = len(self.http.calls)
        for method in ('create','update'):
            with self.assertRaises(PermissionError): getattr(self.client,method)('anything')
        with self.assertRaises(PermissionError): self.client._request('PUT','anything',{})
        self.assertEqual(before,len(self.http.calls))

    def test_branch_move_does_not_mix_record_generations(self):
        self.setup_client(); self.http.branch_head = 'b'*40
        self.client.list('symphony_attempts/',BRANCH)
        self.assertTrue(all('?ref='+HEAD in p for m,p,b in self.http.calls if '/contents/' in p))
        with self.assertRaises(RuntimeError):
            ReadOnlyLedgerContentsClient(self.http,repository='fixture/council',branch=BRANCH,
                                         default_branch='main',expected_head=HEAD)

    def test_unsafe_scope_wrong_ref_default_rejected(self):
        self.setup_client(); before = len(self.http.calls)
        for p,ref in [('docs/private.json',BRANCH),('symphony_attempts/../x',BRANCH),
                      ('symphony_attempts/x','other'),('/symphony_attempts/x',BRANCH)]:
            with self.assertRaises(ValueError): self.client.get(p,ref)
        with self.assertRaises(ValueError):
            ReadOnlyLedgerContentsClient(self.http,repository='fixture/council',branch='main',
                                         default_branch='main',expected_head=HEAD)
        self.assertEqual(before,len(self.http.calls))

    def test_blob_tamper_is_not_a_valid_ledger(self):
        self.setup_client(); self.http.bad_sha = True
        with self.assertRaises(RuntimeError): self.client.list('symphony_attempts',BRANCH)

    def test_capped_or_duplicate_directory_fails_closed(self):
        self.setup_client(); self.http.cap = True
        with self.assertRaises(RuntimeError): self.client.list('symphony_attempts',BRANCH)
        self.http.cap = False; self.http.duplicate = True
        with self.assertRaises(RuntimeError): self.client.list('symphony_attempts',BRANCH)

    def test_missing_record_is_none(self):
        self.setup_client()
        self.assertIsNone(self.client.get('symphony_attempts/missing.json',BRANCH))

    def test_terminal_lineage_uses_original_store_validator(self):
        attempt = self.setup_client()
        files, original = store()
        made = intent(original)
        original.append_started(campaign_id='campaign-1',attempt_id=made.attempt_id,provider_kind='codex',
                                provider_attempt_ref='worker-1',observation_source='LIVE_OBSERVATION')
        original.append_terminal(campaign_id='campaign-1',attempt_id=made.attempt_id,result_id='terminal',
                                 outcome='UNKNOWN',model_started=True,unknown_class='RECOVERABLE_UNKNOWN')
        self.http.files = {p:c.text for p,c in files.files.items()}
        original_reader = GitHubAutonomousAttemptStore(self.client,write_branch=BRANCH)
        restored = original_reader.restore('campaign-1',attempt)
        self.assertEqual(restored.state,'TERMINAL')
        self.assertEqual(restored.terminal['outcome'],'UNKNOWN')
        self.assertEqual(len(original_reader.list_campaign('campaign-1')),1)

    def test_directory_escape_is_rejected_before_followup_get(self):
        self.setup_client()
        request = self.http.request
        def escape(method,path,body=None):
            status,result = request(method,path,body)
            if '/contents/' in path and isinstance(result,list):
                return 200,[{'type':'file','path':'docs/outside.json'}]
            return status,result
        self.http.request = escape
        before = len(self.http.calls)
        with self.assertRaises(RuntimeError): self.client.list('symphony_attempts',BRANCH)
        self.assertEqual(len(self.http.calls),before+1)
