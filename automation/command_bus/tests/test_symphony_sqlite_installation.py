"""New persistent storage gaps only; all worker turns and approvals are fixtures."""
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from ..symphony_result_manifest import canonical
from ..symphony_sqlite_storage import SQLiteStorageReview, ReviewedSQLiteStorage, SEAL
from ..symphony_codex_app_server import JsonlCodexAppServer
from .test_symphony_security_corrective import FakeProcess
from .test_symphony_sqlite_host_recovery import installed_config


class PersistentSQLiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'state'; self.root.mkdir(mode=0o700)
        self.auth = self.base / 'auth'; self.auth.mkdir(mode=0o700)
        (self.auth/'state_5.sqlite').write_bytes(b'EXISTING_WINDOWS_DB_MUST_SURVIVE')
        (self.auth/'auth.json').write_bytes(b'STATIC_AUTH_NOT_COPIED')
        self.workspace = self.base/'workspace'; self.workspace.mkdir()
        self.binary = self.base/'codex'; self.binary.write_bytes(b'STATIC_BINARY')
        db = self.root/'state_5.sqlite'
        with closing(sqlite3.connect(db)) as c, c:
            c.execute('CREATE TABLE _sqlx_migrations(version INTEGER, success INTEGER, checksum BLOB)')
            c.execute('INSERT INTO _sqlx_migrations VALUES(1,1,?)',(b'STATIC_MIGRATION',))
            c.execute('CREATE TABLE work(value TEXT)'); c.execute("INSERT INTO work VALUES('durable')")
        db.chmod(0o600)
        inventory=[{'database':'state_5.sqlite','migrations':[[1,hashlib.sha256(b'STATIC_MIGRATION').hexdigest()]]}]
        self.review=SQLiteStorageReview(self.root,self.auth,self.binary,
            hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            hashlib.sha256(canonical(inventory).encode()).hexdigest(),(self.workspace,))
        self.install=Mock(return_value=True);self.worker=Mock(return_value=True)
        self.store=ReviewedSQLiteStorage(review=self.review,installation_check=self.install)

    def test_seal_and_fresh_object_restart_preserve_data_auth_and_old_database(self):
        before={p.name:p.read_bytes() for p in self.auth.iterdir()}
        self.assertEqual(self.store.seal_initialized(),'CREATED')
        fresh=ReviewedSQLiteStorage(review=self.review,installation_check=self.install)
        self.assertEqual(fresh.seal_initialized(),'NOOP_DUPLICATE')
        self.assertEqual(fresh.readiness()['state'],'STORAGE_READINESS_PASS_NOT_WORKER_ADMISSION')
        with closing(sqlite3.connect(self.root/'state_5.sqlite')) as c, c:self.assertEqual(c.execute('SELECT value FROM work').fetchone(),('durable',))
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.auth.iterdir()})
        self.assertFalse((self.root/'auth.json').exists())

    def test_storage_approval_does_not_approve_worker_or_disable_off_gate(self):
        self.store.seal_initialized()
        with self.assertRaises(PermissionError):self.store.app_server_args(executable=self.binary,auth_home=self.auth,readonly=False)
        with patch('automation.command_bus.symphony_codex_app_server.subprocess.Popen') as launch:
            client=JsonlCodexAppServer(str(self.binary),production_storage=self.store)
            self.assertEqual(client.execute_one_turn(cwd=str(self.workspace),prompt='STATIC').status,'BLOCKED')
            self.assertEqual(client.execute_one_turn(cwd=str(self.workspace),prompt='STATIC',live_enabled=True).status,'UNKNOWN')
            launch.assert_not_called()

    def session(self, process, *, worker=False):
        store=ReviewedSQLiteStorage(review=self.review,installation_check=self.install,
                                    worker_check=self.worker if worker else None)
        with patch.dict(os.environ,{'PATH':'/bin','HOME':str(self.base),'CODEX_HOME':str(self.auth),'GH_TOKEN':'STATIC'},clear=True), \
             patch('automation.command_bus.symphony_codex_app_server.subprocess.Popen',return_value=process) as launch:
            client=JsonlCodexAppServer(str(self.binary),production_storage=store)
            result=(client.execute_one_turn(cwd=str(self.workspace),prompt='STATIC',live_enabled=True)
                    if worker else client.probe_read_only(cwd=str(self.workspace)))
        return result,launch

    def test_durable_readonly_reuse_has_no_thread_or_model_and_keeps_auth_route(self):
        self.store.seal_initialized();proc=FakeProcess(config=installed_config())
        result,launch=self.session(proc)
        self.assertEqual(result['status'],'DONE')
        self.assertEqual([x['method'] for x in proc.calls],['initialize','initialized','account/read','config/read'])
        self.assertIn('sqlite_home=',launch.call_args.args[0][-1])
        self.assertEqual(launch.call_args.kwargs['env']['CODEX_HOME'],str(self.auth))
        self.assertNotIn('GH_TOKEN',launch.call_args.kwargs['env'])
        self.assertEqual(launch.call_args.kwargs['umask'],0o077)
        self.worker.assert_not_called()

    def test_approved_mock_worker_still_requires_same_process_account_config(self):
        self.store.seal_initialized();proc=FakeProcess(config=installed_config())
        result,_=self.session(proc,worker=True);self.assertEqual(result.status,'DONE')
        self.assertEqual([x['method'] for x in proc.calls[:5]],['initialize','initialized','account/read','config/read','thread/start'])
        bad=FakeProcess(account={'account':{'type':'apiKey'},'requiresOpenaiAuth':True},config=installed_config())
        result,_=self.session(bad,worker=True);self.assertEqual(result.status,'BLOCKED')
        self.assertFalse(any(x['method'] in ('thread/start','turn/start') for x in bad.calls))

    def test_fresh_diagnostic_guard_cannot_be_used_for_existing_production_store(self):
        self.store.seal_initialized()
        with patch('automation.command_bus.symphony_codex_app_server.subprocess.Popen') as launch:
            r=JsonlCodexAppServer(str(self.binary),production_storage=self.store).probe_read_only(cwd=str(self.workspace),sqlite_home=self.root)
            self.assertEqual(r['status'],'UNKNOWN');launch.assert_not_called()

    def test_symlink_hardlink_wrong_permissions_and_noncanonical_paths_refused(self):
        db=self.root/'state_5.sqlite'
        link=self.base/'alias';link.symlink_to(self.root,target_is_directory=True)
        for root in (link,self.root/'..'/'state',self.auth,self.workspace):
            s=ReviewedSQLiteStorage(review=replace(self.review,root=root),installation_check=self.install)
            with self.subTest(root=root),self.assertRaises(PermissionError):s.seal_initialized()
        for mode in (0o755,0o777):
            self.root.chmod(mode)
            with self.assertRaises(PermissionError):self.store.seal_initialized()
        self.root.chmod(0o700);db.chmod(0o644)
        with self.assertRaises(PermissionError):self.store.seal_initialized()
        db.chmod(0o600);os.link(db,self.base/'db-link')
        with self.assertRaises(PermissionError):self.store.seal_initialized()

    def test_auth_or_workspace_nested_storage_and_arbitrary_extra_files_refused(self):
        for boundary in (self.auth,self.workspace):
            nested=boundary/'nested';nested.mkdir(mode=0o700)
            with self.assertRaises(PermissionError):ReviewedSQLiteStorage(review=replace(self.review,root=nested),installation_check=self.install).seal_initialized()
        (self.root/'auth.json').write_bytes(b'STATIC')
        with self.assertRaises(PermissionError):self.store.seal_initialized()

    def test_wrong_binary_migration_or_directory_replacement_never_repaired(self):
        self.store.seal_initialized();raw=(self.root/SEAL).read_bytes()
        self.binary.write_bytes(b'BINARY_CHANGED')
        with self.assertRaises(PermissionError):self.store.readiness()
        self.binary.write_bytes(b'STATIC_BINARY')
        with closing(sqlite3.connect(self.root/'state_5.sqlite')) as c, c:c.execute('UPDATE _sqlx_migrations SET checksum=?',(b'CRLF_DIFFERENT',))
        with self.assertRaises(PermissionError):self.store.seal_initialized()
        self.assertEqual((self.root/SEAL).read_bytes(),raw)

    def test_partial_seal_and_corrupt_database_no_overwrite_or_reinitialization(self):
        (self.root/SEAL).write_bytes(b'{partial');(self.root/SEAL).chmod(0o600)
        with self.assertRaises(PermissionError):self.store.seal_initialized()
        self.assertEqual((self.root/SEAL).read_bytes(),b'{partial')
        (self.root/'state_5.sqlite').write_bytes(b'CORRUPT')
        with self.assertRaises(PermissionError):self.store.readiness()
        self.assertEqual((self.root/'state_5.sqlite').read_bytes(),b'CORRUPT')

    def test_crashed_sqlite_writer_committed_wal_survives_readiness(self):
        self.store.seal_initialized()
        code="import sqlite3,os; c=sqlite3.connect(os.environ['STATIC_DB']); c.execute('PRAGMA journal_mode=WAL'); c.execute(\"INSERT INTO work VALUES('after-crash')\"); c.commit(); os._exit(0)"
        subprocess.run([sys.executable,'-c',code],env={**os.environ,'STATIC_DB':str(self.root/'state_5.sqlite')},check=True)
        for p in self.root.iterdir():p.chmod(0o600)
        self.assertTrue(self.store.readiness()['wal_present'])
        with closing(sqlite3.connect(self.root/'state_5.sqlite')) as c, c:self.assertIn(('after-crash',),c.execute('SELECT value FROM work').fetchall())

    def test_offline_backup_restore_new_root_not_auth_and_create_only(self):
        self.store.seal_initialized();dest=self.base/'backup';dest.mkdir(mode=0o700)
        self.assertEqual(self.store.backup_quiescent(dest,quiescent_check=lambda _:True)['credentials_copied'],0)
        restored=ReviewedSQLiteStorage(review=replace(self.review,root=dest),installation_check=self.install)
        self.assertEqual(restored.seal_initialized(),'CREATED');self.assertEqual(restored.readiness()['database_count'],1)
        with self.assertRaises(PermissionError):self.store.backup_quiescent(dest,quiescent_check=lambda _:True)
        with self.assertRaises(PermissionError):self.store.backup_quiescent(self.auth,quiescent_check=lambda _:True)
        self.assertFalse((dest/'auth.json').exists())

    def test_backup_requires_independent_quiescence_and_installation_approval(self):
        self.store.seal_initialized();dest=self.base/'backup';dest.mkdir(mode=0o700)
        with self.assertRaises(PermissionError):self.store.backup_quiescent(dest,quiescent_check=lambda _:False)
        self.assertEqual(list(dest.iterdir()),[])
        self.install.return_value=False
        with self.assertRaises(PermissionError):self.store.backup_quiescent(dest,quiescent_check=lambda _:True)

    def test_concurrent_seal_never_overwrites_single_record(self):
        def attempt(_):
            try:return self.store.seal_initialized()
            except FileExistsError:return 'CONCURRENT_CREATE_GET_ONLY'
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,range(2)))
        self.assertEqual(results.count('CREATED'),1)
        self.assertEqual(self.store.readiness()['database_count'],1)

    def test_auth_launch_identity_and_missing_installation_review_refused(self):
        self.install.return_value=False
        with self.assertRaises(PermissionError):self.store.seal_initialized()
        self.assertFalse((self.root/SEAL).exists())
        self.install.return_value=True;self.store.seal_initialized()
        for binary,auth in [(self.binary,'wrong-auth'),('codex',self.auth)]:
            with self.assertRaises(PermissionError):self.store.app_server_args(executable=binary,auth_home=auth,readonly=True)


if __name__=='__main__':unittest.main()
