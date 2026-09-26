"""Fail-closed helpers for reconstructing GitHub connector blobs locally.

The Work runtime may have GitHub connector access even when its local container
cannot resolve github.com. These helpers allow exact blob verification before
materializing connector-fetched content into a disposable scratch workspace.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

ROOT = "automation/command_bus/"
SUPPORTED_FILE_MODES = frozenset({"100644", "100755"})


@dataclass(frozen=True)
class VerifiedBlob:
    path: str
    sha: str
    mode: str
    size: int


def git_blob_sha(content: bytes) -> str:
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError("blob content must be bytes")
    payload = bytes(content)
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def validate_static_entry(entry: dict[str, Any]) -> VerifiedBlob:
    if not isinstance(entry, dict):
        raise ValueError("static tree entry must be an object")
    required = {"path", "type", "sha", "mode", "size"}
    if not required <= entry.keys():
        raise ValueError("incomplete static tree entry")
    path = entry["path"]
    if not isinstance(path, str) or not path.startswith(ROOT):
        raise ValueError("static path outside command-bus root")
    rel = path[len(ROOT):]
    pure = PurePosixPath(rel)
    if (
        not rel
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError("unsafe static path")
    if entry["type"] != "blob":
        raise ValueError("static entry must be a blob")
    sha = entry["sha"]
    if not isinstance(sha, str) or len(sha) != 40:
        raise ValueError("invalid static blob sha")
    mode = entry["mode"]
    if mode not in SUPPORTED_FILE_MODES:
        raise ValueError("unsupported static blob mode")
    size = entry["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("invalid static blob size")
    return VerifiedBlob(path=path, sha=sha, mode=mode, size=size)


def verify_connector_blob(
    entry: dict[str, Any],
    *,
    fetched_sha: str,
    content: bytes,
) -> VerifiedBlob:
    verified = validate_static_entry(entry)
    if fetched_sha != verified.sha:
        raise ValueError("connector blob sha does not match tree entry")
    if len(content) != verified.size:
        raise ValueError("connector blob size does not match tree entry")
    if git_blob_sha(content) != verified.sha:
        raise ValueError("recomputed git blob sha mismatch")
    return verified


def materialization_relpath(path: str) -> str:
    verified = validate_static_entry({
        "path": path,
        "type": "blob",
        "sha": "0" * 40,
        "mode": "100644",
        "size": 0,
    })
    return verified.path[len(ROOT):]


def require_unique_static_entries(
    entries: list[dict[str, Any]],
) -> tuple[VerifiedBlob, ...]:
    if not isinstance(entries, list) or not entries:
        raise ValueError("static entry list is empty or invalid")
    verified = [validate_static_entry(entry) for entry in entries]
    paths = [item.path for item in verified]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate static path")
    return tuple(sorted(verified, key=lambda item: item.path))
