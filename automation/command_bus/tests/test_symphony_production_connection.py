"""Production seams with explicit STATIC fixtures; no JWT/model/external write."""
import base64
import copy
import hashlib
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from ..symphony_operator_runtime import (RuntimePins, IndependentReviewReader,
    GitHubJobContextReader, MemoryOnlyOIDCRequest, ScopedOperatorLedgerClient,
    ReviewedNarrowCapabilityFactory, PinnedVerifierExecutor, REPOSITORY)
from ..symphony_git_adoption import AppendOnlyAdoptionStore, PROTOCOL as LEDGER, _git_oid
from ..symphony_operator_sender import PROTOCOL, authorization_path
from ..symphony_result_manifest import canonical, digest
from ..executor_backend import ExecutorContent
from ..symphony_codex_app_server import JsonlCodexAppServer
from .test_symphony_security_corrective import AtomicContents, FakeProcess
from .test_symphony_operator_integration import CandidateFixture
from .test_symphony_operator_convergence import capability_fixture
from . import test_symphony_operator_convergence as route_fixtures
from .test_symphony_g61_production_wiring import TempCase, NOW, REPO as STATIC_REPO
from . import test_symphony_operator_installation as installation_fixtures
from ..symphony_operator_runtime import attach_reviewed_runtime
from ..symphony_operator_oidc import GitHubOIDCEnvelopeSignatureVerifier
from .symphony_g6_fixtures import SimulatedCrash, crash_at


def runtime_fixture():
    raw=canonical({'protocol':PROTOCOL,'issuer':'fixture','key_id':'fixture','payload':{}}).encode()
    pins=RuntimePins('a'*40,12,'.github/workflows/symphony-operator-authorize.yml',13,14,'15',
                     'operator_reviews/once.json',hashlib.sha256(raw).hexdigest())
    root='repos/'+REPOSITORY
    bodies={root:{'full_name':REPOSITORY,'default_branch':'main','archived':False,'id':16,'owner':{'id':17}},
        root+'/actions/runs/13':{'id':13,'workflow_id':12,'event':'workflow_dispatch','head_branch':'main',
            'head_sha':pins.source_commit,'run_attempt':1,'status':'in_progress','actor':{'id':15},'triggering_actor':{'id':15}},
        root+'/actions/jobs/14':{'id':14,'run_id':13,'head_sha':pins.source_commit,'status':'in_progress'},
        root+'/actions/workflows/12':{'id':12,'path':pins.workflow_path},
        root+'/git/ref/heads/main':{'ref':'refs/heads/main','object':{'type':'commit','sha':pins.source_commit}},
        root+'/contents/'+pins.review_path+'?ref='+pins.source_commit:{'type':'file','path':pins.review_path,
            'encoding':'base64','content':base64.b64encode(raw).decode(),'sha':_git_oid('blob',raw)}}
    http=Mock();http.request.side_effect=lambda method,path:(200,copy.deepcopy(bodies[path]))
    return pins,raw,bodies,http


class RuntimeReaderTests(unittest.TestCase):
    def test_review_exact_commit_sha_blob_and_canonical_bytes(self):
        pins,raw,_,http=runtime_fixture()
        self.assertEqual(IndependentReviewReader(http=http,pins=pins).read(),raw)
        self.assertEqual(http.request.call_args.args[0],'GET')
        self.assertIn('?ref='+pins.source_commit,http.request.call_args.args[1])

    def test_review_self_hash_or_candidate_wrong_bytes_never_approval(self):
        for field,value in [('sha','b'*40),('path','candidate/once.json'),('encoding','utf-8'),('content','not base64')]:
            pins,_,bodies,http=runtime_fixture();body=bodies[next(k for k in bodies if '/contents/' in k)];body[field]=value
            with self.assertRaises(PermissionError):IndependentReviewReader(http=http,pins=pins).read()
        pins,_,_,http=runtime_fixture()
        with self.assertRaises(PermissionError):IndependentReviewReader(http=http,pins=replace(pins,review_sha256='0'*64)).read()
        with self.assertRaises(PermissionError):IndependentReviewReader(http=http,pins=replace(pins,review_path='candidate/review.json'))

    def test_context_independent_run_job_workflow_and_current_main(self):
        pins,_,_,http=runtime_fixture();context=GitHubJobContextReader(http=http,pins=pins).read()
        self.assertEqual(context['sha'],pins.source_commit);self.assertEqual(context['event_name'],'workflow_dispatch')
        self.assertEqual(len(http.request.call_args_list),5)
        self.assertTrue(all(c.args[0]=='GET' for c in http.request.call_args_list))

    def test_context_pr_event_wrong_actor_rerun_job_source_and_main_drift_refused(self):
        cases=[('actions/runs/13','event','pull_request'),('actions/runs/13','run_attempt',2),
            ('actions/runs/13','actor',{'id':99}),('actions/runs/13','triggering_actor',{'id':99}),
            ('actions/jobs/14','head_sha','b'*40),('actions/jobs/14','status','completed'),
            ('actions/workflows/12','path','.github/workflows/candidate.yml'),
            ('git/ref/heads/main','object',{'type':'commit','sha':'b'*40}),('','archived',True)]
        for path,key,value in cases:
            with self.subTest(path=path,key=key):
                pins,_,bodies,http=runtime_fixture();bodies['repos/'+REPOSITORY+('/'+path if path else '')][key]=value
                with self.assertRaises(PermissionError):GitHubJobContextReader(http=http,pins=pins).read()

    def oidc(self):
        pins,_,_,http=runtime_fixture();reader=GitHubJobContextReader(http=http,pins=pins)
        return MemoryOnlyOIDCRequest(request_url='https://fixture.actions.githubusercontent.com/token?api-version=1',
            request_token='STATIC_REQUEST_BEARER',context_reader=reader,expected_context=reader.read()),reader

    def test_oidc_one_attempt_only_in_memory_no_token_repr(self):
        request,_=self.oidc();reply=Mock(status=200);reply.read.return_value=b'{"value":"STATIC_JWT"}'
        opener=MagicMock();opener.open.return_value.__enter__.return_value=reply
        with patch('automation.command_bus.symphony_operator_runtime.build_opener',return_value=opener):
            self.assertEqual(request('urn:symphony:operator-direct-authorization-v1:sha256:'+'a'*64),'STATIC_JWT')
            with self.assertRaises(PermissionError):request('urn:symphony:operator-direct-authorization-v1:sha256:'+'a'*64)
        self.assertEqual(opener.open.call_count,1);self.assertNotIn('STATIC_REQUEST_BEARER',repr(request))

    def test_copied_oidc_callback_shares_once_only_claim(self):
        request,_=self.oidc();copied=copy.copy(request)
        reply=Mock(status=200);reply.read.return_value=b'{"value":"STATIC_JWT"}'
        opener=MagicMock();opener.open.return_value.__enter__.return_value=reply
        with patch('automation.command_bus.symphony_operator_runtime.build_opener',return_value=opener):
            request('urn:symphony:operator-direct-authorization-v1:sha256:'+'c'*64)
            with self.assertRaises(PermissionError):copied('urn:symphony:operator-direct-authorization-v1:sha256:'+'c'*64)
        self.assertEqual(opener.open.call_count,1)

    def test_oidc_uncertain_request_never_retry_or_leak_exception(self):
        request,_=self.oidc();opener=Mock();opener.open.side_effect=RuntimeError('SECRET_FIXTURE_NEVER_REPORT')
        with patch('automation.command_bus.symphony_operator_runtime.build_opener',return_value=opener):
            for _ in range(2):
                with self.assertRaises(PermissionError) as caught:request('urn:symphony:operator-direct-authorization-v1:sha256:'+'b'*64)
                self.assertNotIn('SECRET_FIXTURE',str(caught.exception));self.assertTrue(caught.exception.__suppress_context__)
        self.assertEqual(opener.open.call_count,1)

    def test_oidc_stale_context_fork_bad_audience_never_request(self):
        for cause in ('context','fork','audience'):
            request,reader=self.oidc();aud='urn:symphony:operator-direct-authorization-v1:sha256:'+'a'*64
            if cause=='context':reader.read=Mock(return_value={})
            if cause=='fork':request._pid=-1
            if cause=='audience':aud='unbound-fixed-audience'
            with patch('automation.command_bus.symphony_operator_runtime.build_opener') as opener:
                with self.assertRaises(PermissionError):request(aud)
                opener.assert_not_called()

    def test_oidc_url_credentials_redirect_source_and_controls_refused(self):
        pins,_,_,http=runtime_fixture();reader=GitHubJobContextReader(http=http,pins=pins)
        for url in ('http://x.actions.githubusercontent.com/token','https://example.com/token',
                    'https://user@x.actions.githubusercontent.com/token','https://x.actions.githubusercontent.com/token?audience=other'):
            with self.assertRaises(PermissionError):MemoryOnlyOIDCRequest(request_url=url,request_token='STATIC',context_reader=reader,expected_context={})
        with self.assertRaises(PermissionError):MemoryOnlyOIDCRequest(request_url='https://x.actions.githubusercontent.com/token',request_token='STATIC\nHEADER',context_reader=reader,expected_context={})


class AdoptionOwnershipTests(unittest.TestCase):
    def store(self,c):return AppendOnlyAdoptionStore(c,write_branch='proof/static-ledger')
    def test_race_identical_payload_one_owner_and_foreign_conflict(self):
        for lost in (False,True):
            c=AtomicContents(race=True,lost_reply=lost)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda s:s._put('symphony_operator_authorizations/once.json',{'same':True}),[self.store(c),self.store(c)]))
            self.assertEqual(sorted(results),['ACCEPTED','CONFLICT']);self.assertEqual(c.creates,2)
            self.assertEqual(len(c.files),1)
            self.assertEqual(len({r['write_claim_nonce'] for r in c.submissions}),2)
    def test_unknown_create_before_persist_no_second_write_in_copied_lifetime(self):
        c=AtomicContents(lost_before=True);s=self.store(c)
        self.assertEqual(s._put('once.json',{}),'UNKNOWN');self.assertEqual(copy.copy(s)._put('once.json',{}),'UNKNOWN')
        self.assertEqual(c.creates,1)
    def test_own_lost_reply_and_restart_duplicate_are_different_authority(self):
        c=AtomicContents(lost_reply=True);s=self.store(c)
        self.assertEqual(s._put('once.json',{}),'ACCEPTED');self.assertEqual(self.store(c)._put('once.json',{}),'NOOP_DUPLICATE')
        self.assertEqual(c.creates,1)
    def test_legacy_record_preserved_and_new_claim_append_validated(self):
        c=AtomicContents();body={'protocol':LEDGER,'path':'legacy.json','payload':{'old':True}}
        raw=canonical({**body,'record_digest':digest(body)});c.files['legacy.json']=ExecutorContent('legacy.json',raw,'STATIC')
        s=self.store(c);self.assertEqual(s._get('legacy.json'),{'old':True})
        self.assertEqual(s._put('legacy.json',{'old':True}),'NOOP_DUPLICATE')
        self.assertEqual(s._put('new.json',{}),'ACCEPTED');self.assertEqual(c.files['legacy.json'].text,raw)
        new=json.loads(c.files['new.json'].text);new['write_claim_version']=True
        new['record_digest']=digest({k:v for k,v in new.items() if k!='record_digest'})
        c.files['new.json']=ExecutorContent('new.json',canonical(new),'STATIC')
        self.assertEqual(s._put('new.json',{}),'CONFLICT')
    def test_fork_cannot_claim_or_write(self):
        c=AtomicContents();s=self.store(c);s._process_id=-1
        self.assertEqual(s._put('once.json',{}),'UNKNOWN');self.assertEqual(c.creates,0)


class RealConnectionSeamTests(TempCase):
    def setUp(self):
        super().setUp()
        # Explicit fixture repository only; the production module remains fixed
        # to the real repository and no HTTP implementation is invoked.
        fixture_repo=patch('automation.command_bus.symphony_operator_runtime.REPOSITORY',STATIC_REPO)
        fixture_repo.start();self.addCleanup(fixture_repo.stop)
    def factory(self):
        f=CandidateFixture(self.tmp);sender,_,calls,flow,*_=capability_fixture(f)
        credential=Mock(return_value='STATIC_TOKEN');permissions=Mock(return_value=True)
        factory=ReviewedNarrowCapabilityFactory(plan=f.plan,credential_callback=credential,permission_check=permissions)
        return f,sender,flow,factory,credential,permissions,calls[0]
    def test_real_reader_seams_attach_existing_same_job_then_replay_no_second_token(self):
        args,issuer,cap=installation_fixtures.InstallationTests.attachment(self)
        pins,_,bodies,http=runtime_fixture();ctx=args['job_context'];raw=args['reviewed_unsigned']
        # All identities remain explicit fixtures; the reader performs genuine
        # REST-shaped GET/binding logic and existing attachment owns the fence.
        pins=replace(pins,source_commit=ctx['sha'],run_id=int(ctx['run_id']),
            actor_id=ctx['actor_id'],review_sha256=hashlib.sha256(raw).hexdigest())
        root='repos/'+STATIC_REPO;bodies={}
        bodies[root]={'full_name':STATIC_REPO,'id':int(ctx['repository_id']),
            'owner':{'id':int(ctx['repository_owner_id'])},'default_branch':'main','archived':False}
        bodies[root+'/actions/runs/'+str(pins.run_id)]={'id':pins.run_id,'workflow_id':pins.workflow_id,
            'event':'workflow_dispatch','head_branch':'main','head_sha':pins.source_commit,'run_attempt':1,
            'status':'in_progress','actor':{'id':int(pins.actor_id)},'triggering_actor':{'id':int(pins.actor_id)}}
        bodies[root+'/actions/jobs/'+str(pins.job_id)]={'id':pins.job_id,'run_id':pins.run_id,'head_sha':pins.source_commit,'status':'in_progress'}
        bodies[root+'/actions/workflows/'+str(pins.workflow_id)]={'id':pins.workflow_id,'path':pins.workflow_path}
        bodies[root+'/git/ref/heads/main']={'ref':'refs/heads/main','object':{'type':'commit','sha':pins.source_commit}}
        bodies[root+'/contents/'+pins.review_path+'?ref='+pins.source_commit]={'type':'file','path':pins.review_path,
            'encoding':'base64','sha':_git_oid('blob',raw),'content':base64.b64encode(raw).decode()}
        http.request.side_effect=lambda method,path:(200,copy.deepcopy(bodies[path]))
        inputs={k:args[k] for k in ('requested_unsigned','token_once','signature_verifier','transport_inputs','now')}
        with patch.object(GitHubOIDCEnvelopeSignatureVerifier,'__call__',side_effect=issuer.verify):
            transport,audit=attach_reviewed_runtime(pins=pins,read_http=http,**inputs)
            self.assertEqual(audit['publication'],0);self.assertEqual(audit['model_dispatch'],0)
            with self.assertRaises(PermissionError):attach_reviewed_runtime(pins=pins,read_http=http,**inputs)
        args['token_once'].assert_called_once();self.assertEqual(cap.refs,[])

    def test_factory_unknown_permission_or_wrong_plan_no_credential(self):
        _,_,_,factory,credential,permissions,claims=self.factory()
        permissions.return_value=None
        with self.assertRaises(PermissionError):factory(claims)
        credential.assert_not_called();permissions.return_value=True
        with self.assertRaises(PermissionError):factory({**claims,'plan_digest':'0'*64})
        credential.assert_not_called()
    def test_narrow_objects_exact_once_no_generic_method_and_no_resend(self):
        f,_,_,factory,credential,_,claims=self.factory();cap=factory(claims)
        self.assertFalse(hasattr(cap,'request'));self.assertFalse(hasattr(cap,'graphql'));self.assertNotIn('STATIC_TOKEN',repr(cap))
        io=Mock();io.send.side_effect=lambda m,p,b:(201,{'sha':next(r['expected_oid'] for r in f.plan['object_requests'] if r['body']==b)})
        cap._io=io
        with self.assertRaises(PermissionError):cap.post_exact_objects('other/repo',f.plan['object_requests'])
        cap.post_exact_objects(STATIC_REPO,f.plan['object_requests'])
        self.assertEqual(io.send.call_count,len(f.plan['object_requests']))
        self.assertTrue(all(c.args[1].startswith('repos/'+STATIC_REPO+'/git/') for c in io.send.call_args_list))
        with self.assertRaises(PermissionError):cap.post_exact_objects(STATIC_REPO,f.plan['object_requests'])
        self.assertEqual(credential.call_count,1)
    def test_objects_uncertain_reply_stays_once_only(self):
        f,_,_,factory,_,_,claims=self.factory();cap=factory(claims);cap._io=Mock();cap._io.send.side_effect=TimeoutError('STATIC')
        with self.assertRaises(TimeoutError):cap.post_exact_objects(STATIC_REPO,f.plan['object_requests'])
        with self.assertRaises(PermissionError):cap.post_exact_objects(STATIC_REPO,f.plan['object_requests'])
        self.assertEqual(cap._io.send.call_count,1)
    def test_exact_force_false_cas_once_and_wrong_before_refused(self):
        f,_,_,factory,_,_,claims=self.factory();cap=factory(claims);cap._io=Mock();cap._io.send.return_value=(200,{})
        wrong=copy.deepcopy(f.plan['single_ref_request']);wrong['variables']['input']['refUpdates'][0]['beforeOid']='0'*40
        with self.assertRaises(PermissionError):cap.update_exact_ref(STATIC_REPO,wrong)
        cap._io.send.assert_not_called();cap.update_exact_ref(STATIC_REPO,f.plan['single_ref_request'])
        with self.assertRaises(PermissionError):cap.update_exact_ref(STATIC_REPO,f.plan['single_ref_request'])
        self.assertEqual(cap._io.send.call_count,1)
    def test_copied_narrow_capability_and_transport_cannot_duplicate_cas(self):
        f,s,flow,factory,_,_,claims=self.factory();cap=factory(claims)
        cap._io=Mock();cap._io.send.return_value=(200,{})
        copied=copy.copy(cap);cap.update_exact_ref(STATIC_REPO,f.plan['single_ref_request'])
        with self.assertRaises(PermissionError):copied.update_exact_ref(STATIC_REPO,f.plan['single_ref_request'])
        self.assertEqual(cap._io.send.call_count,1)
        with self.assertRaises(SimulatedCrash):flow.process(f.w.manifest,now=NOW,crash_hook=crash_at('AFTER_REF_INTENT'))
        copied_sender=copy.copy(s)
        s.compare_and_swap(branch=f.w.manifest['target_branch'],expected_head=f.w.head,candidate_head=f.candidate.commit)
        with self.assertRaises(PermissionError):copied_sender.compare_and_swap(branch=f.w.manifest['target_branch'],expected_head=f.w.head,candidate_head=f.candidate.commit)
        self.assertEqual(f.w.gh.update_refs_requests,1)

    def test_foreign_nonce_even_same_payload_cannot_cas(self):
        f,s,flow,_,_,_,_=self.factory()
        with self.assertRaises(SimulatedCrash):flow.process(f.w.manifest,now=NOW,crash_hook=crash_at('AFTER_REF_INTENT'))
        self.assertEqual(f.w.ledger._put(authorization_path(s._claims['issuer'],s._claims['nonce']),s._nonce_record()),'ACCEPTED')
        with self.assertRaises(PermissionError):s.compare_and_swap(branch=f.w.manifest['target_branch'],expected_head=f.w.head,candidate_head=f.candidate.commit)
        self.assertEqual(f.w.gh.update_refs_requests,0)
    def test_scoped_ledger_only_create_exact_branch_and_no_sha(self):
        client=ScopedOperatorLedgerClient(token='STATIC_TOKEN',branch='proof/static',default_branch='main',namespaces=('records/',))
        io=Mock();io.send.side_effect=TimeoutError('STATIC');client._io=io
        with self.assertRaises(PermissionError):client.create('other/once.json','{}','STATIC','proof/static')
        with self.assertRaises((PermissionError,ValueError)):client.create('records/once.json','{}','STATIC','main')
        with self.assertRaises(PermissionError):client.update('records/once.json','{}','sha','STATIC','proof/static')
        with self.assertRaises(TimeoutError):client.create('records/once.json','{}','STATIC','proof/static')
        with self.assertRaises(PermissionError):client.create('records/once.json','{}','STATIC','proof/static')
        self.assertEqual(io.send.call_count,1);self.assertNotIn('sha',io.send.call_args.args[2])
        self.assertNotIn('STATIC_TOKEN',repr(client))
    def test_verifier_executor_refuses_candidate_command_before_subprocess(self):
        f,args=route_fixtures.RealRouteTests.make(self);executor=PinnedVerifierExecutor(route_inputs=args)
        with patch('automation.command_bus.symphony_operator_runtime.subprocess.run') as run:
            with self.assertRaises(PermissionError):executor(('docker','run','candidate-owned-command'))
            (args['source']/'operator/tests.py').write_text('mutated operator source')
            with self.assertRaises((PermissionError,ValueError)):executor(executor._commands[0])
            run.assert_not_called()


class AppServerReadOnlyTests(unittest.TestCase):
    def probe(self,process):
        with patch.dict(os.environ,{'PATH':'/bin','HOME':'/STATIC_HOME'},clear=True),patch('automation.command_bus.symphony_codex_app_server.subprocess.Popen',return_value=process):
            return JsonlCodexAppServer().probe_read_only(cwd=str(Path(__file__).resolve().parents[3]))
    def test_readonly_account_config_no_thread_model_and_not_admission(self):
        process=FakeProcess();result=self.probe(process)
        self.assertEqual(result['status'],'DONE');self.assertEqual(result['model_dispatch'],0)
        self.assertEqual([c['method'] for c in process.calls],['initialize','initialized','account/read','config/read'])
        self.assertIs(process.calls[2]['params']['refreshToken'],False)
        self.assertIn('NOT_ADMISSION',result['route']['provenance']);self.assertFalse(result['route']['raw_response_saved'])
    def test_request_fields_match_actual_installed_schema_snapshot(self):
        root=Path(__file__).resolve().parents[3]
        schema=json.loads((root/'docs/evidence/symphony-production-connection/installed-schema-contract.json').read_text())
        self.assertTrue(schema['schema_generated_from_installed_binary'])
        process=FakeProcess()
        with patch.dict(os.environ,{'PATH':'/bin','HOME':'/STATIC_HOME'},clear=True),patch('automation.command_bus.symphony_codex_app_server.subprocess.Popen',return_value=process):
            JsonlCodexAppServer().execute_one_turn(cwd=str(root),prompt='STATIC',live_enabled=True)
        mapping={'initialize':'InitializeParams','account/read':'GetAccountParams',
            'config/read':'ConfigReadParams','thread/start':'ThreadStartParams','turn/start':'TurnStartParams'}
        for call in process.calls:
            if call['method'] in mapping:
                contract=schema['selected_requests'][mapping[call['method']]]
                self.assertTrue(set(call['params'])<=set(contract['properties']))
                self.assertTrue(set(contract['required'])<=set(call['params']))

    def test_missing_account_is_blocked_no_refresh_thread_turn(self):
        process=FakeProcess(account={'requiresOpenaiAuth':True,'account':None});result=self.probe(process)
        self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['thread_starts'],0)
        self.assertNotIn('thread/start',[c['method'] for c in process.calls])
    def test_existing_live_guard_stays_closed_and_installed_schema_params(self):
        with patch('automation.command_bus.symphony_codex_app_server.subprocess.Popen') as popen:
            result=JsonlCodexAppServer().execute_one_turn(cwd='/STATIC',prompt='STATIC')
            self.assertEqual(result.status,'BLOCKED');popen.assert_not_called()
        process=FakeProcess()
        with patch.dict(os.environ,{'PATH':'/bin','HOME':'/STATIC_HOME'},clear=True),patch('automation.command_bus.symphony_codex_app_server.subprocess.Popen',return_value=process):
            JsonlCodexAppServer().execute_one_turn(cwd=str(Path(__file__).resolve().parents[3]),prompt='STATIC',live_enabled=True)
        start=next(c for c in process.calls if c['method']=='thread/start')['params']
        self.assertEqual(start['sandbox'],'workspace-write');self.assertIs(start['ephemeral'],True);self.assertNotIn('sandboxPolicy',start)
        turn=next(c for c in process.calls if c['method']=='turn/start')['params']
        self.assertIs(turn['sandboxPolicy']['networkAccess'],False)
