"""Provider-neutral canonical owner receipt adapter.

This module never dispatches a provider and never grants ownership. It converts
an already durable, validator-approved provider terminal receipt into the
canonical source receipt consumed by RuntimeTransitionPublisher.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .github_backend import GitHubContentsClient
from .loop_owner import validate_owner_event
from .validator import validate_receipt

_PROVIDER = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_RECEIPT_REF = re.compile(
    r"^automation/command_bus/receipts/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$"
)


@dataclass(frozen=True)
class OwnerReceiptWriteResult:
    status: str
    reason: str
    receipt: dict[str, Any] | None = None


def build_terminal_owner_receipt(
    owner_event: dict[str, Any],
    *,
    provider_kind: str,
    provider_receipt: dict[str, Any],
    provider_receipt_ref: str,
) -> dict[str, Any]:
    validate_owner_event(owner_event)
    validate_receipt(provider_receipt)
    if owner_event["event_type"] != "TERMINAL":
        raise ValueError("provider terminal receipt may only derive a TERMINAL owner receipt")
    if owner_event.get("terminal_receipt_id") != owner_event["source_receipt_id"]:
        raise ValueError("TERMINAL owner event must bind terminal_receipt_id to source_receipt_id")
    if not isinstance(provider_kind, str) or not _PROVIDER.fullmatch(provider_kind):
        raise ValueError("unsafe provider_kind")
    if not isinstance(provider_receipt_ref, str) or not _RECEIPT_REF.fullmatch(provider_receipt_ref):
        raise ValueError("provider receipt ref must be a canonical durable receipt path")
    prefix = f"automation/command_bus/receipts/{owner_event['loop_id']}/"
    if not provider_receipt_ref.startswith(prefix):
        raise ValueError("provider receipt ref loop mismatch")
    if provider_receipt_ref == owner_event["source_receipt_ref"]:
        raise ValueError("provider and canonical owner receipts must use distinct paths")
    if provider_receipt.get("loop_id") != owner_event["loop_id"]:
        raise ValueError("provider receipt loop mismatch")
    if provider_receipt.get("correlation_id") != owner_event["correlation_id"]:
        raise ValueError("provider receipt correlation mismatch")
    if provider_receipt.get("retry_count") != 0 or provider_receipt.get("fallback_used") is not False:
        raise ValueError("provider receipt violates retry/fallback policy")
    if len(owner_event["evidence_refs"]) != 1:
        raise ValueError("canonical owner receipt requires exactly one evidence ref")
    if owner_event["evidence_refs"] != list(dict.fromkeys(owner_event["evidence_refs"])):
        raise ValueError("owner evidence refs must be unique")

    receipt = {
        "schema_version": 1,
        "receipt_id": owner_event["source_receipt_id"],
        "command_id": owner_event["command_id"],
        "loop_id": owner_event["loop_id"],
        "correlation_id": owner_event["correlation_id"],
        "state": provider_receipt["state"],
        "executed_once": True,
        "retry_count": 0,
        "fallback_used": False,
        "evidence_refs": list(owner_event["evidence_refs"]),
        "provider_kind": provider_kind,
        "provider_source_receipt_id": provider_receipt["receipt_id"],
        "provider_source_receipt_ref": provider_receipt_ref,
        "provider_source_command_id": provider_receipt["command_id"],
        "provider_source_state": provider_receipt["state"],
    }
    if "round" in provider_receipt:
        receipt["provider_source_round"] = provider_receipt["round"]
    validate_receipt(receipt)
    return receipt


class CanonicalOwnerReceiptGitHubBackend:
    """Create-only canonical owner-receipt persistence with exact readback."""

    def __init__(self, client: GitHubContentsClient, *, branch: str):
        if not isinstance(branch, str) or not branch or branch in {"main", "master"}:
            raise ValueError("owner receipt backend requires a non-default data branch")
        self.client = client
        self.branch = branch

    def write(self, owner_event: dict[str, Any], receipt: dict[str, Any]) -> OwnerReceiptWriteResult:
        try:
            validate_owner_event(owner_event)
            validate_receipt(receipt)
            path = owner_event["source_receipt_ref"]
            if not _RECEIPT_REF.fullmatch(path):
                raise ValueError("unsafe owner source receipt path")
            prefix = f"automation/command_bus/receipts/{owner_event['loop_id']}/"
            if not path.startswith(prefix):
                raise ValueError("owner source receipt path loop mismatch")
            expected = {
                "receipt_id": owner_event["source_receipt_id"],
                "command_id": owner_event["command_id"],
                "loop_id": owner_event["loop_id"],
                "correlation_id": owner_event["correlation_id"],
            }
            if any(receipt.get(key) != value for key, value in expected.items()):
                raise ValueError("canonical owner receipt identity mismatch")
            if receipt.get("evidence_refs") != owner_event["evidence_refs"]:
                raise ValueError("canonical owner receipt evidence mismatch")

            existing = self.client.get(path, self.branch)
            if existing is not None:
                record = _json(existing.text)
                validate_receipt(record)
                if _canonical(record) == _canonical(receipt):
                    return OwnerReceiptWriteResult("RECOVERED", "identical owner receipt already exists", record)
                return OwnerReceiptWriteResult("BLOCKED", "conflicting owner receipt already exists", record)

            try:
                self.client.create(
                    path,
                    _canonical(receipt),
                    f"append canonical owner receipt {receipt['receipt_id']}",
                    self.branch,
                )
            except Exception:
                pass

            readback = self.client.get(path, self.branch)
            if readback is None:
                return OwnerReceiptWriteResult("UNKNOWN", "owner receipt write readback unavailable")
            record = _json(readback.text)
            validate_receipt(record)
            if _canonical(record) != _canonical(receipt):
                return OwnerReceiptWriteResult("UNKNOWN", "owner receipt write readback mismatch", record)
            return OwnerReceiptWriteResult("ACCEPTED", "owner receipt written and verified", record)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return OwnerReceiptWriteResult("UNKNOWN", str(exc))


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("receipt readback is not a JSON object")
    return value
