"""Fail-closed resolver for durable evidence readbacks used by Status projection."""
from __future__ import annotations

import re
from typing import Any, Iterable

_EVIDENCE_REF = re.compile(
    r"^automation/command_bus/evidence/[A-Za-z0-9][A-Za-z0-9._-]{0,63}/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$"
)


def validate_evidence_ref(ref: Any) -> str:
    if not isinstance(ref, str) or not _EVIDENCE_REF.fullmatch(ref):
        raise ValueError("evidence ref must be a canonical durable evidence JSON path")
    return ref


def verify_evidence_readbacks(
    required_refs: Iterable[str],
    readbacks: dict[str, Any] | None,
) -> set[str]:
    """Require one independently fetched, JSON-object readback per exact ref."""
    required = list(required_refs)
    if not required or len(required) != len(set(required)):
        raise ValueError("required evidence refs must be non-empty and unique")
    for ref in required:
        validate_evidence_ref(ref)
    if not isinstance(readbacks, dict):
        raise ValueError("evidence readbacks are missing")
    if set(readbacks) != set(required):
        raise ValueError("evidence readback set does not exactly match required refs")
    for ref, document in readbacks.items():
        validate_evidence_ref(ref)
        if not isinstance(document, dict) or not document:
            raise ValueError(f"evidence readback is not a non-empty JSON object: {ref}")
    return set(required)
