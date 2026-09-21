from __future__ import annotations

from pathlib import Path


FORBIDDEN_SNAPSHOT_NAMES = {".git", ".ssh"}
FORBIDDEN_FILE_FRAGMENTS = ("id_rsa", "id_ed25519", ".pem", ".key")


def ensure_within(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if candidate_resolved != root_resolved and root_resolved not in candidate_resolved.parents:
        raise ValueError("path escapes allowed root")
    return candidate_resolved


def validate_snapshot_tree(snapshot_root: Path) -> tuple[str, ...]:
    violations: list[str] = []
    if not snapshot_root.exists():
        return ()
    for path in snapshot_root.rglob("*"):
        rel = path.relative_to(snapshot_root)
        parts = set(rel.parts)
        if parts & FORBIDDEN_SNAPSHOT_NAMES:
            violations.append(str(rel))
            continue
        lowered = path.name.lower()
        if any(fragment in lowered for fragment in FORBIDDEN_FILE_FRAGMENTS):
            violations.append(str(rel))
    return tuple(sorted(set(violations)))
