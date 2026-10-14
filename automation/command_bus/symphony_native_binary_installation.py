"""Create-only native placement primitive; no CLI, downloader or activation.

Only a trusted installer with a separately reviewed approval callback may call
this. Development tests copy synthetic ELF bytes only and never execute them.
Any failed/partial target is preserved for readback; no resume, unlink or retry.
"""
from contextlib import ExitStack
import hashlib
import os

from .symphony_native_binary_preparation import (
    canonical_path, directory_chain, identity, prepare_binary_placement,
    qualify_native_binary, MAX_BINARY,
)


def place_reviewed_binary(review, *, packet_sha256, approval_check=None):
    """Place exact approved bytes in an absent leaf; never start a process."""
    packet = prepare_binary_placement(review)
    if packet["packet_sha256"] != packet_sha256 or not callable(approval_check):
        raise PermissionError("separate exact installation approval required")
    try:
        approved = approval_check(packet_sha256)
    except Exception:
        raise PermissionError("installation approval unavailable") from None
    if approved is not True or prepare_binary_placement(review) != packet:
        raise PermissionError("approval absent or placement drifted")
    source = canonical_path(review.source)
    destination = canonical_path(review.destination)
    expected = packet["source_readback"]["file_identity"]

    def signature(info):
        return [*identity(info), info.st_nlink, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns]

    # Existing parent qualification is repeated and descriptors pin both roots.
    # Same-UID concurrent writers must be excluded by the operator OS boundary.
    with directory_chain(source.parent) as (src_parent, src_chain), \
         directory_chain(destination.parent, private=True) as (dst_parent, dst_chain), \
         ExitStack() as stack:
        if (src_chain != packet["source_readback"]["parent_identities"]
                or dst_chain != packet["destination_parent_identities"]):
            raise PermissionError("parent identity changed")
        src = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                      dir_fd=src_parent)
        stack.callback(os.close, src)
        if signature(os.fstat(src)) != expected:
            raise PermissionError("source identity changed before placement")
        dst = os.open(destination.name,
                      os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      0o700, dir_fd=dst_parent)
        stack.callback(os.close, dst)
        created = identity(os.fstat(dst))
        # Persist the empty exclusive leaf before copying. A later crash leaves
        # a durable quarantine target rather than an automatically resumable slot.
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
                or signature(os.fstat(src)) != expected
                or signature(os.stat(source.name, dir_fd=src_parent,
                                     follow_symlinks=False)) != expected):
            raise PermissionError("source drifted; preserve target")
        if qualify_native_binary(source, review.expected_sha256) != packet["source_readback"]:
            raise PermissionError("source readback changed; preserve target")
        actual = qualify_native_binary(destination, review.expected_sha256)
        if actual["file_identity"][:4] != created:
            raise PermissionError("target replaced; readback only")
    return {"protocol": "SYMPHONY_BINARY_PLACEMENT_RECEIPT_V1",
            "status": "PLACED_NOT_ACTIVATED", "approved_packet_sha256": packet_sha256,
            "actual_readback": actual, "binary_executed": False,
            "model_dispatch": 0, "credentials_changed": 0,
            "activation_authorized": False}
