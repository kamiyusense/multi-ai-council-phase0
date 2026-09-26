"""Fail-closed model for discovering a user-visible persistent Work route.

This module is side-effect free. It never sends cross-thread messages, opens a
browser, creates a Work, starts Jules, or persists chat/session identifiers.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

ACTION = "VISIBLE_WORK_ROUTE_DISCOVERY"

ASSOCIATED_CHAT_STATES = frozenset({
    "ASSOCIATED_CHAT_USABLE",
    "ASSOCIATED_CHAT_PRESENT_BUT_UNVERIFIED",
    "ASSOCIATED_CHAT_NOT_USER_VISIBLE",
    "ASSOCIATED_CHAT_UNAVAILABLE",
    "UNKNOWN",
})
NATIVE_CAPABILITY_STATES = frozenset({"AVAILABLE", "UNAVAILABLE", "UNKNOWN", "SKIPPED_HIGHER_PRIORITY"})
TOOL_KEYS = (
    "send_message_to_thread",
    "read_thread",
    "list_threads",
    "create_thread",
    "thread_resume",
    "equivalent_existing_work_delegation",
)
TRISTATE = frozenset({True, False, "UNKNOWN"})


class RouteDecision(StrEnum):
    ASSOCIATED_CHAT = "ASSOCIATED_CHAT"
    NATIVE_DELEGATION_CANDIDATE = "NATIVE_DELEGATION_CANDIDATE"
    NEEDS_CHATGPT_WEB_PREFLIGHT = "NEEDS_CHATGPT_WEB_PREFLIGHT"
    UNKNOWN = "UNKNOWN"


def validate_discovery_command(command: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version", "command_id", "loop_id", "round", "correlation_id",
        "target", "action", "expected_repo", "expected_pr",
        "expected_target_head", "expected_target_tree", "requires_live_model",
        "requires_github_write", "retry", "fallback", "expires_at",
    }
    if not isinstance(command, dict) or not required <= command.keys():
        raise ValueError("incomplete visible-work discovery command")
    if command["schema_version"] != 1 or command["action"] != ACTION:
        raise ValueError("unsupported visible-work discovery command")
    if command["target"] != "work":
        raise ValueError("visible-work discovery target must be Work")
    if command["retry"] != 0 or command["fallback"] != "disabled":
        raise ValueError("retry/fallback policy violation")
    if command["requires_live_model"] is not False:
        raise ValueError("discovery must not start a delegated/live target model")
    if command["requires_github_write"] is not True:
        raise ValueError("discovery requires durable GitHub evidence")
    for key in ("expected_target_head", "expected_target_tree"):
        value = command[key]
        if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"invalid {key}")
    return command


def validate_discovery_evidence(command: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    validate_discovery_command(command)
    required = {
        "schema_version", "command_id", "correlation_id",
        "target_head_expected", "target_head_observed",
        "target_tree_expected", "target_tree_observed",
        "scheduled_task_title", "associated_chat_state",
        "associated_chat_metadata_exposed", "associated_chat_user_visible",
        "associated_chat_stable", "scheduled_entry_available",
        "associated_chat_identifier_persisted",
        "native_thread_delegation_capability", "native_tool_presence",
        "native_thread_delegation_live_tested", "external_send_attempted",
        "browser_started", "new_work_creation_tested",
        "human_auth_started", "jules_started", "model_started",
        "credential_material_persisted", "retry_count", "fallback_used",
        "route_decision", "evidence_refs", "created_at",
    }
    if not isinstance(evidence, dict) or not required <= evidence.keys():
        raise ValueError("incomplete visible-work discovery evidence")
    expected_bindings = {
        "command_id": command["command_id"],
        "correlation_id": command["correlation_id"],
        "target_head_expected": command["expected_target_head"],
        "target_tree_expected": command["expected_target_tree"],
    }
    for key, expected in expected_bindings.items():
        if evidence.get(key) != expected:
            raise ValueError(f"evidence binding mismatch: {key}")
    if evidence["associated_chat_state"] not in ASSOCIATED_CHAT_STATES:
        raise ValueError("invalid associated_chat_state")
    for key in ("associated_chat_metadata_exposed", "associated_chat_user_visible",
                "associated_chat_stable", "scheduled_entry_available"):
        if evidence[key] not in TRISTATE:
            raise ValueError(f"invalid tristate: {key}")
    if evidence["associated_chat_identifier_persisted"] is not False:
        raise ValueError("chat/session identifiers must not be persisted")
    if evidence["native_thread_delegation_capability"] not in NATIVE_CAPABILITY_STATES:
        raise ValueError("invalid native delegation capability")
    tools = evidence["native_tool_presence"]
    if not isinstance(tools, dict) or set(tools) != set(TOOL_KEYS):
        raise ValueError("native tool presence keys must be exact")
    if any(value not in TRISTATE for value in tools.values()):
        raise ValueError("invalid native tool presence value")
    for key in ("native_thread_delegation_live_tested", "external_send_attempted",
                "browser_started", "new_work_creation_tested", "human_auth_started",
                "jules_started", "model_started", "credential_material_persisted",
                "fallback_used"):
        if evidence[key] is not False:
            raise ValueError(f"unsafe discovery evidence: {key}")
    if evidence["retry_count"] != 0:
        raise ValueError("retry_count must be zero")
    if evidence["route_decision"] not in {item.value for item in RouteDecision}:
        raise ValueError("invalid route_decision")
    if evidence["associated_chat_state"] == "ASSOCIATED_CHAT_USABLE":
        if evidence["associated_chat_user_visible"] is not True or evidence["associated_chat_stable"] is not True:
            raise ValueError("usable associated chat requires stable and user-visible proof")
        if evidence["native_thread_delegation_capability"] != "SKIPPED_HIGHER_PRIORITY":
            raise ValueError("lower-priority native delegation inspection must be skipped")
    return evidence


def choose_route(evidence: dict[str, Any]) -> RouteDecision:
    state = evidence.get("associated_chat_state")
    if state == "ASSOCIATED_CHAT_USABLE":
        return RouteDecision.ASSOCIATED_CHAT
    native = evidence.get("native_thread_delegation_capability")
    if native == "AVAILABLE":
        return RouteDecision.NATIVE_DELEGATION_CANDIDATE
    if native in {"UNAVAILABLE", "UNKNOWN"}:
        return RouteDecision.NEEDS_CHATGPT_WEB_PREFLIGHT
    return RouteDecision.UNKNOWN
