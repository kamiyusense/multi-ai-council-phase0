"""Secret-free human authentication handoff contract for native Cloud Browser takeover."""
from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

HANDOFF_METHOD = "CHATGPT_NATIVE_CLOUD_BROWSER_TAKEOVER"
HANDOFF_SURFACE = "VISIBLE_WORK"
AUTH_ORIGIN = "jules.google.com"
TRANSPORT_ID = "WORK_CLOUD_BROWSER_JULES_UI"
BOOTSTRAP_ACTION = "JULES_HUMAN_AUTH_BOOTSTRAP"
EXPECTED_REPO = "kamiyusense/multi-ai-council-phase0"
EXPECTED_PR = 4
EXPECTED_BRANCH = "feature/relay-transport-7070955470193506982"

_ALLOWED_SECRET_BOOLEAN_KEYS = {"takeover_url_persisted", "credentials_persisted"}
_FORBIDDEN_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "mfa",
    "cookie",
    "bearer",
    "credential",
    "session_token",
    "access_token",
    "refresh_token",
    "control_token",
)
_HANDOFF_FIELDS = {
    "schema_version",
    "handoff_id",
    "triggering_command_id",
    "correlation_id",
    "transport_id",
    "auth_origin",
    "handoff_method",
    "handoff_surface",
    "handoff_state",
    "requested_at",
    "completed_at",
    "takeover_url_persisted",
    "credentials_persisted",
    "task_submitted",
    "jules_task_started",
    "model_started",
    "session_identity_is_correctness_input",
}
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_AUTHENTICATED_AUTH_STATES = frozenset({"AUTHENTICATED"})


class HandoffState(StrEnum):
    REQUESTED = "REQUESTED"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    HUMAN_COMPLETED_UNVERIFIED = "HUMAN_COMPLETED_UNVERIFIED"
    VERIFYING_POST_AUTH = "VERIFYING_POST_AUTH"
    AUTHENTICATED_OBSERVED = "AUTHENTICATED_OBSERVED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


_ALLOWED_TRANSITIONS = {
    HandoffState.REQUESTED: frozenset(
        {
            HandoffState.WAITING_FOR_HUMAN,
            HandoffState.HUMAN_COMPLETED_UNVERIFIED,
            HandoffState.BLOCKED,
            HandoffState.FAILED,
        }
    ),
    HandoffState.WAITING_FOR_HUMAN: frozenset(
        {
            HandoffState.HUMAN_COMPLETED_UNVERIFIED,
            HandoffState.BLOCKED,
            HandoffState.FAILED,
        }
    ),
    HandoffState.HUMAN_COMPLETED_UNVERIFIED: frozenset(
        {
            HandoffState.VERIFYING_POST_AUTH,
            HandoffState.BLOCKED,
            HandoffState.FAILED,
        }
    ),
    HandoffState.VERIFYING_POST_AUTH: frozenset(
        {
            HandoffState.AUTHENTICATED_OBSERVED,
            HandoffState.BLOCKED,
            HandoffState.FAILED,
        }
    ),
    HandoffState.AUTHENTICATED_OBSERVED: frozenset(),
    HandoffState.BLOCKED: frozenset(),
    HandoffState.FAILED: frozenset(),
}


def auth_handoff_path(handoff_id: str, record_id: str) -> str:
    _safe_component(handoff_id, "handoff_id")
    _safe_component(record_id, "record_id")
    return f"automation/command_bus/auth_handoffs/{handoff_id}/{record_id}.json"


def validate_auth_bootstrap_command(command: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "command_id",
        "loop_id",
        "round",
        "correlation_id",
        "target",
        "action",
        "expected_repo",
        "expected_pr",
        "expected_target_head",
        "expected_target_tree",
        "starting_branch",
        "transport_id",
        "auth_origin",
        "handoff_id",
        "requires_live_model",
        "requires_github_write",
        "retry",
        "fallback",
        "expires_at",
    }
    if not isinstance(command, dict) or not required <= command.keys():
        raise ValueError("incomplete auth bootstrap command")
    if command["schema_version"] != 1:
        raise ValueError("unsupported auth bootstrap schema")
    for field in ("command_id", "loop_id", "correlation_id", "handoff_id"):
        _safe_component(command[field], field)
    if command["target"] != "work" or command["action"] != BOOTSTRAP_ACTION:
        raise ValueError("wrong auth bootstrap target/action")
    if command["expected_repo"] != EXPECTED_REPO or command["expected_pr"] != EXPECTED_PR:
        raise ValueError("wrong auth bootstrap repository/PR")
    if command["starting_branch"] != EXPECTED_BRANCH:
        raise ValueError("wrong auth bootstrap starting branch")
    if command["transport_id"] != TRANSPORT_ID or command["auth_origin"] != AUTH_ORIGIN:
        raise ValueError("wrong auth bootstrap transport/origin")
    if command["requires_live_model"] is not False:
        raise ValueError("auth bootstrap must not start a live model")
    if command["requires_github_write"] is not True:
        raise ValueError("auth bootstrap requires durable GitHub write")
    if command["retry"] != 0 or command["fallback"] != "disabled":
        raise ValueError("auth bootstrap retry/fallback policy violation")
    if isinstance(command["round"], bool) or not isinstance(command["round"], int) or command["round"] < 1:
        raise ValueError("invalid auth bootstrap round")
    _sha40(command["expected_target_head"], "expected_target_head")
    _sha40(command["expected_target_tree"], "expected_target_tree")
    _time(command["expires_at"], "expires_at")
    return command


def validate_auth_handoff(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict) or _HANDOFF_FIELDS - record.keys():
        raise ValueError("incomplete auth handoff")
    extra = set(record) - _HANDOFF_FIELDS
    if extra:
        raise ValueError(f"unexpected auth handoff fields: {', '.join(sorted(extra))}")
    _reject_secret_material(record)
    if record["schema_version"] != 1:
        raise ValueError("unsupported auth handoff schema")
    for field in ("handoff_id", "triggering_command_id", "correlation_id"):
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
    if state in {
        HandoffState.HUMAN_COMPLETED_UNVERIFIED,
        HandoffState.VERIFYING_POST_AUTH,
        HandoffState.AUTHENTICATED_OBSERVED,
    } and completed is None:
        raise ValueError("completed handoff requires completed_at")
    for field in (
        "takeover_url_persisted",
        "credentials_persisted",
        "task_submitted",
        "jules_task_started",
        "model_started",
        "session_identity_is_correctness_input",
    ):
        if record[field] is not False:
            raise ValueError(f"{field} must remain false")
    return record


def validate_handoff_successor(previous: dict[str, Any], successor: dict[str, Any]) -> dict[str, Any]:
    validate_auth_handoff(previous)
    validate_auth_handoff(successor)
    immutable = (
        "schema_version",
        "handoff_id",
        "triggering_command_id",
        "correlation_id",
        "transport_id",
        "auth_origin",
        "handoff_method",
        "handoff_surface",
        "requested_at",
        "takeover_url_persisted",
        "credentials_persisted",
        "task_submitted",
        "jules_task_started",
        "model_started",
        "session_identity_is_correctness_input",
    )
    for field in immutable:
        if successor[field] != previous[field]:
            raise ValueError(f"auth handoff identity changed: {field}")
    previous_state = HandoffState(previous["handoff_state"])
    successor_state = HandoffState(successor["handoff_state"])
    if successor_state == previous_state:
        raise ValueError("auth handoff replay/no-op must not create a successor record")
    if successor_state not in _ALLOWED_TRANSITIONS[previous_state]:
        raise ValueError(f"invalid auth handoff transition: {previous_state.value}->{successor_state.value}")
    if previous["completed_at"] is not None and successor["completed_at"] != previous["completed_at"]:
        raise ValueError("completed_at changed after completion")
    return successor


def new_exact_preflight_eligibility(
    handoff: dict[str, Any],
    *,
    user_interaction_complete: bool,
    fresh_target_head: str | None,
    fresh_target_tree: str | None,
) -> tuple[str, str]:
    validate_auth_handoff(handoff)
    if user_interaction_complete is not True:
        return "BLOCKED", "human authentication prerequisite incomplete"
    if handoff["handoff_state"] not in {
        HandoffState.HUMAN_COMPLETED_UNVERIFIED.value,
        HandoffState.AUTHENTICATED_OBSERVED.value,
    }:
        return "BLOCKED", "handoff has not reached human-complete state"
    if not _is_sha40(fresh_target_head) or not _is_sha40(fresh_target_tree):
        return "UNKNOWN", "fresh target head/tree unavailable or invalid"
    return (
        "ALLOWED_NEW_PREFLIGHT",
        "human prerequisite complete; fresh Cloud Browser observation still required",
    )



def same_work_continuation_eligibility(
    handoff: dict[str, Any],
    *,
    associated_work_user_visible: bool | None,
    same_browser_context_open: bool | None,
    executor_resumed_same_work: bool | None,
    fresh_target_head: str | None,
    fresh_target_tree: str | None,
) -> tuple[str, str]:
    """Decide whether the bounded human-auth flow may continue in the same Work.

    This function never uses a chat/thread/browser/session identifier as a
    correctness input.  It only accepts direct boolean observations about the
    already-associated operator surface and browser continuity.
    """
    validate_auth_handoff(handoff)
    if handoff["handoff_state"] != HandoffState.HUMAN_COMPLETED_UNVERIFIED.value:
        return "BLOCKED", "handoff has not reached human-completed-unverified state"
    for value, label in (
        (associated_work_user_visible, "associated Work visibility"),
        (same_browser_context_open, "same browser context continuity"),
        (executor_resumed_same_work, "same Work executor resume"),
    ):
        if value is None:
            return "UNKNOWN", f"{label} is unverified"
        if value is False:
            return "BLOCKED", f"{label} is unavailable"
    if not _is_sha40(fresh_target_head) or not _is_sha40(fresh_target_tree):
        return "UNKNOWN", "fresh target head/tree unavailable or invalid"
    return (
        "VERIFYING_POST_AUTH",
        "same associated Work/browser context is directly observed; fresh post-auth observation required",
    )


def same_work_post_auth_observation(
    *,
    associated_work_user_visible: bool | None,
    same_browser_context_open: bool | None,
    fresh_observation: bool | None,
    jules_task_creation_ui_reached: bool | None,
    auth_gate_present: bool | None,
    observed_repo: str | None,
    observed_branch: str | None,
    repo_selection_explicit: bool | None,
    branch_selection_explicit: bool | None,
    task_submitted: bool | None,
    jules_task_started: bool | None,
    model_started: bool | None,
) -> tuple[str, str]:
    """Validate a fresh post-auth observation without submitting a Jules task."""
    values = (
        associated_work_user_visible,
        same_browser_context_open,
        fresh_observation,
        jules_task_creation_ui_reached,
        auth_gate_present,
        observed_repo,
        observed_branch,
        repo_selection_explicit,
        branch_selection_explicit,
        task_submitted,
        jules_task_started,
        model_started,
    )
    if any(value is None for value in values):
        return "UNKNOWN", "same-Work post-auth observation incomplete"
    if task_submitted or jules_task_started or model_started:
        return "BLOCKED", "post-auth verification must not submit/start Jules"
    if associated_work_user_visible is not True:
        return "BLOCKED", "associated Work is not user-visible"
    if same_browser_context_open is not True:
        return "BLOCKED", "same browser context is not open"
    if fresh_observation is not True:
        return "BLOCKED", "pre-auth DOM/selector assumptions were not discarded"
    if auth_gate_present is True:
        return "BLOCKED", "authentication gate is still present"
    if jules_task_creation_ui_reached is not True:
        return "BLOCKED", "Jules task creation UI not reached"
    if repo_selection_explicit is not True or observed_repo != EXPECTED_REPO:
        return "BLOCKED", "exact repository selection not freshly verified"
    if branch_selection_explicit is not True or observed_branch != EXPECTED_BRANCH:
        return "BLOCKED", "exact branch selection not freshly verified"
    return (
        "AUTHENTICATED_OBSERVED",
        "same associated Work freshly reached Jules task creation UI with exact repo/branch and no auth gate",
    )


def bootstrap_visibility_decision(
    *,
    auth_required: bool | None,
    surface_availability_verified: bool | None,
    user_visible_entry_surfaced: bool | None,
) -> tuple[str, str]:
    """Fail closed unless the native human sign-in entry is proven visible."""
    if auth_required is False:
        return "NO_HANDOFF_NEEDED", "fresh browser observation does not require human authentication"
    if auth_required is not True:
        return "UNKNOWN", "authentication requirement is unverified"
    if surface_availability_verified is not True:
        return "UNKNOWN", "native user-visible sign-in/takeover availability is unverified"
    if user_visible_entry_surfaced is not True:
        return "BLOCKED", "native user-visible sign-in/takeover entry was not surfaced to the human"
    return "WAITING_FOR_HUMAN_AUTH", "native user-visible sign-in/takeover entry is verified visible"

def authenticated_observation(
    *,
    browser_opened: bool | None,
    jules_task_creation_ui_reached: bool | None,
    auth_state: str | None,
    task_submitted: bool | None,
    jules_task_started: bool | None,
    model_started: bool | None,
) -> tuple[str, str]:
    if any(
        value is None
        for value in (
            browser_opened,
            jules_task_creation_ui_reached,
            auth_state,
            task_submitted,
            jules_task_started,
            model_started,
        )
    ):
        return "UNKNOWN", "post-bootstrap browser observation incomplete"
    if task_submitted or jules_task_started or model_started:
        return "BLOCKED", "auth verification must not submit/start Jules"
    if browser_opened is not True or jules_task_creation_ui_reached is not True:
        return "BLOCKED", "Jules task creation UI not reached"
    if auth_state in {"AUTHENTICATION_REQUIRED", "AUTH_REQUIRED"}:
        return "BLOCKED", "authentication not freshly observed as usable"
    if auth_state not in _AUTHENTICATED_AUTH_STATES:
        return "UNKNOWN", f"unexpected post-bootstrap auth_state: {auth_state!r}"
    return (
        "AUTHENTICATED_OBSERVED",
        "fresh Cloud Browser reached Jules task creation UI without auth gate",
    )


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
    if not isinstance(value, str) or not value or not _COMPONENT.fullmatch(value):
        raise ValueError(f"unsafe {field}")


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid {field}")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed


def _is_sha40(value: Any) -> bool:
    return isinstance(value, str) and _HEX40.fullmatch(value) is not None


def _sha40(value: Any, field: str) -> None:
    if not _is_sha40(value):
        raise ValueError(f"{field} must be a lowercase 40-hex SHA")
