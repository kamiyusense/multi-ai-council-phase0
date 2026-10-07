"""Append-only durable campaign events for stop-resistant continuation.

Campaign events describe why a task was isolated or why a reversible decision
was deferred.  They do not grant provider, owner, merge or repository authority.
Every event is content-addressed, create-only and read back after a write.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from .claude_jules_campaign import validate_campaign_policy

PROFILE = "CLAUDE_AUTO_CAMPAIGN_EVENT_V1"
EVIDENCE_ROOT = "automation/command_bus/evidence/claude-auto-campaign-events"
_EVENT_TYPES = {"TASK_BLOCKED", "DEFERRED_DECISION", "RECOVERY_ATTEMPT", "TASK_REPLAN"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KEYS = {"schema_version", "profile", "campaign_id", "event_type", "event_id", "recorded_at", "payload"}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _aware_time(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include timezone")
    return parsed


def _event_id(record_without_id: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(record_without_id).encode("utf-8")).hexdigest()


def _build(campaign_id: str, event_type: str, payload: dict[str, Any], recorded_at: str) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "profile": PROFILE,
        "campaign_id": campaign_id,
        "event_type": event_type,
        "recorded_at": recorded_at,
        "payload": payload,
    }
    record["event_id"] = _event_id(record)
    return validate_campaign_event(record)


def build_task_blocked_event(
    *, campaign_id: str, task_id: str, reason: str, evidence_ref: str, recorded_at: str,
) -> dict[str, Any]:
    return _build(campaign_id, "TASK_BLOCKED", {
        "task_id": task_id,
        "reason": reason,
        "evidence_ref": evidence_ref,
    }, recorded_at)


def build_deferred_decision_event(
    *, campaign_id: str, decision_id: str, question: str, options: list[str], reason: str,
    selected_safe_default: str, reversibility: str, affected_scope: str,
    reconsider_condition: str, recorded_at: str,
) -> dict[str, Any]:
    return _build(campaign_id, "DEFERRED_DECISION", {
        "decision_id": decision_id,
        "question": question,
        "options": options,
        "reason": reason,
        "selected_safe_default": selected_safe_default,
        "reversibility": reversibility,
        "affected_scope": affected_scope,
        "reconsider_condition": reconsider_condition,
    }, recorded_at)


def build_recovery_event(*, campaign_id: str, scope: str, attempt: int, reason: str,
                         boundary_class: str, recorded_at: str) -> dict[str, Any]:
    return _build(campaign_id, "RECOVERY_ATTEMPT", {
        "scope": scope, "attempt": attempt, "reason": reason, "boundary_class": boundary_class,
    }, recorded_at)


def build_replan_event(*, campaign_id: str, task_id: str, intent_sha256: str,
                       canonical_head: str, canonical_tree: str, reason: str,
                       recorded_at: str) -> dict[str, Any]:
    return _build(campaign_id, "TASK_REPLAN", {
        "task_id": task_id, "intent_sha256": intent_sha256,
        "canonical_head": canonical_head, "canonical_tree": canonical_tree, "reason": reason,
    }, recorded_at)


def validate_campaign_event(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _KEYS:
        raise ValueError("campaign event keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != PROFILE:
        raise ValueError("unsupported campaign event")
    if not _SAFE_ID.fullmatch(record["campaign_id"] or ""):
        raise ValueError("unsafe campaign_id")
    if record["event_type"] not in _EVENT_TYPES:
        raise ValueError("unsupported campaign event type")
    _aware_time(record["recorded_at"], "recorded_at")
    if not isinstance(record["payload"], dict):
        raise ValueError("campaign event payload must be an object")
    unsigned = {k: v for k, v in record.items() if k != "event_id"}
    if not _SHA256.fullmatch(record["event_id"] or "") or record["event_id"] != _event_id(unsigned):
        raise ValueError("campaign event digest mismatch")

    payload = record["payload"]
    if record["event_type"] == "TASK_BLOCKED":
        if set(payload) != {"task_id", "reason", "evidence_ref"}:
            raise ValueError("task blocked payload keys mismatch")
        if not _TASK_ID.fullmatch(payload["task_id"] or ""):
            raise ValueError("unsafe task_id")
        for key in ("reason", "evidence_ref"):
            if not isinstance(payload[key], str) or not payload[key]:
                raise ValueError(f"{key} required")
    elif record["event_type"] == "RECOVERY_ATTEMPT":
        if set(payload) != {"scope", "attempt", "reason", "boundary_class"}:
            raise ValueError("recovery attempt payload keys mismatch")
        if not isinstance(payload["scope"], str) or not _SHA256.fullmatch(payload["scope"]):
            raise ValueError("unsafe recovery scope")
        if type(payload["attempt"]) is not int or not 1 <= payload["attempt"] <= 20:
            raise ValueError("recovery attempt must be 1..20")
        if payload["boundary_class"] not in {"TRANSIENT_UNKNOWN", "RECOVERABLE_UNKNOWN"}:
            raise ValueError("unsafe recovery boundary class")
        if not isinstance(payload["reason"], str) or not payload["reason"]:
            raise ValueError("recovery reason required")
    elif record["event_type"] == "TASK_REPLAN":
        if set(payload) != {"task_id", "intent_sha256", "canonical_head", "canonical_tree", "reason"}:
            raise ValueError("replan payload keys mismatch")
        if not isinstance(payload["task_id"], str) or not _TASK_ID.fullmatch(payload["task_id"]):
            raise ValueError("unsafe replan task id")
        if not isinstance(payload["intent_sha256"], str) or not _SHA256.fullmatch(payload["intent_sha256"]):
            raise ValueError("unsafe replan intent digest")
        for key in ("canonical_head", "canonical_tree"):
            if not isinstance(payload[key], str) or not re.fullmatch(r"[0-9a-f]{40}", payload[key]):
                raise ValueError(f"unsafe replan {key}")
        if not isinstance(payload["reason"], str) or not payload["reason"]:
            raise ValueError("replan reason required")
    else:
        expected = {
            "decision_id", "question", "options", "reason", "selected_safe_default",
            "reversibility", "affected_scope", "reconsider_condition",
        }
        if set(payload) != expected:
            raise ValueError("deferred decision payload keys mismatch")
        if not _SAFE_ID.fullmatch(payload["decision_id"] or ""):
            raise ValueError("unsafe decision_id")
        if not isinstance(payload["options"], list) or not payload["options"] or any(
            not isinstance(value, str) or not value for value in payload["options"]
        ):
            raise ValueError("deferred decision options required")
        for key in expected - {"options"}:
            if not isinstance(payload[key], str) or not payload[key]:
                raise ValueError(f"{key} required")
        if payload["selected_safe_default"] not in payload["options"]:
            raise ValueError("selected_safe_default must be one of options")
    return record


def campaign_event_path(campaign_id: str, event_id: str) -> str:
    if not _SAFE_ID.fullmatch(campaign_id or "") or not _SHA256.fullmatch(event_id or ""):
        raise ValueError("unsafe campaign event identity")
    return f"{EVIDENCE_ROOT}/{campaign_id}/{event_id}.json"


class CampaignStateStore:
    def __init__(self, client: Any, *, data_branch: str, campaign_id: str):
        if not isinstance(data_branch, str) or not data_branch:
            raise ValueError("data_branch required")
        if not _SAFE_ID.fullmatch(campaign_id or ""):
            raise ValueError("unsafe campaign_id")
        self.client, self.branch, self.campaign_id = client, data_branch, campaign_id

    def configuration(self, *, origin_loop_id: str, campaign_policy: dict[str, Any],
                      roadmap_sha256: str) -> dict[str, Any]:
        if not isinstance(origin_loop_id, str) or not _SAFE_ID.fullmatch(origin_loop_id):
            raise ValueError("unsafe campaign origin loop")
        if not isinstance(roadmap_sha256, str) or not _SHA256.fullmatch(roadmap_sha256):
            raise ValueError("invalid campaign roadmap digest")
        validated = validate_campaign_policy(campaign_policy)
        if validated["campaign_id"] != self.campaign_id:
            raise ValueError("campaign configuration identity mismatch")
        record = {"schema_version": 1, "profile": "CLAUDE_AUTO_CAMPAIGN_CONFIGURATION_V1",
                  "origin_loop_id": origin_loop_id, "campaign_policy": validated,
                  "roadmap_sha256": roadmap_sha256}
        record["configuration_sha256"] = hashlib.sha256(_canonical(record).encode()).hexdigest()
        return record

    def check_configuration(self, **kwargs: Any) -> str:
        record = self.configuration(**kwargs)
        path = f"{EVIDENCE_ROOT}-configurations/{record['origin_loop_id']}.json"
        existing = self.client.get(path, self.branch)
        if existing is None:
            return "ABSENT"
        try:
            return "VERIFIED" if json.loads(existing.text) == record else "MISMATCH"
        except json.JSONDecodeError:
            return "MISMATCH"

    def bind_configuration(self, **kwargs: Any) -> str:
        record = self.configuration(**kwargs)
        state = self.check_configuration(**kwargs)
        if state != "ABSENT":
            return "RECOVERED" if state == "VERIFIED" else "COLLISION"
        path = f"{EVIDENCE_ROOT}-configurations/{record['origin_loop_id']}.json"
        try:
            self.client.create(path, _canonical(record), "Claude AUTO immutable campaign configuration", self.branch)
        except Exception:
            pass
        # A failed/ambiguous response never authorizes another create.
        state = self.check_configuration(**kwargs)
        return {"VERIFIED": "CREATED", "ABSENT": "UNKNOWN"}.get(state, "COLLISION")

    def persist(self, record: dict[str, Any]) -> str:
        record = validate_campaign_event(record)
        if record["campaign_id"] != self.campaign_id:
            raise ValueError("campaign event belongs to another campaign")
        path = campaign_event_path(self.campaign_id, record["event_id"])
        existing = self.client.get(path, self.branch)
        if existing is not None:
            try:
                return "RECOVERED" if json.loads(existing.text) == record else "COLLISION"
            except json.JSONDecodeError:
                return "COLLISION"
        try:
            self.client.create(path, _canonical(record), f"Claude AUTO campaign event {record['event_type']}", self.branch)
        except Exception:
            pass
        readback = self.client.get(path, self.branch)
        if readback is None:
            return "UNKNOWN"
        try:
            return "CREATED" if json.loads(readback.text) == record else "COLLISION"
        except json.JSONDecodeError:
            return "COLLISION"

    def events(self) -> list[dict[str, Any]]:
        prefix = f"{EVIDENCE_ROOT}/{self.campaign_id}/"
        records = []
        for content in self.client.list(prefix, self.branch):
            record = validate_campaign_event(json.loads(content.text))
            if record["campaign_id"] != self.campaign_id:
                raise ValueError("campaign event path/content mismatch")
            if content.path != campaign_event_path(self.campaign_id, record["event_id"]):
                raise ValueError("campaign event filename/digest mismatch")
            records.append(record)
        return sorted(records, key=lambda r: (r["recorded_at"], r["event_id"]))

    def blocked_tasks(self) -> set[str]:
        return {
            event["payload"]["task_id"]
            for event in self.events()
            if event["event_type"] == "TASK_BLOCKED"
        }

    def deferred_decisions(self) -> list[dict[str, Any]]:
        found = {}
        for event in self.events():
            if event["event_type"] != "DEFERRED_DECISION":
                continue
            key = event["payload"]["decision_id"]
            if key in found and found[key]["payload"] != event["payload"]:
                raise ValueError("conflicting deferred decision history")
            found[key] = event
        return list(found.values())

    def recovery_attempts(self, scope: str) -> int:
        attempts = sorted(event["payload"]["attempt"] for event in self.events()
                          if event["event_type"] == "RECOVERY_ATTEMPT" and event["payload"]["scope"] == scope)
        if attempts != list(range(1, len(attempts) + 1)):
            raise ValueError("recovery history is conflicting or non-contiguous")
        return len(attempts)

    def replanned_intents(self) -> dict[str, dict[str, Any]]:
        found = {}
        for event in self.events():
            if event["event_type"] != "TASK_REPLAN":
                continue
            key = event["payload"]["intent_sha256"]
            if key in found and found[key]["payload"] != event["payload"]:
                raise ValueError("conflicting task replan history")
            found[key] = event
        return found
