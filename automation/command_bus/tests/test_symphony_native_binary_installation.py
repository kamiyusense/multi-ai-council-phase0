"""Create-only placement of synthetic ELF, never an actual Codex executable."""
import os
from unittest import TestCase
from unittest.mock import Mock, patch

from . import test_symphony_native_binary_preparation as fixture
from .. import symphony_native_binary_installation as subject


class NativeInstallationTests(TestCase):
    def setUp(self):
        fixture.BinaryPreparationTests.setUp(self)

    def packet(self):
        return subject.prepare_binary_placement(self.review)

    def place(self, approval=None, pin=None):
        return subject.place_reviewed_binary(self.review,
            packet_sha256=pin or self.packet()["packet_sha256"],
            approval_check=approval)

    def test_missing_false_or_exception_approval_never_creates_target(self):
        for approval in (None, Mock(return_value=False), Mock(side_effect=RuntimeError("PRIVATE"))):
            with self.subTest(approval=approval), self.assertRaises(PermissionError):
                self.place(approval)
            self.assertFalse((self.destination/"codex").exists())

    def test_wrong_packet_does_not_call_approval(self):
        approval=Mock(return_value=True)
        with self.assertRaises(PermissionError): self.place(approval,pin="f"*64)
        approval.assert_not_called()
        self.assertFalse((self.destination/"codex").exists())

    def test_place_readback_no_execution_no_auth_copy_no_duplicate_overwrite(self):
        before=(self.auth/"auth.json").read_bytes()
        approval=Mock(return_value=True)
        with patch("subprocess.Popen") as launch:
            result=self.place(approval)
        launch.assert_not_called()
        approval.assert_called_once()
        p=self.destination/"codex"
        self.assertEqual(p.read_bytes(),self.binary.read_bytes())
        self.assertEqual(result["actual_readback"]["sha256"],self.review.expected_sha256)
        self.assertFalse(result["activation_authorized"])
        self.assertEqual((self.auth/"auth.json").read_bytes(),before)
        inode=p.stat().st_ino
        with self.assertRaises(PermissionError): self.place(approval)
        self.assertEqual(p.stat().st_ino,inode)

    def test_approval_time_source_replacement_stops_before_target_creation(self):
        packet=self.packet()
        def replace_source(_):
            other=self.source/"replacement"
            other.write_bytes(self.binary.read_bytes());other.chmod(0o700)
            other.replace(self.binary)
            return True
        with self.assertRaises(PermissionError):
            self.place(replace_source,pin=packet["packet_sha256"])
        self.assertFalse((self.destination/"codex").exists())

    def test_partial_write_preserved_never_resumed(self):
        write=os.write
        calls=0
        def interrupted(fd, block):
            nonlocal calls
            calls+=1
            if calls==1: return write(fd,block[:7])
            raise OSError("fixture interrupted")
        with patch.object(subject.os,"write",side_effect=interrupted),self.assertRaises(OSError):
            self.place(lambda _:True)
        p=self.destination/"codex"; self.assertEqual(p.read_bytes(),self.binary.read_bytes()[:7])
        with self.assertRaises(PermissionError): self.place(lambda _:True)
        self.assertEqual(p.read_bytes(),self.binary.read_bytes()[:7])

    def test_short_writes_are_completed_without_reopening_target(self):
        write=os.write
        with patch.object(subject.os,"write",side_effect=lambda fd,b:write(fd,b[:3])):
            result=self.place(lambda _:True)
        self.assertEqual(result["status"],"PLACED_NOT_ACTIVATED")
        self.assertEqual((self.destination/"codex").read_bytes(),self.binary.read_bytes())

    def test_destination_appearing_during_approval_is_preserved(self):
        pin=self.packet()["packet_sha256"]
        def collision(_):
            (self.destination/"codex").write_bytes(b"OTHER_INSTALLER")
            return True
        with self.assertRaises(PermissionError): self.place(collision,pin=pin)
        self.assertEqual((self.destination/"codex").read_bytes(),b"OTHER_INSTALLER")
