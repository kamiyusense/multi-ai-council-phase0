"""Create-only native placement; no downloader, verifier factory or activation.

The final name is reserved with mode0600. Only complete, independently signed
bytes can receive execute permission. Partial/failed leaves are never resumed,
overwritten or deleted. Independent callbacks are trusted operator inputs, never
worker/model data. Same-UID malicious writers must be excluded by the OS boundary;
0700 and inode checks alone do not provide that boundary.
"""
from contextlib import ExitStack
import hashlib
import os
import stat
from urllib.parse import urlsplit

from .symphony_native_binary_preparation import (
    canonical_path, directory_chain, identity, prepare_binary_placement,
    qualify_native_binary, MAX_BINARY,
)
from .symphony_result_manifest import digest


def _signature(info):
    return [*identity(info), info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]


def _read_nonexecutable(fd, parent_fd, name, created, expected_sha256, expected_size):
    """Verify the copied descriptor and its name before any execute permission."""
    before = os.fstat(fd)
    if (identity(before) != created or stat.S_IMODE(before.st_mode) != 0o600
            or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_size != expected_size
            or _signature(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
                != _signature(before)):
        raise PermissionError("nonexecutable destination identity changed")
    os.lseek(fd, 0, os.SEEK_SET)
    hasher = hashlib.sha256()
    count = 0
    while block := os.read(fd, 1024 * 1024):
        count += len(block)
        if count > MAX_BINARY or count > expected_size:
            raise PermissionError("copied binary size changed")
        hasher.update(block)
    if (count != expected_size or hasher.hexdigest() != expected_sha256
            or _signature(os.fstat(fd)) != _signature(before)
            or _signature(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
                != _signature(before)):
        raise PermissionError("copied binary digest or identity changed")
    return _signature(before)


def place_reviewed_binary(review, *, packet_sha256, approval_check=None,
                          signature_check=None):
    """Reserve0600 -> copy/readback -> independent Sigstore check -> chmod0700.

    signature_check(readonly_fd, request) must independently verify the blob's
    Sigstore signature, certificate chain/time, issuer, exact workflow identity
    and transparency log against reviewed trust roots. It returns exactly request
    plus the three True verification fields below. Hash agreement, bundle parsing
    and approval_check are NOT signature verification. No default verifier exists.
    The callback may read but must not close/mutate its descriptor or environment.
    The operator must exclude same-UID writers/executors for the entire operation.
    """
    packet = prepare_binary_placement(review)
    if (packet["packet_sha256"] != packet_sha256 or not callable(approval_check)
            or not callable(signature_check)):
        raise PermissionError("separate installation approval and Sigstore verifier required")
    try:
        approved = approval_check(packet_sha256)
    except Exception:
        raise PermissionError("installation approval unavailable") from None
    if approved is not True or prepare_binary_placement(review) != packet:
        raise PermissionError("approval absent or placement drifted")
    source = canonical_path(review.source)
    destination = canonical_path(review.destination)
    expected = packet["source_readback"]["file_identity"]
    tag = urlsplit(review.source_reference).path.split("/")[-2]
    dst = None

    # Keep file descriptors open until directory-chain exits and final readback
    # succeed, so a caught post-chmod error can revoke only OUR created inode.
    with ExitStack() as stack:
        try:
            with directory_chain(source.parent) as (src_parent, src_chain), \
                 directory_chain(destination.parent, private=True) as (dst_parent, dst_chain):
                if (src_chain != packet["source_readback"]["parent_identities"]
                        or dst_chain != packet["destination_parent_identities"]):
                    raise PermissionError("parent identity changed")
                src = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                              dir_fd=src_parent)
                stack.callback(os.close, src)
                if _signature(os.fstat(src)) != expected:
                    raise PermissionError("source identity changed before placement")
                dst = os.open(destination.name,
                              os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=dst_parent)
                stack.callback(os.close, dst)
                created = identity(os.fstat(dst))
                os.fsync(dst)
                os.fsync(dst_parent)
                hasher = hashlib.sha256()
                count = 0
                while block := os.read(src, 1024 * 1024):
                    count += len(block)
                    if count > MAX_BINARY or count > expected[5]:
                        raise PermissionError("source size changed; preserve target")
                    hasher.update(block)
                    pending = memoryview(block)
                    while pending:
                        written = os.write(dst, pending)
                        if written <= 0:
                            raise OSError("partial placement; preserve target")
                        pending = pending[written:]
                os.fsync(dst)
                os.fsync(dst_parent)
                if (count != expected[5] or hasher.hexdigest() != review.expected_sha256
                        or _signature(os.fstat(src)) != expected
                        or _signature(os.stat(source.name, dir_fd=src_parent,
                                             follow_symlinks=False)) != expected):
                    raise PermissionError("source drifted; preserve target")
                copied = _read_nonexecutable(dst, dst_parent, destination.name, created,
                                            review.expected_sha256, expected[5])
                verifier_fd = os.open(destination.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                      dir_fd=dst_parent)
                stack.callback(os.close, verifier_fd)
                if _signature(os.fstat(verifier_fd)) != copied:
                    raise PermissionError("signature input identity changed")
                request = {
                    "protocol": "SYMPHONY_SIGSTORE_BINARY_VERIFICATION_V1",
                    "digest_scope": "EXTRACTED_BINARY_NOT_ARCHIVE",
                    "binary_sha256": review.expected_sha256,
                    "file_identity": copied,
                    "source_reference": review.source_reference,
                    "placement_packet_sha256": packet_sha256,
                    "certificate_identity":
                        "https://github.com/openai/codex/.github/workflows/rust-release.yml@refs/tags/" + tag,
                    "oidc_issuer": "https://token.actions.githubusercontent.com",
                }
                required = {**request, "file_identity": list(copied),
                            "signature_verified": True, "certificate_verified": True,
                            "transparency_log_verified": True}
                try:
                    proof = signature_check(verifier_fd, {**request, "file_identity": list(copied)})
                except Exception:
                    raise PermissionError("independent Sigstore verification unavailable") from None
                if (type(proof) is not dict or proof != required
                        or any(proof.get(k) is not True for k in
                               ("signature_verified", "certificate_verified", "transparency_log_verified"))):
                    raise PermissionError("independent Sigstore verification missing or mismatched")
                if (_signature(os.fstat(verifier_fd)) != copied
                        or _read_nonexecutable(dst, dst_parent, destination.name, created,
                                              review.expected_sha256, expected[5]) != copied
                        or qualify_native_binary(source, review.expected_sha256)
                            != packet["source_readback"]):
                    raise PermissionError("verified bytes changed before permission grant")
            # The verified inode is the one chmod'd; no path-following chmod.
            os.fchmod(dst, 0o700)
            os.fsync(dst)
            actual = qualify_native_binary(destination, review.expected_sha256)
            if (actual["file_identity"][:3] != created[:3]
                    or actual["file_identity"][3:] != _signature(os.fstat(dst))[3:]
                    or actual["parent_identities"] != packet["destination_parent_identities"]):
                raise PermissionError("target replaced; readback only")
        except BaseException:
            # No unlink/retry. Caught interrupts and post-chmod failures preserve
            # this descriptor's inode as0600. Never chmod a substituted path.
            if dst is not None and stat.S_IMODE(os.fstat(dst).st_mode) != 0o600:
                try:
                    os.fchmod(dst, 0o600)
                    os.fsync(dst)
                except BaseException:
                    raise PermissionError("QUARANTINE_UNKNOWN; preserve inode and stop all execution") from None
            raise
    return {"protocol": "SYMPHONY_BINARY_PLACEMENT_RECEIPT_V1",
            "status": "PLACED_NOT_ACTIVATED", "approved_packet_sha256": packet_sha256,
            "actual_readback": actual, "binary_executed": False,
            "signature_receipt_sha256": digest(proof),
            "model_dispatch": 0, "credentials_changed": 0,
            "activation_authorized": False}
