"""Real OFF host/disk/seal/transport with fake Codex IO, no model or remote IO."""
import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from .test_symphony_g61_production_wiring import TempCase, NOW
from .test_symphony_g72_runtime import ObservedWorld, signed
from .test_symphony_security_corrective import FakeProcess
from ..symphony_g73_host import LocalStaticContents, OperatorStaticHost
from ..symphony_sqlite_storage import SQLiteStorageReview, ReviewedSQLiteStorage
from ..symphony_autonomous_runtime import CampaignState, CampaignTask
from ..symphony_result_manifest import digest
from ..symphony_worker_first_preparation import WorkerPreparationReview
from .. import symphony_worker_first_preparation as subject

BRANCH = 'codex/symphony-worker-proof-preparation-fixture'
TARGET = 'codex/symphony-worker-first-fixture'


class WorkerPreparationTests(TempCase):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp)
        self.w = ObservedWorld(root/'world', client=LocalStaticContents(root/'records'))
        self.w.gh.set_branch(TARGET, self.w.head)
        state = CampaignState('g61-static', 1, {'A': CampaignTask('A')})
        self.w.campaign_store.save(state, expected_revision=0)
        events = root/'events.jsonl'; events.touch(mode=0o600)
        self.host = OperatorStaticHost(self.w.adapter(), events=events, workspace=self.w.workspace)
        self.host.adapter.target_reader.branch = TARGET
        self.auth = root/'auth'; self.auth.mkdir(mode=0o700)
        self.binary = root/'codex'; self.binary.write_bytes(b'STATIC_ELF_FIXTURE'); self.binary.chmod(0o700)
        self.dbroot = root/'sqlite'; self.dbroot.mkdir(mode=0o700)
        db = self.dbroot/'state_5.sqlite'
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE _sqlx_migrations(version INTEGER,success INTEGER,checksum BLOB)')
            c.execute('INSERT INTO _sqlx_migrations VALUES(1,1,?)', (b'STATIC_MIGRATION',))
        db.chmod(0o600)
        inventory = [{'database':'state_5.sqlite','migrations':[[1,hashlib.sha256(b'STATIC_MIGRATION').hexdigest()]]}]
        storage_review = SQLiteStorageReview(self.dbroot,self.auth,self.binary,
            hashlib.sha256(self.binary.read_bytes()).hexdigest(),digest(inventory),(self.w.workspace,))
        self.storage = ReviewedSQLiteStorage(review=storage_review,installation_check=lambda _:True)
        self.storage.seal_initialized()
        self.review = WorkerPreparationReview('prepare-fixture-20261014',
            'fixture/council',self.w.issue_id,'A','g61-static',1,1,
            digest(self.w.scope),str(self.w.workspace),BRANCH,self.w.head,TARGET,self.w.head,
            str(self.binary),storage_review.executable_sha256,str(self.auth),'2026-10-10T01:05:00Z')
        self.process = FakeProcess()
        self.env = patch.dict(os.environ,{'PATH':os.defpath,'HOME':str(root),'CODEX_HOME':str(self.auth),
            'CODEX_SQLITE_HOME':'STATIC_SHARED_DB_MUST_NOT_REACH_CHILD','GH_TOKEN':'STATIC_AUTHORITY'},clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.git = patch.object(subject,'_git',side_effect=self.git_value)
        self.git.start(); self.addCleanup(self.git.stop)
        self.fs = patch.object(subject,'_native_linux_state',return_value=True)
        self.fs.start(); self.addCleanup(self.fs.stop)
        self.launch = patch('automation.command_bus.symphony_codex_app_server.subprocess.Popen',return_value=self.process)
        self.launched = self.launch.start(); self.addCleanup(self.launch.stop)

    def git_value(self, workspace, *args):
        return BRANCH if args[0]=='symbolic-ref' else self.w.head if args[0]=='rev-parse' else ''

    def prepare(self, review=None, now=lambda:NOW):
        return subject.prepare_worker(review=review or self.review,storage=self.storage,host=self.host,now=now)

    def test_sealed_same_process_route_bound_to_off_host_without_worker_start(self):
        result = self.prepare()
        self.assertEqual(result['status'],'PREPARED_STATIC_ONLY_NOT_LAUNCH')
        self.assertFalse(result['worker_dispatch_authorized'])
        self.assertEqual([c['method'] for c in self.process.calls],
            ['initialize','initialized','account/read','config/read'])
        child = self.launched.call_args.kwargs['env']
        self.assertNotIn('GH_TOKEN',child); self.assertNotIn('CODEX_SQLITE_HOME',child)
        self.assertEqual(child['CODEX_HOME'],str(self.auth))
        self.assertEqual(self.launched.call_args.kwargs['umask'],0o077)
        self.assertEqual(self.w.campaign_store.restore('g61-static').revision,1)
        self.assertEqual(self.w.gh.update_refs_requests,0)
        self.assertNotIn(str(self.auth),json.dumps(result))

    def test_exact_duplicate_is_get_only_even_after_host_reconstruction(self):
        self.assertEqual(self.prepare()['status'],'PREPARED_STATIC_ONLY_NOT_LAUNCH')
        self.host = OperatorStaticHost(self.host.adapter,events=self.host.events,workspace=self.w.workspace)
        self.assertEqual(self.prepare()['status'],'NOOP_DUPLICATE')
        self.assertEqual(self.launched.call_count,1)

    def test_abandoned_or_ambiguous_intent_never_probes_again(self):
        self.process = FakeProcess(account={'account':{'type':'apiKey'},'requiresOpenaiAuth':True})
        self.launched.return_value = self.process
        self.assertEqual(self.prepare()['status'],'HOLD_CHANGED_OR_UNVERIFIED')
        self.assertEqual(self.prepare()['status'],'HOLD_INTENT_GET_ONLY')
        self.assertEqual(self.launched.call_count,1)

    def test_uncertain_create_or_outcome_is_get_only_and_not_pass(self):
        put = self.host.adapter.ledger._put
        with patch.object(self.host.adapter.ledger,'_put',return_value='UNKNOWN'):
            self.assertEqual(self.prepare()['status'],'HOLD_INTENT_GET_ONLY')
        self.launched.assert_not_called()
        def uncertain(path, body):
            return 'UNKNOWN' if path.endswith('outcome.json') else put(path,body)
        with patch.object(self.host.adapter.ledger,'_put',side_effect=uncertain):
            self.assertEqual(self.prepare()['status'],'HOLD_OUTCOME_GET_ONLY')
        self.assertEqual(self.prepare()['status'],'HOLD_INTENT_GET_ONLY')
        self.assertEqual(self.launched.call_count,1)

    def test_changed_operator_review_cannot_rebind_existing_intent(self):
        self.prepare()
        altered = replace(self.review,expires_at='2026-10-10T01:06:00Z')
        self.assertEqual(self.prepare(altered)['status'],'CONFLICT')
        self.assertEqual(self.launched.call_count,1)

    def test_stale_identity_head_scope_and_unreviewed_default_branch_refused(self):
        for changes in ({'source_head':'b'*40},{'target_head':'b'*40},{'target_branch':'main'},
                        {'workspace_branch':'main'},{'task_id':'B'},{'generation':2},
                        {'runner_generation':2},{'issue_id':'unbound'},{'scope_digest':'b'*64}):
            with self.subTest(changes=changes):
                self.assertEqual(self.prepare(replace(self.review,**changes))['status'],'BLOCKED_UNVERIFIED')
        self.launched.assert_not_called()

    def test_default_branch_named_codex_still_cannot_qualify(self):
        self.host.adapter.target_reader.default_branch=TARGET
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        self.launched.assert_not_called()

    def test_expired_unbounded_naive_or_reversed_clock_refused(self):
        for expires in (NOW,'2026-10-10T01:11:00Z','2026-10-10T01:05:00'):
            self.assertEqual(self.prepare(replace(self.review,expires_at=expires))['status'],'BLOCKED_UNVERIFIED')
        self.launched.assert_not_called()
        clock = iter([NOW,'2026-10-10T00:59:59Z'])
        self.assertEqual(self.prepare(now=lambda:next(clock))['status'],'HOLD_CHANGED_OR_UNVERIFIED')

    def test_workspace_head_or_auth_changes_during_same_process_probe_block(self):
        def drift(*args,**kwargs):
            os.environ['CODEX_HOME'] = str(self.auth/'rebound')
            return self.process
        self.launched.side_effect = drift
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        self.assertEqual(self.launched.call_count,1)

    def test_changed_head_during_probe_never_prepares(self):
        old = self.git_value
        def drift(*args,**kwargs):
            subject._git = lambda workspace,*args: 'b'*40 if args[0]=='rev-parse' else old(workspace,*args)
            return self.process
        self.launched.side_effect = drift
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')

    def test_changed_canonical_target_during_probe_never_prepares(self):
        def drift(*args,**kwargs):
            self.w.gh.advance(TARGET,self.w.gh.tree_files(self.w.head))
            return self.process
        self.launched.side_effect = drift
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')

    def test_changed_observer_key_during_probe_never_prepares(self):
        def drift(*args,**kwargs):
            self.host.adapter.observer.key=b'CHANGED_STATIC_FIXTURE_KEY_32_BYTES'
            return self.process
        self.launched.side_effect=drift
        result=self.prepare()
        self.assertEqual(result['status'],'HOLD_CHANGED_OR_UNVERIFIED')
        self.assertNotIn('CHANGED_STATIC_FIXTURE_KEY',json.dumps(result))

    def test_replaced_snapshot_directory_during_probe_never_prepares(self):
        def drift(*args,**kwargs):
            root=Path(self.w.snapshots.root)
            root.rename(root.with_name('old-snapshots'));root.mkdir(mode=0o700)
            return self.process
        self.launched.side_effect=drift
        self.assertEqual(self.prepare()['status'],'HOLD_CHANGED_OR_UNVERIFIED')

    def test_provider_exception_is_sanitized_and_intent_stays_get_only(self):
        self.launched.side_effect = RuntimeError('STATIC_PRIVATE_SENTINEL')
        result = self.prepare()
        self.assertNotIn('STATIC_PRIVATE_SENTINEL',json.dumps(result))
        self.assertEqual(result['status'],'HOLD_CHANGED_OR_UNVERIFIED')
        self.assertEqual(self.prepare()['status'],'HOLD_INTENT_GET_ONLY')
        self.assertEqual(self.launched.call_count,1)

    def test_binary_storage_seal_and_native_fs_changes_refused_before_probe(self):
        self.binary.write_bytes(b'CHANGED')
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        self.binary.write_bytes(b'STATIC_ELF_FIXTURE')
        with patch.object(subject,'_native_linux_state',return_value=False):
            self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        (self.dbroot/'symphony-sqlite-storage.json').write_bytes(b'partial')
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        self.launched.assert_not_called()

    def test_event_symlink_hardlink_owner_mode_and_storage_overlap_refused(self):
        p = self.host.events
        p.chmod(0o644); self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED'); p.chmod(0o600)
        os.link(p,Path(self.tmp)/'linked-events')
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        self.launched.assert_not_called()

    def test_linked_events_or_operator_root_inside_auth_refused(self):
        p = self.host.events
        other = Path(self.tmp)/'outside-events'; other.touch(mode=0o600)
        p.unlink(); p.symlink_to(other)
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        p.unlink(); p.touch(mode=0o600)
        self.host.events = self.auth/'events.jsonl'; self.host.events.touch(mode=0o600)
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        self.launched.assert_not_called()

    def test_shared_writeable_binary_is_not_an_operator_pin(self):
        self.binary.chmod(0o777)
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED')
        self.launched.assert_not_called()

    def test_metered_parent_and_paid_config_are_not_silently_filtered_into_pass(self):
        os.environ['OPENAI_API_KEY'] = 'STATIC_NOT_KEY'
        self.assertEqual(self.prepare()['status'],'BLOCKED_UNVERIFIED'); self.launched.assert_not_called()
        os.environ.pop('OPENAI_API_KEY')
        self.launched.return_value = FakeProcess(config={'config':{'model_provider':'openai','paid_credit_fallback_configured':True}})
        self.assertEqual(self.prepare()['status'],'HOLD_CHANGED_OR_UNVERIFIED')

    def test_prepared_host_connects_signed_observer_snapshot_before_cleanup(self):
        self.assertEqual(self.prepare()['status'],'PREPARED_STATIC_ONLY_NOT_LAUNCH')
        self.assertEqual(self.host.handle('admission',task_id='A',expected_revision=1,
            account_evidence={'auth_state':'CHATGPT_ACCOUNT'})['result']['status'],'PREPARED_STATIC_ONLY')
        self.host.events.write_text(signed(self.w,'STARTED')+'\n')
        event = self.host.handle('replay')['results'][0]
        self.assertEqual(event['status'],'ACCEPTED')
        attempt = event['attempt_id']; snap_id = 'prepared-before-cleanup'
        captured = self.host.handle('snapshot',attempt_id=attempt,snapshot_id=snap_id,captured_at=NOW)
        self.assertTrue(captured['result']['close_ready'])
        source = self.w.snapshots.load(snap_id)
        shutil.rmtree(self.w.workspace)  # This test's disposable fixture only.
        self.assertEqual(self.w.snapshots.load(snap_id).files,source.files)
        self.host.events.write_text(signed(self.w,'TERMINAL')+'\n')
        self.host.handle('replay')
        fresh = OperatorStaticHost(self.host.adapter,events=self.host.events,workspace=self.w.workspace)
        self.assertEqual(fresh.handle('replay')['results'][0]['status'],'NOOP_DUPLICATE')
        self.assertEqual(self.w.gh.update_refs_requests,0)
        with self.assertRaises(PermissionError): fresh.execute()
