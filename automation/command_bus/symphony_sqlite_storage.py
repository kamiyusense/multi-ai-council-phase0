"""Reviewed persistent Codex SQLite binding; no scheduler, login or activation.

The trusted installer supplies review pins and two separate approval callbacks.
Sealing an isolated initialized store never approves a worker. No directories,
credentials or Codex processes are created here. Original migrations own schema.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from contextlib import closing
from pathlib import Path

from .symphony_result_manifest import canonical

SEAL = "symphony-sqlite-storage.json"
DB_NAME = re.compile(r"(?:state|memories|goals|logs|queue)_[0-9]+\.sqlite")


def private_directory(value):
    path = Path(value)
    if (not path.is_absolute() or path.resolve() != path or path.is_symlink()
            or not path.is_dir()):
        raise PermissionError("canonical existing directory required")
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError("owned private directory required")
    return path


def disjoint(a, b):
    return a != b and a not in b.parents and b not in a.parents


@dataclass(frozen=True)
class SQLiteStorageReview:
    root: Path
    auth_home: Path
    executable: Path
    executable_sha256: str
    migration_sha256: str
    workspace_roots: tuple[Path, ...]

    def binding(self):
        return {"root": str(self.root), "auth_home": str(self.auth_home),
                "executable": str(self.executable),
                "executable_sha256": self.executable_sha256,
                "migration_sha256": self.migration_sha256,
                "workspace_roots": [str(p) for p in self.workspace_roots]}


class ReviewedSQLiteStorage:
    """Explicit installer seam. Callbacks are trusted operator configuration.

    Never acquire these callbacks or pins from a candidate, model, env flag or
    diagnostic receipt. Production approval is not installed by this module.
    The worker approval is checked on each process launch, separately from the
    same-process subscription checks in JsonlCodexAppServer.
    """
    def __init__(self, *, review, installation_check, worker_check=None):
        if type(review) is not SQLiteStorageReview or not callable(installation_check):
            raise PermissionError("independent storage review required")
        self.review = review
        self._installation_check = installation_check
        self._worker_check = worker_check

    def _paths(self):
        r = self.review
        root = private_directory(r.root)
        auth = Path(r.auth_home)
        executable = Path(r.executable)
        if (not auth.is_absolute() or auth.resolve() != auth or not auth.is_dir()
                or not executable.is_absolute() or executable.resolve() != executable
                or not executable.is_file() or executable.is_symlink()
                or not r.workspace_roots
                or any(not Path(p).is_absolute() or Path(p).resolve() != Path(p)
                       or not disjoint(root, Path(p)) for p in r.workspace_roots)
                or not disjoint(root, auth)
                or not re.fullmatch(r"[0-9a-f]{64}", r.executable_sha256 or "")
                or not re.fullmatch(r"[0-9a-f]{64}", r.migration_sha256 or "")
                or hashlib.sha256(executable.read_bytes()).hexdigest() != r.executable_sha256):
            raise PermissionError("storage/auth/workspace/binary binding conflict")
        for p in root.iterdir():
            info = p.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077
                    or not (p.name == SEAL or DB_NAME.fullmatch(p.name)
                            or DB_NAME.fullmatch(p.name.removesuffix("-wal"))
                            or DB_NAME.fullmatch(p.name.removesuffix("-shm")))):
                raise PermissionError("unsafe storage entry")
        return root

    def inspect(self):
        """Read only migrations/integrity, including WAL; never private rows.

        A WAL means recovery is needed, not automatic corruption. SQLite's
        read-only WAL access can maintain shared-memory in this separate store;
        this is not an immutable/main-file-only crash proof or a repair command.
        """
        root = self._paths()
        dbs = sorted(p for p in root.iterdir() if DB_NAME.fullmatch(p.name))
        if not dbs:
            raise PermissionError("Codex-initialized migrations required")
        inventory = []
        identities = {}
        try:
            for p in dbs:
                with closing(sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=1)) as c:
                    c.execute("PRAGMA query_only=ON")
                    if c.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise ValueError("integrity unknown")
                    rows = c.execute("SELECT version, success, checksum FROM _sqlx_migrations ORDER BY version").fetchall()
                    if not rows or any(success != 1 or not isinstance(checksum, bytes)
                                       for _, success, checksum in rows):
                        raise ValueError("migration incomplete")
                    inventory.append({"database": p.name, "migrations":
                        [[v, hashlib.sha256(checksum).hexdigest()] for v, _, checksum in rows]})
                s = p.stat(); identities[p.name] = [s.st_dev, s.st_ino]
        except Exception:
            raise PermissionError("storage health/migrations unavailable; no repair") from None
        fingerprint = hashlib.sha256(canonical(inventory).encode()).hexdigest()
        if fingerprint != self.review.migration_sha256:
            raise PermissionError("migration pin conflict; no rewrite or auto-migration")
        info = root.stat()
        return {"protocol": "SYMPHONY_SQLITE_STORAGE_V1", "binding": self.review.binding(),
                "directory_identity": [info.st_dev, info.st_ino], "databases": identities,
                "migration_sha256": fingerprint}

    def seal_initialized(self):
        """Create-only seal after independently approved original initialization."""
        if self._installation_check(self.review.binding()) is not True:
            raise PermissionError("storage installation not approved")
        record = self.inspect()
        target = self.review.root / SEAL
        raw = canonical(record).encode()
        if target.exists():
            if target.read_bytes() != raw:
                raise PermissionError("existing seal conflict; overwrite forbidden")
            return "NOOP_DUPLICATE"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        # A lost/partial create remains a conflict on readback, never overwritten.
        return "CREATED"

    def readiness(self):
        current = self.inspect()
        seal = self.review.root / SEAL
        if not seal.is_file() or seal.read_bytes() != canonical(current).encode():
            raise PermissionError("storage seal absent/conflicting; readback only")
        return {"state": "STORAGE_READINESS_PASS_NOT_WORKER_ADMISSION",
                "migration_sha256": current["migration_sha256"],
                "database_count": len(current["databases"]),
                "wal_present": any(p.name.endswith("-wal") for p in self.review.root.iterdir()),
                "model_dispatch": 0, "credentials_copied": 0}

    def app_server_args(self, *, executable, auth_home, readonly):
        self.readiness()
        if Path(executable) != self.review.executable or Path(auth_home or "") != self.review.auth_home:
            raise PermissionError("launch identity differs from storage review")
        if readonly is not True:
            if not callable(self._worker_check) or self._worker_check(self.review.binding()) is not True:
                raise PermissionError("separate worker storage approval absent")
        return [str(self.review.executable), "app-server", "-c",
                "sqlite_home=" + json.dumps(str(self.review.root))]

    def backup_quiescent(self, destination, *, quiescent_check):
        """Snapshot into a NEW private directory; no overwrite or credentials.

        Trusted operator must have stopped all writers. Absence of WAL alone
        does not prove this. Restore uses a new reviewed root and fresh seal,
        never replaces a live store or copies platform-incompatible old DBs.
        """
        self.readiness()
        if (not callable(quiescent_check) or quiescent_check(self.review.binding()) is not True
                or self._installation_check(self.review.binding()) is not True
                or any(p.name.endswith(("-wal", "-shm")) for p in self.review.root.iterdir())):
            raise PermissionError("independent quiescence required")
        dest = private_directory(destination)
        if (any(dest.iterdir()) or not disjoint(dest, self.review.root)
                or not disjoint(dest, self.review.auth_home)
                or any(not disjoint(dest, p) for p in self.review.workspace_roots)):
            raise PermissionError("new separate empty backup destination required")
        for p in sorted(self.review.root.iterdir()):
            if DB_NAME.fullmatch(p.name):
                fd = os.open(dest / p.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                os.close(fd)
                with closing(sqlite3.connect(p.as_uri() + "?mode=ro&immutable=1", uri=True)) as source, \
                     closing(sqlite3.connect(dest / p.name)) as target:
                    source.backup(target)
        return {"state": "BACKUP_CREATED_NOT_INSTALLED", "database_count":
                sum(bool(DB_NAME.fullmatch(p.name)) for p in dest.iterdir()),
                "credentials_copied": 0}
