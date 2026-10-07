"""Append-only GitHub-backed durable Loop-owner writer.

The transport is supplied by a connected/authenticated GitHub controller.
This module never discovers credentials and never retries writes. It creates
exactly one immutable generation, reads it back, then re-reads the whole chain.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .github_backend import GitHubContent, GitHubContentsClient
from .loop_owner import validate_owner_chain, validate_owner_event

_ROOT = "automation/command_bus/loop_owner_events"
_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_EVENT_FILE = re.compile(r"^([0-9]{6,})\.json$")


@dataclass(frozen=True)
class OwnerWriteResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None
    chain_length: int | None = None


def owner_event_path(loop_id: str, generation: int) -> str:
    if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
        raise ValueError("unsafe loop_id")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("generation must be a positive integer")
    return f"{_ROOT}/{loop_id}/{generation:06d}.json"


class LoopOwnerGitHubBackend:
    """Create-only owner ledger backend with independent readback."""

    def __init__(self, client: GitHubContentsClient, *, branch: str):
        if not isinstance(branch, str) or not branch:
            raise ValueError("branch is required")
        self.client = client
        self.branch = branch

    def read_chain(self, loop_id: str) -> OwnerWriteResult:
        try:
            chain = self._read_chain(loop_id)
            return OwnerWriteResult("READ", "durable owner chain read", chain[-1] if chain else None, len(chain))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return OwnerWriteResult("UNKNOWN", str(exc))

    def read_events(self, loop_id: str) -> list[dict[str, Any]]:
        """Read and validate the complete owner chain for recovery planning."""
        return self._read_chain(loop_id)

    def append(self, event: dict[str, Any]) -> OwnerWriteResult:
        """Append exactly the next generation and verify the resulting chain.

        No retry is performed. A pre-existing destination is BLOCKED. Ambiguous
        transport failures or readback mismatches are UNKNOWN.
        """
        try:
            validate_owner_event(event)
            loop_id = event["loop_id"]
            chain = self._read_chain(loop_id)
            expected_generation = len(chain) + 1
            if event["generation"] != expected_generation:
                return OwnerWriteResult(
                    "BLOCKED",
                    f"owner generation must be exactly {expected_generation}",
                    chain[-1] if chain else None,
                    len(chain),
                )
            candidate = [*chain, event]
            validate_owner_chain(candidate)
            path = owner_event_path(loop_id, event["generation"])
            if self.client.get(path, self.branch) is not None:
                return OwnerWriteResult("BLOCKED", "owner generation path already exists", chain[-1] if chain else None, len(chain))

            try:
                self.client.create(
                    path,
                    _canonical(event),
                    f"append loop owner {loop_id} generation {event['generation']}",
                    self.branch,
                )
            except Exception:
                # A lost response may follow a successful immutable create.
                # Read the exact generation and complete chain; never resend.
                pass

            created = self.client.get(path, self.branch)
            if created is None:
                return OwnerWriteResult("UNKNOWN", "owner write readback unavailable")
            readback = _decode_content(loop_id, created)
            if readback != event:
                return OwnerWriteResult("UNKNOWN", "owner write readback mismatch", readback)

            recovered = self._read_chain(loop_id)
            if recovered != candidate:
                return OwnerWriteResult("UNKNOWN", "owner chain changed during append", recovered[-1] if recovered else None, len(recovered))
            return OwnerWriteResult("ACCEPTED", "append-only owner generation written and verified", readback, len(recovered))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return OwnerWriteResult("UNKNOWN", str(exc))

    def _read_chain(self, loop_id: str) -> list[dict[str, Any]]:
        prefix = owner_event_path(loop_id, 1).rsplit("/", 1)[0] + "/"
        contents = self.client.list(prefix, self.branch)
        parsed: list[tuple[int, dict[str, Any]]] = []
        seen_paths: set[str] = set()
        for content in contents:
            if content.path in seen_paths:
                raise ValueError("duplicate owner ledger path")
            seen_paths.add(content.path)
            if not content.path.startswith(prefix):
                raise ValueError("owner ledger listing escaped prefix")
            name = content.path[len(prefix):]
            match = _EVENT_FILE.fullmatch(name)
            if match is None:
                raise ValueError("unexpected owner ledger filename")
            generation = int(match.group(1))
            record = _decode_content(loop_id, content)
            if record["generation"] != generation:
                raise ValueError("owner generation/path mismatch")
            if content.path != owner_event_path(loop_id, generation):
                raise ValueError("owner event path is not canonical")
            parsed.append((generation, record))
        parsed.sort(key=lambda item: item[0])
        chain = [record for _, record in parsed]
        if chain:
            validate_owner_chain(chain)
        return chain


def _decode_content(loop_id: str, content: GitHubContent) -> dict[str, Any]:
    record = json.loads(content.text)
    if not isinstance(record, dict):
        raise ValueError("owner event is not a JSON object")
    validate_owner_event(record)
    if record["loop_id"] != loop_id:
        raise ValueError("owner loop/path mismatch")
    return record


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
