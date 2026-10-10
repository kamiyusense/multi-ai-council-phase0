"""G6.3 negative and restart contract tests: mock writes only, no model work."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import stat
import urllib.error
import zipfile
from dataclasses import replace
from unittest import mock

from .test_symphony_g61_production_wiring import World, TempCase, NOW, REPO_ID, TRUSTED, TARGET
from .test_symphony_g62_readiness import prepare, CIWorld, run_g62_matrix
from .symphony_g6_fixtures import crash_at, SimulatedCrash
from ..symphony_g63_sender import RestrictedMockSender, seal_approval, BINDING_KEYS
from ..symphony_g63_archive import (GitHubArtifactArchiveGET, ArchiveUnavailable, inspect_archive, strict_json,
                                  MAX_ARCHIVE, MAX_MEMBER, MAX_MEMBERS)
from ..symphony_g63_verifier import PinnedCIContract, IndependentCIVerifier
from ..symphony_g62_attestation import AttestationUnavailable
from ..symphony_g63_snapshot import StrictWorkspaceSnapshotStore
from ..symphony_result_manifest import digest


def approval(w, plan):
    return seal_approval({'protocol':'SYMPHONY_G63_APPROVAL_V1', 'approval_id':'synthetic-human-approval-A',
        'repository':w.manifest['repository'],'repository_id':REPO_ID,'target_branch':TARGET,'default_branch':'main',
        **{k:w.manifest[k] for k in BINDING_KEYS}, 'candidate_commit':plan['candidate_commit'],
        'plan_digest':plan['plan_digest'],'expires_at':'2026-10-10T02:00:00Z','max_ref_updates':1,'force':False})


def wired(w, *, envelope=None, now=NOW):
    out = w.wired(); plan = prepare(w).plan
    sender = RestrictedMockSender(mock_transport=out.transport, store=w.ledger, manifest=w.manifest, plan=plan,
        approval=envelope or approval(w, plan), validity_reader=out.validity_reader, clock=lambda:now)
    out.transport = sender; out.bridge.transport = sender
    return out


def strict_ci(ci, **change):
    ci.run['workflow_id'] = 7000; ci.job['status'] = 'completed'; ci.job['run_id'] = ci.contract.run_id
    c = PinnedCIContract(**ci.contract.__dict__,workflow_id=7000,run_attempt=1,job_id=7101)
    return IndependentCIVerifier(ci,replace(c,**change),archive_get=lambda r,i:ci.archive,
        trusted_verifiers=TRUSTED,worker_run_id=ci.w.worker)


def zip_bytes(entries):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,data in entries: z.writestr(name,data)
    return out.getvalue()


class SenderTests(TempCase):
    def test_valid_approval_durable_receipt_and_replay_zero_extra_writes(self):
        w=World(self.tmp).ready(); flow=wired(w)
        self.assertEqual(flow.process(w.manifest,now=NOW).status,'ADOPTED')
        writes=(w.gh.object_posts,w.gh.update_refs_requests)
        shutil.rmtree(w.workspace)
        self.assertEqual(flow.process(w.manifest,now=NOW).status,'NOOP_DUPLICATE')
        self.assertEqual(writes,(w.gh.object_posts,w.gh.update_refs_requests)); self.assertEqual(writes[1],1)

    def test_missing_expired_and_rebound_approval_refuse_without_mock_writes(self):
        w=World(self.tmp).ready(); plan=prepare(w).plan; good=approval(w,plan)
        changes=[{'expires_at':NOW},{'force':True},{'max_ref_updates':2},{'max_ref_updates':True},
                 {'target_branch':'main'},{'target_branch':'HEAD'},{'repository':'other/repo'},
                 {'candidate_commit':'f'*40},{'expected_target_head':'f'*40},{'plan_digest':'f'*64}]
        changes += [{k: 'wrong'} for k in BINDING_KEYS]
        for change in changes:
            a=seal_approval({k:v for k,v in {**good,**change}.items() if k!='approval_digest'})
            with self.subTest(change=change),self.assertRaises((PermissionError,ValueError,TypeError)):
                wired(w,envelope=a)
        with self.assertRaises(PermissionError): wired(w,envelope={'approved':True})
        self.assertEqual((w.gh.object_posts,w.gh.update_refs_requests),(0,0))

    def test_off_flags_never_enable_real_send(self):
        w=World(self.tmp).ready(); s=wired(w).transport
        s.mode='LIVE';s.static_only=False;s.live_authorized=True
        with self.assertRaises(PermissionError):s.execute()
        self.assertEqual(w.gh.update_refs_requests,0)

    def test_fence_required_and_branch_candidate_tamper_rejected(self):
        w=World(self.tmp).ready();flow=wired(w);s=flow.transport
        with self.assertRaises(PermissionError):s.compare_and_swap(branch=TARGET,expected_head=w.head,candidate_head=s._approval['candidate_commit'])
        # Obtain real durable mock fence but crash before any ref call.
        with self.assertRaises(SimulatedCrash):flow.process(w.manifest,now=NOW,crash_hook=crash_at('AFTER_REF_INTENT'))
        for change in ({'branch':'main'},{'candidate_head':'f'*40},{'expected_head':'f'*40}):
            with self.assertRaises(PermissionError):s.compare_and_swap(**{'branch':TARGET,'expected_head':w.head,
                'candidate_head':s._approval['candidate_commit'],**change})
        self.assertEqual(w.gh.update_refs_requests,0)

    def test_task_change_after_fence_never_dispatches(self):
        w=World(self.tmp).ready();flow=wired(w)
        def change(point):
            if point=='AFTER_REF_INTENT':
                w.gh.issues[w.number]['labels']={'totalCount':1,'nodes':[{'name':'symphony:invalid'}]}
        self.assertEqual(flow.process(w.manifest,now=NOW,crash_hook=change).status,'UNKNOWN')
        self.assertEqual(w.gh.update_refs_requests,0)
        self.assertEqual(flow.process(w.manifest,now=NOW).status,'UNKNOWN')

    def test_head_or_default_change_at_fence_is_unknown_no_send(self):
        for kind in ('head','default'):
            w=World(os.path.join(self.tmp,kind)).ready();flow=wired(w)
            def change(point):
                if point=='AFTER_REF_INTENT':
                    if kind=='head':w.gh.advance(TARGET,w.gh.tree_files(w.head))
                    else:w.gh.default_branch=TARGET
            self.assertEqual(flow.process(w.manifest,now=NOW,crash_hook=change).status,'UNKNOWN')
            self.assertEqual(w.gh.update_refs_requests,0)

    def test_candidate_object_corruption_before_mock_post(self):
        w=World(self.tmp).ready();flow=wired(w);original=flow.transport.put_candidate
        def corrupt(candidate):
            bad=dict(candidate.objects);oid=next(iter(bad));kind,raw=bad[oid];bad[oid]=(kind,raw+b'wrong')
            return original(replace(candidate,objects=bad))
        flow.transport.put_candidate=corrupt
        self.assertEqual(flow.process(w.manifest,now=NOW).status,'UNKNOWN')
        self.assertEqual((w.gh.object_posts,w.gh.update_refs_requests),(0,0))

    def test_lost_reply_and_all_crash_points_recover_get_only_after_fence(self):
        for point in ('AFTER_INTENT','AFTER_OBJECTS','AFTER_REF_INTENT','AFTER_REF'):
            w=World(os.path.join(self.tmp,point)).ready();flow=wired(w)
            with self.assertRaises(SimulatedCrash):flow.process(w.manifest,now=NOW,crash_hook=crash_at(point))
            before=w.gh.update_refs_requests
            # New sender instance, same existing bridge/store/capability: restart.
            fresh=RestrictedMockSender(mock_transport=w.wired().transport,store=w.ledger,manifest=w.manifest,
                plan=flow.transport._plan,approval=flow.transport._approval,validity_reader=flow.validity_reader,clock=lambda:NOW)
            flow.bridge.transport=fresh
            status=flow.process(w.manifest,now=NOW).status
            self.assertEqual(status,'UNKNOWN' if point=='AFTER_REF_INTENT' else 'ADOPTED')
            if point in ('AFTER_REF_INTENT','AFTER_REF'):self.assertEqual(before,w.gh.update_refs_requests)
            self.assertLessEqual(w.gh.update_refs_requests,1)


class ArchiveTests(TempCase):
    def test_all_members_checked_no_disk_extraction(self):
        raw=zip_bytes([('attestation.json',b'{}'),('extra.txt',b'good')])
        self.assertEqual(inspect_archive(raw,require_attestation=True)['extra.txt'],b'good')
        self.assertEqual(os.listdir(self.tmp),[])

    def test_path_traversal_alias_and_duplicate_rejected(self):
        for name in ('../x','/x','a/../x','a\\x','C:x','a//x','.git/x','bad\x01x'):
            with self.subTest(name=name),self.assertRaises(ArchiveUnavailable):inspect_archive(zip_bytes([(name,b'x')]))
        for entries in ([('x',b'a'),('x',b'b')],[('X',b'a'),('x',b'b')],[('a',b'a'),('a/x',b'b')]):
            with self.assertRaises(ArchiveUnavailable):inspect_archive(zip_bytes(entries))

    def test_symlinks_special_files_and_zip_bomb_refused(self):
        for mode in (stat.S_IFLNK,stat.S_IFIFO,stat.S_IFCHR,stat.S_IFSOCK):
            i=zipfile.ZipInfo('bad');i.external_attr=(mode|0o600)<<16
            with self.assertRaises(ArchiveUnavailable):inspect_archive(zip_bytes([(i,b'x')]))
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('bomb',b'0'*100000)
        with self.assertRaises(ArchiveUnavailable):inspect_archive(out.getvalue())
        with self.assertRaises(ArchiveUnavailable):inspect_archive(zip_bytes([('large',b'x'*(MAX_MEMBER+1))]))
        with self.assertRaises(ArchiveUnavailable):inspect_archive(zip_bytes([(str(i),b'') for i in range(MAX_MEMBERS+1)]))

    def test_truncation_crc_and_digest_unknown_not_pass(self):
        raw=zip_bytes([('x',b'abcdef')])
        for bad in (raw[:-10],raw.replace(b'abcdef',b'ABCDEF')):
            with self.assertRaises(ArchiveUnavailable):inspect_archive(bad)
        with self.assertRaises(ArchiveUnavailable):inspect_archive(raw,digest='sha256:'+'f'*64)
        with self.assertRaises(ValueError):strict_json(b'{"x":1,"x":2}')
        with self.assertRaises(ValueError):strict_json(b'{"x":NaN}')

    def downloader(self, raw, *, location='https://fixture.blob.core.windows.net/path?signed=opaque',loops=False,status=200,length=None):
        calls=[];meta={'id':123,'expired':False,'size_in_bytes':len(raw),'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}
        class Metadata:
            def request(self,method,path):
                calls.append((method,path,None));return 200,meta
        class Response(io.BytesIO):
            def __init__(self):super().__init__(raw);self.status=status;self.headers={} if length is None else {'Content-Length':str(length)}
        class Opener:
            def open(self,req,timeout):
                calls.append((req.method,req.full_url,dict(req.header_items())))
                if len(calls)==2 or loops:
                    raise urllib.error.HTTPError(req.full_url,302,'redirect',{'Location':location},None)
                return Response()
        a=GitHubArtifactArchiveGET(repository='fixture/council',metadata_http=Metadata(),token='not-a-real-token',opener=Opener())
        return a,calls,meta

    def test_redirect_receives_zero_credentials_and_exact_official_id(self):
        raw=zip_bytes([('x',b'good')]);a,calls,meta=self.downloader(raw)
        self.assertEqual(a('fixture/council',123),raw)
        self.assertIn('Authorization',calls[1][2]);self.assertNotIn('Authorization',calls[2][2])
        self.assertNotIn('not-a-real-token',repr(a));self.assertEqual(a.redirects,1)
        for repo,aid in [('other/repo',123),('fixture/council',True),('fixture/council',0)]:
            with self.assertRaises(ArchiveUnavailable):a(repo,aid)

    def test_evil_host_scheme_userinfo_and_redirect_loop_rejected(self):
        for url in ('http://fixture.blob.core.windows.net/x','https://evil.example/x',
                    'https://fixture.blob.core.windows.net.evil.example/x','https://u:p@fixture.blob.core.windows.net/x',
                    'https://fixture.blob.core.windows.net:444/x','https://fixture.blob.core.windows.net/x#fragment'):
            a,c,_=self.downloader(zip_bytes([('x',b'x')]),location=url)
            with self.subTest(url=url),self.assertRaises(ArchiveUnavailable):a('fixture/council',123)
            self.assertEqual(len(c),2)
        a,c,_=self.downloader(zip_bytes([('x',b'x')]),loops=True)
        with self.assertRaises(ArchiveUnavailable):a('fixture/council',123)
        self.assertEqual(a.requests,3)
        self.assertTrue(all('Authorization' not in row[2] for row in c[2:]))

    def test_metadata_wrongid_unknown_digest_expired_refused_before_download(self):
        for change in ({'id':124},{'digest':None},{'expired':True},{'size_in_bytes':MAX_ARCHIVE+1}):
            a,c,meta=self.downloader(zip_bytes([('x',b'x')]));meta.update(change)
            with self.assertRaises(ArchiveUnavailable):a('fixture/council',123)
            self.assertEqual(len(c),1)

    def test_partial_network_response_never_passes_or_retries(self):
        for status,length in ((206,None),(200,99999),(200,MAX_ARCHIVE+1)):
            a,c,_=self.downloader(zip_bytes([('x',b'x')]),status=status,length=length)
            with self.assertRaises(ArchiveUnavailable):a('fixture/council',123)
            self.assertEqual(a.requests,2)


class VerifierTests(TempCase):
    def test_independent_workflow_attempt_job_pins_pass(self):
        w=World(self.tmp).ready();ci=CIWorld(w)
        self.assertTrue(strict_ci(ci).read(w.manifest).evidence.trustworthy)

    def test_forged_workflow_attempt_job_and_self_verifier_refused(self):
        w=World(self.tmp).ready()
        for change in ({'workflow_id':9999},{'run_attempt':2},{'job_id':9999},{'verifier_id':w.worker}):
            ci=CIWorld(w)
            with self.subTest(change=change),self.assertRaises((AttestationUnavailable,ValueError)):
                strict_ci(ci,**change).read(w.manifest)

    def test_strict_json_extra_keys_wrong_integer_and_duplicate_check_refused(self):
        w=World(self.tmp).ready()
        for change in ('extra','bool','duplicate','malformed'):
            ci=CIWorld(w)
            if change=='extra':ci.attestation['forged']='present'
            elif change=='bool':ci.attestation['run_attempt']=True
            elif change=='duplicate':ci.attestation['records'].append(copy.deepcopy(ci.attestation['records'][0]))
            else:ci.attestation['records']=[None]
            ci.reseal()
            with self.assertRaises(AttestationUnavailable):strict_ci(ci).read(w.manifest)

    def test_failed_skipped_duplicated_steps_and_incomplete_job_refused(self):
        w=World(self.tmp).ready()
        for change in ('skipped','failed','duplicate','running'):
            ci=CIWorld(w);r=strict_ci(ci)
            if change=='duplicate':ci.job['steps'].append(copy.deepcopy(ci.job['steps'][0]))
            elif change=='running':ci.job['status']='in_progress'
            else:ci.job['steps'][0]['conclusion']=change
            with self.assertRaises(AttestationUnavailable):r.read(w.manifest)

    def test_hidden_unsafe_archive_member_refused_even_if_attestation_valid(self):
        w=World(self.tmp).ready();ci=CIWorld(w)
        att=json.dumps(ci.attestation).encode();ci.archive=zip_bytes([('attestation.json',att),('../evil',b'x')])
        ci.artifact['digest']='sha256:'+hashlib.sha256(ci.archive).hexdigest()
        with self.assertRaises(AttestationUnavailable):strict_ci(ci).read(w.manifest)


class StrictSnapshotTests(TempCase):
    def test_symlink_rejects_close_and_manifest_without_reading_target(self):
        w=World(self.tmp);outside=w.tmp/'outside';outside.write_bytes(b'private target')
        os.symlink(outside,w.workspace/'proof/link')
        w.snapshots=StrictWorkspaceSnapshotStore(str(w.tmp/'strict-snapshots'))
        r=w.capture();self.assertFalse(r.close_gate_open);self.assertIn('rejected_link:proof/link',r.anomalies)
        self.assertFalse(w.snapshots.load(w.snapshot_id).complete)
        self.assertFalse(w.capture().close_gate_open)
        with self.assertRaises(ValueError):w.make_manifest()
        self.assertFalse(w.snapshots._object_path(hashlib.sha256(outside.read_bytes()).hexdigest()).exists())

    def test_full_snapshot_cleanup_duplicate_and_all_identity_bindings(self):
        w=World(self.tmp);w.snapshots=StrictWorkspaceSnapshotStore(str(w.tmp/'strict-snapshots'))
        self.assertTrue(w.capture().close_gate_open);self.assertEqual(w.capture().status,'NOOP_DUPLICATE')
        w.make_manifest();shutil.rmtree(w.workspace)
        source=w.snapshots.load(w.snapshot_id,expected_campaign_id='g61-static',expected_attempt_id=w.attempt_id,
            expected_worker_run_id=w.worker,expected_workspace_fingerprint=w.manifest['workspace_fingerprint'])
        self.assertTrue(source.complete);self.assertEqual(source.files['src/value.py'].data,b'value = 2\n')

    def test_two_read_bytes_change_rejects_issue_close(self):
        w=World(self.tmp);w.snapshots=StrictWorkspaceSnapshotStore(str(w.tmp/'strict-snapshots'))
        original=w.snapshots._put_object
        def changed(data):
            (w.workspace/'src/value.py').write_bytes(b'value = 999\n');return original(data)
        with mock.patch.object(w.snapshots,'_put_object',changed):r=w.capture()
        self.assertEqual(r.status,'UNSTABLE');self.assertFalse(r.close_gate_open)

    def test_snapshot_bytes_tamper_remains_conflict_no_overwrite(self):
        w=World(self.tmp);w.snapshots=StrictWorkspaceSnapshotStore(str(w.tmp/'strict-snapshots'));w.capture()
        p=w.snapshots._object_path(hashlib.sha256(b'value = 2\n').hexdigest());os.chmod(p,0o600);p.write_bytes(b'tampered')
        self.assertEqual(w.capture().status,'CONFLICT');self.assertEqual(p.read_bytes(),b'tampered')


class RecoverySecurityTests(TempCase):
    def test_new_sender_cannot_directly_resend_existing_fence(self):
        w=World(self.tmp).ready();flow=wired(w)
        with self.assertRaises(SimulatedCrash):flow.process(w.manifest,now=NOW,crash_hook=crash_at('AFTER_REF_INTENT'))
        s=RestrictedMockSender(mock_transport=w.wired().transport,store=w.ledger,manifest=w.manifest,
            plan=flow.transport._plan,approval=flow.transport._approval,validity_reader=flow.validity_reader,clock=lambda:NOW)
        with self.assertRaises(PermissionError):s.compare_and_swap(branch=TARGET,expected_head=w.head,candidate_head=s._approval['candidate_commit'])
        self.assertEqual(w.gh.update_refs_requests,0)

    def test_approval_id_cannot_be_reused_for_another_attempt(self):
        w=World(self.tmp).ready();flow=wired(w);self.assertEqual(flow.process(w.manifest,now=NOW).status,'ADOPTED')
        b=World(w.tmp/'other',task_id='B',client=w.client).ready()
        with self.assertRaises(PermissionError):wired(b)
        self.assertEqual(w.gh.update_refs_requests,1)

    def test_unknown_and_after_apply_reply_loss_recover_without_resend(self):
        for mode in ('before','after'):
            w=World(os.path.join(self.tmp,mode)).ready();flow=wired(w);setattr(w.gh, 'lose_reply_' + mode + '_apply', True)
            first=flow.process(w.manifest,now=NOW).status
            self.assertEqual(first,'UNKNOWN' if mode=='before' else 'ADOPTED')
            self.assertEqual(w.gh.update_refs_requests,1)
            self.assertEqual(flow.process(w.manifest,now=NOW).status,'UNKNOWN' if mode=='before' else 'NOOP_DUPLICATE')
            self.assertEqual(w.gh.update_refs_requests,1)

    def test_observation_failure_isolated_independent_task_still_prepares(self):
        w=World(self.tmp).ready();flow=wired(w)
        with mock.patch.object(w.ledger,'_put',return_value='UNKNOWN'):
            self.assertEqual(flow.process(w.manifest,now=NOW).status,'UNKNOWN')
        b=World(w.tmp/'next',task_id='B',gh=w.gh).ready()
        self.assertEqual(prepare(b).status,'PREPARED_OFF');self.assertEqual(w.gh.update_refs_requests,0)

    def test_rebound_attestation_and_worker_self_hash_no_authority(self):
        w=World(self.tmp).ready()
        for field in ('result_digest','source_digest','scope_digest','expected_target_head'):
            ci=CIWorld(w);ci.attestation[field]='f'*64;ci.reseal()
            with self.assertRaises(AttestationUnavailable):strict_ci(ci).read(w.manifest)
        ci=CIWorld(w);ci.attestation['records'][0]['verifier_id']=w.worker
        ci.attestation['records'][0]['record_digest']=digest({k:v for k,v in ci.attestation['records'][0].items() if k!='record_digest'})
        ci.reseal()
        with self.assertRaises(AttestationUnavailable):strict_ci(ci).read(w.manifest)


def run_g63_matrix():
    import tempfile
    from pathlib import Path
    observed=run_g62_matrix()
    with tempfile.TemporaryDirectory() as tmp:
        for case in ('M01-valid-replay','M02-expired','M03-head-race','M04-task-change','M05-default-drift',
                     'M06-before-fence-crash','M07-after-fence-crash','M08-after-ref-crash','M09-lost-before','M10-lost-after'):
            w=World(Path(tmp)/case).ready();flow=wired(w);first=None
            def hook(point):
                if point=='AFTER_REF_INTENT':
                    if case=='M03-head-race':w.gh.advance(TARGET,w.gh.tree_files(w.head))
                    if case=='M04-task-change':w.gh.issues[w.number]['labels']={'totalCount':1,'nodes':[{'name':'symphony:invalid'}]}
                    if case=='M05-default-drift':w.gh.default_branch=TARGET
            if case=='M02-expired':
                try:wired(w,now='2026-10-10T03:00:00Z')
                except PermissionError:first='REJECTED'
                restarted='REJECTED'
            else:
                points={'M06-before-fence-crash':'AFTER_OBJECTS','M07-after-fence-crash':'AFTER_REF_INTENT','M08-after-ref-crash':'AFTER_REF'}
                if case.startswith('M09'):w.gh.lose_reply_before_apply=True
                if case.startswith('M10'):w.gh.lose_reply_after_apply=True
                try:first=flow.process(w.manifest,now=NOW,crash_hook=crash_at(points[case]) if case in points else hook).status
                except SimulatedCrash:first='CRASH'
                if case=='M05-default-drift':w.gh.default_branch='main'
                before=w.gh.update_refs_requests;shutil.rmtree(w.workspace)
                s=RestrictedMockSender(mock_transport=w.wired().transport,store=w.ledger,manifest=w.manifest,
                    plan=flow.transport._plan,approval=flow.transport._approval,validity_reader=flow.validity_reader,clock=lambda:NOW)
                flow.bridge.transport=s;restarted=flow.process(w.manifest,now=NOW).status
                if case!='M06-before-fence-crash':assert before==w.gh.update_refs_requests
            assert w.gh.update_refs_requests<=1 and w.gh.head('main')==w.head
            observed.append({'case':case,'first':first,'after_cleanup_restart':restarted,
                'update_refs_requests':w.gh.update_refs_requests,'our_ref_mutations':w.gh.ref_mutations,
                'real_github_writes':0,'model_provider_LIVE':0,'default_branch_unchanged':True})
        for root,_,files in os.walk(tmp):
            for n in files:os.chmod(os.path.join(root,n),0o600)
    return observed


class FinalBoundaryTests(TempCase):
    def test_expired_authorization_still_allows_only_verified_receipt_get_replay(self):
        w=World(self.tmp).ready();flow=wired(w);self.assertEqual(flow.process(w.manifest,now=NOW).status,'ADOPTED')
        new=RestrictedMockSender(mock_transport=w.wired().transport,store=w.ledger,manifest=w.manifest,
            plan=flow.transport._plan,approval=flow.transport._approval,validity_reader=flow.validity_reader,
            clock=lambda:'2026-10-10T03:00:00Z')
        flow.bridge.transport=new
        before=w.gh.object_posts
        self.assertEqual(flow.process(w.manifest,now=NOW).status,'NOOP_DUPLICATE')
        self.assertEqual(w.gh.object_posts,before);self.assertEqual(w.gh.update_refs_requests,1)
        with self.assertRaises(PermissionError):new.compare_and_swap(branch=TARGET,expected_head=w.head,
            candidate_head=new._approval['candidate_commit'])

    def test_committed_synthetic_workflow_never_injects_tokens_or_enables_live(self):
        from pathlib import Path
        p=Path(__file__).resolve().parents[3]/'.github/workflows/symphony-g63-synthetic-verifier.yml'
        s=p.read_text()
        self.assertIn('contents: read',s);self.assertNotIn('pull_request_target',s)
        self.assertNotIn('secrets.',s);self.assertIn('persist-credentials: false',s)
        for flag in ('--network none','--read-only','--cap-drop ALL','--security-opt no-new-privileges','--user 65534:65534'):
            self.assertGreaterEqual(s.count(flag),3)
        self.assertNotIn('-e GITHUB_TOKEN',s);self.assertNotIn('-e GH_TOKEN',s)
        self.assertIn('actual_candidate_attestation\':False',s)
        self.assertIn('sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce',s)

    def test_exact_fault_matrix_includes_old_18_cases(self):
        r=run_g63_matrix()
        self.assertEqual(len(r),28);self.assertEqual(len([x for x in r if x['case'][0] in 'KL']),18)
        self.assertTrue(all(x['real_github_writes']==0 and x['model_provider_LIVE']==0 for x in r))
