"""Synthetic new databases only; original sealed storage implementation reused."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from .. import symphony_sqlite_preparation as subject
from ..symphony_sqlite_storage import SQLiteStorageReview, ReviewedSQLiteStorage, SEAL
from ..symphony_result_manifest import digest
from .test_symphony_native_binary_preparation import elf_fixture


class SQLitePreparationTests(unittest.TestCase):
    def setUp(self):
        ancestry = patch('automation.command_bus.symphony_native_binary_preparation.SYSTEM_UID', Path('/').stat().st_uid)
        ancestry.start(); self.addCleanup(ancestry.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        for name in ('state','auth','workspace','binary'):(self.base/name).mkdir(mode=0o700)
        self.root=self.base/'state';self.auth=self.base/'auth';self.workspace=self.base/'workspace'
        (self.auth/'auth.json').write_bytes(b'SYNTHETIC_AUTH_PRESERVE')
        (self.auth/'state_5.sqlite').write_bytes(b'ORIGINAL_DB_MUST_NOT_OPEN')
        self.binary=self.base/'binary'/'codex';self.binary.write_bytes(elf_fixture());self.binary.chmod(0o700)
        self.db=self.root/'state_5.sqlite'
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE _sqlx_migrations(version INTEGER,success INTEGER,checksum BLOB)')
            c.execute('INSERT INTO _sqlx_migrations VALUES(1,1,?)',(b'SYNTHETIC_MIGRATION',))
            c.execute('CREATE TABLE private_rows(value TEXT)')
            c.execute('INSERT INTO private_rows VALUES(?)',('PRIVATE_ROW_SENTINEL',))
        self.db.chmod(0o600)
        inventory=[{'database':self.db.name,'migrations':[[1,hashlib.sha256(b'SYNTHETIC_MIGRATION').hexdigest()]]}]
        self.review=SQLiteStorageReview(self.root,self.auth,self.binary,
            hashlib.sha256(self.binary.read_bytes()).hexdigest(),digest(inventory),(self.workspace,))
        self.approval=Mock(return_value=False)
        self.store=ReviewedSQLiteStorage(review=self.review,installation_check=self.approval)
        for target in ('automation.command_bus.symphony_native_binary_preparation._native_linux_state',
                       'automation.command_bus.symphony_sqlite_preparation._native_linux_state'):
            mock=patch(target,return_value=True);mock.start();self.addCleanup(mock.stop)

    def prepare(self):return subject.prepare_sqlite_review(self.store)

    def test_new_unsealed_store_packet_preserves_all_bytes_and_no_approval(self):
        before={str(p):p.read_bytes() for d in (self.root,self.auth) for p in d.iterdir()}
        result=self.prepare();self.assertEqual(result,self.prepare())
        self.assertFalse(result['existing_seal_verified']);self.assertFalse(result['seal_created'])
        self.assertEqual(result['integrity_check'],'ok');self.approval.assert_not_called()
        self.assertNotIn('PRIVATE_ROW_SENTINEL',str(result))
        self.assertEqual(before,{str(p):p.read_bytes() for d in (self.root,self.auth) for p in d.iterdir()})
        self.assertFalse((self.root/SEAL).exists())

    def test_existing_fixture_seal_validated_never_minted_or_replaced(self):
        self.approval.return_value=True;self.store.seal_initialized();self.approval.reset_mock()
        seal=(self.root/SEAL).read_bytes();self.assertTrue(self.prepare()['existing_seal_verified'])
        self.assertEqual(seal,(self.root/SEAL).read_bytes());self.approval.assert_not_called()

    def test_wrong_migration_version_checksum_or_interrupted_migration_refused(self):
        for sql in ('UPDATE _sqlx_migrations SET version=2',
                    'UPDATE _sqlx_migrations SET success=0',
                    "UPDATE _sqlx_migrations SET checksum=x'01'"):
            with sqlite3.connect(self.db) as c:c.execute(sql)
            with self.subTest(sql=sql),self.assertRaises(PermissionError):self.prepare()
            with sqlite3.connect(self.db) as c:
                c.execute('UPDATE _sqlx_migrations SET version=1,success=1,checksum=?',(b'SYNTHETIC_MIGRATION',))
        self.assertFalse((self.root/SEAL).exists())

    def test_corrupt_database_partial_and_stale_seal_preserved(self):
        self.approval.return_value=True;self.store.seal_initialized()
        (self.root/SEAL).write_bytes(b'PARTIAL_SEAL')
        with self.assertRaises(PermissionError):self.prepare()
        self.assertEqual((self.root/SEAL).read_bytes(),b'PARTIAL_SEAL')
        self.db.write_bytes(b'CORRUPT_DO_NOT_REPAIR')
        with self.assertRaises(PermissionError):self.prepare()
        self.assertEqual(self.db.read_bytes(),b'CORRUPT_DO_NOT_REPAIR')

    def test_unexpected_file_or_wal_requires_recovery_no_implicit_repair(self):
        for name in ('auth.json','state_5.sqlite-wal','state_5.sqlite-shm','unknown.db'):
            p=self.root/name;p.write_bytes(b'PRESERVE');p.chmod(0o600)
            with self.subTest(name=name),self.assertRaises(PermissionError):self.prepare()
            self.assertEqual(p.read_bytes(),b'PRESERVE');p.unlink()

    def test_linked_permissive_or_shared_db_refused(self):
        self.db.chmod(0o644)
        with self.assertRaises(PermissionError):self.prepare()
        self.db.chmod(0o600);os.link(self.db,self.base/'linked')
        with self.assertRaises(PermissionError):self.prepare()

    def test_symlink_or_overlapping_storage_auth_and_workspace_refused(self):
        link=self.base/'alias';link.symlink_to(self.root,target_is_directory=True)
        for root in (link,self.auth,self.workspace,self.root/'..'/'state'):
            self.store.review=replace(self.review,root=root)
            with self.subTest(root=root),self.assertRaises(PermissionError):self.prepare()

    def test_storage_permissions_native_fs_and_missing_pin_refused(self):
        self.root.chmod(0o755)
        with self.assertRaises(PermissionError):self.prepare()
        self.root.chmod(0o700)
        with patch.object(subject,'_native_linux_state',return_value=False),self.assertRaises(PermissionError):self.prepare()
        self.store.review=replace(self.review,migration_sha256='f'*64)
        with self.assertRaises(PermissionError):self.prepare()

    def test_db_replacement_during_independent_inspection_refused(self):
        inspect=self.store.inspect;calls=0
        def drift():
            nonlocal calls
            result=inspect();calls+=1
            if calls==1:
                other=self.root/'new';other.write_bytes(self.db.read_bytes());other.chmod(0o600);other.replace(self.db)
            return result
        with patch.object(self.store,'inspect',side_effect=drift),self.assertRaises(PermissionError):self.prepare()

    def test_schema_fingerprint_is_review_material_not_self_approved_compatibility(self):
        first=self.prepare()
        with sqlite3.connect(self.db) as c:c.execute('CREATE TABLE extra(value TEXT)')
        second=self.prepare()
        self.assertNotEqual(first['schema'],second['schema'])
        self.assertEqual(second['schema_compatibility'],'EXPECTED_MIGRATION_PIN_MATCH_ONLY')
        self.assertEqual(second['independent_seal_approval'],'REQUIRED')
