"""Static export of one lane's durable runtime facts into the existing durable chain shape.

Why: the Control Tower collector reads, for a stable lane id, the state file, the owner chain, the source receipt,
the evidence readbacks and the provider observation. Chat -> Jules already writes these. This adapter lets a second
runtime (Claude -> Jules, Chat -> Work) hand the *same facts* to the *same* collector without a new consumer.

Rules (all fail closed, nothing is written, nothing is issued):
* The stable lane id is owned by the controller runtime of the lane (``STABLE_ID_OWNER``), is never derived from
  worker/transport evidence (colour, carrier PR, label, worker_generation, review event, Work thread/session,
  target PR, command id, loop numbers) and must already be DURABLE in the registry snapshot passed in. A reserved
  PLACEHOLDER name never exports.
* Worker/transport facts are kept as evidence inside the exported documents, never as identity.
* Every exported record carries the stable lane id and lives under that id's directories.
This module grants no live authority and never touches the production registry or Issue #33.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .lane_stable_identity import LANE_SHAPES, validate_lane_stable_identity

# Owner decided by the project owner (2026-10-04): the Chat-led SEMI_AUTO runtime owns chat-work-semi-auto.
# claude-jules follows the same pattern for its own AUTO controller runtime. work-jules has NO owner yet.
STABLE_ID_OWNER = {
    "chat-work": "CHAT_LED_SEMI_AUTO_RUNTIME",
    "claude-jules": "CLAUDE_AUTO_RUNTIME",
}
OWNER_ROLE = {"chat-work": "SEMI_AUTO", "claude-jules": "AUTO"}

# Evidence kinds the stable id must never be derived from.
FORBIDDEN_ID_SOURCES = (
    "cloud_work_colour", "carrier_pr", "lane_label", "worker_generation", "review_event",
    "work_thread_or_session", "target_pr", "command_id", "loop_number", "jules_session_id",
)
_WORKER_EVIDENCE_KEYS = (
    "cloud_work_colour", "carrier_pr", "lane_label", "worker_generation", "review_event_id",
    "work_thread_id", "work_session_id", "jules_session_id", "loop_number",
)
_COLOUR = re.compile(r"(?i)(^|[^a-z])(j-)?(cloud-)?(blue|yellow|green|red)([^a-z]|$)")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ROOT = "automation/command_bus"


class ExportError(ValueError):
    """Raised for every refusal. The message names the rule, never a secret."""


@dataclass(frozen=True)
class LaneExport:
    lane: str
    loop_id: str
    id_owner: str
    chain_files: Mapping[str, Any]
    summary: Mapping[str, Any]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _need(mapping: Any, key: str, kind: type, what: str) -> Any:
    value = mapping.get(key) if isinstance(mapping, dict) else None
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ExportError(f"{what}: {key} is required")
    return value


def validate_identity_owner(lane: str, loop_id: str, durable_context: dict[str, Any], worker_evidence: dict[str, Any]) -> str:
    """Return the owner of the lane's stable id iff the id comes from that owner and from no worker evidence."""
    owner = STABLE_ID_OWNER.get(lane)
    if owner is None:
        raise ExportError(f"{lane}: no stable id owner is decided yet")
    if durable_context.get("id_owner") != owner:
        raise ExportError(f"{lane}: the stable id must be issued by {owner}")
    declared = durable_context.get("derived_from")
    if declared not in (None, [], ()):
        raise ExportError(f"{lane}: a stable id is issued, never derived (derived_from={declared!r})")
    for key in _WORKER_EVIDENCE_KEYS:
        if key in worker_evidence and str(worker_evidence[key]) == loop_id:
            raise ExportError(f"{lane}: stable id equals worker evidence {key}")
    if _COLOUR.search(loop_id):
        raise ExportError(f"{lane}: a colour or carrier name cannot be a stable id")
    return owner


def export_lane_runtime(
    lane: str, *, registry: dict[str, Any], request: dict[str, Any],
    durable_context: dict[str, Any], runtime_facts: dict[str, Any],
) -> LaneExport:
    """Validate ``runtime_facts`` and return the durable chain files for the collector (pure, no writes)."""
    if lane not in LANE_SHAPES:
        raise ExportError("unknown lane")
    loop_id = validate_lane_stable_identity(  # DURABLE in the registry snapshot, never a request/PR/branch identity
        lane, registry=registry, request=request, durable_context=durable_context)
    worker_evidence = runtime_facts.get("worker_evidence", {})
    if not isinstance(worker_evidence, dict):
        raise ExportError("worker_evidence must be an object")
    owner = validate_identity_owner(lane, loop_id, durable_context, worker_evidence)
    if runtime_facts.get("stable_lane_id") != loop_id:
        raise ExportError("runtime facts name another lane id")

    state = _need(runtime_facts, "state", dict, "state")
    target = _need(runtime_facts, "target", dict, "target")
    events = runtime_facts.get("owner_events")
    if not isinstance(events, list) or not events:
        raise ExportError("owner_events: at least one owner event is required")
    receipt = _need(runtime_facts, "receipt", dict, "receipt")
    evidence = _need(runtime_facts, "evidence", dict, "evidence")
    observation = runtime_facts.get("provider_observation")
    if not isinstance(observation, dict):
        raise ExportError("provider_observation is required for an active owner")

    for what, head_key in (("target", "head"), ("target", "tree")):
        if not _SHA40.fullmatch(str(target.get(head_key, ""))):
            raise ExportError(f"{what}: {head_key} must be a full lowercase SHA")
    if isinstance(target.get("pr"), bool) or not isinstance(target.get("pr"), int) or target["pr"] < 1:
        raise ExportError("target: pr must be a positive integer")

    events = copy.deepcopy(events)
    previous = None
    for event in events:
        if event.get("loop_id") != loop_id:
            raise ExportError("owner event carries another lane id")
        if event.get("owner_role") != OWNER_ROLE[lane]:
            raise ExportError(f"owner event role must be {OWNER_ROLE[lane]} for {lane}")
        if previous is not None and not (
            event.get("generation") == previous["generation"] + 1 and event.get("fencing_token", 0) > previous["fencing_token"]
        ):
            raise ExportError("owner generations must be contiguous with a rising fencing token")
        if event.get("command_id") == loop_id or event.get("correlation_id") == loop_id:
            raise ExportError("command or correlation id cannot be the stable id")
        previous = event
    last = events[-1]
    if (target["repo"], target["pr"], target["head"]) != (
            last.get("expected_repo"), last.get("expected_pr"), last.get("expected_target_head")):
        raise ExportError("target does not match the latest owner generation")
    if state.get("loop_id") != loop_id or state.get("last_command_id") != last.get("command_id") \
            or state.get("last_receipt_id") != last.get("source_receipt_id"):
        raise ExportError("state does not match the latest owner event")
    if receipt.get("loop_id") != loop_id or receipt.get("receipt_id") != last.get("source_receipt_id") \
            or receipt.get("command_id") != last.get("command_id"):
        raise ExportError("receipt does not match the latest owner event")
    ref = last["evidence_refs"][0]
    if not ref.startswith(f"{_ROOT}/evidence/{loop_id}/") \
            or not last["source_receipt_ref"].startswith(f"{_ROOT}/receipts/{loop_id}/"):
        raise ExportError("records must live under the stable lane id's directories")
    if observation.get("loop_id") != loop_id or observation.get("generation") != last["generation"]:
        raise ExportError("provider observation does not match the latest owner generation")

    evidence_doc = {"schema_version": 1, "kind": "owner-evidence", **copy.deepcopy(evidence),
                    "stable_lane_id": loop_id, "id_owner": owner, "worker_evidence": copy.deepcopy(worker_evidence)}
    files: dict[str, Any] = {
        f"{_ROOT}/state/{loop_id}.json": copy.deepcopy(state),
        last["source_receipt_ref"]: {"schema_version": 1, **copy.deepcopy(receipt)},
        ref: evidence_doc,
        f"{_ROOT}/loop_owner_observations/{loop_id}/{last['generation']:06d}.json": copy.deepcopy(observation),
    }
    for event in events:
        files[f"{_ROOT}/loop_owner_events/{loop_id}/{event['generation']:06d}.json"] = event
    summary = {
        "stable_lane_id": loop_id, "id_owner": owner, "state": state.get("state"),
        "owner_generation": last["generation"], "fencing_token": last["fencing_token"],
        "source_receipt_ref": last["source_receipt_ref"], "source_receipt_sha256": _digest(files[last["source_receipt_ref"]]),
        "evidence_ref": ref, "evidence_sha256": _digest(evidence_doc),
        "provider_session": {"id": worker_evidence.get("jules_session_id"), "raw_state": evidence.get("provider_raw_state")},
        "target": {"repo": target["repo"], "pr": target["pr"], "head": target["head"], "tree": target["tree"]},
        "result_state": evidence.get("result_state", "NONE"),
        "live_authority": False, "registry_written": False, "issue33_written": False,
    }
    return LaneExport(lane, loop_id, owner, files, summary)
