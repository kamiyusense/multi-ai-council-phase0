"""Optional G7 STATIC: reuse the existing campaign controller/kernel/store."""
from __future__ import annotations
from collections import Counter
from dataclasses import replace
import unittest
from .test_symphony_autonomous_controller import make_store, bootstrap, result
from ..symphony_autonomous_controller import (StaticAutonomousCampaignController,StaticCampaignTaskRunner,
    StaticTargetObserver,StaticQuotaReader,TaskExecutionResult)
from ..symphony_autonomous_policy import HARDENED_AUTONOMOUS_POLICY,QuotaState,UnknownClass
from ..symphony_autonomous_runtime import CampaignState,CampaignTask,TaskOutcome,TaskStatus


def run_g7_soak():
    client,store=make_store()
    tasks={'A-blocked':CampaignTask('A-blocked',expected_target_head='h1'),
           'B-corrective':CampaignTask('B-corrective',expected_target_head='h1')}
    tasks.update({f'T{i:02d}':CampaignTask(f'T{i:02d}',expected_target_head='h1') for i in range(35)})
    bootstrap(store,CampaignState('g7-synthetic-soak',1,tasks))
    scripts={task_id:[result('r-'+task_id)] for task_id in tasks}
    scripts['A-blocked']=[TaskExecutionResult('r-blocked',TaskOutcome.UNKNOWN,UnknownClass.HARD_UNKNOWN)]
    scripts['B-corrective']=[result('r-failed',TaskOutcome.FAILED)]
    scripts['B-corrective::corrective::1']=[result('r-corrective')]
    policy=replace(HARDENED_AUTONOMOUS_POLICY,max_rounds=50)
    sessions=[];starts=[]
    for session in range(10):
        runner=StaticCampaignTaskRunner(scripts)
        end=StaticAutonomousCampaignController(store,campaign_id='g7-synthetic-soak',
            target_observer=StaticTargetObserver('h1'),runner=runner,policy=policy,
            quota_reader=StaticQuotaReader(QuotaState.UNKNOWN)).run_until_boundary(max_steps=5)
        starts.extend(runner.start_calls);sessions.append({'session':session,'status':end.status,'calls':runner.calls})
        if end.status!='BATCH_LIMIT':break
    state=store.restore('g7-synthetic-soak').state
    idle=StaticCampaignTaskRunner(scripts)
    last=StaticAutonomousCampaignController(store,campaign_id='g7-synthetic-soak',
        target_observer=StaticTargetObserver('h1'),runner=idle,policy=policy).run_until_boundary()
    assert state.tasks['A-blocked'].status is TaskStatus.BLOCKED
    assert all(state.tasks[f'T{i:02d}'].status is TaskStatus.COMPLETE for i in range(35))
    assert state.tasks['B-corrective'].status is TaskStatus.COMPLETE
    assert len(set(starts))==len(starts) and not idle.start_calls
    assert state.rounds_completed>=35
    return {'protocol':'SYMPHONY_G7_STATIC_SOAK_V1','result':'PASS','rounds_completed':state.rounds_completed,
        'mock_worker_starts':len(starts),'unique_mock_starts':len(set(starts)),'sessions':sessions,
        'blocked_task_isolated':True,'corrective_task_completed':True,'quota_telemetry_UNKNOWN_continued':True,
        'final_status':last.status,'restart_additional_dispatch':len(idle.start_calls),
        'real_model_starts':0,'real_github_writes':0,'new_scheduler':False}


class G7ReuseTests(unittest.TestCase):
    def test_35_plus_round_soak_across_multiple_sessions_with_isolated_unknown_and_corrective(self):
        r=run_g7_soak();self.assertEqual(r['result'],'PASS');self.assertGreaterEqual(r['rounds_completed'],35)
        self.assertGreater(len(r['sessions']),1);self.assertEqual(r['restart_additional_dispatch'],0)

    def test_confirmed_quota_exhaustion_stops_new_mock_dispatch_unknown_continues(self):
        _,store=make_store();bootstrap(store,CampaignState('g7-quota',1,{'A':CampaignTask('A',expected_target_head='h1')}))
        runner=StaticCampaignTaskRunner({'A':[result('done')]})
        first=StaticAutonomousCampaignController(store,campaign_id='g7-quota',target_observer=StaticTargetObserver('h1'),
            runner=runner,quota_reader=StaticQuotaReader(QuotaState.EXHAUSTED)).run_until_boundary()
        self.assertEqual(runner.calls,[]);self.assertIn('QUOTA',first.status)
        second=StaticAutonomousCampaignController(store,campaign_id='g7-quota',target_observer=StaticTargetObserver('h1'),
            runner=runner,quota_reader=StaticQuotaReader(QuotaState.UNKNOWN)).run_until_boundary()
        self.assertEqual(second.status,'CAMPAIGN_COMPLETE');self.assertEqual(runner.calls,['A'])

    def test_stale_task_replans_and_independent_next_task_proceeds(self):
        _,store=make_store();bootstrap(store,CampaignState('g7-stale',1,{
            'A':CampaignTask('A',expected_target_head='h0'),'B':CampaignTask('B',expected_target_head='h1')}))
        runner=StaticCampaignTaskRunner({'A':[result('a')],'B':[result('b')]})
        done=StaticAutonomousCampaignController(store,campaign_id='g7-stale',target_observer=StaticTargetObserver('h1'),
            runner=runner).run_until_boundary()
        self.assertEqual(done.status,'CAMPAIGN_COMPLETE');self.assertEqual(set(runner.calls),{'A','B'})
        self.assertEqual(store.restore('g7-stale').state.tasks['A'].expected_target_head,'h1')
