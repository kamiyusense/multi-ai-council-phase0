"""Canonical, secret-free evidence document for a runtime transition."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .loop_status_evidence import validate_evidence_ref

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOOP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_REF = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}:[A-Za-z0-9][A-Za-z0-9._/-]{0,191}$")
_STATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ -]{0,63}$")
_KEYS = {
    "schema_version", "evidence_id", "loop_id", "generation", "command_id",
    "correlation_id", "expected_repo", "expected_pr", "expected_target_head",
    "source_receipt_ref", "provider_kind", "provider_state", "observed_at",
    "external_refs", "test_results", "provider_readback", "publication_evidence",
}
_TEST_KEYS = {"name", "status"}
_PUBLICATION_KEYS = {"commit_sha", "tree_sha"}


def evidence_path(loop_id: str, evidence_id: str) -> str:
    if not isinstance(loop_id, str) or not _LOOP.fullmatch(loop_id):
        raise ValueError("unsafe evidence loop_id")
    if not isinstance(evidence_id, str) or not _ID.fullmatch(evidence_id):
        raise ValueError("unsafe evidence_id")
    path = f"automation/command_bus/evidence/{loop_id}/{evidence_id}.json"
    validate_evidence_ref(path)
    return path


def validate_evidence_document(document: dict[str, Any]) -> str:
    if not isinstance(document, dict) or set(document) != _KEYS:
        raise ValueError("canonical evidence document has missing or unexpected fields")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported evidence schema")
    path = evidence_path(document["loop_id"], document["evidence_id"])
    if not isinstance(document["generation"], int) or isinstance(document["generation"], bool) or document["generation"] < 1:
        raise ValueError("invalid evidence generation")
    for key in ("command_id", "correlation_id"):
        if not isinstance(document[key], str) or not _ID.fullmatch(document[key]):
            raise ValueError(f"invalid {key}")
    if not isinstance(document["expected_repo"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", document["expected_repo"]):
        raise ValueError("invalid evidence repository")
    if type(document["expected_pr"]) is not int or document["expected_pr"] < 1:
        raise ValueError("invalid evidence PR")
    if not isinstance(document["expected_target_head"], str) or not _SHA.fullmatch(document["expected_target_head"]):
        raise ValueError("invalid evidence target head")
    receipt_prefix = f"automation/command_bus/receipts/{document['loop_id']}/"
    if not isinstance(document["source_receipt_ref"], str) or not re.fullmatch(re.escape(receipt_prefix) + r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json", document["source_receipt_ref"]):
        raise ValueError("invalid evidence receipt ref")
    if not isinstance(document["provider_kind"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", document["provider_kind"]):
        raise ValueError("invalid provider kind")
    if not isinstance(document["provider_state"], str) or not _STATE.fullmatch(document["provider_state"]):
        raise ValueError("invalid provider state")
    timestamp = document["observed_at"]
    if not isinstance(timestamp, str):
        raise ValueError("evidence observation time is missing")
    observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("evidence observation time needs a timezone")
    refs = document["external_refs"]
    if not isinstance(refs, list) or len(refs) > 32 or any(not isinstance(ref, str) or not _REF.fullmatch(ref) or "://" in ref for ref in refs) or len(refs) != len(set(refs)):
        raise ValueError("external references must be unique safe identifiers, not URLs")
    results = document["test_results"]
    if not isinstance(results, list) or len(results) > 32:
        raise ValueError("invalid test result list")
    for result in results:
        if not isinstance(result, dict) or set(result) != _TEST_KEYS or not isinstance(result["name"], str) or not _ID.fullmatch(result["name"]) or result["status"] not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError("malformed evidence test result")
    readback = document["provider_readback"]
    if readback is not None and (not isinstance(readback, str) or not _REF.fullmatch(readback) or "://" in readback):
        raise ValueError("provider readback must be a safe reference")
    publication = document["publication_evidence"]
    if publication is not None:
        if not isinstance(publication, dict) or set(publication) != _PUBLICATION_KEYS:
            raise ValueError("malformed publication evidence")
        for value in publication.values():
            if value is not None and (not isinstance(value, str) or not _SHA.fullmatch(value)):
                raise ValueError("publication commit/tree must be exact SHA or null")
    return path
