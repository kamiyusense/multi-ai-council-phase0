"""Offline reconciliation of BWJ snapshots; never publishes or dispatches.

PREPARED is a candidate for inspection, not authenticated lineage, a reservation,
semantic approval, or permission to send. The caller must obtain fresh, complete
GitHub readbacks. No thread/session state, network adapter or retry is added.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .cloud_work_lanes import LANES, lane_identity, result_review_task, result_review_verification
from .blue_jules_result_event import (
    EXPECTED_REPOSITORY, EventDecision, EventLineage, classify_jules_result_event,
)
from .blue_work_wake_prepare import (
    CarrierSnapshot, TargetSnapshot, prepare_work_wake,
    RESULT_REVIEW_TASK, RESULT_REVIEW_VERIFICATION,
)
from .reviewer import make_request_v2
from .jules_api_request import _validate_path

PREFIX = "[CW_BLUE_V1]"
RECEIPT_PREFIX = "[CW_BLUE_RECEIPT_V1]"
RESULT_ID = re.compile(r"^blue-jules-result-pr([1-9][0-9]*)-([0-9a-f]{40})$")
SHA = re.compile(r"^[0-9a-f]{40}$")
COMMAND_KEYS = {
    "protocol_version", "command_id", "worker_generation", "target_repository",
    "target_pr", "target_branch", "expected_target_head", "expires_at", "task",
    "allowed_paths", "verification", "live_provider_or_model_allowed", "retry", "fallback",
}
STATUSES = {"PASS", "FAIL", "BLOCKED", "UNKNOWN", "STALE", "NO_OP"}


@dataclass(frozen=True)
class ReconciliationPlan:
    status: str
    reason: str
    command_id: str | None = None
    review_body: str | None = None
    carrier_pr: int | None = None
    purpose: str | None = None
    lane: str = "blue"


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return result


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _body(body: Any, prefix: str) -> dict[str, Any] | None:
    if not isinstance(body, str):
        raise ValueError("unreadable record body")
    if not body.startswith(prefix):
        return None
    if not body.startswith(prefix + "\n"):
        raise ValueError("malformed prefixed record")
    parsed = json.loads(body[len(prefix) + 1:], object_pairs_hook=_pairs)
    if not isinstance(parsed, dict):
        raise ValueError("record must be an object")
    return parsed


def _target(record: dict[str, Any], *, receipt: bool = False) -> None:
    if record.get("target_repository") != EXPECTED_REPOSITORY or not _positive(record.get("target_pr")):
        raise ValueError("target repository/PR invalid")
    branch = record.get("target_branch")
    if (not isinstance(branch, str) or not branch or branch in {"main", "master"}
            or not re.fullmatch(r"[A-Za-z0-9._/-]+", branch)
            or ".." in branch or branch.startswith(("/", "refs/")) or branch.endswith("/")):
        raise ValueError("target branch invalid")
    fields = ("target_head_before", "target_head_after") if receipt else ("expected_target_head",)
    if not all(_sha(record.get(field)) for field in fields):
        raise ValueError("target head invalid")


def _command(command: dict[str, Any], lane: str = "blue") -> str:
    lane_identity(lane)
    if set(command) != COMMAND_KEYS:
        raise ValueError("command keys mismatch")
    if type(command["protocol_version"]) is not int or command["protocol_version"] != 1:
        raise ValueError("protocol mismatch")
    if not _positive(command["worker_generation"]):
        raise ValueError("invalid generation")
    identity = command["command_id"]
    if not isinstance(identity, str) or not identity or len(identity) > 200:
        raise ValueError("invalid command identity")
    _target(command)
    _time(command["expires_at"])
    if (command["live_provider_or_model_allowed"] is not False
            or type(command["retry"]) is not int or command["retry"] != 0
            or command["fallback"] != "disabled"):
        raise ValueError("unsafe execution policy")
    if not isinstance(command["task"], str) or not command["task"].strip():
        raise ValueError("missing bounded task")
    for field in ("allowed_paths", "verification"):
        if not isinstance(command[field], list) or any(not isinstance(v, str) or not v for v in command[field]):
            raise ValueError("invalid " + field)
    if not command["verification"]:
        raise ValueError("verification missing")
    for path in command["allowed_paths"]:
        _validate_path(path)
    match = re.fullmatch(rf"{lane}-jules-result-pr([1-9][0-9]*)-([0-9a-f]{{40}})", identity)
    if any(identity.startswith(color + "-jules-result-") for color in LANES):
        if match is None or int(match[1]) != command["target_pr"] or match[2] != command["expected_target_head"]:
            raise ValueError("reserved result identity mismatch")
        if (command["allowed_paths"] or command["task"] != result_review_task(lane)
                or command["verification"] != list(result_review_verification(lane))):
            raise ValueError("reserved result task must retain BWJ-2 read-only contract")
        return "JULES_RESULT_REVIEW"
    return "CHAT_REQUEST"


def _carrier(pr: Any, worker_state: Any, protocol: Any, lane: str = "blue") -> CarrierSnapshot:
    identity = lane_identity(lane)
    if not isinstance(pr, dict) or not isinstance(worker_state, dict) or not isinstance(protocol, CarrierSnapshot):
        raise ValueError("carrier readback missing")
    if (pr.get("state") != "open" or pr.get("merged") is not False
            or not _positive(pr.get("number")) or not isinstance(pr.get("head"), dict)
            or not _sha(pr["head"].get("sha"))):
        raise ValueError("carrier not open/readable")
    labels = pr.get("labels")
    if not isinstance(labels, list) or not all(isinstance(x, dict) and isinstance(x.get("name"), str) for x in labels):
        raise ValueError("carrier labels unreadable")
    if identity["label"] not in {x["name"] for x in labels}:
        raise ValueError("lane label absent")
    if (worker_state.get("schema_version") != 1 or type(worker_state.get("schema_version")) is not int
            or worker_state.get("lane") != lane or not _positive(worker_state.get("active_generation"))
            or worker_state.get("carrier_pr") != pr["number"]
            or type(worker_state.get("carrier_pr")) is not int
            or worker_state.get("carrier_branch") != pr["head"].get("ref")
            or protocol.lane != lane or protocol.command_prefix != identity["command_prefix"]
            or type(protocol.protocol_version) is not int or protocol.protocol_version != 1
            or type(protocol.worker_generation) is not int
            or protocol.worker_generation != worker_state["active_generation"]):
        raise ValueError("carrier/state/protocol disagreement")
    if pr["head"].get("repo", {}).get("full_name") != EXPECTED_REPOSITORY:
        raise ValueError("carrier repository mismatch")
    return protocol


def _records(reviews: Any, comments: Any, complete: Any, *, focus_id: str | None = None,
             focus_command: dict[str, Any] | None = None, lane: str = "blue") -> tuple[set[str], set[str]]:
    identity_info = lane_identity(lane)
    prefix, receipt_prefix = identity_info["command_prefix"], identity_info["receipt_prefix"]
    if complete is not True or not isinstance(reviews, list) or not isinstance(comments, list):
        raise ValueError("complete paginated reviews/comments required")
    identities: set[str] = set()
    commands: dict[str, dict[str, Any]] = {}
    if focus_command is not None:
        _command(focus_command, lane)
        focus_id = focus_command["command_id"]
    for row in reviews:
        if not isinstance(row, dict):
            raise ValueError("malformed review")
        command = _body(row.get("body"), prefix)
        if command is None:
            continue
        if row.get("state") != "COMMENTED" or not _positive(row.get("id")):
            raise ValueError("command is not a submitted COMMENT review")
        identity = command.get("command_id")
        if not isinstance(identity, str) or not identity or len(identity) > 200:
            raise ValueError("review identity unreadable")
        # Old unrelated Chat smoke records predate generation fencing. Their
        # IDs can forbid resend, but never confer authority or a generation.
        if any(identity.startswith(color + "-jules-result-") for color in LANES) or identity == focus_id:
            _command(command, lane)
            if identity in commands:
                raise ValueError("duplicate submitted command identity")
            if identity == focus_id and focus_command is not None and any(focus_command[k] != command[k] for k in
                    ("protocol_version", "worker_generation", "target_repository", "target_pr", "target_branch", "expected_target_head", "task", "allowed_paths", "verification")):
                raise ValueError("conflicting command identity binding")
            commands[identity] = command
        identities.add(command["command_id"])
    terminal_ids: set[str] = set()
    for row in comments:
        if not isinstance(row, dict):
            raise ValueError("malformed comment")
        receipt = _body(row.get("body"), receipt_prefix)
        if receipt is None:
            continue
        identity = receipt.get("command_id")
        if not isinstance(identity, str) or not identity or len(identity) > 200:
            raise ValueError("receipt identity unreadable")
        if not any(identity.startswith(color + "-jules-result-") for color in LANES) and identity != focus_id:
            identities.add(identity)
            continue
        if (type(receipt.get("protocol_version")) is not int or receipt.get("protocol_version") != 1
                or not _positive(receipt.get("worker_generation"))
                or not isinstance(receipt.get("command_id"), str) or not receipt["command_id"]
                or receipt.get("status") not in STATUSES or receipt.get("terminal") is not True):
            raise ValueError("malformed terminal receipt")
        _target(receipt, receipt=True)
        command = commands.get(identity)
        if command is None:
            raise ValueError("terminal receipt has no verifiable command binding")
        if any(receipt.get(key) != command[key] for key in
               ("command_id", "worker_generation", "target_repository", "target_pr", "target_branch")):
            raise ValueError("terminal receipt command/target/generation mismatch")
        if receipt["target_head_before"] != command["expected_target_head"]:
            raise ValueError("terminal receipt expected HEAD mismatch")
        if _command(command, lane) == "JULES_RESULT_REVIEW" and receipt["target_head_after"] != command["expected_target_head"]:
            raise ValueError("read-only result receipt reports target mutation")
        if not _positive(row.get("id")):
            raise ValueError("terminal receipt comment identity missing")
        if identity in terminal_ids:
            raise ValueError("multiple terminal receipts for one command")
        terminal_ids.add(identity)
        identities.add(receipt["command_id"])
    return identities, terminal_ids


def prepare_reconciled_wake(*, event: Any, lineage: Any, result_pr: Any,
                            carrier_pr: Any, worker_state: Any, protocol: Any,
                            reviews: Any, comments: Any, records_complete: Any,
                            expires_at: Any, now: datetime, lane: str = "blue") -> ReconciliationPlan:
    """Compose BWJ-1/2 with current snapshots; no production transport exists."""
    try:
        carrier = _carrier(carrier_pr, worker_state, protocol, lane)
        classified = classify_jules_result_event(event, lineage, [], lane=lane)
        if classified.decision == EventDecision.IGNORE:
            return ReconciliationPlan("NO_OP", classified.reason or "ignored", classified.command_id)
        if classified.decision != EventDecision.WAKE:
            return ReconciliationPlan("UNKNOWN", classified.reason or "classification unavailable")
        if not isinstance(result_pr, dict) or result_pr.get("state") != "open" or result_pr.get("merged") is not False:
            raise ValueError("result PR not open/readable")
        if (not _positive(result_pr.get("number")) or result_pr["number"] != event["pull_request"]["number"]
                or result_pr["number"] == carrier_pr["number"]):
            raise ValueError("result PR identity mismatch")
        for side in ("head", "base"):
            if not isinstance(result_pr.get(side), dict):
                raise ValueError("result branch readback unavailable")
            if result_pr[side].get("repo", {}).get("full_name") != EXPECTED_REPOSITORY:
                raise ValueError("fork/unrelated result repository")
        if (result_pr["base"].get("ref") != lineage.work_branch
                or result_pr["base"].get("sha") != lineage.expected_target_head):
            raise ValueError("current result lineage mismatch")
        target = TargetSnapshot(EXPECTED_REPOSITORY, result_pr["number"], result_pr["head"].get("ref"),
                                event["pull_request"]["head"]["sha"], result_pr["head"].get("sha"))
        prepared = prepare_work_wake(classified, carrier, target, [], expires_at, now)
        if prepared.status != "PREPARED":
            return ReconciliationPlan(prepared.status, "BWJ-2 refused candidate", prepared.command_id)
        command = _body(prepared.review_body, lane_identity(lane)["command_prefix"])
        purpose = _command(command, lane)
        seen, _ = _records(reviews, comments, records_complete, focus_command=command, lane=lane)
        if command["command_id"] in seen:
            return ReconciliationPlan("NO_OP", "existing bound command/terminal receipt", command["command_id"])
        return ReconciliationPlan("PREPARED", "offline candidate only; no authenticated lineage or send authority",
                                  prepared.command_id, prepared.review_body, carrier_pr["number"], purpose, lane)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return ReconciliationPlan("UNKNOWN", str(exc))


def assess_cloud_review(*, body: Any, active_generation: Any, fixed_generation: Any,
                       current_target: Any, reviews: Any, comments: Any,
                       records_complete: Any, now: datetime, lane: str = "blue") -> ReconciliationPlan:
    """Offline worker preflight for both purposes. Does not run the task."""
    try:
        if not _positive(active_generation) or not _positive(fixed_generation):
            raise ValueError("worker identity unavailable")
        if fixed_generation != active_generation:
            return ReconciliationPlan("NO_OP", "stale worker; no receipt permitted")
        command = _body(body, lane_identity(lane)["command_prefix"])
        if command is None:
            return ReconciliationPlan("NO_OP", "different lane/non-command")
        purpose = _command(command, lane)
        if command["worker_generation"] != active_generation:
            return ReconciliationPlan("STALE", "command generation mismatch", command["command_id"])
        # Only terminal comments guard worker replay. The triggering review
        # itself must not cause NO_OP just because it is in the review list.
        _, terminals = _records(reviews, comments, records_complete, focus_command=command, lane=lane)
        matching = [parsed for row in reviews
                    if (parsed := _body(row["body"], lane_identity(lane)["command_prefix"])) is not None
                    and parsed["command_id"] == command["command_id"]]
        if len(matching) != 1 or matching[0] != command:
            raise ValueError("exact submitted command readback missing/conflicting/duplicated")
        if command["command_id"] in terminals:
            return ReconciliationPlan("NO_OP", "terminal command", command["command_id"])
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("current time unavailable")
        if now >= _time(command["expires_at"]):
            return ReconciliationPlan("STALE", "expired command", command["command_id"])
        if not isinstance(current_target, dict):
            raise ValueError("target readback unavailable")
        _target(current_target)
        if any(current_target.get(k) != command[k] for k in ("target_repository", "target_pr", "target_branch")):
            raise ValueError("target identity mismatch")
        if current_target["expected_target_head"] != command["expected_target_head"]:
            return ReconciliationPlan("STALE", "target head moved", command["command_id"])
        return ReconciliationPlan("VALIDATED", "offline preflight only; task authority not granted",
                                  command["command_id"], purpose=purpose, lane=lane)
    except (ValueError, TypeError, KeyError) as exc:
        return ReconciliationPlan("UNKNOWN", str(exc))


def prepare_result_review_request(plan: ReconciliationPlan, *, target_tree: str,
                                  evidence_refs: list[str], expires_at: str,
                                  now: datetime) -> dict[str, Any]:
    """Reuse the existing durable reviewer contract; not a semantic verdict."""
    if not isinstance(plan, ReconciliationPlan) or plan.status != "PREPARED" or plan.purpose != "JULES_RESULT_REVIEW":
        raise ValueError("prepared result wake required")
    lane = plan.lane
    command = _body(plan.review_body, lane_identity(lane)["command_prefix"])
    _command(command, lane)
    if plan.command_id != command["command_id"] or not _positive(plan.carrier_pr):
        raise ValueError("prepared plan identity mismatch")
    if not _sha(target_tree) or not isinstance(evidence_refs, list) or not evidence_refs:
        raise ValueError("exact tree and evidence references required")
    _time(expires_at)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("current time unavailable")
    if _time(expires_at) <= now:
        raise ValueError("review already expired")
    if _time(expires_at) > _time(command["expires_at"]):
        raise ValueError("review expiry exceeds wake expiry")
    return make_request_v2(request_id=command["command_id"], loop_id=command["command_id"], round=1,
                           correlation_id=command["command_id"], expected_target_head=command["expected_target_head"],
                           expected_target_tree=target_tree, reviewer_role="reviewer", review_kind="JULES_RESULT",
                           evidence_refs=evidence_refs, allowed_decisions=["PASS", "FAIL", "BLOCKED", "UNKNOWN"],
                           expires_at=expires_at)


def assess_blue_review(**kwargs):
    return assess_cloud_review(**kwargs, lane="blue")
