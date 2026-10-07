"""Append-only durable execution-attempt evidence for autonomous campaigns.

This store is deliberately separate from the Phase-0 PREPARE_ONLY executor
ledger. It records an attempt's durable intent, observed start, and terminal
evidence but never starts a provider/model itself.

Every record is create-only. A write exception is resolved by exact readback
once and is never blindly resent.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .executor_backend import ExecutorContentsClient


class AttemptLineageError(RuntimeError):
    """Invalid durable evidence, distinct from a transient transport read failure."""


PROTOCOL_VERSION = "SYMPHONY_AUTONOMOUS_ATTEMPT_V1"
INTENT_TYPE = "SYMPHONY_AUTONOMOUS_ATTEMPT_INTENT_V1"
STARTED_TYPE = "SYMPHONY_AUTONOMOUS_ATTEMPT_STARTED_V1"
TERMINAL_TYPE = "SYMPHONY_AUTONOMOUS_ATTEMPT_TERMINAL_V1"
RETIRED_TYPE = "SYMPHONY_AUTONOMOUS_ATTEMPT_RETIRED_V1"
OBSERVATION_TYPE = "SYMPHONY_AUTONOMOUS_ATTEMPT_OBSERVATION_V1"

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL_OUTCOMES = {"DONE", "FAILED", "BLOCKED", "UNKNOWN", "STALE"}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")
    return value


def make_attempt_id(
    *,
    campaign_id: str,
    task_id: str,
    generation: int,
    attempt_number: int,
    expected_target_head: str,
) -> str:
    """Return a path-safe deterministic identity for one logical task attempt."""
    _safe_id(campaign_id, "campaign identity")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("invalid task identity")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("generation must be a positive integer")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number < 1:
        raise ValueError("attempt_number must be a positive integer")
    if not isinstance(expected_target_head, str) or not expected_target_head:
        raise ValueError("expected_target_head must be non-empty")
    identity = {
        "campaign_id": campaign_id,
        "task_id": task_id,
        "generation": generation,
        "attempt_number": attempt_number,
        "expected_target_head": expected_target_head,
    }
    return "attempt-" + hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()[:32]


def _path(campaign_id: str, attempt_id: str, kind: str) -> str:
    _safe_id(campaign_id, "campaign identity")
    _safe_id(attempt_id, "attempt identity")
    if kind not in {"intent", "started", "terminal", "retired"} and re.fullmatch(r"observation-[0-9]{8}", kind) is None:
        raise ValueError("invalid attempt record kind")
    return f"symphony_attempts/{campaign_id}/{attempt_id}/{kind}.json"


@dataclass(frozen=True)
class AttemptIdentity:
    campaign_id: str
    task_id: str
    attempt_id: str
    generation: int
    attempt_number: int
    expected_target_head: str
    expected_target_tree: str | None
    runner_generation: int


@dataclass(frozen=True)
class AttemptSnapshot:
    state: str
    identity: AttemptIdentity
    intent: dict[str, Any]
    started: dict[str, Any] | None = None
    terminal: dict[str, Any] | None = None
    retired: dict[str, Any] | None = None


@dataclass(frozen=True)
class AttemptWriteResult:
    status: str
    attempt_id: str
    kind: str
    reason: str | None = None


def _validate_identity(record: dict[str, Any]) -> AttemptIdentity:
    campaign_id = _safe_id(record.get("campaign_id"), "campaign identity")
    attempt_id = _safe_id(record.get("attempt_id"), "attempt identity")
    task_id = record.get("task_id")
    generation = record.get("generation")
    attempt_number = record.get("attempt_number")
    target_head = record.get("expected_target_head")
    target_tree = record.get("expected_target_tree")
    runner_generation = record.get("runner_generation")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("invalid task identity")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("invalid attempt generation")
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number < 1:
        raise ValueError("invalid attempt number")
    if not isinstance(target_head, str) or not target_head:
        raise ValueError("invalid expected target head")
    if target_tree is not None and not isinstance(target_tree, str):
        raise ValueError("invalid expected target tree")
    if isinstance(runner_generation, bool) or not isinstance(runner_generation, int) or runner_generation < 1:
        raise ValueError("invalid runner generation")
    expected_attempt_id = make_attempt_id(
        campaign_id=campaign_id,
        task_id=task_id,
        generation=generation,
        attempt_number=attempt_number,
        expected_target_head=target_head,
    )
    if attempt_id != expected_attempt_id:
        raise ValueError("attempt identity digest mismatch")
    return AttemptIdentity(
        campaign_id, task_id, attempt_id, generation, attempt_number,
        target_head, target_tree, runner_generation,
    )


def _validate_record(record: dict[str, Any], *, kind: str) -> AttemptIdentity:
    if not isinstance(record, dict):
        raise ValueError("attempt record must be an object")
    validation_kind = "observation" if kind.startswith("observation-") else kind
    expected_type = {
        "intent": INTENT_TYPE,
        "started": STARTED_TYPE,
        "terminal": TERMINAL_TYPE,
        "retired": RETIRED_TYPE,
        "observation": OBSERVATION_TYPE,
    }[validation_kind]
    if (
        record.get("protocol_version") != PROTOCOL_VERSION
        or record.get("record_type") != expected_type
    ):
        raise ValueError("wrong autonomous attempt protocol")
    identity = _validate_identity(record)
    if validation_kind == "observation":
        number = record.get("observation_number")
        if type(number) is not int or number < 1 or kind != f"observation-{number:08d}":
            raise ValueError("invalid observation sequence")
    if kind == "intent":
        scope_digest = record.get("scope_digest")
        if not isinstance(scope_digest, str) or _DIGEST.fullmatch(scope_digest) is None:
            raise ValueError("invalid attempt scope digest")
        if record.get("dispatch_authorized") is not False:
            raise ValueError("durable intent must not authorize LIVE dispatch")
        if not isinstance(record.get("scope"), dict) or _digest(record["scope"]) != scope_digest:
            raise ValueError("attempt scope digest mismatch")
    elif kind == "retired":
        if not isinstance(record.get("intent_digest"), str) or _DIGEST.fullmatch(record["intent_digest"]) is None:
            raise ValueError("invalid retirement predecessor")
        proof = record.get("fence_proof")
        if (not isinstance(proof, dict) or proof.get("attempt_id") != identity.attempt_id
                or proof.get("runner_generation") != identity.runner_generation
                or type(proof.get("runner_generation")) is not int
                or proof.get("state") not in {"STOPPED", "FENCED"}
                or not isinstance(proof.get("evidence_ref"), str) or not proof["evidence_ref"]):
            raise ValueError("invalid bound stop/fence proof")
    elif kind == "started":
        predecessor = record.get("intent_digest")
        if not isinstance(predecessor, str) or _DIGEST.fullmatch(predecessor) is None:
            raise ValueError("invalid attempt intent digest")
        if record.get("start_observed") is not True:
            raise ValueError("STARTED record requires observed start")
        for field in ("provider_kind", "provider_attempt_ref"):
            if not isinstance(record.get(field), str) or not record[field]:
                raise ValueError(f"invalid attempt {field}")
        if record.get("observation_source") not in {"STATIC_SIMULATION", "LIVE_OBSERVATION"}:
            raise ValueError("invalid attempt observation source")
        for field in ("thread_id", "turn_id", "workspace_fingerprint"):
            value = record.get(field)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"invalid attempt {field}")
    else:
        predecessor = record.get("predecessor_digest")
        if not isinstance(predecessor, str) or _DIGEST.fullmatch(predecessor) is None:
            raise ValueError("invalid terminal predecessor digest")
        outcome = record.get("outcome")
        if outcome not in _TERMINAL_OUTCOMES:
            raise ValueError("invalid attempt terminal outcome")
        unknown_class = record.get("unknown_class")
        if outcome == "UNKNOWN":
            if unknown_class not in {"TRANSIENT_UNKNOWN", "RECOVERABLE_UNKNOWN", "TASK_BLOCKED", "HARD_UNKNOWN"}:
                raise ValueError("UNKNOWN terminal requires unknown_class")
        elif unknown_class is not None:
            raise ValueError("unknown_class requires UNKNOWN outcome")
        if type(record.get("affects_campaign_authority", False)) is not bool:
            raise ValueError("invalid terminal authority scope")
        result_id = record.get("result_id")
        if not isinstance(result_id, str) or not result_id:
            raise ValueError("invalid attempt terminal result id")
        model_started = record.get("model_started")
        if model_started is not None and type(model_started) is not bool:
            raise ValueError("invalid model_started certainty")
        if not isinstance(record.get("evidence_refs"), list) or any(
            not isinstance(item, str) or not item for item in record["evidence_refs"]
        ):
            raise ValueError("invalid terminal evidence refs")
    return identity


def _decode(path: str, text: str, *, kind: str) -> tuple[dict[str, Any], AttemptIdentity]:
    try:
        record = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AttemptLineageError("malformed autonomous attempt record") from exc
    try:
        identity = _validate_record(record, kind=kind)
    except ValueError as exc:
        raise AttemptLineageError(str(exc)) from exc
    if path != _path(identity.campaign_id, identity.attempt_id, kind):
        raise AttemptLineageError("autonomous attempt path mismatch")
    return record, identity


def _same_identity(expected: AttemptIdentity, actual: AttemptIdentity) -> bool:
    return expected == actual


class GitHubAutonomousAttemptStore:
    """Create-only attempt evidence with predecessor and replay validation."""

    def __init__(
        self,
        client: ExecutorContentsClient,
        *,
        write_branch: str,
        default_branch: str = "main",
    ):
        if not isinstance(write_branch, str) or not write_branch or write_branch == default_branch:
            raise ValueError("attempt evidence requires a non-default write branch")
        self.client = client
        self.write_branch = write_branch
        self.default_branch = default_branch

    def _get(self, campaign_id: str, attempt_id: str, kind: str) -> tuple[dict[str, Any], AttemptIdentity] | None:
        path = _path(campaign_id, attempt_id, kind)
        content = self.client.get(path, self.write_branch)
        if content is None:
            return None
        return _decode(content.path, content.text, kind=kind)

    def _append(self, record: dict[str, Any], *, kind: str) -> AttemptWriteResult:
        identity = _validate_record(record, kind=kind)
        path = _path(identity.campaign_id, identity.attempt_id, kind)
        text = _canonical(record)
        try:
            if self.client.get(path, self.write_branch) is not None:
                return AttemptWriteResult("CONFLICT", identity.attempt_id, kind, "record already exists")
            self.client.create(
                path,
                text,
                f"append Symphony attempt {kind} {identity.attempt_id}",
                self.write_branch,
            )
        except Exception:
            try:
                found = self.client.get(path, self.write_branch)
                if found is not None and found.text == text:
                    return AttemptWriteResult("ACCEPTED", identity.attempt_id, kind)
            except Exception:
                pass
            return AttemptWriteResult(
                "AMBIGUOUS", identity.attempt_id, kind,
                "attempt write outcome could not be verified",
            )
        try:
            found = self.client.get(path, self.write_branch)
            if found is not None and found.text == text:
                return AttemptWriteResult("ACCEPTED", identity.attempt_id, kind)
        except Exception:
            pass
        return AttemptWriteResult(
            "AMBIGUOUS", identity.attempt_id, kind,
            "attempt post-write readback did not verify exact content",
        )

    def append_intent(
        self,
        *,
        campaign_id: str,
        task_id: str,
        generation: int,
        attempt_number: int,
        expected_target_head: str,
        runner_generation: int,
        scope: dict[str, Any],
        expected_target_tree: str | None = None,
    ) -> AttemptWriteResult:
        if not isinstance(scope, dict):
            raise ValueError("attempt scope must be an object")
        attempt_id = make_attempt_id(
            campaign_id=campaign_id,
            task_id=task_id,
            generation=generation,
            attempt_number=attempt_number,
            expected_target_head=expected_target_head,
        )
        record = {
            "record_type": INTENT_TYPE,
            "protocol_version": PROTOCOL_VERSION,
            "campaign_id": campaign_id,
            "task_id": task_id,
            "attempt_id": attempt_id,
            "generation": generation,
            "attempt_number": attempt_number,
            "expected_target_head": expected_target_head,
            "expected_target_tree": expected_target_tree,
            "runner_generation": runner_generation,
            "scope_digest": _digest(scope),
            "scope": scope,
            # This ledger records authorization decisions made elsewhere. Merely
            # creating an intent record must never become LIVE authorization.
            "dispatch_authorized": False,
        }
        return self._append(record, kind="intent")

    def append_started(
        self,
        *,
        campaign_id: str,
        attempt_id: str,
        provider_kind: str,
        provider_attempt_ref: str,
        observation_source: str,
        thread_id: str | None = None,
        turn_id: str | None = None,
        workspace_fingerprint: str | None = None,
    ) -> AttemptWriteResult:
        intent_pair = self._get(campaign_id, attempt_id, "intent")
        if intent_pair is None:
            return AttemptWriteResult("CONFLICT", attempt_id, "started", "attempt intent missing")
        if self._get(campaign_id, attempt_id, "terminal") is not None:
            return AttemptWriteResult("CONFLICT", attempt_id, "started", "attempt already terminal")
        if self._get(campaign_id, attempt_id, "retired") is not None:
            return AttemptWriteResult("CONFLICT", attempt_id, "started", "attempt retired")
        intent, identity = intent_pair
        record = {
            "record_type": STARTED_TYPE,
            "protocol_version": PROTOCOL_VERSION,
            **{
                "campaign_id": identity.campaign_id,
                "task_id": identity.task_id,
                "attempt_id": identity.attempt_id,
                "generation": identity.generation,
                "attempt_number": identity.attempt_number,
                "expected_target_head": identity.expected_target_head,
                "expected_target_tree": identity.expected_target_tree,
                "runner_generation": identity.runner_generation,
            },
            "intent_digest": _digest(intent),
            "start_observed": True,
            "provider_kind": provider_kind,
            "provider_attempt_ref": provider_attempt_ref,
            "observation_source": observation_source,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "workspace_fingerprint": workspace_fingerprint,
        }
        return self._append(record, kind="started")

    def append_terminal(
        self,
        *,
        campaign_id: str,
        attempt_id: str,
        result_id: str,
        outcome: str,
        model_started: bool | None,
        evidence_refs: list[str] | tuple[str, ...] = (),
        unknown_class: str | None = None,
        affects_campaign_authority: bool = False,
    ) -> AttemptWriteResult:
        intent_pair = self._get(campaign_id, attempt_id, "intent")
        if intent_pair is None:
            return AttemptWriteResult("CONFLICT", attempt_id, "terminal", "attempt intent missing")
        intent, identity = intent_pair
        if self._get(campaign_id, attempt_id, "retired") is not None:
            return AttemptWriteResult("CONFLICT", attempt_id, "terminal", "attempt retired")
        started_pair = self._get(campaign_id, attempt_id, "started")
        if started_pair is not None and model_started is False:
            raise ValueError("terminal contradicts observed start")
        if model_started is True and started_pair is None:
            return AttemptWriteResult(
                "CONFLICT", attempt_id, "terminal",
                "model-started terminal result requires STARTED evidence",
            )
        predecessor = started_pair[0] if started_pair is not None else intent
        record = {
            "record_type": TERMINAL_TYPE,
            "protocol_version": PROTOCOL_VERSION,
            **{
                "campaign_id": identity.campaign_id,
                "task_id": identity.task_id,
                "attempt_id": identity.attempt_id,
                "generation": identity.generation,
                "attempt_number": identity.attempt_number,
                "expected_target_head": identity.expected_target_head,
                "expected_target_tree": identity.expected_target_tree,
                "runner_generation": identity.runner_generation,
            },
            "predecessor_digest": _digest(predecessor),
            "result_id": result_id,
            "outcome": outcome,
            "model_started": model_started,
            "evidence_refs": list(evidence_refs),
            "unknown_class": unknown_class,
            "affects_campaign_authority": affects_campaign_authority,
        }
        return self._append(record, kind="terminal")

    def retire_unstarted(self, campaign_id: str, attempt_id: str, *, fence_proof: dict[str, Any]) -> AttemptWriteResult:
        snapshot = self.restore(campaign_id, attempt_id)
        if snapshot is None or snapshot.state != "CLAIMED_UNSTARTED" or snapshot.retired is not None:
            return AttemptWriteResult("CONFLICT", attempt_id, "retired", "attempt is not unstarted")
        record = {
            **{k: snapshot.intent[k] for k in (
                "campaign_id", "task_id", "attempt_id", "generation", "attempt_number",
                "expected_target_head", "expected_target_tree", "runner_generation",
            )},
            "record_type": RETIRED_TYPE, "protocol_version": PROTOCOL_VERSION,
            "intent_digest": _digest(snapshot.intent), "fence_proof": dict(fence_proof),
        }
        return self._append(record, kind="retired")

    def append_observation(
        self, campaign_id: str, attempt_id: str, *, result_id: str, outcome: str,
        unknown_class: str | None = None, affects_campaign_authority: bool = False,
        evidence_refs: list[str] | tuple[str, ...] = (),
    ) -> AttemptWriteResult:
        """Append read-only recovery evidence; never overwrite a terminal record."""
        snapshot = self.restore(campaign_id, attempt_id)
        if (snapshot is None or snapshot.terminal is None
                or snapshot.terminal["outcome"] != "UNKNOWN"
                or snapshot.terminal.get("unknown_class") != "TRANSIENT_UNKNOWN"):
            return AttemptWriteResult("CONFLICT", attempt_id, "observation", "attempt not awaiting observation")
        previous = snapshot.terminal
        if result_id == previous["result_id"]:
            return AttemptWriteResult("CONFLICT", attempt_id, "observation", "duplicate observation result id")
        number = previous.get("observation_number", 0) + 1
        record = {
            **{k: snapshot.intent[k] for k in (
                "campaign_id", "task_id", "attempt_id", "generation", "attempt_number",
                "expected_target_head", "expected_target_tree", "runner_generation",
            )},
            "record_type": OBSERVATION_TYPE, "protocol_version": PROTOCOL_VERSION,
            "predecessor_digest": _digest(previous), "observation_number": number,
            "result_id": result_id, "outcome": outcome,
            "model_started": previous["model_started"], "evidence_refs": list(evidence_refs),
            "unknown_class": unknown_class, "affects_campaign_authority": affects_campaign_authority,
        }
        return self._append(record, kind=f"observation-{number:08d}")

    def restore(self, campaign_id: str, attempt_id: str) -> AttemptSnapshot | None:
        intent_pair = self._get(campaign_id, attempt_id, "intent")
        if intent_pair is None:
            return None
        intent, identity = intent_pair
        started_pair = self._get(campaign_id, attempt_id, "started")
        terminal_pair = self._get(campaign_id, attempt_id, "terminal")
        retired_pair = self._get(campaign_id, attempt_id, "retired")
        started = None
        terminal = None
        prefix = f"symphony_attempts/{campaign_id}/{attempt_id}/"
        observations = sorted(
            (c for c in self.client.list(prefix, self.write_branch)
             if c.path.rsplit("/", 1)[-1].startswith("observation-")),
            key=lambda c: c.path,
        )
        if observations and terminal_pair is None:
            raise AttemptLineageError("observation evidence has no terminal predecessor")
        if retired_pair is not None:
            retired, retired_identity = retired_pair
            if (retired_identity != identity or retired["intent_digest"] != _digest(intent)
                    or started_pair is not None or terminal_pair is not None or observations):
                raise AttemptLineageError("invalid retirement lineage")
            return AttemptSnapshot("CLAIMED_UNSTARTED", identity, intent, retired=retired)

        if started_pair is not None:
            started, started_identity = started_pair
            if not _same_identity(identity, started_identity):
                raise AttemptLineageError("attempt STARTED identity mismatch")
            if started["intent_digest"] != _digest(intent):
                raise AttemptLineageError("attempt STARTED predecessor mismatch")

        if terminal_pair is not None:
            terminal, terminal_identity = terminal_pair
            if not _same_identity(identity, terminal_identity):
                raise AttemptLineageError("attempt terminal identity mismatch")
            predecessor = started if started is not None else intent
            if terminal["predecessor_digest"] != _digest(predecessor):
                raise AttemptLineageError("attempt terminal predecessor mismatch")
            if terminal["model_started"] is True and started is None:
                raise AttemptLineageError("attempt terminal claims unproven model start")
            if started is not None and terminal["model_started"] is False:
                raise AttemptLineageError("terminal contradicts observed start")
            for number, content in enumerate(observations, 1):
                kind = f"observation-{number:08d}"
                observed, observed_identity = _decode(content.path, content.text, kind=kind)
                if (observed_identity != identity or observed["predecessor_digest"] != _digest(terminal)
                        or terminal["outcome"] != "UNKNOWN"
                        or terminal.get("unknown_class") != "TRANSIENT_UNKNOWN"
                        or observed["model_started"] != terminal["model_started"]):
                    raise AttemptLineageError("invalid observation evidence lineage")
                terminal = observed
            return AttemptSnapshot("TERMINAL", identity, intent, started, terminal)

        if started is not None:
            return AttemptSnapshot("STARTED_UNRESOLVED", identity, intent, started, None)
        return AttemptSnapshot("CLAIMED_UNSTARTED", identity, intent, None, None)

    def list_campaign(self, campaign_id: str) -> list[AttemptSnapshot]:
        _safe_id(campaign_id, "campaign identity")
        prefix = f"symphony_attempts/{campaign_id}/"
        attempts: set[str] = set()
        for content in self.client.list(prefix, self.write_branch):
            parts = content.path.split("/")
            if (len(parts) != 4 or parts[0] != "symphony_attempts" or parts[1] != campaign_id
                    or (parts[3] not in {"intent.json", "started.json", "terminal.json", "retired.json"}
                        and re.fullmatch(r"observation-[0-9]{8}\.json", parts[3]) is None)):
                raise AttemptLineageError("autonomous attempt listing path mismatch")
            attempts.add(_safe_id(parts[2], "attempt identity"))
        output = []
        for attempt_id in sorted(attempts):
            restored = self.restore(campaign_id, attempt_id)
            if restored is None:
                raise AttemptLineageError("attempt record set has no intent")
            output.append(restored)
        return output


def attempt_recovery_action(
    snapshot: AttemptSnapshot,
    *,
    old_attempt_stopped_or_fenced: bool,
    independent_safe_work: bool,
) -> str:
    """Classify restart behavior without authorizing any provider operation."""
    if type(old_attempt_stopped_or_fenced) is not bool or type(independent_safe_work) is not bool:
        raise ValueError("attempt recovery evidence must be boolean")
    if snapshot.state == "TERMINAL":
        return "APPLY_TERMINAL_RESULT"
    if snapshot.state == "STARTED_UNRESOLVED":
        return "ISOLATE_TASK_CONTINUE" if independent_safe_work else "STOP_UNRESOLVED_ATTEMPT"
    if snapshot.state == "CLAIMED_UNSTARTED":
        if old_attempt_stopped_or_fenced:
            return "RECLAIM_ALLOWED"
        return "ISOLATE_TASK_CONTINUE" if independent_safe_work else "STOP_UNFENCED_ATTEMPT"
    raise ValueError("unknown attempt snapshot state")
