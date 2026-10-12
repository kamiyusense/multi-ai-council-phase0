"""Authentic signed format, real production adapters; synthetic IO/model only."""
import hashlib
import hmac
import json
import shutil
from pathlib import Path
from dataclasses import asdict, replace
from unittest import mock
from .test_symphony_g61_production_wiring import World, TempCase, NOW
from .test_symphony_g63_connection import wired, approval, strict_ci
from .test_symphony_g62_readiness import prepare, CIWorld
from .symphony_g6_fixtures import crash_at, SimulatedCrash
from ..symphony_g72_runtime import StaticObservationReceiptAdapter
from ..symphony_g63_snapshot import StrictWorkspaceSnapshotStore
from ..symphony_g63_sender import seal_approval
from ..symphony_production_observer import SymphonyProductionObserver, ObservedIssue, PROTOCOL
from ..symphony_campaign_store import GitHubCampaignStateStore
from ..symphony_autonomous_runtime import CampaignState, CampaignTask, TaskStatus, AutonomousCampaignKernel
from ..symphony_autonomous_policy import HARDENED_AUTONOMOUS_POLICY, QuotaState
from ..symphony_result_manifest import digest
from ..symphony_git_adoption import make_adoption_id

# Fixture-only MAC, not a credential or key used by any real observation process.
KEY = b'g72-synthetic-fixture-only-mac-key'


def signed(w, kind, status=None, **changes):
    p = dict(protocol=PROTOCOL, issue_id=w.issue_id, worker_run_id=w.worker,
        attempt_number=int(w.worker[:15],16)+1, workspace=str(w.workspace), kind=kind,
        status=status or ('RUNNING' if kind=='STARTED' else 'WORKER_STOPPED'))
    p.update(changes); raw=json.dumps(p,sort_keys=True,separators=(',',':'))
    return json.dumps({'payload_json':raw,'mac':hmac.new(KEY,raw.encode(),hashlib.sha256).hexdigest()})


class ObservedWorld(World):
    def __init__(self, tmp, *, task_id='A', gh=None, client=None, generation=1):
        super().__init__(tmp,task_id=task_id,gh=gh,client=client)
        if ":" in task_id:
            bad=self.workspace/("proof/"+task_id+".md")
            bad.rename(self.workspace/("proof/"+task_id.replace(":", "-")+".md"))
        self.generation=generation
        # Old World's manually seeded attempt is not used anywhere in this chain.
        self.worker=hashlib.sha256((task_id+':'+str(self.tmp)+':'+str(generation)).encode()).hexdigest()[:32]
        for p,e in self.gh.tree_files(self.head).items():
            path=self.workspace/p;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(e.data)
        (self.workspace/'src/value.py').write_text('value = '+str(100+ord(task_id[0]))+'\n')
        self.snapshots=StrictWorkspaceSnapshotStore(str(self.tmp/'strict-snapshots'))
        self.campaign_store=GitHubCampaignStateStore(self.client,write_branch='fixture/g72-campaign')
        self.observer=SymphonyProductionObserver(self.attempts,campaign_id='g61-static',key=KEY,
            issues={self.issue_id:ObservedIssue(task_id,generation,self.head,generation,self.scope)})
        self.flow=None

    def factory(self, manifest, snapshot_id):
        self.manifest,self.snapshot_id=manifest,snapshot_id
        if self.flow is None:
            if self.external['tests']=='FAIL':
                self.flow=self.wired()  # independent, explicitly synthetic FAIL; cannot publish
            else:
                plan=prepare(self).plan
                a=approval(self,plan)
                a=seal_approval({**{k:v for k,v in a.items() if k!='approval_digest'},
                    'approval_id':'g72-synthetic-'+self.attempt_id})
                self.flow=wired(self,envelope=a)
                ci=CIWorld(self);verifier=strict_ci(ci)
                self.flow.verification_reader=lambda:verifier.read(self.manifest).evidence
        return self.flow

    def adapter(self):
        return StaticObservationReceiptAdapter(observer=self.observer,snapshots=self.snapshots,
            campaign_store=self.campaign_store,ledger=self.ledger,target_reader=self.target_reader(),
            flow_factory=self.factory,campaign_id='g61-static',generation=self.generation)

    def reserve(self):
        cp=self.campaign_store.restore('g61-static')
        if cp is None:
            state=CampaignState('g61-static',self.generation,{self.task_id:CampaignTask(self.task_id)})
            assert self.campaign_store.save(state,expected_revision=0).status=='ACCEPTED'
        r=self.adapter().admission(self.task_id,expected_revision=self.revision(),
            account_evidence={'auth_state':'CHATGPT_ACCOUNT'})
        assert r.status=='PREPARED_STATIC_ONLY',r
        r=self.adapter().capture(signed(self,'STARTED'));assert r.status=='ACCEPTED',r
        self.attempt_id=r.attempt_id;self.snapshot_id='g72-snapshot-'+digest(self.attempt_id)[:24]
        return self

    def snapshot_before_close(self):
        return self.adapter().snapshot(self.attempt_id,snapshot_id=self.snapshot_id,captured_at=NOW)

    def terminal(self):
        return self.adapter().capture(signed(self,'TERMINAL'))

    def revision(self):return self.campaign_store.restore('g61-static').revision

    def settle(self, **kw):
        return self.adapter().settle(self.attempt_id,expected_revision=self.revision(),now=NOW,
            constraints_known=kw.pop('constraints_known',True),**kw)

    def ready(self):
        self.reserve();assert self.snapshot_before_close().close_ready;assert self.terminal().status=='NOOP_DUPLICATE'
        return self


def run_g72_chain(root):
    """Fixture driver: existing kernel selects/reserves; signed event IO, no scheduler."""
    w=ObservedWorld(Path(root)/'A');store=w.campaign_store
    names=['A','B','C','D','E','F']
    state=CampaignState('g61-static',1,{x:CampaignTask(x) for x in names})
    assert store.save(state,expected_revision=0).status=='ACCEPTED'
    worlds=[];records=[]
    for name in ['A','B','B::corrective::1','C','D','E','F']:
        generation=store.restore('g61-static').state.generation
        current=ObservedWorld(Path(root)/name.replace(':','-'),task_id=name,gh=w.gh,client=w.client,generation=generation)
        # Existing kernel chooses corrective ahead of independent work.
        cp=store.restore('g61-static');next_action=AutonomousCampaignKernel(cp.state).next_action(
            canonical_head=w.gh.head('proof/g61-static'),quota_state=QuotaState.UNKNOWN)
        assert next_action.task_id==name,(name,next_action)
        if name=='B':current.external['tests']='FAIL'
        current.reserve();assert current.snapshot_before_close().close_ready
        # Natural continuations are observed, never approval-gated.
        for _ in range(2):assert current.adapter().capture(signed(current,'WORKER_UPDATE')).status=='READ_ONLY'
        assert current.terminal().status=='NOOP_DUPLICATE'
        if name=='B':
            result=current.adapter().corrective(current.attempt_id,expected_revision=current.revision())
            assert result.status=='CORRECTIVE_TASK_CREATED',result
        elif name=='D':
            current.adapter()._flow(current.attempt_id)  # independent qualification at original HEAD
            w.gh.advance('proof/g61-static',w.gh.tree_files(current.head))
            result=current.settle();assert result.status=='STALE_REPLAN',result
            cp=store.restore('g61-static');k=AutonomousCampaignKernel(cp.state)
            k.replan_stale_task(name,canonical_head=w.gh.head('proof/g61-static'),
                task_still_valid=False,canonical_trustworthy=True)
            assert store.save(k.state,expected_revision=cp.revision).status=='ACCEPTED'
        elif name=='E':
            result=current.settle(crash_hook=lambda p: None,constraints_known=False)
            assert result.status=='HOLD_AUTHORITY',result
        else:
            result=current.settle();assert result.status=='ADOPTED',result
        records.append({'task':name,'result':asdict(result),'observed_nonce':current.attempt().identity.attempt_number,
            'logical_attempts':store.restore('g61-static').state.tasks[name].attempts,'synthetic':True,
            'started_record':current.attempt().started,'terminal_record':current.attempt().terminal,
            'lifetime_binding':current.ledger._get(current.adapter()._path('lifetime',current.attempt_id)),
            'snapshot_manifest_sha256':current.snapshots.manifest_sha256(current.snapshot_id),
            'result_digest':current.manifest['result_digest'],'source_digest':current.manifest['source_digest'],
            'scope_digest':current.manifest['scope_digest'],
            'receipt':current.ledger.get('g61-static',make_adoption_id(current.manifest),'receipt'),
            'checkpoint_digest':store.restore('g61-static').state_digest,
            'fixture_mac_accepted':True,'simulated_ungated_worker_updates':2})
        worlds.append(current)
        if name=='C':
            cp=store.restore('g61-static');cp.state.generation=2
            assert store.save(cp.state,expected_revision=cp.revision).status=='ACCEPTED'
    # Fresh generation/session replays old receipts without changing state or sending.
    first=worlds[0];first.generation=2
    before=(w.gh.object_posts,w.gh.update_refs_requests,store.restore('g61-static').state_digest)
    assert first.adapter().capture(signed(first,'STARTED')).status=='NOOP_DUPLICATE'
    assert first.adapter().capture(signed(first,'TERMINAL')).status=='NOOP_DUPLICATE'
    replay=first.settle(recover_only=True)
    assert replay.status=='NOOP_DUPLICATE',replay
    assert before==(w.gh.object_posts,w.gh.update_refs_requests,store.restore('g61-static').state_digest)
    cp=store.restore('g61-static')
    assert all(cp.state.tasks[x].status is TaskStatus.COMPLETE for x in ('A','B','C','F'))
    assert all(cp.state.tasks[x].status is TaskStatus.BLOCKED for x in ('D','E'))
    return {'protocol':'SYMPHONY_G72_SYNTHETIC_CHAIN_V1','result':'PASS','synthetic':True,'tasks':records,
        'successful_receipts':w.gh.update_refs_requests,'failed_candidate_corrective':True,
        'stale_replan':True,'unknown_isolation':True,'generations':[1,2],
        'fresh_sessions':len(worlds)+1,'restart_start':'NOOP_DUPLICATE','restart_terminal':'NOOP_DUPLICATE',
        'restart_receipt':replay.status,'restart_extra_model_dispatch':0,'restart_extra_mock_git_writes':0,
        'counts':{'live_model':0,'live_worker':0,'live_publication':0,'actual_result_adoption':0}}


class G72RuntimeTests(TempCase):
    def test_authentic_nonce_not_logical_budget_counter_full_chain(self):
        w=ObservedWorld(self.tmp).ready();self.assertGreater(w.attempt().identity.attempt_number,1)
        self.assertEqual(w.settle().status,'ADOPTED')
        self.assertEqual(w.campaign_store.restore('g61-static').state.tasks['A'].attempts,1)

    def test_three_or_more_completions_corrective_stale_unknown_two_generations(self):
        r=run_g72_chain(self.tmp);self.assertEqual(r['successful_receipts'],4)
        self.assertEqual(r['restart_extra_model_dispatch'],0)

    def test_snapshot_before_late_terminal_and_after_workspace_cleanup(self):
        w=ObservedWorld(self.tmp).reserve();self.assertTrue(w.snapshot_before_close().close_ready)
        self.assertEqual(w.settle().status,'HOLD_AUTHORITY');self.assertEqual(w.gh.update_refs_requests,0)
        shutil.rmtree(w.workspace);w.terminal()
        self.assertEqual(w.settle().status,'ADOPTED')
        self.assertTrue(w.snapshot_before_close().close_ready)

    def test_mac_rejection_and_worker_workspace_rebinding_no_overwrite(self):
        w=ObservedWorld(self.tmp).reserve();before=w.client.create_calls
        self.assertEqual(w.adapter().capture('{}').status,'CONFLICT')
        self.assertEqual(w.adapter().capture(signed(w,'TERMINAL',workspace='/wrong')).status,'CONFLICT')
        self.assertEqual(w.client.create_calls,before)

    def test_two_workers_cannot_claim_same_logical_slot(self):
        w=ObservedWorld(self.tmp).reserve();original=w.worker;w.worker='f'*32
        self.assertEqual(w.adapter().capture(signed(w,'STARTED')).status,'CONFLICT')
        w.worker=original;w.snapshot_before_close();w.terminal()
        self.assertEqual(w.settle().status,'ADOPTED')

    def test_duplicate_terminal_and_restart_no_extra_ref_or_round(self):
        w=ObservedWorld(self.tmp).ready();self.assertEqual(w.settle().status,'ADOPTED')
        before=(w.gh.object_posts,w.gh.update_refs_requests,w.revision())
        for _ in range(3):
            self.assertEqual(w.adapter().capture(signed(w,'STARTED')).status,'NOOP_DUPLICATE')
            self.assertEqual(w.adapter().capture(signed(w,'TERMINAL')).status,'NOOP_DUPLICATE')
            self.assertEqual(w.settle(recover_only=True).status,'NOOP_DUPLICATE')
        self.assertEqual(before,(w.gh.object_posts,w.gh.update_refs_requests,w.revision()))

    def test_unknown_constraints_do_not_write_and_next_work_remains_ready(self):
        w=ObservedWorld(self.tmp).ready();self.assertEqual(w.settle(constraints_known=False).status,'HOLD_AUTHORITY')
        self.assertEqual(w.gh.update_refs_requests,0)
        self.assertEqual(w.campaign_store.restore('g61-static').state.tasks['A'].status,TaskStatus.BLOCKED)

    def test_lost_checkpoint_response_receipt_recovery_get_only(self):
        w=ObservedWorld(self.tmp).ready()
        with mock.patch.object(w.campaign_store,'save',return_value=type('R',(),{'status':'UNKNOWN','revision':None})()):
            self.assertEqual(w.settle().status,'CHECKPOINT_UNKNOWN')
        before=(w.gh.object_posts,w.gh.update_refs_requests)
        self.assertEqual(w.settle(recover_only=True).status,'ADOPTED')
        self.assertEqual(before,(w.gh.object_posts,w.gh.update_refs_requests))

    def test_crash_after_fence_no_blind_resend(self):
        w=ObservedWorld(self.tmp).ready()
        with self.assertRaises(SimulatedCrash):w.settle(crash_hook=crash_at('AFTER_REF_INTENT'))
        self.assertEqual(w.settle().status,'UNKNOWN');self.assertEqual(w.settle().status,'UNKNOWN')
        self.assertEqual(w.gh.update_refs_requests,0)

    def test_delayed_verifier_is_hold_then_recovers_without_new_worker(self):
        w=ObservedWorld(self.tmp).ready();w.factory(w.make_manifest(),w.snapshot_id)
        old=w.flow.verification_reader
        w.flow.verification_reader=lambda:(_ for _ in ()).throw(OSError('not yet available'))
        self.assertNotEqual(w.settle().status,'ADOPTED');self.assertEqual(w.gh.update_refs_requests,0)
        w.flow.verification_reader=old
        self.assertEqual(w.settle().status,'ADOPTED');self.assertEqual(w.campaign_store.restore('g61-static').state.tasks['A'].attempts,1)

    def test_no_live_capability_or_flag_toggle(self):
        w=ObservedWorld(self.tmp).ready();a=w.adapter();a.static_only=False;a.live_authorized=True
        with self.assertRaises(PermissionError):a.execute()
        self.assertEqual(w.gh.update_refs_requests,0)

    def test_new_admission_api_route_block_but_readback_not_quota_gated(self):
        w=ObservedWorld(self.tmp).ready();self.assertEqual(w.settle().status,'ADOPTED')
        with mock.patch('automation.command_bus.symphony_g72_runtime.new_worker_cost_gate',side_effect=AssertionError('new worker gate used')):
            self.assertEqual(w.settle(recover_only=True).status,'NOOP_DUPLICATE')

    def test_stale_controller_revision_never_sends(self):
        w=ObservedWorld(self.tmp).ready()
        r=w.adapter().settle(w.attempt_id,expected_revision=0,now=NOW,constraints_known=True)
        self.assertEqual(r.status,'HOLD_AUTHORITY');self.assertEqual(w.gh.update_refs_requests,0)

    def test_worker_failed_status_is_not_independent_failure_or_done(self):
        w=ObservedWorld(self.tmp).reserve();w.snapshot_before_close()
        w.adapter().capture(signed(w,'TERMINAL',status='WORKER_FAILED'))
        self.assertEqual(w.adapter().corrective(w.attempt_id,expected_revision=w.revision()).status,'HOLD_AUTHORITY')
        self.assertEqual(w.campaign_store.restore('g61-static').state.rounds_completed,0)

class G72RaceTests(TempCase):
    def test_failure_corrective_duplicate_exactly_once(self):
        w=ObservedWorld(self.tmp);w.external['tests']='FAIL';w.ready()
        r=w.adapter().corrective(w.attempt_id,expected_revision=w.revision())
        self.assertEqual(r.status,'CORRECTIVE_TASK_CREATED');before=w.revision()
        r=w.adapter().corrective(w.attempt_id,expected_revision=before)
        self.assertEqual(r.status,'NOOP_DUPLICATE');self.assertEqual(w.revision(),before)
        self.assertEqual(w.gh.update_refs_requests,0)

    def test_failed_candidate_untrusted_validity_cannot_create_corrective(self):
        w=ObservedWorld(self.tmp);w.external['tests']='FAIL';w.ready();w.adapter()._flow(w.attempt_id)
        original=w.flow.validity_reader
        w.flow.validity_reader=lambda target:replace(original(target),trustworthy=False)
        self.assertEqual(w.adapter().corrective(w.attempt_id,expected_revision=w.revision()).status,'HOLD_AUTHORITY')
        self.assertEqual(w.campaign_store.restore('g61-static').state.rounds_completed,0)

    def test_two_controllers_stale_checkpoint_no_second_mock_send(self):
        w=ObservedWorld(self.tmp).ready();a,b=w.adapter(),w.adapter();rev=w.revision()
        self.assertEqual(a.settle(w.attempt_id,expected_revision=rev,now=NOW,constraints_known=True).status,'ADOPTED')
        self.assertEqual(b.settle(w.attempt_id,expected_revision=rev,now=NOW,constraints_known=True).status,'HOLD_AUTHORITY')
        self.assertEqual(w.gh.update_refs_requests,1)

    def test_default_head_task_change_at_fence_zero_dispatch(self):
        for mode in ('default','head','task'):
            w=ObservedWorld(Path(self.tmp)/mode).ready()
            def race(point):
                if point=='AFTER_REF_INTENT':
                    if mode=='default':w.gh.default_branch='proof/g61-static'
                    elif mode=='head':w.gh.advance('proof/g61-static',w.gh.tree_files(w.head))
                    else:w.gh.issues[w.number]['labels']={'totalCount':1,'nodes':[{'name':'symphony:invalid'}]}
            self.assertEqual(w.settle(crash_hook=race).status,'UNKNOWN')
            self.assertEqual(w.gh.update_refs_requests,0)

    def test_object_sha_tamper_never_ref_or_done(self):
        w=ObservedWorld(self.tmp).ready();w.gh.tamper_created_sha=True
        self.assertNotEqual(w.settle().status,'ADOPTED');self.assertEqual(w.gh.update_refs_requests,0)

    def test_lost_ref_response_before_after_one_request_get_recovery(self):
        for mode in ('before','after'):
            w=ObservedWorld(Path(self.tmp)/mode).ready();setattr(w.gh,'lose_reply_'+mode+'_apply',True)
            r=w.settle();self.assertEqual(r.status,'UNKNOWN' if mode=='before' else 'ADOPTED')
            self.assertEqual(w.settle().status,'UNKNOWN' if mode=='before' else 'NOOP_DUPLICATE')
            self.assertEqual(w.gh.update_refs_requests,1)

    def test_durable_binding_write_unavailable_holds_without_observation_retry(self):
        w=ObservedWorld(self.tmp).reserve()
        p=w.adapter()._path('lifetime',w.attempt_id)
        # Fixture-only loss of local binding after signed STARTED was saved.
        del w.client.files[p]
        with mock.patch.object(w.ledger,'_put',return_value='UNKNOWN'):
            self.assertEqual(w.adapter().capture(signed(w,'STARTED')).status,'UNKNOWN')
        self.assertEqual(w.gh.update_refs_requests,0)
        self.assertEqual(w.adapter().capture(signed(w,'STARTED')).status,'ACCEPTED')

    def test_post_snapshot_unapproved_mutation_cannot_enter_saved_result(self):
        w=ObservedWorld(self.tmp).reserve();w.snapshot_before_close()
        (w.workspace/'unapproved.txt').write_text('late mutation')
        w.terminal();self.assertEqual(w.settle().status,'ADOPTED')
        self.assertNotIn('unapproved.txt',w.gh.tree_files(w.gh.head('proof/g61-static')))

    def test_unapproved_file_inside_snapshot_is_not_adopted(self):
        w=ObservedWorld(self.tmp).reserve();(w.workspace/'unapproved.txt').write_text('unapproved')
        w.snapshot_before_close();w.terminal()
        self.assertNotEqual(w.settle().status,'ADOPTED');self.assertEqual(w.gh.update_refs_requests,0)

class G72CloseAndRecoveryTests(TempCase):
    def test_tracker_close_after_snapshot_before_terminal_with_explicit_scope_permission(self):
        w=ObservedWorld(self.tmp).reserve();self.assertTrue(w.snapshot_before_close().close_ready)
        issue=w.gh.issues[w.number];issue['state']='CLOSED';issue['stateReason']='COMPLETED'
        issue['labels']={'totalCount':1,'nodes':[{'name':'symphony:adopt-after-close'}]}
        self.assertEqual(w.settle().status,'HOLD_AUTHORITY')
        shutil.rmtree(w.workspace);w.terminal()
        self.assertEqual(w.settle().status,'ADOPTED');self.assertEqual(w.gh.update_refs_requests,1)

    def test_tracker_close_without_independent_adopt_after_close_permission_holds(self):
        w=ObservedWorld(self.tmp).reserve();w.snapshot_before_close();w.terminal()
        issue=w.gh.issues[w.number];issue['state']='CLOSED';issue['stateReason']='COMPLETED'
        self.assertNotEqual(w.settle().status,'ADOPTED');self.assertEqual(w.gh.update_refs_requests,0)

    def test_crash_after_ref_before_receipt_recovers_get_only_no_new_worker(self):
        w=ObservedWorld(self.tmp).ready()
        with self.assertRaises(SimulatedCrash):w.settle(crash_hook=crash_at('AFTER_REF'))
        before=(w.gh.object_posts,w.gh.update_refs_requests)
        self.assertEqual(w.settle().status,'ADOPTED')
        self.assertEqual(before,(w.gh.object_posts,w.gh.update_refs_requests))
        self.assertEqual(w.campaign_store.restore('g61-static').state.tasks['A'].attempts,1)

    def test_crash_after_checkpoint_restore_noop(self):
        w=ObservedWorld(self.tmp).ready()
        with self.assertRaises(SimulatedCrash):w.settle(crash_hook=crash_at('AFTER_CAMPAIGN_CHECKPOINT'))
        before=w.revision();self.assertEqual(w.settle(recover_only=True).status,'NOOP_DUPLICATE')
        self.assertEqual(before,w.revision())

    def test_verified_receipt_replay_after_target_advanced_independent_next_task(self):
        w=ObservedWorld(self.tmp).ready();self.assertEqual(w.settle().status,'ADOPTED')
        files=w.gh.tree_files(w.gh.head('proof/g61-static'));w.gh.advance('proof/g61-static',files)
        before=(w.gh.object_posts,w.gh.update_refs_requests)
        self.assertEqual(w.settle(recover_only=True).status,'NOOP_DUPLICATE')
        self.assertEqual(before,(w.gh.object_posts,w.gh.update_refs_requests))
