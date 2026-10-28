"""Create-only placement of synthetic ELF, never an actual Codex executable."""
import os
import stat
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

from . import test_symphony_native_binary_preparation as fixture
from .. import symphony_native_binary_installation as subject


class NativeInstallationTests(TestCase):
    def setUp(self):
        fixture.BinaryPreparationTests.setUp(self)

    def packet(self):
        return subject.prepare_binary_placement(self.review)

    def signed_fixture(self, fd, request):
        # Trust seam fixture only: no real signature/certificate is verified.
        self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)
        with self.assertRaises(OSError):
            os.write(fd, b"must be read-only")
        return {**request, "signature_verified": True, "certificate_verified": True,
                "transparency_log_verified": True}

    def place(self, approval=None, pin=None, verifier="fixture"):
        return subject.place_reviewed_binary(self.review,
            packet_sha256=pin or self.packet()["packet_sha256"],
            approval_check=approval,
            signature_check=self.signed_fixture if verifier == "fixture" else verifier)

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

    def assert_quarantined(self, expected=None):
        p = self.destination/"codex"
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        if expected is not None:
            self.assertEqual(p.read_bytes(), expected)
        inode = p.stat().st_ino
        verifier = Mock(side_effect=AssertionError("retry must not verify again"))
        with self.assertRaises(PermissionError):
            self.place(lambda _: True, verifier=verifier)
        verifier.assert_not_called()
        self.assertEqual(p.stat().st_ino, inode)

    def test_hash_and_approval_without_signature_verifier_cannot_create(self):
        approval = Mock(return_value=True)
        with self.assertRaises(PermissionError):
            self.place(approval, verifier=None)
        approval.assert_not_called()
        self.assertFalse((self.destination/"codex").exists())

    def test_copy_and_verification_remain_nonexecutable_until_all_checks(self):
        write = os.write
        chmod = os.fchmod
        checked = False
        def inspect_write(fd, block):
            self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)
            return write(fd, block)
        def verify(fd, request):
            nonlocal checked
            self.assertEqual((self.destination/"codex").read_bytes(), self.binary.read_bytes())
            self.assertEqual(request["digest_scope"], "EXTRACTED_BINARY_NOT_ARCHIVE")
            self.assertEqual(request["binary_sha256"], self.review.expected_sha256)
            checked = True
            return self.signed_fixture(fd, request)
        def grant(fd, mode):
            self.assertTrue(checked)
            self.assertEqual(mode, 0o700)
            self.assertEqual(os.fstat(fd).st_ino, (self.destination/"codex").stat().st_ino)
            return chmod(fd, mode)
        with patch.object(subject.os, "write", side_effect=inspect_write), \
             patch.object(subject.os, "fchmod", side_effect=grant):
            self.place(lambda _: True, verifier=verify)
        self.assertEqual(stat.S_IMODE((self.destination/"codex").stat().st_mode), 0o700)

    def test_signature_false_is_not_digest_success(self):
        with self.assertRaises(PermissionError):
            self.place(lambda _: True, verifier=lambda *_: False)
        self.assert_quarantined(self.binary.read_bytes())

    def test_signature_boolean_true_is_not_a_verification_receipt(self):
        with self.assertRaises(PermissionError):
            self.place(lambda _: True, verifier=lambda *_: True)
        self.assert_quarantined(self.binary.read_bytes())

    def test_signature_exception_is_sanitized_and_preserves_nonexecutable(self):
        with self.assertRaisesRegex(PermissionError, "verification unavailable") as error:
            self.place(lambda _: True, verifier=Mock(side_effect=RuntimeError("PRIVATE")))
        self.assertNotIn("PRIVATE", str(error.exception))
        self.assert_quarantined(self.binary.read_bytes())

    def test_wrong_signature_identity_issuer_certificate_log_or_inode_refused(self):
        bad = ({"certificate_identity": "https://github.com/other/workflow"},
               {"oidc_issuer": "https://other.invalid"},
               {"signature_verified": False}, {"certificate_verified": False},
               {"transparency_log_verified": False}, {"signature_verified": 1},
               {"binary_sha256": "e"*64}, {"file_identity": [0]*8},
               {"digest_scope": "ARCHIVE"})
        # Each subcase has its own existing fixture; never remove a failed leaf.
        for changes in bad:
            with self.subTest(changes=changes):
                case = type(self)("runTest")
                case.setUp()
                try:
                    def verify(fd, request):
                        return {**case.signed_fixture(fd, request), **changes}
                    with case.assertRaises(PermissionError):
                        case.place(lambda _: True, verifier=verify)
                    case.assert_quarantined()
                finally:
                    case.doCleanups()

    def test_interrupt_during_copy_preserves_nonexecutable_partial(self):
        write = os.write
        def interrupt(fd, block):
            write(fd, block[:7])
            raise KeyboardInterrupt()
        with patch.object(subject.os, "write", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
            self.place(lambda _: True)
        self.assert_quarantined(self.binary.read_bytes()[:7])

    def test_zero_write_preserves_nonexecutable_empty_leaf(self):
        with patch.object(subject.os, "write", return_value=0), self.assertRaises(OSError):
            self.place(lambda _: True)
        self.assert_quarantined(b"")

    def test_corrupt_destination_rejected_before_signature_or_chmod(self):
        write = os.write
        verifier = Mock(side_effect=AssertionError("must not verify corrupt copy"))
        def corrupt(fd, block):
            return write(fd, bytes([block[0] ^ 1]) + bytes(block[1:]))
        with patch.object(subject.os, "write", side_effect=corrupt), self.assertRaises(PermissionError):
            self.place(lambda _: True, verifier=verifier)
        verifier.assert_not_called()
        self.assert_quarantined()

    def test_replacement_during_signature_never_chmods_substituted_file(self):
        original_inode = None
        def verify(fd, request):
            nonlocal original_inode
            original_inode = os.fstat(fd).st_ino
            (self.destination/"codex").rename(self.destination/"quarantined-original")
            replacement = self.destination/"codex"
            replacement.write_bytes(b"OTHER_WRITER"); replacement.chmod(0o600)
            return self.signed_fixture(fd, request)
        with patch.object(subject.os, "fchmod", wraps=os.fchmod) as chmod, self.assertRaises(PermissionError):
            self.place(lambda _: True, verifier=verify)
        chmod.assert_not_called()
        original = self.destination/"quarantined-original"
        self.assertEqual(original.stat().st_ino, original_inode)
        self.assertEqual(stat.S_IMODE(original.stat().st_mode), 0o600)
        self.assert_quarantined(b"OTHER_WRITER")

    def test_inplace_mutation_after_signature_rejected(self):
        def verify(fd, request):
            proof = self.signed_fixture(fd, request)
            p = self.destination/"codex"
            p.write_bytes(b"X"*len(self.binary.read_bytes()))
            return proof
        with self.assertRaises(PermissionError):
            self.place(lambda _: True, verifier=verify)
        self.assert_quarantined()

    def test_hardlink_added_during_signature_rejected(self):
        def verify(fd, request):
            proof = self.signed_fixture(fd, request)
            os.link(self.destination/"codex", self.destination/"other-link")
            return proof
        with self.assertRaises(PermissionError):
            self.place(lambda _: True, verifier=verify)
        self.assert_quarantined(self.binary.read_bytes())
        self.assertEqual(stat.S_IMODE((self.destination/"other-link").stat().st_mode), 0o600)

    def test_permission_grant_failure_preserves_verified_nonexecutable(self):
        with patch.object(subject.os, "fchmod", side_effect=PermissionError("fixture denied")), \
             self.assertRaises(PermissionError):
            self.place(lambda _: True)
        self.assert_quarantined(self.binary.read_bytes())

    def test_error_after_permission_change_revokes_using_same_descriptor(self):
        chmod = os.fchmod
        def grant_then_error(fd, mode):
            chmod(fd, mode)
            if mode == 0o700:
                raise OSError("fixture post-grant failure")
        with patch.object(subject.os, "fchmod", side_effect=grant_then_error), self.assertRaises(OSError):
            self.place(lambda _: True)
        self.assert_quarantined(self.binary.read_bytes())

    def test_interrupt_after_permission_change_revokes(self):
        chmod = os.fchmod
        def grant_then_interrupt(fd, mode):
            chmod(fd, mode)
            if mode == 0o700:
                raise KeyboardInterrupt()
        with patch.object(subject.os, "fchmod", side_effect=grant_then_interrupt), self.assertRaises(KeyboardInterrupt):
            self.place(lambda _: True)
        self.assert_quarantined(self.binary.read_bytes())

    def test_failed_revocation_is_unknown_never_success_or_automatic_retry(self):
        chmod = os.fchmod
        def fail(fd, mode):
            if mode == 0o700:
                chmod(fd, mode)
                raise OSError("post-grant")
            raise OSError("revoke denied")
        with patch.object(subject.os, "fchmod", side_effect=fail), \
             self.assertRaisesRegex(PermissionError, "QUARANTINE_UNKNOWN"):
            self.place(lambda _: True)
        p = self.destination/"codex"
        self.assertEqual(p.read_bytes(), self.binary.read_bytes())
        # Only already fully verified bytes can be executable in this UNKNOWN.
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)
        with self.assertRaises(PermissionError):
            self.place(lambda _: True)

    def test_post_grant_readback_failure_revokes_created_inode_only(self):
        original = subject.qualify_native_binary
        def readback(path, sha):
            if path == self.destination/"codex":
                raise PermissionError("fixture readback failed")
            return original(path, sha)
        with patch.object(subject, "qualify_native_binary", side_effect=readback), self.assertRaises(PermissionError):
            self.place(lambda _: True)
        self.assert_quarantined(self.binary.read_bytes())

    def test_concurrent_installer_is_rejected_without_resuming_leaf(self):
        nested = []
        def verify(fd, request):
            def concurrent():
                try:
                    self.place(lambda _: True)
                except PermissionError:
                    nested.append("REFUSED")
            t = threading.Thread(target=concurrent)
            t.start(); t.join(timeout=5)
            self.assertFalse(t.is_alive())
            return self.signed_fixture(fd, request)
        result = self.place(lambda _: True, verifier=verify)
        self.assertEqual(nested, ["REFUSED"])
        self.assertEqual(result["status"], "PLACED_NOT_ACTIVATED")

    def test_replaced_fifo_before_verifier_open_is_refused_without_blocking(self):
        original = subject._read_nonexecutable
        def replace_after_read(*args):
            result = original(*args)
            (self.destination/"codex").rename(self.destination/"original")
            os.mkfifo(self.destination/"codex", mode=0o600)
            return result
        with patch.object(subject, "_read_nonexecutable", side_effect=replace_after_read), \
             self.assertRaises(PermissionError):
            self.place(lambda _: True)
        self.assertTrue(stat.S_ISFIFO((self.destination/"codex").stat().st_mode))
        self.assertEqual(stat.S_IMODE((self.destination/"original").stat().st_mode), 0o600)
        self.assertEqual((self.destination/"original").read_bytes(), self.binary.read_bytes())

    def test_permission_grant_uses_verified_inode_even_if_name_is_replaced(self):
        chmod = os.fchmod
        original_inode = None
        def replace_at_grant(fd, mode):
            nonlocal original_inode
            if mode == 0o700:
                original_inode = os.fstat(fd).st_ino
                (self.destination/"codex").rename(self.destination/"original")
                p = self.destination/"codex";p.write_bytes(b"OTHER_WRITER");p.chmod(0o600)
            return chmod(fd, mode)
        with patch.object(subject.os, "fchmod", side_effect=replace_at_grant), self.assertRaises(PermissionError):
            self.place(lambda _: True)
        self.assertEqual((self.destination/"original").stat().st_ino, original_inode)
        self.assertEqual(stat.S_IMODE((self.destination/"original").stat().st_mode), 0o600)
        self.assert_quarantined(b"OTHER_WRITER")
