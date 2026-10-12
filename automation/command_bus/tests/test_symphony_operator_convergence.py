"""New wiring tests only; all candidates/IO/authorities are explicit fixtures."""
import copy
import hashlib
import os
from dataclasses import replace
from pathlib import Path
from unittest import mock

from .test_symphony_operator_integration import (CandidateFixture, FakeExternalIssuer,
    sender_fixture, ISSUED, EXPIRY)
from .test_symphony_g61_production_wiring import TempCase, NOW, REPO
from .symphony_g6_fixtures import SimulatedCrash, crash_at
from ..symphony_github_readers import read_repository_identity
from ..symphony_operator_capability import OperatorCapabilityBoundGitTransport
from ..symphony_operator_verifier_route import prepare_real_verifier_route, run_real_verifier_job
from ..symphony_operator_oidc import authorization_audience
from ..symphony_operator_sender import DOMAIN, authorization_path
from ..symphony_result_manifest import canonical, digest, FileEntry
from ..symphony_git_adoption import StaticAdoptionBridge, make_adoption_id, PROTOCOL as LEDGER_PROTOCOL


class FakeNarrowCapability:
    def __init__(self,f):
        self.f=f; self.objects=[]; self.refs=[]; self.ledgers=[]
    def post_exact_objects(self,repository,requests):
        self.objects.append((repository,requests))
        for r in requests:
            status,data=self.f.w.gh.request(r['method'],'repos/'+repository+'/'+r['path'],r['body'])
            assert status==201 and data['sha']==r['expected_oid']
    def update_exact_ref(self,repository,request):
        self.refs.append((repository,request))
        return self.f.w.gh.graphql(request['document'],request['variables'])
    def create_ledger_record(self,repository,branch,path,text,message):
        self.ledgers.append((repository,branch,path,text))
        return self.f.w.client.create(path,text,message,branch)


def capability_fixture(f, *, factory=None, raw=None, sender_kwargs=None):
    if hasattr(f, "_verified_sender_fixture"):
        v,issuer,oldraw,verifier = f._verified_sender_fixture
        flow,s,issuer,oldraw,v,verifier=sender_fixture(f,verified=v,issuer=issuer,raw=oldraw,verifier=verifier)
    else:
        flow,s,issuer,oldraw,v,verifier=sender_fixture(f)
        f._verified_sender_fixture=(v,issuer,oldraw,verifier)
    cap=FakeNarrowCapability(f); calls=[]
    def default(claims):
        calls.append(claims); return cap
    args=dict(verification=v,envelope_verifier=verifier,authorization=raw or oldraw,
        manifest=f.w.manifest,plan=f.plan,store=f.w.ledger,target_reader=f.w.target_reader(),
        candidate_reader=f.reader().candidates,validity_reader=flow.validity_reader,
        repository_identity=lambda:read_repository_identity(f.w.gh,REPO),
        constraints_reader=lambda:{'repository':REPO,'repository_id':v.receipt['binding']['repository_id'],
            'default_branch':'main','target_branch':f.w.manifest['target_branch'],
            'expected_target_head':f.w.head,'ledger_branch':f.w.ledger.branch,'owner_login':REPO.split('/')[0],
            'rules_complete':True,'proof_ref_write_allowed':True,'ledger_create_allowed':True,'objects_create_allowed':True},
        now=lambda:NOW,
        capability_factory=factory or default)
    args.update(sender_kwargs or {})
    return OperatorCapabilityBoundGitTransport(**args),cap,calls,flow,issuer,oldraw


class NarrowCapabilityTests(TempCase):
    def test_no_factory_and_bad_signature_do_not_acquire_permission(self):
        f=CandidateFixture(self.tmp)
        with self.assertRaises(PermissionError):
            capability_fixture(f,sender_kwargs={'capability_factory':None})
        factory=mock.Mock()
        raw=b'{"protocol":"fake"}'
        with self.assertRaises(PermissionError):capability_fixture(f,factory=factory,raw=raw)
        factory.assert_not_called()
        self.assertEqual(f.w.gh.update_refs_requests,0)

    def test_old_static_bridge_guard_stays_closed_no_generic_client(self):
        f=CandidateFixture(self.tmp);s,cap,calls,*_=capability_fixture(f)
        self.assertFalse(s.static_only)
        self.assertFalse(hasattr(s,'request'));self.assertFalse(hasattr(s,'graphql'))
        with self.assertRaises(ValueError):
            StaticAdoptionBridge(store=f.w.ledger,transport=s,repository=REPO,
                                 target_branch=f.w.manifest['target_branch'],default_branch='main')
        with self.assertRaises(PermissionError):s.execute()
        self.assertEqual(len(calls),1)
        self.assertEqual((cap.refs,cap.objects,cap.ledgers),([],[],[]))

    def test_reuses_existing_intent_and_exact_one_cas_then_restart_only_get(self):
        f=CandidateFixture(self.tmp);s,cap,calls,flow,issuer,raw=capability_fixture(f)
        with self.assertRaises(SimulatedCrash):flow.process(f.w.manifest,now=NOW,crash_hook=crash_at('AFTER_REF_INTENT'))
        self.assertEqual(s.compare_and_swap(branch=f.w.manifest['target_branch'],
            expected_head=f.w.head,candidate_head=f.candidate.commit),'SUCCESS_REPLY')
        self.assertEqual(cap.refs,[(REPO,f.plan['single_ref_request'])])
        with self.assertRaises(PermissionError):s.compare_and_swap(branch=f.w.manifest['target_branch'],
            expected_head=f.w.head,candidate_head=f.candidate.commit)
        factory=mock.Mock()
        # Fresh adapter observes the durable fence and never calls a factory.
        fresh,*_=capability_fixture(f,factory=factory)
        factory.assert_not_called()
        self.assertEqual(fresh.read_candidate(f.candidate.commit),f.candidate)
        self.assertEqual(f.w.gh.update_refs_requests,1)

    def test_lost_cas_reply_before_and_after_apply_cannot_resend(self):
        for applied in (False,True):
            f=CandidateFixture(os.path.join(self.tmp,str(applied)));s,cap,_,flow,*_=capability_fixture(f)
            with self.assertRaises(SimulatedCrash):flow.process(f.w.manifest,now=NOW,crash_hook=crash_at('AFTER_REF_INTENT'))
            setattr(f.w.gh,'lose_reply_after_apply' if applied else 'lose_reply_before_apply',True)
            with self.assertRaises(Exception):s.compare_and_swap(branch=f.w.manifest['target_branch'],
                expected_head=f.w.head,candidate_head=f.candidate.commit)
            with self.assertRaises(PermissionError):s.compare_and_swap(branch=f.w.manifest['target_branch'],
                expected_head=f.w.head,candidate_head=f.candidate.commit)
            factory=mock.Mock();fresh,*_=capability_fixture(f,factory=factory)
            factory.assert_not_called()
            self.assertEqual(f.w.gh.update_refs_requests,1)
            with self.assertRaises(PermissionError):fresh.compare_and_swap(branch=f.w.manifest['target_branch'],
                expected_head=f.w.head,candidate_head=f.candidate.commit)

    def test_object_binding_and_ambiguous_object_fence_reuse_no_posts(self):
        f=CandidateFixture(self.tmp);s,cap,_,flow,*_=capability_fixture(f)
        with self.assertRaises(SimulatedCrash):flow.process(f.w.manifest,now=NOW,crash_hook=crash_at('AFTER_INTENT'))
        self.assertEqual(s.put_candidate(f.candidate),'NOOP_OBJECTS_ALREADY_VERIFIED')
        forged=replace(f.candidate,parent='f'*40)
        with self.assertRaises(PermissionError):s.put_candidate(forged)
        # Missing object + already consumed nonce is unresolved, never resent.
        f.w.gh.objects.pop(f.candidate.commit)
        f.w.ledger._put(authorization_path(s._claims['issuer'],s._claims['nonce']),s._nonce_record())
        with self.assertRaises(PermissionError):s.put_candidate(f.candidate)
        self.assertEqual(cap.objects,[])

    def test_node_default_target_task_and_expiry_revalidated_before_callback(self):
        for cause in ('node','default','head','task','expired','rules','owner','permission'):
            f=CandidateFixture(os.path.join(self.tmp,cause));s,cap,_,flow,*_=capability_fixture(f)
            with self.assertRaises(SimulatedCrash):flow.process(f.w.manifest,now=NOW,crash_hook=crash_at('AFTER_REF_INTENT'))
            if cause=='node':s._identity=lambda:{'repository_id':'wrong','default_branch':'main','archived':False}
            if cause=='default':f.w.gh.default_branch=f.w.manifest['target_branch']
            if cause=='head':f.w.gh.advance(f.w.manifest['target_branch'],f.w.gh.tree_files(f.w.head))
            if cause in ('rules','owner','permission'):
                old=s._constraints
                field={'rules':'rules_complete','owner':'owner_login','permission':'proof_ref_write_allowed'}[cause]
                s._constraints=lambda:{**old(),field:False if cause!='owner' else 'wrong'}
            if cause=='task':f.w.gh.issues[f.w.number]['labels']={'totalCount':1,'nodes':[{'name':'symphony:invalid'}]}
            if cause=='expired':
                s._clock=lambda:EXPIRY;s._verifier.now=lambda:EXPIRY
            with self.assertRaises(PermissionError):s.compare_and_swap(branch=f.w.manifest['target_branch'],
                expected_head=f.w.head,candidate_head=f.candidate.commit)
            self.assertEqual(cap.refs,[])

    def test_exact_ledger_create_only_no_default_other_namespace_or_blind_retry(self):
        f=CandidateFixture(self.tmp);s,cap,*_=capability_fixture(f)
        path=authorization_path(s._claims['issuer'],s._claims['nonce'])
        ledger=f.w.ledger.branch
        for branch,p in [('main',path),(ledger,'unapproved/a.json'),(ledger,'../bad'),('other',path)]:
            with self.assertRaises(PermissionError):s.create_ledger_record(p,'{}','proof',branch)
        path=f.w.ledger.path(f.w.manifest['campaign_id'],make_adoption_id(f.w.manifest),'inspection-'+'a'*64)
        body={'protocol':LEDGER_PROTOCOL,'path':path,'payload':{'fixture':True}}
        text=canonical({**body,'record_digest':digest(body)})
        got=s.create_ledger_record(path,text,'proof',ledger)
        self.assertEqual(s.create_ledger_record(path,text,'proof',ledger),got)
        with self.assertRaises(PermissionError):s.create_ledger_record(path,'{}','proof',ledger)
        self.assertEqual(len(cap.ledgers),1)

    def test_ledger_lost_reply_before_and_after_apply_is_durably_get_only(self):
        for applied in (False,True):
            f=CandidateFixture(os.path.join(self.tmp,str(applied)));s,cap,*_=capability_fixture(f)
            path=f.w.ledger.path(f.w.manifest['campaign_id'],make_adoption_id(f.w.manifest),'inspection-'+'b'*64);branch=f.w.ledger.branch
            body={'protocol':LEDGER_PROTOCOL,'path':path,'payload':{'fixture':True}}
            text=canonical({**body,'record_digest':digest(body)})
            original=cap.create_ledger_record
            def lost(*args):
                if applied:original(*args)
                raise TimeoutError('fixture lost reply')
            cap.create_ledger_record=lost
            with self.assertRaises(TimeoutError):s.create_ledger_record(path,text,'proof',branch)
            fresh,freshcap,*_=capability_fixture(f)
            if applied:self.assertIsNotNone(fresh.create_ledger_record(path,text,'proof',branch))
            else:
                with self.assertRaises(PermissionError):fresh.create_ledger_record(path,text,'proof',branch)
            self.assertEqual(freshcap.ledgers,[])

    def test_nonce_conflict_after_acquisition_blocks_writer(self):
        f=CandidateFixture(self.tmp);s,cap,*_=capability_fixture(f)
        f.w.ledger._put(authorization_path(s._claims['issuer'],s._claims['nonce']),{'different':True})
        with self.assertRaises(PermissionError):s.create_ledger_record('anything','{}','proof',f.w.ledger.branch)
        self.assertEqual(cap.ledgers,[])


class RealRouteTests(TempCase):
    def make(self):
        f=CandidateFixture(self.tmp)
        src=Path(self.tmp)/'trusted';candidate=Path(self.tmp)/'isolated'
        for root,files in [(src,{p:FileEntry(raw) for p,raw in f.files.items()}),(candidate,f.candidate.files)]:
            for path,entry in files.items():
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(entry.data)
        # Explicit fixture-only independently authenticated source inventory.
        inventory=replace(f.w.target_reader().read(),files={p:FileEntry(raw) for p,raw in f.files.items()})
        args=dict(contract=f.contract,manifest=f.w.manifest,candidate=f.candidate,attempt=f.w.attempt(),
            snapshots=f.w.snapshots,source=src,source_inventory=inventory,candidate_root=candidate,now=NOW)
        return f,args

    def test_operator_source_and_snapshot_only_plan_is_off_no_dispatch(self):
        f,args=self.make();p=prepare_real_verifier_route(**args)
        self.assertFalse(p['authorized_to_execute']);self.assertEqual(p['mode'],'OFF')
        for command in [p['commands']['syntax'],*p['commands']['tests'],p['commands']['secret_scan']]:
            self.assertIn('--pull=never',command);self.assertIn('none',command)
            self.assertIn('--read-only',command);self.assertIn('65534:65534',command)
            self.assertNotIn('GITHUB_TOKEN',' '.join(command))
        self.assertIn('/source/operator/tests.py',p['commands']['tests'][0])
        self.assertFalse(p['candidate_code_tests_selected'])
        self.assertEqual((p['model_dispatch'],p['publication']),(0,0))

    def test_static_lifetime_candidate_mutation_source_mutation_and_self_tests_refused(self):
        for kind in ('static','worker','candidate','source','inventory','expired'):
            root=Path(self.tmp)/kind;root.mkdir()
            oldtmp=self.tmp;self.tmp=str(root)
            f,args=self.make();self.tmp=oldtmp
            if kind=='static':args['attempt']=f.static_attempt
            if kind=='worker':args['manifest']={**f.w.manifest,'worker_run_id':'wrong'}
            if kind=='candidate':(args['candidate_root']/'operator-test.py').write_text('worker says PASS')
            if kind=='source':(args['source']/'operator/tests.py').write_text('worker says PASS')
            if kind=='inventory':args['source_inventory']=replace(args['source_inventory'],trustworthy=False)
            if kind=='expired':args['now']=EXPIRY
            with self.assertRaises(ValueError):prepare_real_verifier_route(**args)

    def test_domain_digest_binds_exact_payload_not_fixed_signal_identity_audience(self):
        a=DOMAIN+canonical({'payload':{'one_run':1}}).encode()
        b=DOMAIN+canonical({'payload':{'one_run':2}}).encode()
        self.assertNotEqual(authorization_audience(a),authorization_audience(b))
        with self.assertRaises(ValueError):authorization_audience(b'not-domain')

    def job_context(self,f):
        c=f.contract
        return {'repository':c.ci.repository,'workflow_id':c.ci.workflow_id,
            'run_id':c.ci.run_id,'run_attempt':c.ci.run_attempt,'job_id':c.ci.job_id,
            'head_sha':c.ci.candidate_commit,'workflow_source_commit':c.workflow_source_commit}

    def test_trusted_fixture_job_emits_original_strict_and_real_format_for_existing_reader(self):
        f,args=self.make();calls=[]
        def run(argv):
            calls.append(argv);return {'returncode':0,'stdout':b'fixture-only pass','stderr':b''}
        emitted=run_real_verifier_job(job_context=self.job_context(f),run_command=run,**args)
        self.assertFalse(emitted['candidate_qualified']);self.assertEqual(len(calls),3)
        self.assertEqual(set(emitted['artifact_members']),{'attestation.json','operator-attestation.json'})
        self.assertIn('AFTER_UPLOAD_GET',emitted['archive_sha256_scope'])
        f.ci.archive=emitted['archive'];f.ci.artifact['digest']='sha256:'+emitted['archive_sha256']
        f.contract=replace(f.contract,archive_sha256=emitted['archive_sha256'])
        verified=f.verified();self.assertTrue(verified.bundle.evidence.trustworthy)
        self.assertEqual((f.w.gh.object_posts,f.w.gh.update_refs_requests),(0,0))

    def test_wrong_job_head_failed_check_and_host_source_change_do_not_emit(self):
        f,args=self.make();context=self.job_context(f);run=mock.Mock(return_value={'returncode':0,'stdout':b'','stderr':b''})
        with self.assertRaises(ValueError):run_real_verifier_job(job_context={**context,'head_sha':f.w.head},run_command=run,**args)
        run.assert_not_called()
        run.return_value={'returncode':1,'stdout':b'untrusted output','stderr':b'failure'}
        with self.assertRaises(ValueError):run_real_verifier_job(job_context=context,run_command=run,**args)
        self.assertEqual(run.call_count,1)
        def mutate(argv):
            (args['source']/'operator/tests.py').write_text('changed during check')
            return {'returncode':0,'stdout':b'','stderr':b''}
        with self.assertRaises(ValueError):run_real_verifier_job(job_context=context,run_command=mutate,**args)
