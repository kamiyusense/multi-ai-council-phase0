"""Read-only native binary qualification and create-only placement review packet.

Never download, copy, chmod, install, authenticate or execute Codex. Digest and
release reference are independent operator INPUTS, not authenticated provenance.
A packet is not an installation seal, model admission or publication authority.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import struct

from .scripts.symphony_worker_first_preflight import _native_linux_state, _safe_dir, _separate
from .symphony_result_manifest import digest

SHA256 = re.compile(r'[0-9a-f]{64}')
RELEASE = re.compile(r'https://github\.com/openai/codex/releases/download/[A-Za-z0-9_.+-]+/[A-Za-z0-9_.+-]+')
SYSTEM_UID = 0  # Production system-owned ancestry; sandbox fixtures patch this observation.
MAX_BINARY = 512 * 1024 * 1024


def canonical_path(value):
    text = str(value)
    path = Path(text)
    if (not path.is_absolute() or str(path) != text
            or '..' in path.parts or path.resolve() != path
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise PermissionError('canonical unlinked absolute path required')
    return path


def identity(info):
    return [info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)]


@contextmanager
def directory_chain(path, *, private=False):
    """Anchor every component with openat/O_NOFOLLOW, then re-read the chain.

    Assumes operator-owned ancestors and exclusion of concurrent same-uid writers.
    Root-owned sticky scratch ancestry is allowed for isolated Cloud fixtures.
    """
    path = canonical_path(path)
    chain = []
    with ExitStack() as stack:
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for index, component in enumerate(('/', *path.parts[1:])):
            if index:
                fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                stack.callback(os.close, fd)
            info = os.fstat(fd)
            mode = stat.S_IMODE(info.st_mode)
            if (info.st_uid not in (SYSTEM_UID, os.getuid()) or mode & 0o022
                    and not (info.st_uid == SYSTEM_UID and info.st_mode & stat.S_ISVTX)):
                raise PermissionError('directory ancestry is not operator controlled')
            chain.append(identity(info))
        if private and (info.st_uid != os.getuid() or mode != 0o700):
            raise PermissionError('private owned parent required')
        yield fd, chain
        current = canonical_path(path)
        observed = [identity(p.stat()) for p in reversed((current, *current.parents))]
        if observed != chain:
            raise PermissionError('directory ancestry drifted; readback only')


def _regular_read(parent_fd, name, *, expected_sha256):
    if not SHA256.fullmatch(expected_sha256 or ''):
        raise PermissionError('exact independent digest required')
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    def signature(info):
        return [*identity(info), info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    def safe(info):
        return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o7022
                and info.st_mode & stat.S_IXUSR and 1 <= info.st_size <= MAX_BINARY)
    if not safe(before):
        raise PermissionError('owned single-link executable required')
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        if signature(os.fstat(fd)) != signature(before):
            raise PermissionError('binary changed before open')
        hasher = hashlib.sha256(); header = b''; count = 0
        while block := os.read(fd, 1024 * 1024):
            count += len(block)
            if count > MAX_BINARY:
                raise PermissionError('binary grew beyond limit')
            header = (header + block[:64])[:64]
            hasher.update(block)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (not safe(after) or signature(after) != signature(before)
                or signature(named) != signature(before) or count != before.st_size
                or hasher.hexdigest() != expected_sha256):
            raise PermissionError('binary digest or filesystem identity drifted')
        return {'sha256': hasher.hexdigest(), 'file_identity': signature(after), 'bytes': count}, header
    finally:
        os.close(fd)


def qualify_native_binary(path, expected_sha256):
    """Finite readback; ELF header compatibility is not publisher authentication."""
    path = canonical_path(path)
    if path.name != 'codex' or not _native_linux_state(path.parent):
        raise PermissionError('native Linux Codex storage required')
    with directory_chain(path.parent) as (fd, chain):
        record, header = _regular_read(fd, path.name, expected_sha256=expected_sha256)
        # ELF64 little-endian, current version, executable/shared object, Linux
        # x86_64 or aarch64. Full loader/version qualification remains Local work.
        if (len(header) < 64 or header[:7] != b'\x7fELF\x02\x01\x01' or header[7] not in (0, 3)
                or struct.unpack_from('<H', header, 16)[0] not in (2, 3)
                or struct.unpack_from('<H', header, 18)[0] not in (62, 183)
                or struct.unpack_from('<I', header, 20)[0] != 1):
            raise PermissionError('reviewed Linux ELF header required')
        record.update({'path': str(path), 'parent_identities': chain,
                       'elf_machine': struct.unpack_from('<H', header, 18)[0],
                       'native_storage': True, 'binary_executed': False})
    return record


@dataclass(frozen=True)
class BinaryPlacementReview:
    source: str
    destination: str
    expected_sha256: str
    source_reference: str
    protected_roots: tuple[str, ...]


def prepare_binary_placement(review):
    """No installer. Requires existing private destination parent, absent leaf."""
    if (type(review) is not BinaryPlacementReview
            or not RELEASE.fullmatch(review.source_reference or '') or not review.protected_roots):
        raise PermissionError('independent placement inputs required')
    source = canonical_path(review.source)
    destination = canonical_path(review.destination)
    boundaries = tuple(_safe_dir(p) for p in review.protected_roots)
    if (destination.name != 'codex' or source == destination
            or any(not _separate(p, boundary) for p in (source, destination, destination.parent)
                   for boundary in boundaries) or not _native_linux_state(destination.parent)):
        raise PermissionError('placement overlaps protected roots or nonnative storage')
    first = qualify_native_binary(source, review.expected_sha256)
    with directory_chain(destination.parent, private=True) as (fd, chain):
        try:
            os.stat(destination.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise PermissionError('existing destination must not be overwritten')
        if qualify_native_binary(source, review.expected_sha256) != first:
            raise PermissionError('source drifted during review')
        # Reject a concurrent installer, including an incomplete/duplicate leaf.
        try:
            os.stat(destination.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise PermissionError('destination changed; GET-only recovery')
        packet = {'protocol': 'SYMPHONY_BINARY_PLACEMENT_REVIEW_V1',
                  'mode': 'PREPARE_ONLY', 'review': asdict(review), 'source_readback': first,
                  'destination_parent_identities': chain, 'destination_absent': True,
                  'source_provenance': 'PINNED_INPUT_NOT_AUTHENTICATED',
                  'installation_approval': 'REQUIRED_INDEPENDENT_REVIEW',
                  'installation_started': False, 'model_dispatch': 0,
                  'credentials_changed': 0, 'production_installed': False}
    return {**packet, 'packet_sha256': digest(packet)}
