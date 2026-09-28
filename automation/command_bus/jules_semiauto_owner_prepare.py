"""Prepare-only durable ACQUIRE bundle for Chat -> Jules Semi-Auto.

This adapter does not dispatch Jules, does not write GitHub, does not grant
owner authority, and does not verify the provider independently.

It accepts:
- one already-valid JULES_CHAT_SEMIAUTO_V1 request;
- explicit durable identity context supplied by the controller;
- one verified Jules Create Session response;
- one fresh target PR readback.

It prepares the records needed by the existing RuntimeTransitionPublisher.
Live publication remains NOT_WIRED until separate owner authority and provider
verification sources are configured.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Any

from .jules_api_request import validate_request
from .jules_session_acceptance import extract_session_acceptance
from .loop_owner import validate_owner_event
from .loop_owner_observation import validate_provider_observation
from .runtime_state_initializer import build_initial_prepared_state
from .runtime_transition_coordinator import TransitionRequest
from .runtime_transition_evidence import validate_evidence_document
from .validator import validate_receipt, validate_state

_CONTEXT_KEYS = {
    "loop_id",
    "correlation_id",
    "holder_id",
    "target_pr",
    "owner_expires_at",
}
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_OWNER_LEASE = timedelta(hours=4)


@dataclass(frozen=True)
class JulesSemiAutoAcquireBundle:
    acceptance_session_id: str
    target_pr: int
    initial_state: dict[str, Any]
    source_receipt: dict[str, Any]
    owner_event: dict[str, Any]
    evidence_document: dict[str, Any]
    provider_observation_input: dict[str, Any]
    transition_request: TransitionRequest


def prepare_jules_semiauto_acquire(
    *,
    request: dict[str, Any],
    durable_context: dict[str, Any],
    session_response: dict[str, Any],
    target_pr_readback: dict[str, Any],
    now: datetime | None = None,
) -> JulesSemiAutoAcquireBundle:
    validate_request(request, now=now)
    context = _validate_context(durable_context)
    target = _normalize_target(target_pr_readback)

    if target["repo"] != request["target_repo"]:
        raise ValueError("target PR repository mismatch")
    if target["pr"] != context["target_pr"]:
        raise ValueError("target PR number mismatch")
    if target["branch"] != request["target_branch"]:
        raise ValueError("target PR head branch mismatch")
    if target["head"] != request["expected_target_head"]:
        raise ValueError("target PR head SHA mismatch")
    if target["state"] != "open" or target["merged"] is not False:
        raise ValueError("durable ACQUIRE requires an OPEN non-merged target PR")

    acceptance = extract_session_acceptance(
        session_response,
        expected_branch=request["target_branch"],
    )
    claimed = _time(acceptance.session_create_time, "Jules createTime")
    expires = _time(context["owner_expires_at"], "owner_expires_at")
    if expires <= claimed:
        raise ValueError("owner lease must expire after Jules session acceptance")
    if expires - claimed > _MAX_OWNER_LEASE:
        raise ValueError("owner lease exceeds bounded maximum")

    loop_id = context["loop_id"]
    command_id = request["command_id"]
    correlation_id = context["correlation_id"]
    receipt_id = f"dispatch-{command_id}"
    evidence_id = f"dispatch-{command_id}"
    evidence_ref = (
        f"automation/command_bus/evidence/{loop_id}/{evidence_id}.json"
    )
    receipt_ref = (
        f"automation/command_bus/receipts/{loop_id}/{receipt_id}.json"
    )
    session_ref = f"jules-session:{acceptance.session_id}"

    owner_event = {
        "schema_version": 1,
        "event_id": f"owner-{command_id}-g1",
        "event_type": "ACQUIRE",
        "loop_id": loop_id,
        "owner_role": "SEMI_AUTO",
        "holder_id": context["holder_id"],
        "generation": 1,
        "fencing_token": 1,
        "previous_generation": None,
        "claimed_at": acceptance.session_create_time,
        "expires_at": context["owner_expires_at"],
        "expected_repo": request["target_repo"],
        "expected_pr": context["target_pr"],
        "expected_target_head": request["expected_target_head"],
        "command_id": command_id,
        "correlation_id": correlation_id,
        "source_receipt_id": receipt_id,
        "source_receipt_ref": receipt_ref,
        "evidence_refs": [evidence_ref],
    }
    validate_owner_event(owner_event)

    source_receipt = {
        "schema_version": 1,
        "receipt_id": receipt_id,
        "command_id": command_id,
        "loop_id": loop_id,
        "correlation_id": correlation_id,
        "state": "DONE",
        "executed_once": True,
        "retry_count": 0,
        "fallback_used": False,
        "evidence_refs": [evidence_ref],
        "provider_kind": "JULES",
        "provider_state": "SESSION_ACCEPTED",
        "provider_source_ref": session_ref,
    }
    validate_receipt(source_receipt)

    evidence_document = {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "loop_id": loop_id,
        "generation": 1,
        "command_id": command_id,
        "correlation_id": correlation_id,
        "expected_repo": request["target_repo"],
        "expected_pr": context["target_pr"],
        "expected_target_head": request["expected_target_head"],
        "source_receipt_ref": receipt_ref,
        "provider_kind": "JULES",
        "provider_state": "RUNNING",
        "observed_at": acceptance.session_create_time,
        "external_refs": [session_ref],
        "test_results": [
            {"name": "jules-session-accepted", "status": "PASS"},
        ],
        "provider_readback": session_ref,
        "publication_evidence": None,
    }
    if validate_evidence_document(evidence_document) != evidence_ref:
        raise ValueError("prepared evidence path mismatch")

    provider_observation_input = {
        "schema_version": 1,
        "observation_id": f"jules-session-{acceptance.session_id}",
        "loop_id": loop_id,
        "owner_role": "SEMI_AUTO",
        "holder_id": context["holder_id"],
        "generation": 1,
        "fencing_token": 1,
        "expected_repo": request["target_repo"],
        "expected_pr": context["target_pr"],
        "expected_target_head": request["expected_target_head"],
        "state": "RUNNING",
        "evidence_ref": evidence_ref,
        "observed_at": acceptance.session_create_time,
        "expires_at": context["owner_expires_at"],
    }
    validate_provider_observation(
        {**provider_observation_input, "verified": True}
    )

    initial_state = build_initial_prepared_state(
        loop_id=loop_id,
        expected_repo=request["target_repo"],
        expected_pr=context["target_pr"],
        expected_target_head=request["expected_target_head"],
        expires_at=context["owner_expires_at"],
    )
    desired_state = {
        **initial_state,
        "state": "RUNNING",
        "last_command_id": command_id,
        "last_receipt_id": receipt_id,
    }
    validate_state(desired_state)

    transition_request = TransitionRequest(
        owner_event=owner_event,
        evidence_document=evidence_document,
        provider_observation_input=provider_observation_input,
        expected_prior_state=initial_state,
        desired_state=desired_state,
    )
    return JulesSemiAutoAcquireBundle(
        acceptance_session_id=acceptance.session_id,
        target_pr=context["target_pr"],
        initial_state=initial_state,
        source_receipt=source_receipt,
        owner_event=owner_event,
        evidence_document=evidence_document,
        provider_observation_input=provider_observation_input,
        transition_request=transition_request,
    )


def _validate_context(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _CONTEXT_KEYS:
        raise ValueError("durable context shape is invalid")
    loop_id = value["loop_id"]
    if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
        raise ValueError("invalid durable loop_id")
    for field in ("correlation_id", "holder_id"):
        item = value[field]
        if not isinstance(item, str) or not _COMPONENT.fullmatch(item):
            raise ValueError(f"invalid durable {field}")
    target_pr = value["target_pr"]
    if isinstance(target_pr, bool) or not isinstance(target_pr, int) or target_pr < 1:
        raise ValueError("durable target_pr must be a positive integer")
    _time(value["owner_expires_at"], "owner_expires_at")
    return dict(value)


def _normalize_target(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("target PR readback is required")
    head_value = raw.get("head")
    if isinstance(head_value, dict):
        head = head_value.get("sha")
        branch = head_value.get("ref")
    else:
        head = head_value
        branch = raw.get("branch")
    repo_value = raw.get("repo", raw.get("repository"))
    if isinstance(repo_value, dict):
        repo = repo_value.get("full_name")
    else:
        repo = repo_value
    value = {
        "repo": repo,
        "pr": raw.get("pr", raw.get("pr_number", raw.get("number"))),
        "branch": branch,
        "head": head,
        "state": raw.get("state"),
        "merged": raw.get("merged"),
    }
    if (
        not isinstance(value["repo"], str)
        or isinstance(value["pr"], bool)
        or not isinstance(value["pr"], int)
        or not isinstance(value["branch"], str)
        or not isinstance(value["head"], str)
        or not isinstance(value["state"], str)
        or not isinstance(value["merged"], bool)
    ):
        raise ValueError("target PR readback is incomplete")
    return value


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed
