"""Static Jules input adapter. It never grants owner authority or verifies a provider."""
from __future__ import annotations

import json
from typing import Any

from .github_backend import GitHubContentsClient
from .loop_owner import validate_owner_event
from .runtime_transition_evidence import validate_evidence_document
from .runtime_transition_receipt import (
    CanonicalOwnerReceiptGitHubBackend,
    OwnerReceiptWriteResult,
    build_terminal_owner_receipt,
)


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


def prepare_jules_terminal_owner_receipt(
    owner_event: dict[str, Any],
    *,
    jules_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Derive one canonical TERMINAL owner receipt from a durable Jules receipt.

    The original Jules receipt remains immutable at its own round-scoped path.
    This function only prepares a new owner receipt; it performs no write.
    """
    round_number = jules_receipt.get("round")
    if isinstance(round_number, bool) or not isinstance(round_number, int) or round_number < 1:
        raise ValueError("Jules receipt round is required")
    provider_ref = (
        f"automation/command_bus/receipts/{owner_event['loop_id']}/"
        f"{round_number:06d}.json"
    )
    return build_terminal_owner_receipt(
        owner_event,
        provider_kind="JULES",
        provider_receipt=jules_receipt,
        provider_receipt_ref=provider_ref,
    )


class JulesTerminalOwnerReceiptAdapter:
    """Read a durable Jules terminal receipt and publish one canonical owner receipt."""

    def __init__(self, client: GitHubContentsClient, *, branch: str):
        self.client = client
        self.branch = branch
        self.backend = CanonicalOwnerReceiptGitHubBackend(client, branch=branch)

    def publish(self, owner_event: dict[str, Any], *, jules_round: int) -> OwnerReceiptWriteResult:
        try:
            if isinstance(jules_round, bool) or not isinstance(jules_round, int) or jules_round < 1:
                raise ValueError("Jules round must be a positive integer")
            validate_owner_event(owner_event)
            source_ref = (
                f"automation/command_bus/receipts/{owner_event['loop_id']}/"
                f"{jules_round:06d}.json"
            )
            content = self.client.get(source_ref, self.branch)
            if content is None:
                return OwnerReceiptWriteResult("UNKNOWN", "durable Jules receipt readback unavailable")
            jules_receipt = json.loads(content.text)
            if not isinstance(jules_receipt, dict):
                raise ValueError("durable Jules receipt is not a JSON object")
            canonical = prepare_jules_terminal_owner_receipt(
                owner_event,
                jules_receipt=jules_receipt,
            )
            return self.backend.write(owner_event, canonical)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return OwnerReceiptWriteResult("UNKNOWN", str(exc))
