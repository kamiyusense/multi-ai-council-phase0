"""Create-only durable campaign checkpoints for the hardened Symphony track.

Campaign state is stored as an append-only hash-linked sequence. The store never
blindly retries a create. An ambiguous create is resolved by exact readback; a
fresh controller can restore the latest verified checkpoint without relying on
session memory.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .executor_backend import ExecutorContentsClient
from .symphony_autonomous_runtime import CampaignState


PROTOCOL_VERSION = "SYMPHONY_CAMPAIGN_V1"
CHECKPOINT_TYPE = "SYMPHONY_CAMPAIGN_CHECKPOINT_V1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _path(campaign_id: str, revision: int) -> str:
    if not isinstance(campaign_id, str) or _ID.fullmatch(campaign_id) is None:
        raise ValueError("invalid campaign identity")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("revision must be a positive integer")
    return f"symphony_campaigns/{campaign_id}/states/{revision:08d}.json"


@dataclass(frozen=True)
class CampaignCheckpoint:
    revision: int
    state_digest: str
    previous_state_digest: str | None
    state: CampaignState


@dataclass(frozen=True)
class SaveResult:
    status: str
    revision: int | None = None
    state_digest: str | None = None
    reason: str | None = None


def _record_for(
    state: CampaignState,
    *,
    revision: int,
    previous_revision: int,
    previous_state_digest: str | None,
) -> dict[str, Any]:
    state_record = state.to_dict()
    return {
        "record_type": CHECKPOINT_TYPE,
        "protocol_version": PROTOCOL_VERSION,
        "campaign_id": state.campaign_id,
        "generation": state.generation,
        "revision": revision,
        "previous_revision": previous_revision,
        "previous_state_digest": previous_state_digest,
        "state_digest": _digest(state_record),
        "state": state_record,
    }


def _decode(content_path: str, text: str) -> tuple[dict[str, Any], CampaignCheckpoint]:
    try:
        record = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("malformed campaign checkpoint JSON") from exc
    required = {
        "record_type", "protocol_version", "campaign_id", "generation", "revision",
        "previous_revision", "previous_state_digest", "state_digest", "state",
    }
    if not isinstance(record, dict) or not required <= record.keys():
        raise RuntimeError("incomplete campaign checkpoint")
    if record["record_type"] != CHECKPOINT_TYPE or record["protocol_version"] != PROTOCOL_VERSION:
        raise RuntimeError("wrong campaign checkpoint protocol")
    revision = record["revision"]
    previous_revision = record["previous_revision"]
    if (isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
            or isinstance(previous_revision, bool) or not isinstance(previous_revision, int)
            or previous_revision != revision - 1):
        raise RuntimeError("invalid campaign checkpoint revision")
    if content_path != _path(record["campaign_id"], revision):
        raise RuntimeError("campaign checkpoint path mismatch")
    digest = record["state_digest"]
    previous_digest = record["previous_state_digest"]
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise RuntimeError("invalid campaign checkpoint digest")
    if previous_digest is not None and (
        not isinstance(previous_digest, str) or _DIGEST.fullmatch(previous_digest) is None
    ):
        raise RuntimeError("invalid previous campaign digest")
    if revision == 1 and previous_digest is not None:
        raise RuntimeError("first campaign checkpoint must have no predecessor digest")
    if revision > 1 and previous_digest is None:
        raise RuntimeError("campaign checkpoint predecessor digest missing")
    if not isinstance(record["state"], dict) or _digest(record["state"]) != digest:
        raise RuntimeError("campaign checkpoint state digest mismatch")
    try:
        state = CampaignState.from_dict(record["state"])
    except (TypeError, ValueError, KeyError) as exc:
        raise RuntimeError("invalid durable campaign state") from exc
    if state.campaign_id != record["campaign_id"] or state.generation != record["generation"]:
        raise RuntimeError("campaign checkpoint identity mismatch")
    return record, CampaignCheckpoint(revision, digest, previous_digest, state)


class GitHubCampaignStateStore:
    """Append-only campaign checkpoint store with stale-writer fencing."""

    def __init__(
        self,
        client: ExecutorContentsClient,
        *,
        write_branch: str,
        default_branch: str = "main",
    ):
        if not isinstance(write_branch, str) or not write_branch or write_branch == default_branch:
            raise ValueError("campaign checkpoints require a non-default write branch")
        self.client = client
        self.write_branch = write_branch
        self.default_branch = default_branch

    def _chain(self, campaign_id: str) -> list[CampaignCheckpoint]:
        prefix = f"symphony_campaigns/{campaign_id}/states/"
        contents = self.client.list(prefix, self.write_branch)
        decoded: list[tuple[dict[str, Any], CampaignCheckpoint]] = []
        for content in contents:
            record, checkpoint = _decode(content.path, content.text)
            if record["campaign_id"] != campaign_id:
                raise RuntimeError("campaign checkpoint leaked across campaign identity")
            decoded.append((record, checkpoint))
        decoded.sort(key=lambda item: item[1].revision)
        previous_digest: str | None = None
        previous_generation: int | None = None
        for expected_revision, (record, checkpoint) in enumerate(decoded, start=1):
            if checkpoint.revision != expected_revision:
                raise RuntimeError("campaign checkpoint revision gap")
            if record["previous_revision"] != expected_revision - 1:
                raise RuntimeError("campaign checkpoint predecessor revision mismatch")
            if checkpoint.previous_state_digest != previous_digest:
                raise RuntimeError("campaign checkpoint hash chain mismatch")
            if previous_generation is not None and checkpoint.state.generation < previous_generation:
                raise RuntimeError("campaign generation moved backwards")
            previous_digest = checkpoint.state_digest
            previous_generation = checkpoint.state.generation
        return [checkpoint for _, checkpoint in decoded]

    def restore(self, campaign_id: str) -> CampaignCheckpoint | None:
        if not isinstance(campaign_id, str) or _ID.fullmatch(campaign_id) is None:
            raise ValueError("invalid campaign identity")
        chain = self._chain(campaign_id)
        return chain[-1] if chain else None

    def save(self, state: CampaignState, *, expected_revision: int) -> SaveResult:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("expected_revision must be a non-negative integer")
        try:
            chain = self._chain(state.campaign_id)
        except Exception as exc:
            return SaveResult("UNKNOWN", reason=f"campaign readback unavailable: {type(exc).__name__}")
        latest = chain[-1] if chain else None
        actual_revision = latest.revision if latest else 0
        if actual_revision != expected_revision:
            return SaveResult(
                "CONFLICT", actual_revision,
                latest.state_digest if latest else None,
                "stale campaign checkpoint revision",
            )
        revision = expected_revision + 1
        previous_digest = latest.state_digest if latest else None
        record = _record_for(
            state,
            revision=revision,
            previous_revision=expected_revision,
            previous_state_digest=previous_digest,
        )
        path = _path(state.campaign_id, revision)
        text = _canonical(record)
        try:
            if self.client.get(path, self.write_branch) is not None:
                return SaveResult("CONFLICT", revision, reason="checkpoint path already exists")
            self.client.create(
                path,
                text,
                f"append Symphony campaign {state.campaign_id} checkpoint {revision}",
                self.write_branch,
            )
        except Exception:
            # Ambiguous create: read back once and never resend.
            try:
                found = self.client.get(path, self.write_branch)
                if found is not None and found.text == text:
                    return SaveResult("ACCEPTED", revision, record["state_digest"])
            except Exception:
                pass
            return SaveResult(
                "AMBIGUOUS", revision, record["state_digest"],
                "checkpoint create outcome could not be verified",
            )
        try:
            found = self.client.get(path, self.write_branch)
            if found is not None and found.text == text:
                return SaveResult("ACCEPTED", revision, record["state_digest"])
        except Exception:
            pass
        return SaveResult(
            "AMBIGUOUS", revision, record["state_digest"],
            "checkpoint post-write readback did not verify exact content",
        )
