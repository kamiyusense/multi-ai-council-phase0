"""Actual original reader/host/receipt chain with credential-free recorded IO."""
import base64
import hashlib
from dataclasses import replace
from .test_symphony_g61_production_wiring import TempCase, NOW, TRUSTED, REPO
from .test_symphony_g72_runtime import ObservedWorld
from .test_symphony_ledger_reader import RecordedGET, HEAD, BRANCH
from .test_symphony_g62_readiness import CIWorld
from .test_symphony_g63_connection import strict_ci
from ..symphony_operator_readiness import (RecoveryLedgerContentsClient, OperatorRecoveryHost,
                                          ReadOnlyGitObjectReader)
from ..symphony_verifier_provenance import PinnedSourceCIVerifier
from ..symphony_g62_attestation import AttestationUnavailable
from ..symphony_git_adoption import _git_oid, make_adoption_id
from ..symphony_result_manifest import digest, seal_manifest


def attached(w):
    http = RecordedGET({p:c.text for p,c in w.client.files.items()})
    client = RecoveryLedgerContentsClient(http, repository=REPO, branch=BRANCH,
                                          default_branch='main', expected_head=HEAD)
    h = OperatorRecoveryHost(client, campaign_id='g61-static', generation=w.generation,
        target_reader=w.target_reader(), candidate_reader=ReadOnlyGitObjectReader(w.gh,repository=REPO))
    return h, http


class RecoveryHostTests(TempCase):
    def test_original_host_view_and_unknown_without_copy_or_adoption(self):
        w = ObservedWorld(self.tmp).ready(); host, http = attached(w)
        before = digest(w.campaign_store.restore('g61-static').state.to_dict())
        out = host.handle('restore')
        self.assertEqual(out['view']['protocol'],'SYMPHONY_G73_HOST_VIEW_V1')
        self.assertEqual(out['attempts'][-1]['outcome'],'UNKNOWN')
        self.assertFalse(out['checkpoint_applied']); self.assertEqual(out['real_publication'],0)
        self.assertEqual(before,digest(w.campaign_store.restore('g61-static').state.to_dict()))
        self.assertTrue(all(m=='GET' and b is None for m,p,b in http.calls))
        self.assertEqual(w.gh.object_posts,0)

    def test_complete_original_mock_receipt_inspected_but_running_task_not_done(self):
        w = ObservedWorld(self.tmp).ready()
        a,b,m,flow,seam = w.adapter()._flow(w.attempt_id)
        self.assertEqual(flow.process(m,now=NOW).status,'ADOPTED') # existing mock setup only
        host, http = attached(w); before = digest(w.campaign_store.restore('g61-static').state.to_dict())
        counts = (w.gh.object_posts,w.gh.update_refs_requests)
        for _ in range(2):
            out = host.handle('inspect_receipt',manifest=m)
            self.assertEqual(out['status'],'RECEIPT_INTEGRITY_VERIFIED_NOT_APPLIED')
            self.assertFalse(out['applied'])
        self.assertEqual(before,digest(w.campaign_store.restore('g61-static').state.to_dict()))
        self.assertEqual(counts,(w.gh.object_posts,w.gh.update_refs_requests))
        self.assertTrue(all(method=='GET' and body is None for method,path,body in http.calls))

    def test_no_checkpoint_or_receipt_is_hold_not_synthesized_done(self):
        w = ObservedWorld(self.tmp).ready(); a,b,m,flow,seam = w.adapter()._flow(w.attempt_id)
        h, http = attached(w)
        for p in list(http.files):
            if p.startswith('symphony_campaigns/'): del http.files[p]
        self.assertEqual(h.restore()['view']['status'],'HOLD_CHECKPOINT_MISSING')
        self.assertEqual(h.inspect_receipt(m)['status'],'HOLD_RECEIPT_MISSING')
        self.assertEqual(h.restore()['attempts'][-1]['outcome'],'UNKNOWN')

    def test_corrupt_original_receipt_lock_and_candidate_is_conflict(self):
        w = ObservedWorld(self.tmp).ready(); a,b,m,flow,seam = w.adapter()._flow(w.attempt_id)
        self.assertEqual(flow.process(m,now=NOW).status,'ADOPTED')
        h, http = attached(w);intent=w.ledger.get('g61-static',make_adoption_id(m),'intent')
        key=w.ledger._lock_path(intent);del http.files[key]
        self.assertEqual(h.inspect_receipt(m)['status'],'CONFLICT')
        http.files[key]=w.client.files[key].text
        w.gh.tamper_blob_reads[next(oid for oid,(kind,raw) in w.gh.objects.items() if kind=='blob')]=b'corrupted'
        # Force tamper of a candidate blob rather than an unrelated base object.
        candidate=h.transport.read_candidate(intent['candidate_commit'])
        if candidate:
            oid=next(oid for oid,(kind,raw) in candidate.objects.items() if kind=='blob')
            w.gh.tamper_blob_reads[oid]=b'corrupted'
        self.assertEqual(h.inspect_receipt(m)['status'],'CONFLICT')

    def test_host_flags_operations_never_enable_write_or_model(self):
        w=ObservedWorld(self.tmp).ready();h,http=attached(w);before=len(http.calls)
        h.mode='LIVE';h.live_authorized=True
        for op in ('admission','replay','snapshot','settle','recover','publish','close_issue','execute'):
            with self.assertRaises(PermissionError):h.handle(op)
        with self.assertRaises(PermissionError):h.execute()
        with self.assertRaises(PermissionError):h.transport._rest('POST','git/blobs',{})
        self.assertEqual(before,len(http.calls));self.assertEqual(w.gh.update_refs_requests,0)

    def test_wrong_generation_and_cross_campaign_deny_authority(self):
        w=ObservedWorld(self.tmp).ready();h,http=attached(w);h.adapter.generation+=1
        with self.assertRaises(ValueError):h.restore()
        a,b,m,flow,seam=w.adapter()._flow(w.attempt_id)
        rebound=seal_manifest({**m,'campaign_id':'other-campaign'})
        self.assertEqual(h.inspect_receipt(rebound)['status'],'CONFLICT')
        self.assertEqual(w.gh.update_refs_requests,0)


def provenance(ci):
    original=strict_ci(ci)
    source=ci.w.head
    original_request=ci.request
    workflows={source:ci.workflow,ci.contract.candidate_commit:ci.workflow}
    def get(method,path,body=None):
        if '/contents/' in path:
            ci.log.append((method,path));assert method=='GET' and body is None
            raw=workflows[path.split('?ref=')[1]]
            return 200,{'type':'file','path':ci.contract.workflow_path,'encoding':'base64',
                         'sha':_git_oid('blob',raw),'content':base64.b64encode(raw).decode()}
        return original_request(method,path,body)
    reader=PinnedSourceCIVerifier(type('GET',(),{'request':staticmethod(get)})(),original.contract,
        workflow_source_commit=source,archive_get=lambda r,i:ci.archive,
        trusted_verifiers=TRUSTED,worker_run_id=ci.w.worker)
    return reader, workflows


class WorkflowProvenanceTests(TempCase):
    def world(self):
        w=ObservedWorld(self.tmp).ready();w.adapter()._flow(w.attempt_id)
        return w,CIWorld(w)

    def test_distinct_operator_source_and_candidate_same_pinned_bytes(self):
        w,ci=self.world();r,workflows=provenance(ci)
        self.assertNotEqual(r.workflow_source_commit,r.contract.candidate_commit)
        self.assertTrue(r.read(w.manifest).evidence.trustworthy)
        self.assertTrue(any('?ref='+r.workflow_source_commit in p for m,p in ci.log))
        self.assertTrue(any('?ref='+r.contract.candidate_commit in p for m,p in ci.log))
        self.assertEqual(w.gh.update_refs_requests,0)

    def test_worker_changed_or_source_changed_workflow_rejected(self):
        w,ci=self.world();r,workflows=provenance(ci)
        for commit in list(workflows):
            good=workflows[commit];workflows[commit]=good+b'# worker changed workflow'
            with self.assertRaises(AttestationUnavailable):r.read(w.manifest)
            workflows[commit]=good

    def test_run_head_is_candidate_not_workflow_source(self):
        w,ci=self.world();r,workflows=provenance(ci);ci.run['head_sha']=r.workflow_source_commit
        with self.assertRaises(AttestationUnavailable):r.read(w.manifest)

    def test_source_pin_never_bypasses_original_job_archive_scope_bindings(self):
        w,ci=self.world();r,workflows=provenance(ci);ci.attestation['scope_digest']='f'*64;ci.reseal()
        with self.assertRaises(AttestationUnavailable):r.read(w.manifest)
        ci.attestation['scope_digest']=w.manifest['scope_digest'];ci.reseal()
        ci.job['steps'][0]['conclusion']='skipped'
        with self.assertRaises(AttestationUnavailable):r.read(w.manifest)

    def test_synthetic_attestation_cannot_be_promoted(self):
        w,ci=self.world();r,workflows=provenance(ci)
        ci.attestation['protocol']='SYMPHONY_G72_SYNTHETIC_CANDIDATE_V1';ci.reseal()
        with self.assertRaises(AttestationUnavailable):r.read(w.manifest)

    def test_workflow_blob_oid_and_path_rejected_before_archive(self):
        w,ci=self.world();r,workflows=provenance(ci)
        get=r.http.request;archives=[]
        r.archive_get=lambda repo,oid:archives.append(oid) or ci.archive
        def bad(method,path,body=None):
            status,data=get(method,path,body)
            if '/contents/' in path:data={**data,'sha':'f'*40}
            return status,data
        r.http.request=bad
        with self.assertRaises(AttestationUnavailable):r.read(w.manifest)
        self.assertEqual(archives,[])
