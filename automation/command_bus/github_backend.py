"""GitHub Contents-style durable persistence for reviewer records.

The client protocol is deliberately tiny. Production controllers provide the
connected GitHub transport; tests use a deterministic fake. Reviewer records
are append-only. Only loop state may be updated. Every write is followed by an
independent readback; an unverifiable write returns UNKNOWN and is never
retried automatically.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .reviewer import ReviewerLedger, ReviewResult
from .state_machine import StateMachine

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PREFIXES = {
    "request": "review_requests",
    "claim": "review_claims",
    "response": "review_responses",
    "receipt": "review_receipts",
}
_IDS = {
    "request": "request_id",
    "claim": "claim_id",
    "response": "response_id",
    "receipt": "receipt_id",
}


@dataclass(frozen=True)
class GitHubContent:
    path: str
    text: str
    sha: str


class GitHubContentsClient(Protocol):
    """Minimal transport implemented by the controller's connected GitHub."""

    def get(self, path: str, ref: str) -> GitHubContent | None: ...
    def list(self, prefix: str, ref: str) -> list[GitHubContent]: ...
    def create(self, path: str, text: str, message: str, branch: str) -> GitHubContent: ...
    def update(self, path: str, text: str, sha: str, message: str, branch: str) -> GitHubContent: ...


def record_path(kind: str, loop_id: str, record_id: str) -> str:
    if kind not in _PREFIXES:
        raise ValueError("unknown reviewer record kind")
    _safe_component(loop_id, "loop_id")
    _safe_component(record_id, _IDS[kind])
    return f"{_PREFIXES[kind]}/{loop_id}/{record_id}.json"


def state_path(loop_id: str) -> str:
    _safe_component(loop_id, "loop_id")
    return f"state/{loop_id}.json"


class GitHubRecordBackend:
    def __init__(self, client: GitHubContentsClient, *, branch: str, ref: str | None = None):
        self.client = client
        self.branch = branch
        self.ref = ref or branch

    def append(self, kind: str, loop_id: str, record: dict[str, Any]) -> ReviewResult:
        """Append one immutable record and verify it by independent branch readback."""
        try:
            _validate_record(kind, loop_id, record)
            _validate_references_for_append(self, kind, loop_id, record)
            record_id = record[_IDS[kind]]
            path = record_path(kind, loop_id, record_id)
            if self.client.get(path, self.branch) is not None:
                return ReviewResult("BLOCKED", "duplicate durable record")
            self.client.create(
                path,
                _canonical(record),
                f"append reviewer {kind} {record_id}",
                self.branch,
            )
            verified = self.client.get(path, self.branch)
            if verified is None:
                return ReviewResult("UNKNOWN", "write readback unavailable")
            readback = _decode_record(kind, loop_id, record_id, verified)
            if readback != record:
                return ReviewResult("UNKNOWN", "write readback mismatch", readback)
            return ReviewResult("ACCEPTED", "append-only record written and verified", readback)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))

    def read(self, kind: str, loop_id: str, record_id: str) -> ReviewResult:
        try:
            content = self.client.get(record_path(kind, loop_id, record_id), self.ref)
            if content is None:
                return ReviewResult("UNKNOWN", "durable record missing")
            record = _decode_record(kind, loop_id, record_id, content)
            return ReviewResult("READ", "durable record read", record)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))

    def write_state(self, loop_id: str, state: dict[str, Any]) -> ReviewResult:
        """Create/update mutable state using current branch SHA, then verify."""
        try:
            _validate_state(loop_id, state)
            path = state_path(loop_id)
            text = _canonical(state)
            current = self.client.get(path, self.branch)
            if current is None:
                self.client.create(path, text, f"create reviewer state {loop_id}", self.branch)
            else:
                self.client.update(
                    path, text, current.sha, f"update reviewer state {loop_id}", self.branch
                )
            verified = self.client.get(path, self.branch)
            if verified is None:
                return ReviewResult("UNKNOWN", "state write readback unavailable")
            readback = json.loads(verified.text)
            _validate_state(loop_id, readback)
            if readback != state:
                return ReviewResult("UNKNOWN", "state write readback mismatch", readback)
            return ReviewResult("ACCEPTED", "mutable state written and verified", readback)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))

    def read_state(self, loop_id: str) -> ReviewResult:
        try:
            content = self.client.get(state_path(loop_id), self.ref)
            if content is None:
                return ReviewResult("UNKNOWN", "durable state missing")
            state = json.loads(content.text)
            _validate_state(loop_id, state)
            return ReviewResult("READ", "durable state read", state)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))

    def recover(
        self, loop_id: str, *, expected_ids: dict[str, list[str]] | None = None
    ) -> ReviewResult:
        """Reconstruct a fresh ledger from durable records and validate the graph."""
        state_result = self.read_state(loop_id)
        if state_result.status != "READ":
            return state_result
        records: dict[str, list[dict[str, Any]]] = {kind: [] for kind in _PREFIXES}
        try:
            for kind, prefix in _PREFIXES.items():
                contents = self.client.list(f"{prefix}/{loop_id}/", self.ref)
                for content in sorted(contents, key=lambda item: item.path):
                    raw = json.loads(content.text)
                    if not isinstance(raw, dict):
                        raise ValueError(f"malformed {kind} record")
                    record_id = raw.get(_IDS[kind])
                    if content.path != record_path(kind, loop_id, record_id):
                        raise ValueError(f"{kind} path identity mismatch")
                    _validate_record(kind, loop_id, raw)
                    records[kind].append(raw)

            _reject_duplicate_ids(records)
            _validate_record_graph(records)

            for kind, ids in (expected_ids or {}).items():
                if kind not in _PREFIXES:
                    raise ValueError("unknown expected record kind")
                present = {record[_IDS[kind]] for record in records[kind]}
                if any(record_id not in present for record_id in ids):
                    raise ValueError(f"missing expected {kind} record")

            ledger = ReviewerLedger()
            for record in records["request"]:
                ledger.append_request(record)
            for record in records["claim"]:
                ledger.append_claim(record)
            for record in records["response"]:
                ledger.append_response(record)
            for record in records["receipt"]:
                ledger.receipts.append(deepcopy(record))
            return ReviewResult(
                "RECOVERED",
                "fresh durable session recovered",
                {"ledger": ledger, "state": state_result.record},
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))


def _decode_record(
    kind: str, loop_id: str, record_id: str, content: GitHubContent
) -> dict[str, Any]:
    if content.path != record_path(kind, loop_id, record_id):
        raise ValueError("durable record path mismatch")
    record = json.loads(content.text)
    if not isinstance(record, dict):
        raise ValueError("durable record is not an object")
    if record.get(_IDS[kind]) != record_id:
        raise ValueError("durable record identity mismatch")
    _validate_record(kind, loop_id, record)
    return record


def _validate_record(kind: str, loop_id: str, record: dict[str, Any]) -> None:
    if kind not in _PREFIXES:
        raise ValueError("unknown reviewer record kind")
    if not isinstance(record, dict):
        raise ValueError("record must be an object")
    record_id = record.get(_IDS[kind])
    _safe_component(loop_id, "loop_id")
    _safe_component(record_id, _IDS[kind])

    if kind == "request":
        if record.get("loop_id") != loop_id:
            raise ValueError("request loop/path mismatch")
        ReviewerLedger().append_request(record)
        return

    if kind == "claim":
        _safe_component(record.get("request_id"), "request_id")
        reviewer = record.get("reviewer_instance_id")
        if not isinstance(reviewer, str) or not reviewer:
            raise ValueError("invalid reviewer_instance_id")
        ReviewerLedger().append_claim(record)
        return

    if kind == "response":
        if record.get("loop_id") != loop_id:
            raise ValueError("response loop/path mismatch")
        _safe_component(record.get("request_id"), "request_id")
        ReviewerLedger().append_response(record)
        return

    _validate_receipt(loop_id, record)


def _validate_receipt(loop_id: str, receipt: dict[str, Any]) -> None:
    required = {
        "schema_version", "receipt_id", "response_id", "request_id", "state",
        "loop_id", "round", "correlation_id", "expected_target_head",
    }
    if not required <= receipt.keys():
        raise ValueError("invalid review receipt")
    if receipt["schema_version"] != 1 or receipt["state"] != "CONSUMED":
        raise ValueError("invalid review receipt")
    if receipt["loop_id"] != loop_id:
        raise ValueError("receipt loop/path mismatch")
    for field in (
        "receipt_id", "response_id", "request_id", "loop_id",
        "correlation_id", "expected_target_head",
    ):
        if not isinstance(receipt[field], str) or not receipt[field]:
            raise ValueError(f"invalid receipt {field}")
    if isinstance(receipt["round"], bool) or not isinstance(receipt["round"], int) or receipt["round"] < 1:
        raise ValueError("invalid receipt round")
    if receipt.get("review_profile") == "DURABLE_REVIEW_V2":
        tree = receipt.get("expected_target_tree")
        if not isinstance(tree, str) or not tree:
            raise ValueError("invalid durable review receipt target tree")


def _validate_state(loop_id: str, state: dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    if state.get("loop_id") != loop_id:
        raise ValueError("state loop/path mismatch")
    StateMachine(state)


def _branch_read(
    backend: GitHubRecordBackend, kind: str, loop_id: str, record_id: str
) -> dict[str, Any]:
    content = backend.client.get(record_path(kind, loop_id, record_id), backend.branch)
    if content is None:
        raise ValueError(f"referenced review {kind} unavailable")
    return _decode_record(kind, loop_id, record_id, content)


def _validate_references_for_append(
    backend: GitHubRecordBackend, kind: str, loop_id: str, record: dict[str, Any]
) -> None:
    if kind == "request":
        return
    request = _branch_read(backend, "request", loop_id, record["request_id"])

    if kind == "claim":
        if request.get("review_profile") == "DURABLE_REVIEW_V2":
            if record.get("role") != request.get("reviewer_role"):
                raise ValueError("reviewer claim role mismatch")
        claimed_at = _time(record["claimed_at"])
        claim_expiry = _time(record["expires_at"])
        request_expiry = _time(request["expires_at"])
        if claimed_at >= claim_expiry or claim_expiry > request_expiry:
            raise ValueError("claim/request expiry mismatch")
        return

    if kind == "response":
        _match_context(request, record)
        submitted_at = _time(record["submitted_at"])
        matches = []
        for content in backend.client.list(f"{_PREFIXES['claim']}/{loop_id}/", backend.branch):
            claim = json.loads(content.text)
            _validate_record("claim", loop_id, claim)
            if (
                claim.get("request_id") == record["request_id"]
                and claim.get("reviewer_instance_id") == record.get("reviewer_instance_id")
                and claim.get("reviewer_generation") == record.get("reviewer_generation")
                and _time(claim["claimed_at"]) <= submitted_at < _time(claim["expires_at"])
            ):
                matches.append(claim)
        if len(matches) != 1:
            raise ValueError("response has no unique valid reviewer claim")
        return

    response = _branch_read(backend, "response", loop_id, record["response_id"])
    if response.get("request_id") != record["request_id"]:
        raise ValueError("receipt request/response mismatch")
    _match_context(response, record)


def _validate_record_graph(records: dict[str, list[dict[str, Any]]]) -> None:
    requests = {r["request_id"]: r for r in records["request"]}
    responses = {r["response_id"]: r for r in records["response"]}
    claims_by_request: dict[str, list[dict[str, Any]]] = {}

    for claim in records["claim"]:
        request = requests.get(claim["request_id"])
        if request is None:
            raise ValueError("claim references missing request")
        if request.get("review_profile") == "DURABLE_REVIEW_V2":
            if claim.get("role") != request.get("reviewer_role"):
                raise ValueError("reviewer claim role mismatch")
        claimed_at = _time(claim["claimed_at"])
        claim_expiry = _time(claim["expires_at"])
        request_expiry = _time(request["expires_at"])
        if claimed_at >= claim_expiry or claim_expiry > request_expiry:
            raise ValueError("claim/request expiry mismatch")
        claims_by_request.setdefault(claim["request_id"], []).append(claim)

    for claims in claims_by_request.values():
        generations = [claim["reviewer_generation"] for claim in claims]
        if len(generations) != len(set(generations)):
            raise ValueError("duplicate reviewer generation")

    for response in records["response"]:
        request = requests.get(response["request_id"])
        if request is None:
            raise ValueError("response references missing request")
        _match_context(request, response)
        if request.get("review_profile") == "DURABLE_REVIEW_V2":
            if response.get("reviewer_role") != request.get("reviewer_role"):
                raise ValueError("reviewer role mismatch")
            if response.get("review_kind") != request.get("review_kind"):
                raise ValueError("review kind mismatch")
            if response.get("decision") not in request.get("allowed_decisions", []):
                raise ValueError("review decision not allowed by request")
        submitted_at = _time(response["submitted_at"])
        owners = [
            claim for claim in claims_by_request.get(response["request_id"], [])
            if claim["reviewer_instance_id"] == response["reviewer_instance_id"]
            and claim["reviewer_generation"] == response["reviewer_generation"]
            and _time(claim["claimed_at"]) <= submitted_at < _time(claim["expires_at"])
        ]
        if len(owners) != 1:
            raise ValueError("response has no unique valid reviewer claim")

    for receipt in records["receipt"]:
        request = requests.get(receipt["request_id"])
        response = responses.get(receipt["response_id"])
        if request is None or response is None:
            raise ValueError("receipt references missing request or response")
        if response["request_id"] != receipt["request_id"]:
            raise ValueError("receipt request/response mismatch")
        _match_context(response, receipt)


def _reject_duplicate_ids(records: dict[str, list[dict[str, Any]]]) -> None:
    for kind, items in records.items():
        ids = [item[_IDS[kind]] for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate {kind} identity")


def _match_context(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    keys = ("loop_id", "round", "correlation_id", "expected_target_head")
    if tuple(expected.get(key) for key in keys) != tuple(actual.get(key) for key in keys):
        raise ValueError("durable record context mismatch")
    if expected.get("review_profile") == "DURABLE_REVIEW_V2":
        if actual.get("review_profile") != "DURABLE_REVIEW_V2":
            raise ValueError("durable review profile mismatch")
        if actual.get("expected_target_tree") != expected.get("expected_target_tree"):
            raise ValueError("durable review target tree mismatch")
        if "reviewer_role" in actual and actual.get("reviewer_role") != expected.get("reviewer_role"):
            raise ValueError("durable reviewer role mismatch")
        if "review_kind" in actual and actual.get("review_kind") != expected.get("review_kind"):
            raise ValueError("durable review kind mismatch")


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _safe_component(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or not _COMPONENT.fullmatch(value)
    ):
        raise ValueError(f"unsafe {field}")
