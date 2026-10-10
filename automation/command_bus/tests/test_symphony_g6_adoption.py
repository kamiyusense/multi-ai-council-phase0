from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import subprocess
import unittest
from dataclasses import replace

from .symphony_g6_fixtures import Fixture, MemoryGit, SimulatedCrash, crash_at, HEAD, NEXT, TARGET, REPOSITORY, NOW
from .test_symphony_campaign_store import FakeCampaignContents
from ..executor_backend import ExecutorContent
from ..symphony_autonomous_runtime import AutonomousCampaignKernel, CampaignState, CampaignTask, TaskStatus
from ..symphony_autonomous_policy import QuotaState
from ..symphony_campaign_store import GitHubCampaignStateStore
from ..symphony_git_adoption import AppendOnlyAdoptionStore, make_adoption_id, construct_candidate
from ..symphony_result_adoption import AdoptionAction, decide_verified_result_adoption
from ..symphony_result_manifest import (FileEntry, ProofMutationPolicy, MutationOperation, SourceResult, canonical,
    classify_mutation, digest, inventory_digest, seal_manifest)


class G6ResultInspectionTests(unittest.TestCase):
    def inspect(self, fixture=None, **changes):
        f = fixture or Fixture(); target = f.git.read_target()
        args = dict(manifest=f.manifest, attempt=f.attempt_reader(), target=target,
            source=f.source_reader(), validity=f.validity_reader(target), verification=f.verification_reader())
        args.update(changes)
        return decide_verified_result_adoption(**args)

    def test_actual_add_modify_hashes_paths_and_verification_allow_adopt(self):
        f=Fixture(); result=self.inspect(f)
        self.assertEqual(result.decision.action, AdoptionAction.ADOPT)
        self.assertEqual(result.evidence['changed_paths'], ['proof/answer.md', 'src/value.py'])
        self.assertEqual(f.attempt_reader().terminal['outcome'], 'UNKNOWN')

    def test_terminal_alone_does_not_authorize_adoption(self):
        self.assertEqual(self.inspect(manifest=None).decision.action, AdoptionAction.HOLD_AUTHORITY)
        for status in ['WORKER_COMPLETED','WORKER_FAILED','WORKER_STOPPED']:
            f=Fixture(); snap=f.attempt_reader(); terminal=dict(snap.terminal);terminal['evidence_refs'][-1]='sym-g5-status:'+status
            result=self.inspect(f,manifest=None,attempt=replace(snap,terminal=terminal))
            self.assertEqual(result.decision.action,AdoptionAction.HOLD_AUTHORITY)

    def test_all_mutation_classes_derived_from_actual_type_mode_bytes(self):
        text=FileEntry(b'x\n'); other=FileEntry(b'y\n')
        cases=[(None,text,{},'ADD'),(text,other,{},'MODIFY'),(text,None,{},'DELETE'),
               (text,other,{'source_path':'old'},'RENAME'),(text,other,{'source_path':'old','source_retained':True},'COPY'),
               (text,FileEntry(b'x\n','100755'),{},'MODE_CHANGE'),(None,FileEntry(b'target','120000','symlink'),{},'SYMLINK'),
               (None,FileEntry(b'a'*40,'160000','gitlink'),{},'SUBMODULE'),(None,FileEntry(b'x\0'),{},'BINARY'),
               (None,FileEntry(b'x','bad','unknown'),{},'UNCLASSIFIED')]
        for old,new,options,expected in cases:
            with self.subTest(expected=expected):self.assertEqual(classify_mutation(old,new,**options).value,expected)

    def test_unsafe_mutations_held_and_policy_can_be_opened_explicitly(self):
        for change in [None,FileEntry(b'x','100755'),FileEntry(b'target','120000','symlink'),FileEntry(b'a'*40,'160000','gitlink'),FileEntry(b'\0binary')]:
            f=Fixture()
            if change is None:del f.source_files['src/value.py']
            else:f.source_files['src/value.py']=change
            f.reseal();self.assertEqual(self.inspect(f).decision.action,AdoptionAction.ISOLATE_TASK)
        f=Fixture();del f.source_files['src/value.py'];f.reseal()
        policy=ProofMutationPolicy(allowed_operations=frozenset({MutationOperation.ADD,MutationOperation.DELETE}))
        self.assertEqual(self.inspect(f,policy=policy).decision.action,AdoptionAction.ADOPT)

    def test_path_traversal_absolute_git_protected_and_prefix_boundary_rejected(self):
        for path in ['../escape','/outside','proof/../escape','proof/.git/config','proof/./x','proof//x','proof\\x','C:/outside','proofx/x','.github/workflows/x','AGENTS.md']:
            f=Fixture();f.source_files[path]=FileEntry(b'x\n');f.reseal()
            with self.subTest(path=path):self.assertEqual(self.inspect(f).decision.action,AdoptionAction.ISOLATE_TASK)

    def test_undeclared_files_duplicate_paths_wrong_content_hash_and_digest_conflict(self):
        f=Fixture();f.source_files['proof/extra']=FileEntry(b'undeclared\n')
        self.assertEqual(self.inspect(f).decision.action,AdoptionAction.CONFLICT)
        for key,value in [('result_digest','0'*64),('source_digest','0'*64)]:
            f=Fixture();f.manifest[key]=value
            if key!='result_digest':f.manifest=seal_manifest(f.manifest)
            self.assertEqual(self.inspect(f).decision.action,AdoptionAction.CONFLICT)
        f=Fixture();f.manifest['mutations'].append(copy.deepcopy(f.manifest['mutations'][0]));f.manifest=seal_manifest(f.manifest)
        self.assertEqual(self.inspect(f).decision.action,AdoptionAction.CONFLICT)
        f=Fixture();f.manifest['mutations'][0]['content_sha256']='0'*64;f.manifest=seal_manifest(f.manifest)
        self.assertEqual(self.inspect(f).decision.action,AdoptionAction.CONFLICT)

    def test_worker_attempt_workspace_issue_and_generation_mismatch_conflict(self):
        for key,value in [('worker_run_id','f'*32),('attempt_id','attempt-wrong'),('workspace_fingerprint','f'*64),('issue_id','STATIC-wrong'),('generation',True),('attempt_number',True),('runner_generation',True),('task_id','B')]:
            f=Fixture();f.manifest[key]=value;f.manifest=seal_manifest(f.manifest)
            with self.subTest(key=key):self.assertEqual(self.inspect(f).decision.action,AdoptionAction.CONFLICT)

    def test_fresh_head_advance_is_task_replan_and_unavailable_validity_holds(self):
        f=Fixture();target=replace(f.git.read_target(),head=NEXT)
        self.assertEqual(self.inspect(f,target=target).decision.action,AdoptionAction.STALE_REPLAN)
        self.assertEqual(self.inspect(validity=None).decision.action,AdoptionAction.HOLD_AUTHORITY)
        f=Fixture();f.valid=False;self.assertEqual(self.inspect(f).decision.action,AdoptionAction.ISOLATE_TASK)
        f=Fixture();f.request_digest='f'*64;self.assertEqual(self.inspect(f).decision.action,AdoptionAction.ISOLATE_TASK)

    def test_independent_verification_missing_failed_wrong_result_or_secret_holds(self):
        self.assertEqual(self.inspect(verification=None).decision.action,AdoptionAction.HOLD_AUTHORITY)
        f=Fixture();f.checks['tests']=False;self.assertEqual(self.inspect(f).decision.action,AdoptionAction.HOLD_AUTHORITY)
        v=replace(f.verification_reader(),result_digest='f'*64);self.assertEqual(self.inspect(f,verification=v).decision.action,AdoptionAction.HOLD_AUTHORITY)
        f=Fixture();f.source_files['proof/answer.md']=FileEntry(('ghp_'+'syntheticcredential'*3+'\n').encode());f.reseal()
        self.assertEqual(self.inspect(f).decision.action,AdoptionAction.ISOLATE_TASK)

    def test_incomplete_source_and_file_directory_collision_do_not_construct(self):
        f=Fixture();self.assertEqual(self.inspect(f,source=replace(f.source_reader(),complete=False)).decision.action,AdoptionAction.HOLD_AUTHORITY)
        f.source_files['src']=FileEntry(b'blob parent');f.reseal();self.assertEqual(self.inspect(f).decision.action,AdoptionAction.ISOLATE_TASK)

    def test_same_inputs_same_decision_and_no_input_mutation(self):
        f=Fixture();before=copy.deepcopy(f.manifest)
        self.assertEqual(self.inspect(f),self.inspect(f));self.assertEqual(before,f.manifest)

    def test_real_g51_terminal_is_immutable_reference_not_a_result_or_live_authorization(self):
        path=pathlib.Path(__file__).resolve().parents[3]/'docs/evidence/symphony-g51-local-live/issue-342/terminal-durable-readback.json'
        raw=path.read_bytes();original=hashlib.sha256(raw).hexdigest();fixture=json.loads(raw)['snapshot'];client=FakeCampaignContents()
        for kind in ['intent','started','terminal']:
            p=f"symphony_attempts/{fixture['identity']['campaign_id']}/{fixture['identity']['attempt_id']}/{kind}.json"
            client.files[p]=ExecutorContent(p,canonical(fixture[kind]),'fixture')
        from ..symphony_attempt_store import GitHubAutonomousAttemptStore
        snap=GitHubAutonomousAttemptStore(client,write_branch='fixture/history').restore(fixture['identity']['campaign_id'],fixture['identity']['attempt_id'])
        self.assertEqual(self.inspect(attempt=snap,manifest=None).decision.action,AdoptionAction.HOLD_AUTHORITY)
        self.assertEqual(snap.terminal['outcome'],'UNKNOWN');self.assertEqual(len(client.files),3)
        self.assertEqual(original,hashlib.sha256(path.read_bytes()).hexdigest())


    def test_explicit_rename_and_copy_are_conservative_profile_holds(self):
        for retained,operation in [(False,"RENAME"),(True,"COPY")]:
            f=Fixture();origin="src/value.py";old=f.base[origin];f.source_files["proof/relocated"]=old
            if not retained:del f.source_files[origin]
            f.reseal();f.manifest["mutations"]=[m for m in f.manifest["mutations"] if m["path"] not in {origin,"proof/relocated"}]
            if retained:
                new=f.source_files[origin];f.manifest["mutations"].append({"path":origin,"source_path":None,"operation":"MODIFY","before_sha256":old.sha256,"content_sha256":new.sha256,"mode":new.mode,"type":new.kind})
            f.manifest["mutations"].append({"path":"proof/relocated","source_path":origin,"operation":operation,"before_sha256":old.sha256,"content_sha256":old.sha256,"mode":old.mode,"type":old.kind});f.manifest=seal_manifest(f.manifest)
            self.assertEqual(self.inspect(f).decision.action,AdoptionAction.ISOLATE_TASK)

    def test_missing_secret_attestation_or_malformed_verifier_does_not_adopt(self):
        f=Fixture();del f.checks["secret_scan"];self.assertEqual(self.inspect(f).decision.action,AdoptionAction.HOLD_AUTHORITY)
        for bad in [replace(f.verification_reader(),checks={"syntax":True,"tests":True,"secret_scan":"yes"}),replace(f.verification_reader(),evidence_refs=({},))]:
            self.assertEqual(self.inspect(f,verification=bad).decision.action,AdoptionAction.HOLD_AUTHORITY)

    def test_declared_mode_operation_lie_cannot_bypass_actual_mutation_class(self):
        f=Fixture();f.source_files["src/value.py"]=FileEntry(b"value = 2\n","100755");f.reseal();f.manifest["mutations"][-1]["operation"]="MODIFY";f.manifest=seal_manifest(f.manifest)
        self.assertEqual(self.inspect(f).decision.action,AdoptionAction.CONFLICT)

class G6CrashRecoveryTests(unittest.TestCase):
    def test_A_intent_then_crash_before_objects_restores_and_adopts_once(self):
        f=Fixture()
        with self.assertRaises(SimulatedCrash):f.run(hook=crash_at('AFTER_INTENT'))
        self.assertEqual(f.git.object_creates,0);self.assertEqual(f.git.ref_calls,0)
        self.assertEqual(f.run(now='2026-10-11T00:00:00Z').status,'ADOPTED')
        self.assertEqual(f.git.ref_calls,1);self.assertEqual(f.git.ref_mutations,1)

    def test_B_objects_then_crash_before_ref_reuses_content_addressed_objects(self):
        f=Fixture()
        with self.assertRaises(SimulatedCrash):f.run(hook=crash_at('AFTER_OBJECTS'))
        created=f.git.object_creates;self.assertGreater(created,0);self.assertEqual(f.git.head,HEAD)
        self.assertEqual(f.run().status,'ADOPTED');self.assertEqual(f.git.object_creates,created);self.assertEqual(f.git.ref_calls,1)

    def test_C_ref_success_response_lost_then_crash_before_receipt_GET_only(self):
        f=Fixture();f.git.lose_ref_response=True
        with self.assertRaises(SimulatedCrash):f.run(hook=crash_at('AFTER_REF'))
        self.assertNotEqual(f.git.head,HEAD);self.assertEqual(f.git.ref_calls,1)
        self.assertEqual(f.run().status,'ADOPTED');self.assertEqual(f.git.ref_calls,1)

    def test_D_receipt_replay_NOOP_even_if_target_later_advances(self):
        f=Fixture();first=f.run();self.assertEqual(first.status,'ADOPTED');counts=(f.git.ref_calls,f.git.object_calls,f.client.create_calls)
        f.git.head=NEXT;second=f.run();self.assertEqual(second.status,'NOOP_DUPLICATE');self.assertEqual(second.receipt,first.receipt)
        self.assertEqual(counts,(f.git.ref_calls,f.git.object_calls,f.client.create_calls))

    def test_E_canonical_advanced_before_inspection_zero_git_writes(self):
        f=Fixture();f.git.head=NEXT;self.assertEqual(f.run().status,'STALE_REPLAN');self.assertEqual((f.git.ref_calls,f.git.object_calls),(0,0))

    def test_F_invalid_task_zero_git_writes_and_no_campaign_termination(self):
        f=Fixture();f.valid=False;self.assertEqual(f.run().status,'ISOLATE_TASK');self.assertEqual((f.git.ref_calls,f.git.object_calls),(0,0))

    def test_G_delete_result_zero_git_writes(self):
        f=Fixture();del f.source_files['src/value.py'];f.reseal();self.assertEqual(f.run().status,'ISOLATE_TASK');self.assertEqual((f.git.ref_calls,f.git.object_calls),(0,0))

    def test_H_scope_outside_isolates_one_task_and_independent_task_adopts(self):
        f=Fixture();f.source_files['outside']=FileEntry(b'no');f.reseal();self.assertEqual(f.run().status,'ISOLATE_TASK')
        other=Fixture(task_id='B',client=f.client,git=f.git);self.assertEqual(other.run().status,'ADOPTED');self.assertEqual(f.git.ref_calls,1)

    def test_I_result_digest_conflict_zero_git_writes(self):
        f=Fixture();f.manifest['result_digest']='0'*64;self.assertEqual(f.run().status,'CONFLICT');self.assertEqual((f.git.ref_calls,f.git.object_calls),(0,0))

    def test_J_worker_identity_conflict_zero_git_writes(self):
        f=Fixture();f.manifest['worker_run_id']='f'*32;f.manifest=seal_manifest(f.manifest);self.assertEqual(f.run().status,'CONFLICT');self.assertEqual(f.git.ref_calls,0)

    def test_uncertain_ref_fence_old_head_never_resends_even_when_no_CAS_happened(self):
        f=Fixture()
        with self.assertRaises(SimulatedCrash):f.run(hook=crash_at('AFTER_REF_INTENT'))
        self.assertEqual(f.git.ref_calls,0)
        for _ in range(2):self.assertEqual(f.run().status,'UNKNOWN')
        self.assertEqual(f.git.ref_calls,0);self.assertEqual(f.git.head,HEAD)

    def test_post_ref_GET_unavailable_later_recovers_without_resend(self):
        f=Fixture();f.git.fail_reads_after_ref=True;self.assertEqual(f.run().status,'UNKNOWN');self.assertEqual(f.git.ref_calls,1)
        f.git.fail_reads_after_ref=False;self.assertEqual(f.run().status,'ADOPTED');self.assertEqual(f.git.ref_calls,1)

    def test_receipt_create_response_lost_and_readback_missing_then_replay_no_ref_retry(self):
        f=Fixture();aid=make_adoption_id(f.manifest);path=f.store.path(f.campaign,aid,'receipt')
        f.client.raise_after_create_path=path;f.client.fail_get_paths.add(path)
        self.assertEqual(f.run().status,'UNKNOWN');self.assertEqual(f.git.ref_calls,1);creates=f.client.create_calls
        f.client.fail_get_paths.clear();self.assertEqual(f.run().status,'NOOP_DUPLICATE');self.assertEqual(f.client.create_calls,creates);self.assertEqual(f.git.ref_calls,1)

    def test_head_moves_between_inspection_and_ref_no_ref_call(self):
        f=Fixture();f.git.advance_on_read=2;self.assertEqual(f.run().status,'STALE_REPLAN');self.assertEqual(f.git.ref_calls,0);self.assertEqual(f.git.head,NEXT)

    def test_atomic_write_race_cannot_overwrite_advanced_head(self):
        f=Fixture();f.git.move_during_cas=True;self.assertEqual(f.run().status,'UNKNOWN');self.assertEqual(f.git.head,NEXT);self.assertEqual(f.git.ref_mutations,0)
        self.assertEqual(f.run().status,'UNKNOWN');self.assertEqual(f.git.ref_calls,1)

    def test_result_source_changes_during_object_creation_no_ref_write(self):
        f=Fixture();f.git.before_object_put=lambda:f.source_files.update({'proof/late':FileEntry(b'late')})
        self.assertEqual(f.run().status,'CONFLICT');self.assertEqual(f.git.ref_calls,0)

    def test_task_validity_changes_just_before_ref_isolates(self):
        f=Fixture();f.git.before_object_put=lambda:setattr(f,'valid',False)
        self.assertEqual(f.run().status,'ISOLATE_TASK');self.assertEqual(f.git.ref_calls,0)

    def test_default_branch_alias_custom_default_ledger_and_live_transport_rejected(self):
        f=Fixture()
        for target,default in [('main','main'),('master','main'),('refs/heads/main','main'),('trunk','trunk'),(f.store.branch,'main'),('proof/../bad','main')]:
            with self.subTest(target=target),self.assertRaises(ValueError):f.bridge(target_branch=target,default_branch=default)
        for branch in ['main','refs/heads/main','trunk']:
            with self.assertRaises(ValueError):AppendOnlyAdoptionStore(f.client,write_branch=branch,default_branch='trunk')
        f.git.static_only=False
        with self.assertRaises(ValueError):f.bridge()
        f.git.static_only=True;f.git.atomic_expected_head=False
        with self.assertRaises(ValueError):f.bridge()

    def test_tampered_intent_receipt_and_candidate_cannot_overwrite(self):
        for kind in ['intent','receipt']:
            f=Fixture();self.assertEqual(f.run().status,'ADOPTED');aid=make_adoption_id(f.manifest);p=f.store.path(f.campaign,aid,kind);c=f.client.files[p];r=json.loads(c.text);r['payload']['result_digest']='0'*64
            f.client.files[p]=ExecutorContent(p,canonical(r),c.sha);count=f.client.create_calls
            self.assertEqual(f.run().status,'CONFLICT');self.assertEqual(f.client.create_calls,count);self.assertEqual(f.git.ref_calls,1)
        f=Fixture();first=f.run();c=f.git.candidates[first.receipt['head_after']];f.git.candidates[c.commit]=replace(c,files={**c.files,'proof/evil':FileEntry(b'evil')})
        self.assertEqual(f.run().status,'CONFLICT');self.assertEqual(f.git.ref_calls,1)

    def test_candidate_object_hashes_match_official_Git_hash_object(self):
        f=Fixture();c=construct_candidate(parent=HEAD,files=f.source_files,created_at=NOW,adoption_id=make_adoption_id(f.manifest))
        for sha,(kind,data) in c.objects.items():
            result=subprocess.run(['git','hash-object','-t',kind,'--stdin'],input=data,capture_output=True,check=True)
            self.assertEqual(result.stdout.decode().strip(),sha)
        self.assertEqual(f.git.ref_calls,0)

    def test_campaign_complete_requires_receipt_and_recovery_checkpoint_is_idempotent(self):
        f=Fixture();kernel=AutonomousCampaignKernel(CampaignState(f.campaign,1,{'A':CampaignTask('A',expected_target_head=HEAD),'B':CampaignTask('B',expected_target_head=HEAD)}));kernel.mark_dispatched('A',canonical_head=HEAD)
        self.assertEqual(f.bridge().apply_receipt_to_campaign(kernel,manifest=f.manifest).status,'HOLD_AUTHORITY');self.assertEqual(kernel.state.tasks['A'].status,TaskStatus.RUNNING)
        self.assertEqual(f.run().status,'ADOPTED');self.assertEqual(kernel.state.tasks['A'].status,TaskStatus.RUNNING)
        self.assertEqual(f.bridge().apply_receipt_to_campaign(kernel,manifest=f.manifest).status,'ADOPTED');self.assertEqual(kernel.state.tasks['A'].status,TaskStatus.COMPLETE)
        store=GitHubCampaignStateStore(f.client,write_branch='fixture/campaign-ledger');self.assertEqual(store.save(kernel.state,expected_revision=0).status,'ACCEPTED')
        restored=AutonomousCampaignKernel(store.restore(f.campaign).state);self.assertEqual(f.bridge().apply_receipt_to_campaign(restored,manifest=f.manifest).status,'NOOP_DUPLICATE');self.assertIsNone(restored.state.terminal_reason)
        self.assertEqual(restored.next_action(canonical_head=HEAD,quota_state=QuotaState.UNKNOWN).task_id,'B')

    def test_unavailable_readers_never_default_to_adopt(self):
        for flag in ['source_available','verification_available','validity_available']:
            f=Fixture();setattr(f,flag,False);self.assertEqual(f.run().status,'HOLD_AUTHORITY');self.assertEqual(f.git.ref_calls,0)
        f=Fixture();self.assertEqual(f.run(manifest=None).status,'HOLD_AUTHORITY');self.assertEqual(f.git.object_calls,0)


    def test_old_receipt_cannot_complete_a_newer_campaign_attempt(self):
        f=Fixture();self.assertEqual(f.run().status,"ADOPTED");kernel=AutonomousCampaignKernel(CampaignState(f.campaign,1,{"A":CampaignTask("A",status=TaskStatus.RUNNING,expected_target_head=HEAD,attempts=2)}))
        self.assertEqual(f.bridge().apply_receipt_to_campaign(kernel,manifest=f.manifest).status,"CONFLICT");self.assertEqual(kernel.state.rounds_completed,0)

    def test_actual_object_database_tamper_is_detected_on_receipt_replay(self):
        f=Fixture();self.assertEqual(f.run().status,"ADOPTED");blob=next(k for k,v in f.git.objects.items() if v[0]=="blob");f.git.objects[blob]=("blob",b"tampered")
        self.assertEqual(f.run().status,"CONFLICT");self.assertEqual(f.git.ref_calls,1)

    def test_missing_target_lock_or_rechecksummed_receipt_binding_is_conflict(self):
        f=Fixture();self.assertEqual(f.run().status,"ADOPTED");p=next(p for p in f.client.files if p.startswith("symphony_adoption_locks/"));del f.client.files[p]
        self.assertEqual(f.run().status,"CONFLICT");self.assertEqual(f.git.ref_calls,1)
        f=Fixture();self.assertEqual(f.run().status,"ADOPTED");aid=make_adoption_id(f.manifest);p=f.store.path(f.campaign,aid,"receipt");c=f.client.files[p];r=json.loads(c.text);r["payload"]["head_after"]=NEXT;r["record_digest"]=digest({k:v for k,v in r.items() if k!="record_digest"});f.client.files[p]=ExecutorContent(p,canonical(r),c.sha)
        self.assertEqual(f.run().status,"CONFLICT");self.assertEqual(f.git.ref_calls,1)

    def test_two_results_cannot_both_own_one_canonical_head(self):
        f=Fixture()
        with self.assertRaises(SimulatedCrash):f.run(hook=crash_at("AFTER_INTENT"))
        other=Fixture(task_id="B",client=f.client,git=f.git);self.assertEqual(other.run().status,"CONFLICT");self.assertEqual(f.git.ref_calls,0)
        self.assertEqual(f.run().status,"ADOPTED");self.assertEqual(f.git.ref_mutations,1)

    def test_stale_and_rejected_decisions_are_durable_and_duplicate_safe(self):
        f=Fixture();f.git.head=NEXT;first=f.run();calls=f.client.create_calls;second=f.run()
        self.assertEqual(first.status,"STALE_REPLAN");self.assertEqual(first.decision_evidence,second.decision_evidence);self.assertEqual(f.client.create_calls,calls)
        self.assertTrue(any("inspection-" in p for p in f.client.files));self.assertEqual(f.git.ref_calls,0)


    def test_committed_A_J_fixture_matches_executed_crash_matrix(self):
        from .symphony_g6_fixtures import run_crash_matrix
        root=pathlib.Path(__file__).parent/"fixtures/symphony_g6"
        matrix=json.loads((root/"crash-matrix.json").read_text());actual=run_crash_matrix()
        self.assertEqual({r["case"]:r["result"] for r in actual},matrix["expected_results"])
        for r in actual:
            if r["case"] in {"C","D"}:self.assertEqual(r["new_ref_calls_during_resume"],0)
            if r["case"] in {"E","F","G","I","J"}:self.assertEqual(r["ref_calls_after_resume"],0)
            if r["case"]=="H":self.assertEqual(r["independent_task_result"],"ADOPTED")
        manifest=json.loads((root/"example-result-manifest.json").read_text());self.assertEqual(manifest,Fixture().manifest)


    def test_corrective_task_identity_can_flow_without_new_human_gate(self):
        f=Fixture(task_id="A::corrective::1");self.assertEqual(f.run().status,"ADOPTED")

    def test_task_local_stale_checkpoint_is_recoverable_not_campaign_death(self):
        f=Fixture();f.git.head=NEXT;result=f.run();kernel=AutonomousCampaignKernel(CampaignState(f.campaign,1,{"A":CampaignTask("A",expected_target_head=HEAD)}));kernel.mark_dispatched("A",canonical_head=HEAD)
        self.assertEqual(f.bridge().apply_decision_to_campaign(kernel,manifest=f.manifest,result=result).status,"STALE_REPLAN");self.assertEqual(kernel.state.tasks["A"].status,TaskStatus.STALE);self.assertEqual(kernel.state.rounds_completed,0);self.assertIsNone(kernel.state.terminal_reason)
        self.assertEqual(f.bridge().apply_decision_to_campaign(kernel,manifest=f.manifest,result=result).status,"NOOP_DUPLICATE")
        self.assertEqual(kernel.next_action(canonical_head=NEXT,quota_state=QuotaState.UNKNOWN).kind.value,"REPLAN_TASK")

    def test_task_isolation_preserves_independent_work_and_unknown_late_receipt_recovers(self):
        f=Fixture();kernel=AutonomousCampaignKernel(CampaignState(f.campaign,1,{"A":CampaignTask("A",expected_target_head=HEAD),"B":CampaignTask("B",expected_target_head=HEAD)}));kernel.mark_dispatched("A",canonical_head=HEAD)
        f.git.fail_reads_after_ref=True;result=f.run();self.assertEqual(result.status,"UNKNOWN")
        self.assertEqual(f.bridge().apply_decision_to_campaign(kernel,manifest=f.manifest,result=result).status,"UNKNOWN");self.assertEqual(kernel.state.tasks["A"].status,TaskStatus.BLOCKED);self.assertIsNone(kernel.state.terminal_reason)
        self.assertEqual(kernel.next_action(canonical_head=HEAD,quota_state=QuotaState.UNKNOWN).task_id,"B")
        f.git.fail_reads_after_ref=False;self.assertEqual(f.run().status,"ADOPTED");self.assertEqual(f.bridge().apply_receipt_to_campaign(kernel,manifest=f.manifest).status,"ADOPTED");self.assertEqual(kernel.state.tasks["A"].status,TaskStatus.COMPLETE);self.assertEqual(f.git.ref_calls,1)


if __name__=='__main__':unittest.main()
