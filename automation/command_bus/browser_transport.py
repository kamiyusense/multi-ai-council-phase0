"""Static dual-browser transport contract for Jules UI preflight.

This module is intentionally transport-neutral and side-effect free. It models
two browser transport identities without opening a browser, authenticating,
submitting a Jules task, or starting a model.

A second transport is never a retry/fallback of the first command. It requires
a fresh command identity/correlation/generation/expiry and proof that the
predecessor is terminal with no ambiguous external side effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

TRANSPORT_CLOUD = "WORK_CLOUD_BROWSER_JULES_UI"
TRANSPORT_COMPUTER_USE = "WORK_COMPUTER_USE_JULES_UI"
SUPPORTED_TRANSPORTS = frozenset({TRANSPORT_CLOUD, TRANSPORT_COMPUTER_USE})
ACTION = "JULES_BROWSER_TRANSPORT_PREFLIGHT"
TARGET_REPO = "kamiyusense/multi-ai-council-phase0"
TARGET_PR = 4
TARGET_BRANCH = "feature/relay-transport-7070955470193506982"

TERMINAL_RECEIPT_STATES = frozenset({"DONE", "BLOCKED", "FAILED", "UNKNOWN", "CANCELLED"})
TERMINAL_EVIDENCE_STATES = frozenset({"PASS", "BLOCKED", "BLOCKED_AUTH", "UNKNOWN", "FAILED"})
SENSITIVE_KEY_FRAGMENTS = ("password", "passwd", "token", "cookie", "credential", "secret", "mfa")


class CapabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class EligibilityState(StrEnum):
    ALLOWED_NEW_COMMAND = "ALLOWED_NEW_COMMAND"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EligibilityResult:
    state: EligibilityState
    reason: str


def validate_browser_transport_command(command: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version", "command_id", "loop_id", "round", "correlation_id",
        "generation", "target", "action", "transport_id", "expected_repo",
        "expected_pr", "expected_target_head", "expected_target_tree",
        "starting_branch", "requires_live_model", "requires_github_write",
        "retry", "fallback", "expires_at",
    }
    if not isinstance(command, dict) or not required <= command.keys():
        raise ValueError("incomplete browser transport command")
    if command["schema_version"] != 1 or command["action"] != ACTION:
        raise ValueError("unsupported browser transport command")
    if command["target"] != "work":
        raise ValueError("browser transport target must be Work")
    if command["transport_id"] not in SUPPORTED_TRANSPORTS:
        raise ValueError("unknown browser transport_id")
    if command["expected_repo"] != TARGET_REPO or command["expected_pr"] != TARGET_PR:
        raise ValueError("wrong browser transport target")
    if command["starting_branch"] != TARGET_BRANCH:
        raise ValueError("wrong browser starting branch")
    if command["retry"] != 0 or command["fallback"] != "disabled":
        raise ValueError("retry/fallback policy violation")
    if command["requires_live_model"] is not False:
        raise ValueError("browser preflight must not start a live model")
    if command["requires_github_write"] is not True:
        raise ValueError("browser preflight requires durable GitHub write")
    if isinstance(command["generation"], bool) or not isinstance(command["generation"], int) or command["generation"] < 1:
        raise ValueError("invalid transport generation")
    if isinstance(command["round"], bool) or not isinstance(command["round"], int) or command["round"] < 1:
        raise ValueError("invalid browser transport round")
    for key in ("command_id", "loop_id", "correlation_id", "expected_target_head",
                "expected_target_tree", "expires_at"):
        if not isinstance(command[key], str) or not command[key]:
            raise ValueError(f"invalid browser transport {key}")
    expiry = datetime.fromisoformat(command["expires_at"].replace("Z", "+00:00"))
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        raise ValueError("browser transport expiry must include timezone")
    return command


def validate_browser_preflight_evidence(command: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    validate_browser_transport_command(command)
    required = {
        "schema_version", "command_id", "correlation_id", "generation",
        "predecessor_command_id", "transport_id", "repository_expected",
        "repository_observed", "branch_expected", "branch_observed",
        "repo_selection_explicit", "branch_selection_explicit", "auth_state",
        "browser_opened", "jules_page_reached", "task_submitted",
        "jules_task_started", "model_started", "target_head_expected",
        "target_head_observed", "target_tree_expected", "target_tree_observed",
        "retry_count", "fallback_used", "terminal_state", "blocker",
        "external_action_uncertainty", "github_mutation_possible",
        "evidence_refs", "created_at",
    }
    if not isinstance(evidence, dict) or not required <= evidence.keys():
        raise ValueError("incomplete browser preflight evidence")
    _reject_sensitive_auth_material(evidence)
    binding = {
        "command_id": command["command_id"],
        "correlation_id": command["correlation_id"],
        "generation": command["generation"],
        "transport_id": command["transport_id"],
        "repository_expected": command["expected_repo"],
        "branch_expected": command["starting_branch"],
        "target_head_expected": command["expected_target_head"],
        "target_tree_expected": command["expected_target_tree"],
        "predecessor_command_id": command.get("predecessor_command_id"),
    }
    for key, expected in binding.items():
        if evidence.get(key) != expected:
            raise ValueError(f"browser evidence binding mismatch: {key}")
    if evidence["retry_count"] != 0 or evidence["fallback_used"] is not False:
        raise ValueError("browser evidence retry/fallback policy violation")
    if evidence["task_submitted"] not in {True, False, "UNKNOWN"}:
        raise ValueError("invalid task_submitted state")
    if evidence["jules_task_started"] not in {True, False, "UNKNOWN"}:
        raise ValueError("invalid jules_task_started state")
    if evidence["model_started"] not in {True, False, "UNKNOWN"}:
        raise ValueError("invalid model_started state")
    if evidence["external_action_uncertainty"] not in {True, False, "UNKNOWN"}:
        raise ValueError("invalid external action uncertainty")
    if evidence["github_mutation_possible"] not in {True, False, "UNKNOWN"}:
        raise ValueError("invalid GitHub mutation possibility")
    if evidence["terminal_state"] not in TERMINAL_EVIDENCE_STATES:
        raise ValueError("browser preflight evidence is not terminal")
    return evidence


def secondary_transport_eligibility(
    previous_command: dict[str, Any],
    previous_state: dict[str, Any],
    previous_receipt: dict[str, Any] | None,
    previous_evidence: dict[str, Any],
    *,
    fresh_target_head: str | None,
    fresh_target_tree: str | None,
) -> EligibilityResult:
    try:
        validate_browser_transport_command(previous_command)
        validate_browser_preflight_evidence(previous_command, previous_evidence)
    except (ValueError, TypeError, KeyError) as exc:
        return EligibilityResult(EligibilityState.UNKNOWN, str(exc))

    if previous_receipt is None:
        return EligibilityResult(EligibilityState.BLOCKED, "terminal receipt missing")
    if previous_receipt.get("state") not in TERMINAL_RECEIPT_STATES:
        return EligibilityResult(EligibilityState.BLOCKED, "predecessor receipt is not terminal")
    if previous_receipt.get("command_id") != previous_command["command_id"]:
        return EligibilityResult(EligibilityState.UNKNOWN, "terminal receipt command binding mismatch")
    if previous_receipt.get("correlation_id") != previous_command["correlation_id"]:
        return EligibilityResult(EligibilityState.UNKNOWN, "terminal receipt correlation mismatch")
    if previous_receipt.get("retry_count") != 0 or previous_receipt.get("fallback_used") is not False:
        return EligibilityResult(EligibilityState.BLOCKED, "predecessor retry/fallback policy violated")
    if previous_state.get("last_command_id") != previous_command["command_id"]:
        return EligibilityResult(EligibilityState.UNKNOWN, "predecessor state command binding mismatch")
    if previous_state.get("state") not in {"COMPLETE", "HALTED", "FAILED", "UNKNOWN", "EXPIRED", "BLOCKED"}:
        return EligibilityResult(EligibilityState.BLOCKED, "predecessor state is not terminal")

    for field in ("task_submitted", "jules_task_started", "model_started"):
        value = previous_evidence.get(field)
        if value == "UNKNOWN":
            return EligibilityResult(EligibilityState.UNKNOWN, f"{field} is UNKNOWN")
        if value is True:
            return EligibilityResult(EligibilityState.BLOCKED, f"{field} is true")
        if value is not False:
            return EligibilityResult(EligibilityState.UNKNOWN, f"{field} unverifiable")

    for field in ("external_action_uncertainty", "github_mutation_possible"):
        value = previous_evidence.get(field)
        if value == "UNKNOWN":
            return EligibilityResult(EligibilityState.UNKNOWN, f"{field} is UNKNOWN")
        if value is True:
            return EligibilityResult(EligibilityState.BLOCKED, f"{field} is true")
        if value is not False:
            return EligibilityResult(EligibilityState.UNKNOWN, f"{field} unverifiable")

    if not fresh_target_head or not fresh_target_tree:
        return EligibilityResult(EligibilityState.UNKNOWN, "fresh target head/tree unavailable")
    if fresh_target_head != previous_command["expected_target_head"]:
        return EligibilityResult(EligibilityState.BLOCKED, "target head changed")
    if fresh_target_tree != previous_command["expected_target_tree"]:
        return EligibilityResult(EligibilityState.BLOCKED, "target tree changed")

    if previous_evidence["target_head_observed"] != fresh_target_head:
        return EligibilityResult(EligibilityState.UNKNOWN, "observed target head does not match fresh readback")
    if previous_evidence["target_tree_observed"] != fresh_target_tree:
        return EligibilityResult(EligibilityState.UNKNOWN, "observed target tree does not match fresh readback")

    return EligibilityResult(
        EligibilityState.ALLOWED_NEW_COMMAND,
        "terminal predecessor proved no task/model/GitHub mutation and target is unchanged",
    )


def validate_successor_command(
    previous_command: dict[str, Any],
    successor: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    validate_browser_transport_command(previous_command)
    validate_browser_transport_command(successor)
    if successor["command_id"] == previous_command["command_id"]:
        raise ValueError("same command_id cannot switch transport")
    if successor["correlation_id"] == previous_command["correlation_id"]:
        raise ValueError("successor must use a fresh correlation_id")
    if successor["transport_id"] == previous_command["transport_id"]:
        raise ValueError("successor must use a different transport")
    if successor["generation"] <= previous_command["generation"]:
        raise ValueError("successor transport generation must advance")
    if successor.get("predecessor_command_id") != previous_command["command_id"]:
        raise ValueError("successor predecessor_command_id mismatch")
    if successor["expires_at"] == previous_command["expires_at"]:
        raise ValueError("successor must use a fresh expiry")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("successor validation time must include timezone")
    successor_expiry = datetime.fromisoformat(successor["expires_at"].replace("Z", "+00:00"))
    if successor_expiry <= now:
        raise ValueError("successor expiry must be in the future")
    if successor["expected_target_head"] != previous_command["expected_target_head"]:
        raise ValueError("successor target head changed during handoff")
    if successor["expected_target_tree"] != previous_command["expected_target_tree"]:
        raise ValueError("successor target tree changed during handoff")
    return successor


def validate_result_fence(command: dict[str, Any], evidence: dict[str, Any]) -> None:
    validate_browser_transport_command(command)
    if evidence.get("command_id") != command["command_id"]:
        raise ValueError("stale browser result command")
    if evidence.get("correlation_id") != command["correlation_id"]:
        raise ValueError("stale browser result correlation")
    if evidence.get("generation") != command["generation"]:
        raise ValueError("stale browser result generation")
    if evidence.get("transport_id") != command["transport_id"]:
        raise ValueError("browser result transport mismatch")


class StaticBrowserTransportAdapter:
    """Static/mock adapter; never opens a browser or starts Jules."""

    live_transport = False

    def __init__(self, transport_id: str, capability_state: CapabilityState) -> None:
        if transport_id not in SUPPORTED_TRANSPORTS:
            raise ValueError("unknown browser transport_id")
        self.transport_id = transport_id
        self.capability_state = capability_state

    def capability(self) -> dict[str, Any]:
        return {
            "transport_id": self.transport_id,
            "capability_state": self.capability_state.value,
            "browser_opened": False,
            "jules_page_reached": False,
            "task_submitted": False,
            "jules_task_started": False,
            "model_started": False,
            "external_send_attempted": False,
            "retry_count": 0,
            "fallback_used": False,
        }


def _reject_sensitive_auth_material(value: Any, path: str = "evidence") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SENSITIVE_KEY_FRAGMENTS):
                raise ValueError(f"sensitive auth material forbidden in {path}.{key}")
            _reject_sensitive_auth_material(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_auth_material(child, f"{path}[{index}]")


def replay_disposition(
    command: dict[str, Any],
    *,
    existing_command: dict[str, Any] | None = None,
    terminal_receipt: dict[str, Any] | None = None,
) -> str:
    """Return NEW or NO_OP; reject identity reuse with a different transport."""
    validate_browser_transport_command(command)
    if terminal_receipt is not None:
        if terminal_receipt.get("command_id") != command["command_id"]:
            raise ValueError("terminal receipt command binding mismatch")
        if terminal_receipt.get("state") not in TERMINAL_RECEIPT_STATES:
            raise ValueError("receipt is not terminal")
        return "NO_OP"
    if existing_command is None:
        return "NEW"
    validate_browser_transport_command(existing_command)
    if existing_command["command_id"] != command["command_id"]:
        return "NEW"
    if existing_command["transport_id"] != command["transport_id"]:
        raise ValueError("same command_id cannot bind a different transport")
    if existing_command["correlation_id"] != command["correlation_id"]:
        raise ValueError("same command_id cannot bind a different correlation")
    return "NO_OP"
