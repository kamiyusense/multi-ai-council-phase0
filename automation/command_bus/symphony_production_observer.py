"""Authenticated, observation-only ingress for a pinned Symphony worker hook.

Official Symphony owns worker lifecycle. This module neither starts workers
nor adopts their Git changes. A MAC authenticates the local event producer; durable writes
still use the existing create-only attempt store and its exact readback.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

from .symphony_attempt_store import AttemptWriteResult, GitHubAutonomousAttemptStore, make_attempt_id


PROTOCOL = "SYMPHONY_G5_WORKER_OBSERVATION_V1"


@dataclass(frozen=True)
class ObservedIssue:
    task_id: str
    generation: int
    expected_target_head: str
    runner_generation: int
    scope: dict[str, Any]


class SymphonyProductionObserver:
    """Consume one signed local hook event without controlling upstream work."""

    def __init__(self, store: GitHubAutonomousAttemptStore, *, campaign_id: str,
                 issues: dict[str, ObservedIssue], key: bytes):
        if type(store) is not GitHubAutonomousAttemptStore or not campaign_id:
            raise ValueError("invalid production observation store/campaign")
        if not issues or any(not issue_id or type(bound) is not ObservedIssue
                             for issue_id, bound in issues.items()):
            raise ValueError("explicit issue-to-campaign binding required")
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("observation MAC key must contain at least 32 bytes")
        self.store = store
        self.campaign_id = campaign_id
        self.issues = issues
        self.key = key

    def capture_line(self, line: str) -> AttemptWriteResult:
        """Validate an exact signed JSONL envelope, then append ledger evidence.

        The caller must feed a local hook-owned stream. The signature is checked
        before any lookup/write. Malformed or unrelated events stay isolated.
        """
        try:
            envelope = json.loads(line)
            if type(envelope) is not dict or set(envelope) != {"payload_json", "mac"}:
                raise ValueError("invalid envelope")
            payload_json, mac = envelope["payload_json"], envelope["mac"]
            if type(payload_json) is not str or type(mac) is not str or len(mac) != 64:
                raise ValueError("invalid signed payload")
            expected_mac = hmac.new(self.key, payload_json.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(mac, expected_mac):
                raise ValueError("observation MAC mismatch")
            payload = json.loads(payload_json)
            if type(payload) is not dict or set(payload) != {
                "protocol", "issue_id", "attempt_number", "worker_run_id",
                "kind", "workspace", "status",
            } or payload["protocol"] != PROTOCOL:
                raise ValueError("invalid observation payload")
            issue_id = payload["issue_id"]
            if type(issue_id) is not str or issue_id not in self.issues:
                raise ValueError("unbound issue")
            attempt_number = payload["attempt_number"]
            worker_run_id = payload["worker_run_id"]
            kind = payload["kind"]
            workspace = payload["workspace"]
            status = payload["status"]
            if (type(worker_run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", worker_run_id) is None
                    or type(attempt_number) is not int
                    or attempt_number != int(worker_run_id[:15], 16) + 1
                    or type(workspace) is not str or not workspace.startswith("/")
                    or kind not in {"STARTED", "TERMINAL", "WORKER_UPDATE", "RETRY_SCHEDULED", "STALLED", "STATUS_AVAILABLE"}
                    or status not in {"RUNNING", "WORKER_COMPLETED", "WORKER_FAILED", "WORKER_STOPPED"}):
                raise ValueError("invalid worker observation fields")
            if (kind == "STARTED" and status != "RUNNING") or (kind == "TERMINAL" and status == "RUNNING"):
                raise ValueError("inconsistent worker observation")
        except (TypeError, ValueError, UnicodeError) as exc:
            return AttemptWriteResult("CONFLICT", "unbound", "observation", str(exc))

        bound = self.issues[issue_id]
        attempt_id = make_attempt_id(
            campaign_id=self.campaign_id, task_id=bound.task_id,
            generation=bound.generation, attempt_number=attempt_number,
            expected_target_head=bound.expected_target_head,
        )
        if kind not in {"STARTED", "TERMINAL"}:
            return AttemptWriteResult("READ_ONLY", attempt_id, kind, "upstream scheduler retains authority")
        evidence_ref = "sym-g5:sha256:" + hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        snapshot = self.store.restore(self.campaign_id, attempt_id)
        if kind == "STARTED":
            if snapshot is None:
                intent = self.store.append_intent(
                    campaign_id=self.campaign_id, task_id=bound.task_id,
                    generation=bound.generation, attempt_number=attempt_number,
                    expected_target_head=bound.expected_target_head,
                    runner_generation=bound.runner_generation, scope=bound.scope,
                )
                if intent.status != "ACCEPTED":
                    return intent
                snapshot = self.store.restore(self.campaign_id, attempt_id)
            if snapshot is None:
                return AttemptWriteResult("AMBIGUOUS", attempt_id, "started", "intent readback unavailable")
            if snapshot.identity.runner_generation != bound.runner_generation or snapshot.intent["scope"] != bound.scope:
                return AttemptWriteResult("CONFLICT", attempt_id, "started", "attempt binding changed")
            if snapshot.started is not None:
                same = (snapshot.started["provider_attempt_ref"] == worker_run_id
                        and snapshot.started["workspace_fingerprint"] == hashlib.sha256(workspace.encode()).hexdigest()
                        and snapshot.started["observation_source"] == "LIVE_OBSERVATION")
                return AttemptWriteResult("NOOP_DUPLICATE" if same else "CONFLICT", attempt_id, "started")
            if snapshot.terminal is not None or snapshot.retired is not None:
                return AttemptWriteResult("CONFLICT", attempt_id, "started", "attempt already closed")
            return self.store.append_started(
                campaign_id=self.campaign_id, attempt_id=attempt_id,
                provider_kind="OFFICIAL_SYMPHONY_CODEX",
                provider_attempt_ref=worker_run_id,
                observation_source="LIVE_OBSERVATION",
                workspace_fingerprint=hashlib.sha256(workspace.encode()).hexdigest(),
            )

        if snapshot is None or snapshot.started is None:
            return AttemptWriteResult("CONFLICT", attempt_id, "terminal", "STARTED evidence missing")
        if (snapshot.started["provider_attempt_ref"] != worker_run_id
                or snapshot.started["workspace_fingerprint"] != hashlib.sha256(workspace.encode()).hexdigest()
                or snapshot.started["observation_source"] != "LIVE_OBSERVATION"):
            return AttemptWriteResult("CONFLICT", attempt_id, "terminal", "worker binding mismatch")
        # A finished worker is not proof that its tracker task is complete.
        # The terminal is intentionally UNKNOWN until G6 result adoption.
        result_id = "sym-g5-worker:" + worker_run_id
        if snapshot.terminal is not None:
            same = (snapshot.terminal["result_id"] == result_id
                    and snapshot.terminal["outcome"] == "UNKNOWN"
                    and snapshot.terminal["unknown_class"] == "RECOVERABLE_UNKNOWN"
                    and snapshot.terminal["evidence_refs"] == [evidence_ref, "sym-g5-status:" + status])
            return AttemptWriteResult("NOOP_DUPLICATE" if same else "CONFLICT", attempt_id, "terminal")
        return self.store.append_terminal(
            campaign_id=self.campaign_id, attempt_id=attempt_id,
            result_id=result_id, outcome="UNKNOWN", unknown_class="RECOVERABLE_UNKNOWN",
            model_started=None, evidence_refs=[evidence_ref, "sym-g5-status:" + status],
        )

    def replay_file(self, path: str) -> list[AttemptWriteResult]:
        """Replay complete signed lines after a reader restart; duplicates are safe."""
        results = []
        with open(path, "r", encoding="utf-8") as source:
            for line in source:
                if not line.endswith("\n"):
                    break  # producer may be midway through its final append
                results.append(self.capture_line(line))
        return results
