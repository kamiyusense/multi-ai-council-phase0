"""G6.1 pre-close workspace snapshot: keep actual result bytes after cleanup.

Official Symphony removes an Issue's workspace when the Issue reaches a
terminal tracker state. That cleanup is unchanged. Instead, before the proof
Issue is closed, the controller captures a complete inventory of the
workspace into a content-addressed store *outside* the workspace, reads every
object back, and only then reports the close gate as open. Later result
inspection reads source bytes from this snapshot, never from the (possibly
deleted) workspace.

Properties:
- create-only objects (``sha256/<aa>/<digest>``) and create-only manifests;
  an existing different manifest is a CONFLICT, never overwritten
- two-pass capture; a workspace that changes during capture is UNSTABLE
- no symlink following; symlinks are recorded as Git symlink entries
- nested ``.git``, special files, junctions and unsafe names are anomalies:
  the snapshot is still kept, but ``complete=False`` makes the inspector hold
- load verifies the manifest digest and every object's SHA-256 and size
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .symphony_result_manifest import DIGEST, FileEntry, ID, SourceResult, canonical, digest, inventory_digest, safe_path

PROTOCOL = "SYMPHONY_G61_WORKSPACE_SNAPSHOT_V1"
MANIFEST_KEYS = {"protocol", "snapshot_id", "campaign_id", "attempt_id", "worker_run_id", "workspace_path",
                 "workspace_fingerprint", "entries", "excluded", "anomalies", "inventory_digest",
                 "captured_at", "manifest_digest"}


class SnapshotIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotResult:
    status: str  # VERIFIED | NOOP_DUPLICATE | UNSTABLE | CONFLICT
    reason: str
    snapshot_id: str
    manifest_sha256: str | None = None
    inventory_digest: str | None = None
    file_count: int = 0
    total_bytes: int = 0
    anomalies: tuple[str, ...] = ()

    @property
    def close_gate_open(self) -> bool:
        return self.status in {"VERIFIED", "NOOP_DUPLICATE"} and not self.anomalies

    def to_dict(self) -> dict:
        return {"protocol": PROTOCOL, "status": self.status, "reason": self.reason, "snapshot_id": self.snapshot_id,
                "manifest_sha256": self.manifest_sha256, "inventory_digest": self.inventory_digest,
                "file_count": self.file_count, "total_bytes": self.total_bytes,
                "anomalies": list(self.anomalies), "close_gate_open": self.close_gate_open}


def workspace_fingerprint(workspace: str) -> str:
    # Same derivation as the G5 production observer's STARTED record.
    return hashlib.sha256(workspace.encode()).hexdigest()


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def scan_workspace(workspace: str, *, exclude_top: Iterable[str] = (".git",)) -> tuple[dict[str, FileEntry], list[str], list[str]]:
    """Return (files, excluded, anomalies). Reads bytes; never follows links."""
    if tuple(exclude_top) != (".git",):
        raise ValueError("only top-level .git may be excluded; full inventory required")
    # Anchor every traversal to a directory descriptor. A pathname check followed
    # by read_bytes would follow a concurrently swapped parent/link.
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
        raise SnapshotIntegrityError("secure no-follow snapshot unsupported on this platform")
    files: dict[str, FileEntry] = {}; excluded: list[str] = []; anomalies: list[str] = []
    def signature(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    def walk(fd, prefix):
        for name in sorted(os.listdir(fd)):
            rel = prefix + name
            if not prefix and name == ".git":
                excluded.append(rel); continue
            if prefix and name.casefold() == ".git":
                anomalies.append("nested_git:" + rel); continue
            if not safe_path(rel):
                anomalies.append("unsafe_name:" + digest(rel)[:16]); continue
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if getattr(before, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                anomalies.append("junction:" + rel); continue
            if stat.S_ISLNK(before.st_mode):
                files[rel] = FileEntry(os.fsencode(os.readlink(name, dir_fd=fd)), "120000", "symlink")
            elif stat.S_ISDIR(before.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    if signature(os.fstat(child)) != signature(before):
                        raise SnapshotIntegrityError("directory replaced during capture")
                    walk(child, rel + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(before.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(child, "rb") as handle:
                    if signature(os.fstat(handle.fileno())) != signature(before):
                        raise SnapshotIntegrityError("file replaced during capture")
                    data = handle.read()
                    if signature(os.fstat(handle.fileno())) != signature(before):
                        raise SnapshotIntegrityError("file changed during capture")
                files[rel] = FileEntry(data, "100755" if before.st_mode & stat.S_IXUSR else "100644", "blob")
            else:
                anomalies.append("special_file:" + rel)
            if signature(os.stat(name, dir_fd=fd, follow_symlinks=False)) != signature(before):
                raise SnapshotIntegrityError("entry changed during capture")
    try:
        fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            root_info = os.fstat(fd)
            walk(fd, "")
            if signature(os.stat(workspace, follow_symlinks=False)) != signature(root_info):
                raise SnapshotIntegrityError("workspace root changed during capture")
        finally:
            os.close(fd)
    except OSError as exc:
        raise SnapshotIntegrityError("workspace capture unavailable or changed") from exc
    return files, excluded, sorted(anomalies)


def _sync_directory(path: Path):
    """Persist create-only directory entries before releasing the close gate."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class WorkspaceSnapshotStore:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)

    def _object_path(self, sha: str) -> Path:
        return self.root / "objects" / "sha256" / sha[:2] / sha

    def _manifest_path(self, snapshot_id: str) -> Path:
        if not ID.fullmatch(snapshot_id or ""):
            raise ValueError("invalid snapshot id")
        return self.root / "snapshots" / f"{snapshot_id}.json"

    def _put_object(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self._object_path(sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Publish fully written bytes atomically, never expose a partial object.
        temp = path.with_name("." + sha + "." + uuid.uuid4().hex + ".tmp")
        with open(temp, "xb") as handle:
            os.chmod(temp, 0o600)
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        try:
            os.chmod(temp, stat.S_IREAD)
            os.link(temp, path)
        except FileExistsError:
            pass
        finally:
            temp.unlink(missing_ok=True)
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise SnapshotIntegrityError("existing snapshot object differs from its address")
        for directory in (path.parent, path.parent.parent, path.parent.parent.parent, self.root):
            _sync_directory(directory)
        return sha

    def capture(self, *, workspace: str, snapshot_id: str, campaign_id: str, attempt_id: str,
                worker_run_id: str, captured_at: str, exclude_top: Iterable[str] = (".git",)) -> SnapshotResult:
        for value in (campaign_id, attempt_id, snapshot_id):
            if not ID.fullmatch(value or ""):
                raise ValueError("invalid snapshot identity")
        if tuple(exclude_top) != (".git",):
            raise ValueError("only top-level .git may be excluded")
        real_ws, real_root = Path(os.path.realpath(workspace)), Path(os.path.realpath(self.root))
        if _inside(real_root, real_ws) or _inside(real_ws, real_root):
            raise ValueError("snapshot store must be outside the workspace (and vice versa)")
        manifest_path = self._manifest_path(snapshot_id)
        files, excluded, anomalies = scan_workspace(workspace, exclude_top=exclude_top)
        current = inventory_digest(files)
        if manifest_path.exists():
            try:
                existing = self._read_manifest(snapshot_id)
                self.load(snapshot_id)  # a duplicate is only NOOP if every stored byte still verifies
            except SnapshotIntegrityError:
                return SnapshotResult("CONFLICT", "existing snapshot unreadable or altered; never overwritten", snapshot_id)
            same = (existing["campaign_id"] == campaign_id and existing["attempt_id"] == attempt_id
                    and existing["excluded"] == excluded and existing["anomalies"] == anomalies
                    and existing["inventory_digest"] == current and existing["worker_run_id"] == worker_run_id
                    and existing["workspace_fingerprint"] == workspace_fingerprint(workspace))
            return self._result("NOOP_DUPLICATE" if same else "CONFLICT",
                                "snapshot already captured" if same else "snapshot id reused for different bytes", snapshot_id)
        try:
            for entry in files.values():
                self._put_object(entry.data)
        except SnapshotIntegrityError as exc:
            return SnapshotResult("CONFLICT", str(exc), snapshot_id)
        second, second_excluded, second_anomalies = scan_workspace(workspace, exclude_top=exclude_top)
        if inventory_digest(second) != current or second_anomalies != anomalies or second_excluded != excluded:
            return SnapshotResult("UNSTABLE", "workspace changed during capture; close gate stays shut", snapshot_id)
        body = {"protocol": PROTOCOL, "snapshot_id": snapshot_id, "campaign_id": campaign_id, "attempt_id": attempt_id,
                "worker_run_id": worker_run_id, "workspace_path": workspace,
                "workspace_fingerprint": workspace_fingerprint(workspace),
                "entries": {p: {**e.description(), "size": len(e.data)} for p, e in sorted(files.items())},
                "excluded": excluded, "anomalies": anomalies, "inventory_digest": current, "captured_at": captured_at}
        text = canonical({**body, "manifest_digest": digest(body)})
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temp = manifest_path.with_name(f".{snapshot_id}.{uuid.uuid4().hex}.tmp")
        with open(temp, "x", encoding="utf-8") as handle:
            os.chmod(temp, 0o600)
            handle.write(text); handle.flush(); os.fsync(handle.fileno())
        try:
            os.link(temp, manifest_path)  # create-only publish; fails if it exists
        except FileExistsError:
            return SnapshotResult("CONFLICT", "concurrent snapshot manifest publish", snapshot_id)
        finally:
            temp.unlink(missing_ok=True)
        os.chmod(manifest_path, stat.S_IREAD)
        _sync_directory(manifest_path.parent)
        _sync_directory(self.root)
        source = self.load(snapshot_id)  # full readback of every object
        if inventory_digest(source.files) != current:
            return SnapshotResult("CONFLICT", "snapshot readback differs from capture", snapshot_id)
        return self._result("VERIFIED", "complete inventory and bytes stored outside workspace", snapshot_id)

    def _result(self, status: str, reason: str, snapshot_id: str) -> SnapshotResult:
        manifest = self._read_manifest(snapshot_id)
        return SnapshotResult(status, reason, snapshot_id, self.manifest_sha256(snapshot_id), manifest["inventory_digest"],
                              len(manifest["entries"]), sum(e["size"] for e in manifest["entries"].values()),
                              tuple(manifest["anomalies"]))

    def manifest_sha256(self, snapshot_id: str) -> str:
        return hashlib.sha256(self._manifest_path(snapshot_id).read_bytes()).hexdigest()

    def _read_manifest(self, snapshot_id: str) -> dict:
        try:
            manifest = json.loads(self._manifest_path(snapshot_id).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SnapshotIntegrityError("snapshot manifest unavailable") from exc
        if (type(manifest) is not dict or set(manifest) != MANIFEST_KEYS or manifest["protocol"] != PROTOCOL
                or manifest["snapshot_id"] != snapshot_id
                or digest({k: v for k, v in manifest.items() if k != "manifest_digest"}) != manifest["manifest_digest"]):
            raise SnapshotIntegrityError("snapshot manifest digest/schema mismatch")
        return manifest

    def load(self, snapshot_id: str, *, expected_worker_run_id: str | None = None,
             expected_campaign_id: str | None = None, expected_attempt_id: str | None = None,
             expected_workspace_fingerprint: str | None = None) -> SourceResult:
        """Verified SourceResult. Any missing/altered object raises; never partial."""
        manifest = self._read_manifest(snapshot_id)
        if expected_worker_run_id is not None and manifest["worker_run_id"] != expected_worker_run_id:
            raise SnapshotIntegrityError("snapshot belongs to another worker")
        for key, expected in (("campaign_id", expected_campaign_id), ("attempt_id", expected_attempt_id),
                              ("workspace_fingerprint", expected_workspace_fingerprint)):
            if expected is not None and manifest[key] != expected:
                raise SnapshotIntegrityError("snapshot identity mismatch: " + key)
        if manifest["excluded"] not in ([], [".git"]):
            raise SnapshotIntegrityError("unexpected snapshot exclusion")
        if workspace_fingerprint(manifest["workspace_path"]) != manifest["workspace_fingerprint"]:
            raise SnapshotIntegrityError("snapshot workspace fingerprint mismatch")
        files = {}
        for path, meta in manifest["entries"].items():
            if (not safe_path(path) or not isinstance(meta, dict)
                    or not DIGEST.fullmatch(meta.get("sha256", ""))
                    or type(meta.get("size")) is not int or meta["size"] < 0):
                raise SnapshotIntegrityError("unsafe path in snapshot manifest")
            try:
                data = self._object_path(meta["sha256"]).read_bytes()
            except OSError as exc:
                raise SnapshotIntegrityError("snapshot object missing") from exc
            if hashlib.sha256(data).hexdigest() != meta["sha256"] or len(data) != meta["size"]:
                raise SnapshotIntegrityError("snapshot object bytes altered")
            files[path] = FileEntry(data, meta["mode"], meta["type"])
        if inventory_digest(files) != manifest["inventory_digest"]:
            raise SnapshotIntegrityError("snapshot inventory digest mismatch")
        return SourceResult(manifest["workspace_fingerprint"], files, True, not manifest["anomalies"])

    def source_reader(self, snapshot_id: str, *, expected_worker_run_id: str):
        return lambda: self.load(snapshot_id, expected_worker_run_id=expected_worker_run_id)
