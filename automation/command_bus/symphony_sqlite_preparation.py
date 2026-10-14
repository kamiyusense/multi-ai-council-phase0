"""Read-only SQLite installation/migration review packet around the sealed seam.

No migrations, writes, repairs, seals, approval callbacks or Codex subprocesses.
Only independently selected new storage is read; never select an auth DB.
A live WAL requires existing crash-recovery procedure, not immutable inspection.
"""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat

from .symphony_native_binary_preparation import canonical_path, directory_chain, identity, qualify_native_binary
from .scripts.symphony_worker_first_preflight import _native_linux_state, _safe_dir, _separate
from .symphony_sqlite_storage import ReviewedSQLiteStorage, DB_NAME, SEAL, SEAL_LOCK
from .symphony_result_manifest import digest


def prepare_sqlite_review(storage):
    if type(storage) is not ReviewedSQLiteStorage:
        raise PermissionError('existing independently pinned storage required')
    review = storage.review
    root = canonical_path(review.root)
    boundaries = (review.auth_home, *review.workspace_roots)
    if (not review.workspace_roots or not _native_linux_state(root)
            or any(not _separate(root, _safe_dir(p)) for p in boundaries)):
        raise PermissionError('new native storage must be disjoint')
    binary = qualify_native_binary(review.executable, review.executable_sha256)
    with directory_chain(root, private=True) as (fd, chain):
        entries = sorted(os.listdir(fd))
        databases = [n for n in entries if DB_NAME.fullmatch(n)]
        if not databases or any(n not in (SEAL, SEAL_LOCK) and not DB_NAME.fullmatch(n) for n in entries):
            raise PermissionError('unexpected files or WAL; use reviewed recovery, no repair')
        before = {}
        for name in entries:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise PermissionError('private single-link regular storage entry required')
            before[name] = [*identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        # Reuse original migration inventory, expected digest and quick_check.
        first = storage.inspect()
        schema = []
        for name in databases:
            # Quiescent new storage only: immutable=1 prevents even SHM creation.
            with closing(sqlite3.connect((root/name).as_uri()+'?mode=ro&immutable=1',
                                         uri=True, timeout=1)) as connection:
                connection.execute('PRAGMA query_only=ON')
                if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise PermissionError('full integrity unavailable')
                schema.append({'database': name,
                    'user_version': connection.execute('PRAGMA user_version').fetchone()[0],
                    'schema_sha256': digest(connection.execute(
                        "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").fetchall())})
        current = {}
        for name in sorted(os.listdir(fd)):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            current[name] = [*identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        if (before != current or storage.inspect() != first
                or qualify_native_binary(review.executable, review.executable_sha256) != binary):
            raise PermissionError('storage or binary drifted; readback only')
        # An existing seal is validated, never minted or replaced by this packet.
        sealed = SEAL in entries
        if sealed:
            storage.readiness()
        packet = {'protocol': 'SYMPHONY_SQLITE_MIGRATION_REVIEW_V1', 'mode': 'PREPARE_ONLY',
            'binding': review.binding(), 'storage_readback': first, 'binary_readback': binary,
            'directory_identities': chain, 'file_identities': before, 'schema': schema,
            'existing_seal_verified': sealed, 'independent_seal_approval': 'REQUIRED',
            'quick_check': 'ok', 'integrity_check': 'ok',
            'schema_compatibility': 'EXPECTED_MIGRATION_PIN_MATCH_ONLY',
            'migration_executed': False, 'seal_created': False, 'model_dispatch': 0,
            'production_installed': False, 'auth_database_accessed': False}
    return {**packet, 'packet_sha256': digest(packet)}
