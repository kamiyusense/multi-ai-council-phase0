"""G7.1 end-to-end STATIC: real bytes/adapters, simulated worker/GitHub/CI.

No fixture calls a model or network. Official scheduling is never replaced.
"""
import copy
import hashlib
import json
from dataclasses import replace, asdict
from pathlib import Path
from unittest import mock
from .test_symphony_g61_production_wiring import World, TempCase, NOW
from .test_symphony_g63_connection import wired, approval, strict_ci
from .test_symphony_g62_readiness import prepare, CIWorld
from .symphony_g6_fixtures import SimulatedCrash, crash_at
from ..executor_backend import ExecutorContent
from ..symphony_g71_campaign import StaticReceiptCampaignSeam, new_worker_cost_gate
from ..symphony_g63_sender import seal_approval
from ..symphony_g63_snapshot import StrictWorkspaceSnapshotStore
from ..symphony_campaign_store import GitHubCampaignStateStore
from ..symphony_autonomous_runtime import CampaignState, CampaignTask, TaskStatus, AutonomousCampaignKernel
from ..symphony_autonomous_policy import QuotaState, HARDENED_AUTONOMOUS_POLICY
from ..symphony_git_adoption import make_adoption_id
from ..symphony_result_manifest import seal_manifest, digest


class CampaignWorld(World):
    @property
    def worker(self):return self._worker

    @worker.setter
    def worker(self, unused):
        # Unique simulated lifetime without changing the existing World helper.
        self._worker=hashlib.sha256((self.task_id+':'+self.attempt_id).encode()).hexdigest()[:32]


def ready(tmp, task='A', gh=None, client=None):
    w=CampaignWorld(tmp,task_id=task,gh=gh,client=client)
    # Preserve the complete fresh target inventory, including preceding tasks.
    for p,e in w.gh.tree_files(w.head).items():
        path=w.workspace/p;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(e.data)
    (w.workspace/'src/value.py').write_bytes(('value = '+str(100+ord(task[0]))+'\n').encode())
    w.snapshots=StrictWorkspaceSnapshotStore(str(w.tmp/'strict-snapshot'))
    w.ready();return w


def connected(w, *, flow=None, bootstrap=True):
    store=GitHubCampaignStateStore(w.client,write_branch='fixture/campaign-checkpoints')
    if bootstrap:
        cp=store.restore('g61-static')
        state=cp.state if cp else CampaignState('g61-static',1,{})
        state.tasks[w.task_id]=CampaignTask(w.task_id,status=TaskStatus.RUNNING,
            expected_target_head=w.head,attempts=1)
        assert store.save(state,expected_revision=cp.revision if cp else 0).status=='ACCEPTED'
    if flow is None:
        plan=prepare(w).plan
        a=approval(w,plan);a=seal_approval({**{k:v for k,v in a.items() if k!='approval_digest'},
                                         'approval_id':'synthetic-g71-'+w.attempt_id})
        flow=wired(w,envelope=a)
        ci=CIWorld(w);v=strict_ci(ci)
        flow.verification_reader=lambda:v.read(w.manifest).evidence
    seam=StaticReceiptCampaignSeam(flow=flow,campaign_store=store,campaign_id='g61-static',generation=1)
    return seam,store


def settle(seam,store,w,**kw):
    return seam.settle(w.manifest,expected_revision=store.restore('g61-static').revision,now=NOW,
                       constraints_known=True,**kw)


def run_g71_chain(root, *, rounds=4):
    """Fixture driver only. Existing kernel chooses next action; no new scheduler.

    A succeeds, B replans locally, C remains UNKNOWN, D and later succeed. Every
    task has a new simulated observed lifetime and a fresh controller instance.
    """
    if type(rounds) is not int or rounds<4 or rounds>100:raise ValueError('4..100 fixture rounds')
    gh=client=None;observed=[];worker_ids=set();attempt_ids=set();first=None
    task_ids=[chr(65+i) if i<26 else 'Z'+format(i,'03d') for i in range(rounds)]
    policy=replace(HARDENED_AUTONOMOUS_POLICY,max_rounds=rounds+5)
    for i in range(rounds):
        task=task_ids[i]
        if i:
            cp=store.restore('g61-static');kernel=AutonomousCampaignKernel(cp.state,policy=policy)
            selected=kernel.next_action(canonical_head=gh.head('proof/g61-static'),quota_state=QuotaState.UNKNOWN)
            assert selected.task_id==task and selected.kind.value=='DISPATCH_TASK'
            kernel.mark_dispatched(task,canonical_head=gh.head('proof/g61-static'))
            assert store.save(kernel.state,expected_revision=cp.revision).status=='ACCEPTED'
        w=ready(Path(root)/task,task,gh,client);gh=w.gh;client=w.client
        worker_ids.add(w.worker);attempt_ids.add(w.attempt_id)
        if not i:
            store=GitHubCampaignStateStore(w.client,write_branch='fixture/campaign-checkpoints')
            state=CampaignState('g61-static',1,{t:CampaignTask(t) for t in task_ids})
            kernel=AutonomousCampaignKernel(state,policy=policy)
            assert kernel.next_action(canonical_head=w.head).task_id==task
            kernel.mark_dispatched(task,canonical_head=w.head)
            assert store.save(state,expected_revision=0).status=='ACCEPTED'
        if i==1:
            # Realistic stale result: target moves after manifest/CI production.
            flow=w.wired();seam,store=connected(w,flow=flow,bootstrap=False)
            gh.advance(w.manifest['target_branch'],gh.tree_files(w.head))
        else:seam,store=connected(w,bootstrap=False)
        seam.policy=policy
        saved_reader=seam.flow.transport.read_candidate
        def lost_readback(point):
            if i==2 and point=='AFTER_REF':
                seam.flow.transport.read_candidate=lambda commit:None
        if i==2:gh.lose_reply_after_apply=True
        result=settle(seam,store,w,crash_hook=lost_readback)
        seam.flow.transport.read_candidate=saved_reader
        gh.lose_reply_after_apply=False
        taskstate=store.restore('g61-static').state.tasks[task].status.value
        if i==1:
            cp=store.restore('g61-static');kernel=AutonomousCampaignKernel(cp.state)
            kernel.replan_stale_task(task,canonical_head=gh.head(w.manifest['target_branch']),
                                    task_still_valid=False,canonical_trustworthy=True)
            assert store.save(kernel.state,expected_revision=cp.revision).status=='ACCEPTED'
        if i==0:first=(w,seam,store)
        observed.append({'task':task,'attempt_id':w.attempt_id,'worker_run_id':w.worker,
            'terminal_outcome':w.attempt().terminal['outcome'],'result':asdict(result),'task_state':taskstate,
            'model_launches':0,'real_github_writes':0})
    w,seam,store=first;seam,store=connected(w,flow=seam.flow,bootstrap=False)
    before=(gh.object_posts,gh.update_refs_requests)
    replay=seam.recover_receipt(w.manifest,expected_revision=store.restore('g61-static').revision)
    assert replay.status=='NOOP_DUPLICATE' and before==(gh.object_posts,gh.update_refs_requests)
    state=store.restore('g61-static').state
    assert state.tasks['A'].status is TaskStatus.COMPLETE
    assert state.tasks['B'].status is TaskStatus.BLOCKED and state.tasks['C'].status is TaskStatus.BLOCKED
    assert all(state.tasks[x['task']].status is TaskStatus.COMPLETE for x in observed[3:])
    assert len(attempt_ids)==rounds
    # Each source and simulated observed worker lifetime has a distinct identity.
    assert len(worker_ids)==rounds
    return {'protocol':'SYMPHONY_G71_STATIC_CHAIN_V1','result':'PASS','synthetic':True,
        'tasks':observed,'rounds':rounds,'sessions':rounds+1,'mock_completed':state.rounds_completed,
        'mock_ref_requests':gh.update_refs_requests,'receipt_replay':replay.status,
        'restart_additional_dispatch':0,'restart_additional_git_writes':0,
        'existing_kernel_selected_all_tasks':True,'distinct_attempts':len(attempt_ids),'distinct_fixture_workers':len(worker_ids),
        'real_model_starts':0,'real_result_adoption':0,'real_github_runtime_writes':0,
        'new_scheduler':False,'existing_kernel_next_action':AutonomousCampaignKernel(state,policy=policy).next_action(
            quota_state=QuotaState.UNKNOWN,canonical_head=gh.head(w.manifest['target_branch'])).kind.value}


class G71CampaignTests(TempCase):
    def test_chain_success_stale_replan_unknown_isolation_and_next_independent_task(self):
        r=run_g71_chain(self.tmp);self.assertEqual(r['mock_completed'],2)
        self.assertEqual(r['distinct_attempts'],4);self.assertEqual(r['distinct_fixture_workers'],4)
        self.assertEqual(r['tasks'][1]['result']['status'],'STALE_REPLAN')
        self.assertEqual(r['tasks'][2]['result']['status'],'UNKNOWN')

    def test_configurable_42_task_receipt_soak_with_43_fresh_sessions(self):
        r=run_g71_chain(self.tmp,rounds=42)
        self.assertEqual((r['mock_completed'],r['distinct_fixture_workers'],r['sessions']),(40,42,43))
        self.assertEqual(r['restart_additional_git_writes'],0)

    def test_worker_stopped_and_self_pass_never_complete_without_receipt(self):
        w=ready(self.tmp);s,store=connected(w)
        r=s.recover_receipt(w.manifest,expected_revision=store.restore('g61-static').revision)
        self.assertEqual(r.status,'HOLD_AUTHORITY');self.assertFalse(r.continuation_ready)
        self.assertEqual(store.restore('g61-static').state.rounds_completed,0)
        self.assertEqual(w.gh.update_refs_requests,0)

    def test_manifest_full_identity_rebinding_never_changes_campaign_or_sends(self):
        w=ready(self.tmp);s,store=connected(w);rev=store.restore('g61-static').revision
        changes={'task_id':'B','attempt_id':'attempt-wrong','generation':2,'attempt_number':2,
                 'runner_generation':2,'worker_run_id':'f'*32,'workspace_fingerprint':'f'*64,
                 'expected_target_head':'f'*40,'scope_digest':'f'*64,'campaign_id':'wrong'}
        for key,val in changes.items():
            m=seal_manifest({**w.manifest,key:val})
            with self.subTest(key=key):
                r=s.settle(m,expected_revision=rev,now=NOW,constraints_known=True)
                self.assertEqual(r.status,'HOLD_AUTHORITY');self.assertFalse(r.continuation_ready)
        self.assertEqual(w.gh.update_refs_requests,0);self.assertEqual(store.restore('g61-static').revision,rev)

    def test_missing_result_or_wrong_receipt_cannot_mark_done(self):
        for kind in ('result','receipt'):
            w=ready(Path(self.tmp)/kind);s,store=connected(w);self.assertEqual(settle(s,store,w).status,'ADOPTED')
            # Simulate incomplete campaign checkpoint at the receipt seam.
            cp=store.restore('g61-static');cp.state.tasks['A'].status=TaskStatus.RUNNING
            cp.state.processed_result_ids.clear();cp.state.rounds_completed=0
            self.assertEqual(store.save(cp.state,expected_revision=cp.revision).status,'ACCEPTED')
            path=w.ledger.path('g61-static',make_adoption_id(w.manifest),kind)
            if kind=='result':del w.client.files[path]
            else:
                old=w.client.files[path];v=json.loads(old.text);v['payload']['head_after']='f'*40
                v['record_digest']=digest({k:x for k,x in v.items() if k!='record_digest'})
                w.client.files[path]=ExecutorContent(path,json.dumps(v),old.sha)
            r=s.recover_receipt(w.manifest,expected_revision=store.restore('g61-static').revision)
            self.assertEqual(r.status,'CONFLICT');self.assertFalse(r.continuation_ready)
            self.assertEqual(store.restore('g61-static').state.rounds_completed,0)

    def test_task_head_or_attempt_mismatch_blocks_before_publication(self):
        for name,val in [('attempts',2),('expected_target_head','f'*40)]:
            w=ready(Path(self.tmp)/name);s,store=connected(w);cp=store.restore('g61-static')
            setattr(cp.state.tasks['A'],name,val);store.save(cp.state,expected_revision=cp.revision)
            self.assertEqual(settle(s,store,w).status,'HOLD_AUTHORITY');self.assertEqual(w.gh.update_refs_requests,0)

    def test_delayed_terminal_does_not_dispatch_or_advance(self):
        w=ready(self.tmp);s,store=connected(w);old=w.attempt()
        s.flow.attempt_reader=lambda:replace(old,state='STARTED_UNRESOLVED',terminal=None)
        self.assertEqual(settle(s,store,w).status,'HOLD_AUTHORITY');self.assertEqual(w.gh.update_refs_requests,0)
        s.flow.attempt_reader=w.attempt
        self.assertEqual(settle(s,store,w).status,'ADOPTED')

    def test_stale_revision_and_overlapping_generation_do_not_send(self):
        w=ready(self.tmp);s,store=connected(w);cp=store.restore('g61-static');rev=cp.revision
        cp.state.generation=2;store.save(cp.state,expected_revision=rev)
        self.assertEqual(s.settle(w.manifest,expected_revision=rev,now=NOW,constraints_known=True).status,'HOLD_AUTHORITY')
        self.assertEqual(settle(s,store,w).status,'HOLD_AUTHORITY');self.assertEqual(w.gh.update_refs_requests,0)

    def test_after_campaign_apply_crash_recovers_receipt_without_resend(self):
        w=ready(self.tmp);s,store=connected(w)
        with self.assertRaises(SimulatedCrash):settle(s,store,w,crash_hook=crash_at('AFTER_CAMPAIGN_APPLY'))
        before=(w.gh.object_posts,w.gh.update_refs_requests)
        fresh,_=connected(w,flow=s.flow,bootstrap=False)
        r=fresh.recover_receipt(w.manifest,expected_revision=store.restore('g61-static').revision)
        self.assertEqual(r.status,'ADOPTED');self.assertTrue(r.continuation_ready)
        self.assertEqual(before,(w.gh.object_posts,w.gh.update_refs_requests))
        self.assertEqual(store.restore('g61-static').state.rounds_completed,1)

    def test_after_checkpoint_crash_replay_is_noop(self):
        w=ready(self.tmp);s,store=connected(w)
        with self.assertRaises(SimulatedCrash):settle(s,store,w,crash_hook=crash_at('AFTER_CAMPAIGN_CHECKPOINT'))
        cp=store.restore('g61-static');before=w.client.create_calls
        self.assertEqual(s.recover_receipt(w.manifest,expected_revision=cp.revision).status,'NOOP_DUPLICATE')
        self.assertEqual(w.client.create_calls,before);self.assertEqual(w.gh.update_refs_requests,1)

    def test_partial_checkpoint_blocks_continuation_but_receipt_survives(self):
        w=ready(self.tmp);s,store=connected(w)
        with mock.patch.object(store,'save',return_value=type('Save',(),{'status':'UNKNOWN','revision':None})()):
            r=settle(s,store,w)
        self.assertEqual(r.status,'CHECKPOINT_UNKNOWN');self.assertFalse(r.continuation_ready)
        self.assertEqual(store.restore('g61-static').state.rounds_completed,0)
        self.assertEqual(s.recover_receipt(w.manifest,expected_revision=store.restore('g61-static').revision).status,'ADOPTED')
        self.assertEqual(w.gh.update_refs_requests,1)

    def test_competing_checkpoint_writer_cannot_return_ready(self):
        w=ready(self.tmp);s,store=connected(w)
        def rival(point):
            if point=='AFTER_CAMPAIGN_APPLY':
                cp=store.restore('g61-static');cp.state.generation=2;store.save(cp.state,expected_revision=cp.revision)
        r=settle(s,store,w,crash_hook=rival)
        self.assertEqual(r.status,'CHECKPOINT_CONFLICT');self.assertFalse(r.continuation_ready)
        self.assertEqual(store.restore('g61-static').state.rounds_completed,0)
        self.assertEqual(w.gh.update_refs_requests,1)

    def test_unknown_rules_or_permission_only_isolate_task_without_git_write(self):
        w=ready(self.tmp);s,store=connected(w)
        r=s.settle(w.manifest,expected_revision=store.restore('g61-static').revision,now=NOW)
        self.assertEqual(r.status,'HOLD_AUTHORITY');self.assertEqual(w.gh.update_refs_requests,0)
        self.assertEqual(store.restore('g61-static').state.tasks['A'].status,TaskStatus.BLOCKED)
        b=ready(Path(self.tmp)/'next','B',w.gh,w.client);s2,st2=connected(b)
        self.assertEqual(settle(s2,st2,b).status,'ADOPTED')

    def test_after_fence_crash_isolated_and_no_blind_resend(self):
        w=ready(self.tmp);s,store=connected(w)
        with self.assertRaises(SimulatedCrash):settle(s,store,w,crash_hook=crash_at('AFTER_REF_INTENT'))
        self.assertEqual(settle(s,store,w).status,'UNKNOWN');self.assertEqual(w.gh.update_refs_requests,0)
        self.assertEqual(settle(s,store,w).status,'UNKNOWN');self.assertEqual(w.gh.update_refs_requests,0)

    def test_lost_reply_before_after_applied_recovery_one_request(self):
        for mode in ('before','after'):
            w=ready(Path(self.tmp)/mode);s,store=connected(w)
            setattr(w.gh,'lose_reply_'+mode+'_apply',True)
            r=settle(s,store,w)
            self.assertEqual(r.status,'UNKNOWN' if mode=='before' else 'ADOPTED')
            r2=settle(s,store,w)
            self.assertEqual(r2.status,'UNKNOWN' if mode=='before' else 'NOOP_DUPLICATE')
            self.assertEqual(w.gh.update_refs_requests,1)

    def test_tampered_snapshot_ci_and_worker_self_pass_hold(self):
        for mode in ('snapshot','artifact','self-pass'):
            w=ready(Path(self.tmp)/mode);s,store=connected(w)
            if mode=='snapshot':
                p=w.snapshots._object_path(hashlib.sha256((w.workspace/'src/value.py').read_bytes()).hexdigest())
                p.chmod(0o600);p.write_bytes(b'tampered')
            else:
                ci=CIWorld(w)
                if mode=='artifact':ci.attestation['result_digest']='f'*64
                else:ci.attestation['records'][0]['verifier_id']=w.worker
                ci.reseal();v=strict_ci(ci);s.flow.verification_reader=lambda:v.read(w.manifest).evidence
            r=settle(s,store,w);self.assertNotEqual(r.status,'ADOPTED')
            self.assertEqual(store.restore('g61-static').state.rounds_completed,0);self.assertEqual(w.gh.update_refs_requests,0)

    def test_expired_mock_envelope_rejects_and_recovery_not_quota_gated(self):
        w=ready(self.tmp);s,store=connected(w);self.assertEqual(settle(s,store,w).status,'ADOPTED')
        gate=new_worker_cost_gate({'auth_state':'CHATGPT_ACCOUNT'},quota=QuotaState.EXHAUSTED,exhaustion_confirmed=True)
        self.assertFalse(gate['compatible'])
        self.assertEqual(s.recover_receipt(w.manifest,expected_revision=store.restore('g61-static').revision).status,'NOOP_DUPLICATE')
        self.assertEqual(w.gh.update_refs_requests,1)

    def test_subscription_selector_names_and_paid_fallback_block(self):
        account={'auth_state':'CHATGPT_ACCOUNT'}
        for name in ('OPENAI_API_KEY','CODEX_API_KEY','AZURE_OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_API_BASE'):
            self.assertFalse(new_worker_cost_gate(account,environment_keys=[name])['compatible'])
        for key in ('metered_fallback_configured','paid_provider_fallback_configured','paid_credit_fallback_configured'):
            self.assertFalse(new_worker_cost_gate(account,**{key:True})['compatible'])
        self.assertFalse(new_worker_cost_gate({'auth_state':'API_KEY'})['compatible'])

    def test_unavailable_telemetry_and_unconfirmed_exhaustion_are_unknown(self):
        account={'auth_state':'CHATGPT_ACCOUNT'}
        for q in (QuotaState.UNKNOWN,QuotaState.EXHAUSTED):
            g=new_worker_cost_gate(account,quota=q)
            self.assertTrue(g['compatible']);self.assertEqual(g['quota'],'UNKNOWN');self.assertFalse(g['dispatch_authorized'])
        self.assertFalse(new_worker_cost_gate(account,quota=QuotaState.EXHAUSTED,exhaustion_confirmed=True)['compatible'])

    def test_policy_is_configurable_and_original_scheduler_untouched(self):
        w=ready(self.tmp);s,store=connected(w)
        p=replace(HARDENED_AUTONOMOUS_POLICY,max_rounds=80,max_corrective_rounds_per_task=5,max_transient_retries=7)
        seam=StaticReceiptCampaignSeam(flow=s.flow,campaign_store=store,campaign_id='g61-static',generation=1,policy=p)
        self.assertEqual(seam.policy.max_rounds,80);self.assertFalse(hasattr(seam,'dispatch'))
        self.assertFalse(hasattr(seam,'start_worker'));self.assertEqual(settle(seam,store,w).status,'ADOPTED')


class G71AdditionalFaultTests(TempCase):
    def test_before_fence_restart_resumes_and_checkpoints_exactly_once(self):
        for point in ('AFTER_INTENT','AFTER_OBJECTS','AFTER_REF'):
            w=ready(Path(self.tmp)/point);s,store=connected(w)
            with self.assertRaises(SimulatedCrash):settle(s,store,w,crash_hook=crash_at(point))
            fresh,_=connected(w,flow=s.flow,bootstrap=False)
            self.assertEqual(settle(fresh,store,w).status,'ADOPTED')
            self.assertEqual(settle(fresh,store,w).status,'NOOP_DUPLICATE')
            self.assertEqual(w.gh.update_refs_requests,1)
            self.assertEqual(store.restore('g61-static').state.rounds_completed,1)

    def test_mock_candidate_mismatch_does_not_complete(self):
        w=ready(self.tmp);s,store=connected(w)
        def mismatch(point):
            if point=='AFTER_OBJECTS':s.flow.transport.read_candidate=lambda oid:None
        r=settle(s,store,w,crash_hook=mismatch)
        self.assertNotEqual(r.status,'ADOPTED');self.assertEqual(store.restore('g61-static').state.rounds_completed,0)

    def test_competing_target_claim_is_local_conflict_no_overwrite(self):
        w=ready(self.tmp);s,store=connected(w)
        with self.assertRaises(SimulatedCrash):settle(s,store,w,crash_hook=crash_at('AFTER_INTENT'))
        original=dict(w.client.files)
        b=ready(Path(self.tmp)/'B','B',w.gh,w.client);s2,st2=connected(b)
        r=settle(s2,st2,b);self.assertEqual(r.status,'CONFLICT');self.assertEqual(w.gh.update_refs_requests,0)
        for path,old in original.items():self.assertEqual(w.client.files[path],old)

    def test_expired_envelope_cannot_start_mock_publication(self):
        w=ready(self.tmp)
        with self.assertRaises(PermissionError):wired(w,now='2026-10-10T03:00:00Z')
        self.assertEqual((w.gh.object_posts,w.gh.update_refs_requests),(0,0))

    def test_snapshot_result_bytes_are_independently_bound_and_terminal_duplicate_noop(self):
        w=ready(self.tmp);s,store=connected(w)
        original=w.attempt()
        from ..symphony_upstream_event_adapter import UpstreamWorkerEvent,capture_static_attempt_event
        event=UpstreamWorkerEvent(campaign_id='g61-static',task_id='A',generation=1,attempt_id=w.attempt_id,
            runner_generation=1,expected_target_head=w.head,event_kind='STARTED',evidence_ref=w.worker,
            source_authentication='STATIC_SIMULATION')
        before=w.client.create_calls
        self.assertEqual(capture_static_attempt_event(w.attempts,event).status,'NOOP_DUPLICATE')
        terminal=original.terminal
        self.assertEqual(w.attempts.append_terminal(campaign_id='g61-static',attempt_id=w.attempt_id,
            **{k:terminal[k] for k in ('result_id','outcome','model_started','evidence_refs','unknown_class')}).status,'CONFLICT')
        self.assertEqual(w.attempt(),original);self.assertEqual(before,w.client.create_calls)
        self.assertEqual(settle(s,store,w).status,'ADOPTED')
        self.assertEqual(settle(s,store,w).status,'NOOP_DUPLICATE')
        self.assertEqual(w.gh.update_refs_requests,1)


class G71SignedObservationTests(TempCase):
    def test_signed_synthetic_observer_restart_is_noop_for_both_events(self):
        from .test_symphony_production_observer import SymphonyProductionObserverTests
        f=SymphonyProductionObserverTests();f.setUp()
        # In-memory test key/events only, not a new LIVE identity or launch.
        events=[f.event('STARTED'),f.event('TERMINAL',status='WORKER_STOPPED')]
        self.assertEqual([f.observer.capture_line(e).status for e in events],['ACCEPTED','ACCEPTED'])
        writes=f.client.create_calls
        self.assertEqual([f.fresh().capture_line(e).status for e in events],['NOOP_DUPLICATE','NOOP_DUPLICATE'])
        self.assertEqual(f.client.create_calls,writes)


class G71ActiveAttemptTests(TempCase):
    def test_ready_stale_or_unbound_blocked_task_cannot_publish(self):
        for status in (TaskStatus.READY,TaskStatus.STALE,TaskStatus.BLOCKED,TaskStatus.COMPLETE):
            w=ready(Path(self.tmp)/status.value);s,store=connected(w)
            cp=store.restore('g61-static');cp.state.tasks['A'].status=status
            store.save(cp.state,expected_revision=cp.revision)
            self.assertEqual(settle(s,store,w).status,'HOLD_AUTHORITY')
            self.assertEqual(w.gh.update_refs_requests,0)


class G71CheckpointReadFailureTests(TempCase):
    def test_checkpoint_post_save_read_error_never_advertises_ready(self):
        w=ready(self.tmp);s,store=connected(w);original=store.restore;calls=0
        def unavailable(campaign):
            nonlocal calls
            calls+=1
            if calls==3:raise OSError('synthetic read unavailable')
            return original(campaign)
        # settle() helper reads revision, seam restores, then post-save read fails.
        with mock.patch.object(store,'restore',side_effect=unavailable):r=settle(s,store,w)
        self.assertEqual(r.status,'CHECKPOINT_UNKNOWN');self.assertFalse(r.continuation_ready)
        self.assertEqual(s.recover_receipt(w.manifest,expected_revision=store.restore('g61-static').revision).status,'NOOP_DUPLICATE')
        self.assertEqual(w.gh.update_refs_requests,1)
