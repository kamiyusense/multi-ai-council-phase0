"""Create-only evidence and provider-observation persistence with readback."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .github_backend import GitHubContentsClient
from .loop_owner_observation import provider_observation_path, validate_provider_observation
from .runtime_transition_evidence import validate_evidence_document


@dataclass(frozen=True)
class RecordWriteResult:
    status: str
    reason: str
    path: str | None = None
    record: dict[str, Any] | None = None


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


class _CreateOnlyWriter:
    def __init__(self, client: GitHubContentsClient, *, branch: str):
        if not isinstance(branch, str) or not branch or branch in {"main", "master"}:
            raise ValueError("a non-default data branch is required")
        self.client = client
        self.branch = branch

    def _write(
        self,
        path: str,
        record: dict[str, Any],
        validate: Callable[[dict[str, Any]], Any],
        label: str,
    ) -> RecordWriteResult:
        try:
            validate(record)
            canonical = _canonical(record)
            existing = self.client.get(path, self.branch)
            if existing is not None:
                validate(json.loads(existing.text))
                if existing.text == canonical and json.loads(existing.text) == record:
                    return RecordWriteResult("RECOVERED", "identical append-only record already exists", path, record)
                return RecordWriteResult("BLOCKED", "conflicting or noncanonical record already exists", path)
            try:
                self.client.create(path, canonical, f"append {label} {path}", self.branch)
            except Exception:
                # The write may have succeeded. Read back exactly once; never resend.
                pass
            readback = self.client.get(path, self.branch)
            if readback is None:
                return RecordWriteResult("UNKNOWN", "create result cannot be read back", path)
            validate(json.loads(readback.text))
            if readback.text != canonical or json.loads(readback.text) != record:
                return RecordWriteResult("UNKNOWN", "create readback differs from requested bytes or record", path)
            return RecordWriteResult("ACCEPTED", "append-only record written and verified", path, record)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return RecordWriteResult("UNKNOWN", str(exc), path)


class CanonicalEvidenceGitHubBackend(_CreateOnlyWriter):
    def write(self, document: dict[str, Any]) -> RecordWriteResult:
        try:
            path = validate_evidence_document(document)
        except (ValueError, TypeError, KeyError) as exc:
            return RecordWriteResult("UNKNOWN", str(exc))
        return self._write(path, document, validate_evidence_document, "runtime evidence")


class ProviderObservationGitHubBackend(_CreateOnlyWriter):
    def write(self, observation: dict[str, Any]) -> RecordWriteResult:
        try:
            validate_provider_observation(observation)
            if observation["verified"] is not True:
                raise ValueError("unverified provider observation cannot be published")
            path = provider_observation_path(observation["loop_id"], observation["generation"])
        except (ValueError, TypeError, KeyError) as exc:
            return RecordWriteResult("UNKNOWN", str(exc))
        return self._write(path, observation, validate_provider_observation, "provider observation")
