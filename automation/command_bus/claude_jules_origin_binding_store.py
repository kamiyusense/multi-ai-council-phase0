"""Static durable binding store for CLAUDE_AUTO_ORIGIN_BINDING_V1.

This module provides the durable persistence boundary for origin bindings.
It relies on existing current carrier validation before invocation. It
uses the standard GitHubContentsClient pattern: create-only, independent readback,
retry=0, and exact cross-binding verification on read. No live authorization or
workflow changes are implied.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .github_backend import GitHubContentsClient
from .claude_jules_origin_binding import (
    COMMAND_ID_RE,
    verify_binding_record,
)


@dataclass(frozen=True)
class BindingStoreResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


def _get_path(command_id: str) -> str:
    if not isinstance(command_id, str) or not COMMAND_ID_RE.match(command_id):
        raise ValueError("unsafe or invalid command_id")
    return f"automation/command_bus/evidence/claude-auto-origin-bindings/{command_id}.json"


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


class ClaudeJulesOriginBindingStore:
    def __init__(self, client: GitHubContentsClient, branch: str) -> None:
        if not isinstance(branch, str) or not branch or branch in {"main", "master"}:
            raise ValueError("durable store requires a non-default data branch")
        self.client = client
        self.branch = branch

    def persist(
        self,
        record: dict[str, Any],
        carrier_request: dict[str, Any],
        carrier_claim: dict[str, Any],
    ) -> BindingStoreResult:
        try:
            verified = verify_binding_record(record, carrier_request, carrier_claim)
            command_id = verified["command_id"]
            path = _get_path(command_id)
            canonical = _canonical(verified)
        except Exception as exc:
            return BindingStoreResult("UNKNOWN", f"input validation failed: {exc}")

        try:
            existing = self.client.get(path, self.branch)
            if existing is not None:
                try:
                    existing_record = json.loads(existing.text)
                    existing_verified = verify_binding_record(
                        existing_record, carrier_request, carrier_claim
                    )
                    if _canonical(existing_verified) == canonical:
                        return BindingStoreResult(
                            "RECOVERED",
                            "identical binding record already exists",
                            existing_verified,
                        )
                    return BindingStoreResult(
                        "BLOCKED",
                        "different binding record already exists",
                        existing_verified,
                    )
                except Exception as exc:
                    return BindingStoreResult("UNKNOWN", f"existing record is unverifiable: {exc}")
        except Exception as exc:
            return BindingStoreResult("UNKNOWN", f"failed to check existing record: {exc}")

        try:
            self.client.create(
                path,
                canonical,
                f"persist origin binding for {command_id}",
                self.branch,
            )
        except Exception:
            pass  # create error is resolved by the following readback

        try:
            readback = self.client.get(path, self.branch)
            if readback is None:
                return BindingStoreResult(
                    "UNKNOWN", "create result unverified, missing readback; no retry"
                )

            readback_record = json.loads(readback.text)
            readback_verified = verify_binding_record(
                readback_record, carrier_request, carrier_claim
            )

            if _canonical(readback_verified) != canonical:
                return BindingStoreResult(
                    "UNKNOWN", "readback content mismatch; no retry", readback_verified
                )

            return BindingStoreResult("ACCEPTED", "binding record created and verified", readback_verified)
        except Exception as exc:
            return BindingStoreResult("UNKNOWN", f"readback verification failed: {exc}")

    def read(
        self,
        command_id: str,
        carrier_request: dict[str, Any],
        carrier_claim: dict[str, Any],
    ) -> BindingStoreResult:
        try:
            path = _get_path(command_id)
            existing = self.client.get(path, self.branch)
            if existing is None:
                return BindingStoreResult("UNKNOWN", "binding record missing")

            record = json.loads(existing.text)
            if not isinstance(record, dict):
                return BindingStoreResult("UNKNOWN", "binding record is not a json object")

            verified = verify_binding_record(record, carrier_request, carrier_claim)

            if verified["command_id"] != command_id:
                return BindingStoreResult("UNKNOWN", "read record command_id mismatch")

            return BindingStoreResult("READ", "binding record successfully read", verified)
        except Exception as exc:
            return BindingStoreResult("UNKNOWN", f"read operation failed: {exc}")
