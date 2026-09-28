"""Static Jules input adapter. It never grants owner authority or verifies a provider."""
from __future__ import annotations

from typing import Any

from .loop_owner import validate_owner_event
from .runtime_transition_evidence import validate_evidence_document


def prepare_jules_evidence(
    owner_event: dict[str, Any],
    *,
    jules_receipt: dict[str, Any],
    publication: dict[str, Any],
    observed_at: str,
    provider_readback: str,
) -> dict[str, Any]:
    """Prepare canonical evidence for a separately authorized owner generation.

    The Jules terminal receipt is historical input, not the canonical owner
    receipt. A controller must produce/read back that canonical receipt first.
    This function neither certifies a provider observation nor performs writes.
    """
    validate_owner_event(owner_event)
    if jules_receipt.get("retry_count") != 0 or jules_receipt.get("fallback_used") is not False:
        raise ValueError("Jules receipt must preserve retry=0/fallback=disabled")
    if publication.get("repository") != owner_event["expected_repo"] or publication.get("pr_number") != owner_event["expected_pr"]:
        raise ValueError("Jules publication target mismatch")
    if publication.get("resulting_commit") != owner_event["expected_target_head"]:
        raise ValueError("Jules publication head mismatch")
    refs = jules_receipt.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        raise ValueError("Jules external evidence identifiers are missing")
    evidence_id = owner_event["evidence_refs"][0].removesuffix(".json").rsplit("/", 1)[-1]
    document = {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "loop_id": owner_event["loop_id"],
        "generation": owner_event["generation"],
        "command_id": owner_event["command_id"],
        "correlation_id": owner_event["correlation_id"],
        "expected_repo": owner_event["expected_repo"],
        "expected_pr": owner_event["expected_pr"],
        "expected_target_head": owner_event["expected_target_head"],
        "source_receipt_ref": owner_event["source_receipt_ref"],
        "provider_kind": "JULES",
        "provider_state": "COMPLETE",
        "observed_at": observed_at,
        "external_refs": refs,
        "test_results": [
            {"name": "jules-tests", "status": "PASS" if publication.get("tests_passed") is True else "UNKNOWN"},
            {"name": "compileall", "status": "PASS" if publication.get("compileall_passed") is True else "UNKNOWN"},
            {"name": "diff-check", "status": "PASS" if publication.get("diff_check_passed") is True else "UNKNOWN"},
        ],
        "provider_readback": provider_readback,
        "publication_evidence": {
            "commit_sha": publication.get("resulting_commit"),
            "tree_sha": publication.get("result_tree"),
        },
    }
    path = validate_evidence_document(document)
    if path != owner_event["evidence_refs"][0]:
        raise ValueError("Jules evidence path is not bound to the owner event")
    return document
