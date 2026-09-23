"""Secret-free human authentication handoff contract for native Cloud Browser takeover."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

HANDOFF_METHOD = "CHATGPT_NATIVE_CLOUD_BROWSER_TAKEOVER"
HANDOFF_SURFACE = "VISIBLE_WORK"
AUTH_ORIGIN = "jules.google.com"
TRANSPORT_ID = "WORK_CLOUD_BROWSER_JULES_UI"
_ALLOWED_SECRET_BOOLEAN_KEYS = {"takeover_url_persisted", "credentials_persisted"}
_FORBIDDEN_KEY_FRAGMENTS = ("password", "passwd", "mfa", "cookie", "bearer", "credential", "session_token", "access_token", "refresh_token", "control_token")

class HandoffState(StrEnum):
    REQUESTED = "REQUESTED"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    HUMAN_COMPLETED_UNVERIFIED = "HUMAN_COMPLETED_UNVERIFIED"
    AUTHENTICATED_OBSERVED = "AUTHENTICATED_OBSERVED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"

def auth_handoff_path(handoff_id: str, record_id: str) -> str:
    _safe_component(handoff_id, "handoff_id")
    _safe_component(record_id, "record_id")
    return f"automation/command_bus/auth_handoffs/{handoff_id}/{record_id}.json"

def validate_auth_handoff(record: dict[str, Any]) -> dict[str, Any]:
    required = {"schema_version","handoff_id","triggering_command_id","correlation_id","transport_id","auth_origin","handoff_method","handoff_surface","handoff_state","requested_at","completed_at","takeover_url_persisted","credentials_persisted","task_submitted","jules_task_started","model_started","session_identity_is_correctness_input"}
    if not isinstance(record, dict) or not required <= record.keys():
        raise ValueError("incomplete auth handoff")
    _reject_secret_material(record)
    if record["schema_version"] != 1:
        raise ValueError("unsupported auth handoff schema")
    for field in ("handoff_id","triggering_command_id","correlation_id"):
        _safe_component(record[field], field)
    if record["transport_id"] != TRANSPORT_ID or record["auth_origin"] != AUTH_ORIGIN:
        raise ValueError("wrong auth transport/origin")
    if record["handoff_method"] != HANDOFF_METHOD or record["handoff_surface"] != HANDOFF_SURFACE:
        raise ValueError("wrong auth handoff route")
    try:
        state = HandoffState(record["handoff_state"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid handoff state") from exc
    requested = _time(record["requested_at"], "requested_at")
    completed = None if record["completed_at"] is None else _time(record["completed_at"], "completed_at")
    if completed is not None and completed < requested:
        raise ValueError("completed_at precedes requested_at")
    if state in {HandoffState.REQUESTED, HandoffState.WAITING_FOR_HUMAN} and completed is not None:
        raise ValueError("incomplete handoff must not have completed_at")
    if state in {HandoffState.HUMAN_COMPLETED_UNVERIFIED, HandoffState.AUTHENTICATED_OBSERVED} and completed is None:
        raise ValueError("completed handoff requires completed_at")
    for field in ("takeover_url_persisted","credentials_persisted","task_submitted","jules_task_started","model_started","session_identity_is_correctness_input"):
        if record[field] is not False:
            raise ValueError(f"{field} must remain false")
    return record

def new_exact_preflight_eligibility(handoff: dict[str, Any], *, user_interaction_complete: bool, fresh_target_head: str | None, fresh_target_tree: str | None) -> tuple[str,str]:
    validate_auth_handoff(handoff)
    if not user_interaction_complete:
        return "BLOCKED", "human authentication prerequisite incomplete"
    if handoff["handoff_state"] not in {HandoffState.HUMAN_COMPLETED_UNVERIFIED.value,HandoffState.AUTHENTICATED_OBSERVED.value}:
        return "BLOCKED", "handoff has not reached human-complete state"
    if not fresh_target_head or not fresh_target_tree:
        return "UNKNOWN", "fresh target head/tree unavailable"
    return "ALLOWED_NEW_PREFLIGHT", "human prerequisite complete; fresh Cloud Browser observation still required"

def authenticated_observation(*, browser_opened: bool | None, jules_task_creation_ui_reached: bool | None, auth_state: str | None, task_submitted: bool | None, jules_task_started: bool | None, model_started: bool | None) -> tuple[str,str]:
    if any(value is None for value in (browser_opened,jules_task_creation_ui_reached,auth_state,task_submitted,jules_task_started,model_started)):
        return "UNKNOWN", "post-bootstrap browser observation incomplete"
    if task_submitted or jules_task_started or model_started:
        return "BLOCKED", "auth verification must not submit/start Jules"
    if browser_opened is not True or jules_task_creation_ui_reached is not True:
        return "BLOCKED", "Jules task creation UI not reached"
    if auth_state in {"AUTHENTICATION_REQUIRED","AUTH_REQUIRED","UNKNOWN"}:
        return "BLOCKED", "authentication not freshly observed as usable"
    return "AUTHENTICATED_OBSERVED", "fresh Cloud Browser reached Jules task creation UI without auth gate"

def _reject_secret_material(value: Any, path: str = "handoff") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in _ALLOWED_SECRET_BOOLEAN_KEYS:
                if child is not False:
                    raise ValueError(f"{key} must remain false")
                continue
            if "takeover_url" in lowered:
                raise ValueError("raw takeover URL field forbidden")
            if any(fragment in lowered for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise ValueError(f"sensitive auth material forbidden in {path}.{key}")
            _reject_secret_material(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_material(child, f"{path}[{index}]")

def _safe_component(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value or value in {".",".."}:
        raise ValueError(f"unsafe {field}")

def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid {field}")
    parsed = datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed
