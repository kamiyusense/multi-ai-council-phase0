from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class FileDiff:
    created: tuple[FileRecord, ...]
    modified: tuple[FileRecord, ...]
    deleted: tuple[FileRecord, ...]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def persist_raw(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def capture_then_parse(path: Path, data: bytes, parser: Callable[[bytes], T]) -> T:
    persist_raw(path, data)
    return parser(data)


def snapshot_tree(root: Path) -> dict[str, FileRecord]:
    if not root.exists():
        return {}
    records: dict[str, FileRecord] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        records[rel] = FileRecord(rel, path.stat().st_size, sha256_file(path))
    return records


def diff_snapshots(before: dict[str, FileRecord], after: dict[str, FileRecord]) -> FileDiff:
    before_keys = set(before)
    after_keys = set(after)
    created = tuple(after[key] for key in sorted(after_keys - before_keys))
    deleted = tuple(before[key] for key in sorted(before_keys - after_keys))
    modified = tuple(
        after[key]
        for key in sorted(before_keys & after_keys)
        if before[key].sha256 != after[key].sha256
    )
    return FileDiff(created, modified, deleted)


_SECRET_REPLACEMENTS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b"),
)


def mask_known_secrets(text: str) -> str:
    masked = text
    for pattern in _SECRET_REPLACEMENTS:
        masked = pattern.sub("[REDACTED_SECRET]", masked)
    return masked


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
