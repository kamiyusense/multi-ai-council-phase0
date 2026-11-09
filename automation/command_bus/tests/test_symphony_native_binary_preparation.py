"""Isolated synthetic ELF files only. Never execute or download Codex."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from .. import symphony_native_binary_preparation as subject
from ..symphony_result_manifest import digest


def elf_fixture(machine=62):
    raw = bytearray(64)
    raw[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', raw, 16, 2, machine, 1)
    return bytes(raw) + b'SYNTHETIC_NOT_EXECUTABLE_CODE'


class BinaryPreparationTests(unittest.TestCase):
    def setUp(self):
        ancestry = patch('automation.command_bus.symphony_native_binary_preparation.SYSTEM_UID', Path('/').stat().st_uid)
        ancestry.start(); self.addCleanup(ancestry.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'source'; self.source.mkdir(mode=0o700)
        self.binary = self.source/'codex'; self.binary.write_bytes(elf_fixture()); self.binary.chmod(0o700)
        self.destination = self.root/'destination'; self.destination.mkdir(mode=0o700)
        self.auth = self.root/'auth'; self.auth.mkdir(mode=0o700)
        (self.auth/'auth.json').write_bytes(b'SYNTHETIC_AUTH_DO_NOT_READ_OR_COPY')
        self.review = subject.BinaryPlacementReview(str(self.binary),str(self.destination/'codex'),
            hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            'https://github.com/openai/codex/releases/download/review-fixture/codex-linux.tar.gz',
            (str(self.auth),))
        self.fs = patch.object(subject,'_native_linux_state',return_value=True)
        self.native = self.fs.start(); self.addCleanup(self.fs.stop)

    def prepare(self, review=None):
        return subject.prepare_binary_placement(review or self.review)

    def test_repeatable_packet_does_not_install_execute_or_change_auth(self):
        before = self.binary.read_bytes(), (self.auth/'auth.json').read_bytes()
        with patch('subprocess.Popen') as launch:
            first = self.prepare(); self.assertEqual(first,self.prepare())
        launch.assert_not_called()
        self.assertFalse((self.destination/'codex').exists())
        self.assertFalse(first['installation_started'])
        self.assertEqual(first['source_provenance'],'PINNED_INPUT_NOT_AUTHENTICATED')
        raw = dict(first); checksum = raw.pop('packet_sha256'); self.assertEqual(checksum,digest(raw))
        self.assertEqual(before,(self.binary.read_bytes(),(self.auth/'auth.json').read_bytes()))

    def test_wrong_digest_release_reference_or_missing_boundaries_refused(self):
        for changes in ({'expected_sha256':'b'*64},{'expected_sha256':''},
                        {'source_reference':'https://github.com.evil/openai/codex'},
                        {'source_reference':'https://github.com/openai/codex/releases/download/v/a?token=x'},
                        {'protected_roots':()}):
            with self.subTest(changes=changes),self.assertRaises(PermissionError):
                self.prepare(replace(self.review,**changes))

    def test_existing_partial_or_duplicate_destination_preserved(self):
        p = self.destination/'codex'; p.write_bytes(b'PARTIAL_DO_NOT_OVERWRITE')
        with self.assertRaises(PermissionError):self.prepare()
        self.assertEqual(p.read_bytes(),b'PARTIAL_DO_NOT_OVERWRITE')

    def test_destination_dangling_symlink_and_source_symlink_refused(self):
        dest=self.destination/'codex';dest.symlink_to(self.root/'missing')
        with self.assertRaises(PermissionError):self.prepare()
        dest.unlink()
        alias=self.root/'alias';alias.symlink_to(self.source,target_is_directory=True)
        with self.assertRaises(PermissionError):self.prepare(replace(self.review,source=str(alias/'codex')))

    def test_hardlink_shared_writable_setid_and_nonexecutable_refused(self):
        for mode in (0o777,0o600,0o4700,0o2700):
            self.binary.chmod(mode)
            with self.subTest(mode=mode),self.assertRaises(PermissionError):self.prepare()
        self.binary.chmod(0o700);os.link(self.binary,self.root/'linked')
        with self.assertRaises(PermissionError):self.prepare()

    def test_windows_mount_overlay_unknown_and_nonprivate_destination_refused(self):
        for location in (self.source,self.destination):
            self.native.side_effect=lambda p: p != location
            with self.subTest(location=location),self.assertRaises(PermissionError):self.prepare()
        self.native.side_effect=None;self.destination.chmod(0o755)
        with self.assertRaises(PermissionError):self.prepare()

    def test_source_or_destination_in_auth_and_path_traversal_refused(self):
        for changes in ({'source':str(self.source/'..'/'source'/'codex')},
                        {'destination':str(self.auth/'codex')},
                        {'protected_roots':(str(self.source),)},
                        {'destination':'relative/codex'}):
            with self.subTest(changes=changes),self.assertRaises(PermissionError):self.prepare(replace(self.review,**changes))

    def test_header_mismatch_and_incompatible_elf_refused(self):
        for raw in (b'WINDOWS_PE',elf_fixture(3),elf_fixture().replace(b'\x7fELF',b'NOPE')):
            self.binary.write_bytes(raw)
            with self.subTest(raw=raw[:8]),self.assertRaises(PermissionError):
                self.prepare(replace(self.review,expected_sha256=hashlib.sha256(raw).hexdigest()))

    def test_identical_bytes_replaced_inode_during_preparation_refused(self):
        original=subject.qualify_native_binary;calls=0
        def replace_inode(*args):
            nonlocal calls
            result=original(*args);calls+=1
            if calls==1:
                other=self.source/'new';other.write_bytes(self.binary.read_bytes());other.chmod(0o700)
                other.replace(self.binary)
            return result
        with patch.object(subject,'qualify_native_binary',side_effect=replace_inode),self.assertRaises(PermissionError):self.prepare()

    def test_named_binary_replaced_during_descriptor_read_refused(self):
        read=os.read;changed=False
        def drift(fd,n):
            nonlocal changed
            block=read(fd,n)
            if block and not changed:
                changed=True;other=self.source/'new';other.write_bytes(self.binary.read_bytes());other.chmod(0o700)
                other.replace(self.binary)
            return block
        with patch.object(subject.os,'read',side_effect=drift),self.assertRaises(PermissionError):self.prepare()

    def test_parent_replacement_during_read_refused(self):
        read=os.read;changed=False
        def drift(fd,n):
            nonlocal changed
            block=read(fd,n)
            if block and not changed:
                changed=True;self.source.rename(self.root/'old-source');self.source.mkdir(mode=0o700)
                replacement=self.source/'codex';replacement.write_bytes(elf_fixture());replacement.chmod(0o700)
            return block
        with patch.object(subject.os,'read',side_effect=drift),self.assertRaises(PermissionError):self.prepare()

    def test_wrong_owner_and_group_writable_ancestor_refused(self):
        self.source.chmod(0o770)
        with self.assertRaises(PermissionError):self.prepare()
        self.source.chmod(0o700)
        with patch.object(subject.os,'getuid',return_value=os.getuid()+1),self.assertRaises(PermissionError):self.prepare()

    def test_concurrent_destination_creation_is_hold_not_overwrite(self):
        original=subject.qualify_native_binary;calls=0
        def drift(*args):
            nonlocal calls
            result=original(*args);calls+=1
            if calls==2:(self.destination/'codex').write_bytes(b'OTHER_INSTALLER')
            return result
        with patch.object(subject,'qualify_native_binary',side_effect=drift),self.assertRaises(PermissionError):self.prepare()
        self.assertEqual((self.destination/'codex').read_bytes(),b'OTHER_INSTALLER')
