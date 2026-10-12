"""Candidate bytes, immutable operator pins, synthetic provenance regressions."""
import base64
import copy
import hashlib
import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path
from .test_symphony_g61_production_wiring import World, TempCase
from .test_symphony_g62_readiness import CIWorld
from ..symphony_g72_candidate import (CandidateExecutionPins, prepare_candidate_inputs, export_inputs,
    SyntheticCandidateQualificationReader, PROTOCOL)
from ..scripts.symphony_g72_synthetic_candidate import inputs
from ..symphony_g63_verifier import PinnedCIContract
from ..symphony_result_manifest import digest


def qualification(tmp):
    w=World(tmp).ready();ci=CIWorld(w)
    ci.run['workflow_id']=7000;ci.job['status']='completed';ci.job['run_id']=ci.contract.run_id;ci.job['name']='synthetic-verifier'
    contract=PinnedCIContract(**ci.contract.__dict__,workflow_id=7000,run_attempt=1,job_id=7101)
    plan=inputs(contract.workflow_sha256,'python@sha256:'+'1'*64,'scanner@sha256:'+'2'*64)
    body={'protocol':PROTOCOL,'synthetic':True,'workflow_source_commit':contract.candidate_commit,
        'workflow_sha256':contract.workflow_sha256,'run_id':contract.run_id,'run_attempt':1,'job_name':'synthetic-verifier',
        'actual_candidate_attestation':False,'actual_result_adoption':0,'model_starts':0,
        **{k:plan[k] for k in ('candidate_commit','candidate_tree','result_digest','source_digest',
                             'scope_digest','expected_target_head','input_digest')},
        'checks':{k:'PASS' for k in ('syntax','tests','secret_scan')}}
    def seal():
        att={**body,'attestation_digest':digest(body)}
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('g72-attestation.json',json.dumps(att))
        ci.archive=out.getvalue();ci.artifact['digest']='sha256:'+hashlib.sha256(ci.archive).hexdigest()
    seal()
    def reader():return SyntheticCandidateQualificationReader(ci,contract,archive_get=lambda r,i:ci.archive,expected_inputs=plan)
    return ci,body,seal,reader,plan


class G72CandidateTests(TempCase):
    def test_full_synthetic_git_candidate_objects_and_export_hashes(self):
        plan=inputs('f'*64,'python@sha256:'+'1'*64,'scanner@sha256:'+'2'*64)
        root=Path(self.tmp)/'candidate';export_inputs(plan,root)
        self.assertEqual((root/'value.py').read_bytes(),b'value = 2\n')
        self.assertTrue(plan['synthetic']);self.assertFalse(plan['publication_authorized'])
        self.assertEqual(len(plan['candidate_commit']),40)
        with self.assertRaises(ValueError):export_inputs(plan,root)

    def test_tampered_candidate_bytes_or_path_never_export(self):
        for field,value in [('content_base64',base64.b64encode(b'wrong').decode()),('sha256','f'*64)]:
            plan=inputs('f'*64,'python@sha256:'+'1'*64,'scanner@sha256:'+'2'*64)
            plan['files']['value.py'][field]=value
            plan['input_digest']=digest({k:v for k,v in plan.items() if k!='input_digest'})
            with self.assertRaises(ValueError):export_inputs(plan,Path(self.tmp)/field)

    def test_independent_actual_archive_provenance_returns_synthetic_only(self):
        ci,body,seal,reader,plan=qualification(self.tmp)
        r=reader().read();self.assertEqual(r['status'],'QUALIFIED_SYNTHETIC_ONLY')
        self.assertFalse(r['production_verification_evidence'])
        self.assertNotEqual(body['candidate_commit'],body['workflow_source_commit'])

    def test_cross_run_job_attempt_candidate_source_scope_head_digest_forgery(self):
        ci,body,seal,reader,plan=qualification(self.tmp)
        changes={'run_id':7002,'run_attempt':2,'job_name':'other-job','candidate_commit':'f'*40,
            'source_digest':'f'*64,'scope_digest':'f'*64,'expected_target_head':'f'*40,
            'result_digest':'f'*64,'input_digest':'f'*64,'workflow_source_commit':'f'*40,
            'workflow_sha256':'f'*64,'actual_candidate_attestation':True}
        original=copy.deepcopy(body)
        for key,value in changes.items():
            body.clear();body.update(original);body[key]=value;seal()
            with self.subTest(key=key),self.assertRaises(Exception):reader().read()

    def test_skipped_failed_duplicate_steps_and_wrong_workflow_pin_refused(self):
        ci,body,seal,reader,plan=qualification(self.tmp)
        original=copy.deepcopy(ci.job['steps'])
        for mode in ('skipped','failure','duplicate'):
            ci.job['steps']=copy.deepcopy(original)
            if mode=='duplicate':ci.job['steps'].append(copy.deepcopy(ci.job['steps'][0]))
            else:ci.job['steps'][0]['conclusion']=mode
            with self.assertRaises(Exception):reader().read()
        ci.job['steps']=original;ci.run['workflow_id']=7002
        with self.assertRaises(Exception):reader().read()

    def test_authenticated_archive_digest_and_unsafe_zip_member_refused(self):
        ci,body,seal,reader,plan=qualification(self.tmp)
        ci.artifact['digest']='sha256:'+'f'*64
        with self.assertRaises(Exception):reader().read()
        seal();out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('../unsafe',b'bad')
        ci.archive=out.getvalue();ci.artifact['digest']='sha256:'+hashlib.sha256(ci.archive).hexdigest()
        with self.assertRaises(Exception):reader().read()

    def test_worker_cannot_choose_test_command_images_or_workflow(self):
        w=World(self.tmp).ready();source=w.snapshots.load(w.snapshot_id)
        good=CandidateExecutionPins('f'*64,('test_value',),'python@sha256:'+'1'*64,'scanner@sha256:'+'2'*64)
        for pins in (replace(good,test_modules=('test;curl',)),replace(good,python_image='python:latest'),replace(good,workflow_sha256='')):
            with self.assertRaises(ValueError):prepare_candidate_inputs(manifest=w.manifest,source=source,
                created_at='2026-10-10T01:00:00Z',pins=pins)

    def test_non_synthetic_inputs_never_production_qualified(self):
        ci,body,seal,reader,plan=qualification(self.tmp);plan['synthetic']=False
        with self.assertRaises(ValueError):reader()

class G72PublisherTests(TempCase):
    def test_exact_proposal_has_one_non_force_expected_head_ref_and_no_capability(self):
        from .test_symphony_g62_readiness import preparer,prepare
        from ..symphony_g72_publisher import PublisherPreparationBoundary
        from ..symphony_g63_sender import RestrictedMockSender
        w=World(self.tmp).ready();p=PublisherPreparationBoundary(preparer(w));plan=prepare(w).plan
        proposal=p.capability_proposal(plan=plan,manifest=w.manifest,approval_id='future-only',expires_at='2026-10-10T02:00:00Z')
        update=proposal['single_ref_request']['variables']['input']['refUpdates']
        self.assertEqual(len(update),1);self.assertFalse(update[0]['force'])
        self.assertEqual(update[0]['beforeOid'],w.head);self.assertFalse(proposal['authorized_to_send'])
        p.mode='LIVE';p.live_authorized=True
        with self.assertRaises(PermissionError):p.execute(proposal)
        self.assertEqual(w.gh.update_refs_requests,0)
        with self.assertRaises(ValueError):PublisherPreparationBoundary(w.wired().transport)

    def test_tampered_plan_or_ref_cannot_be_proposed(self):
        from .test_symphony_g62_readiness import preparer,prepare
        from ..symphony_g72_publisher import PublisherPreparationBoundary
        w=World(self.tmp).ready();p=PublisherPreparationBoundary(preparer(w));plan=prepare(w).plan
        bad=copy.deepcopy(plan);bad['single_ref_request']['variables']['input']['refUpdates'][0]['force']=True
        bad['plan_digest']=digest({k:v for k,v in bad.items() if k!='plan_digest'})
        with self.assertRaises(ValueError):p.capability_proposal(plan=bad,manifest=w.manifest,approval_id='future',expires_at='later')
        self.assertEqual(w.gh.update_refs_requests,0)
