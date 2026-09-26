"""Fail-closed ChatGPT Web existing-Work preflight contract.

The live executor may navigate only. It must not send a message, create a Work,
start a target model turn, start human auth, or start Jules.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

ACTION = "CHATGPT_WEB_EXISTING_WORK_PREFLIGHT"
TARGET_REPO = "kamiyusense/multi-ai-council-phase0"
TARGET_PR = 4
TRISTATE = frozenset({True, False, "UNKNOWN"})
AUTH_STATES = frozenset({"AUTHENTICATED", "AUTH_REQUIRED", "BLOCKED", "UNKNOWN"})
CLASSIFICATIONS = frozenset({"PASS", "NO_SUITABLE_EXISTING_WORK", "BLOCKED_AUTH", "BLOCKED", "UNKNOWN"})
ROUTE_DECISIONS = frozenset({"EXISTING_WORK_UI_RELAY_CANDIDATE", "NEEDS_FIXED_WORK_PREPARE", "UNKNOWN"})


class WebRouteDecision(StrEnum):
    EXISTING_WORK_UI_RELAY_CANDIDATE = "EXISTING_WORK_UI_RELAY_CANDIDATE"
    NEEDS_FIXED_WORK_PREPARE = "NEEDS_FIXED_WORK_PREPARE"
    UNKNOWN = "UNKNOWN"


def validate_command(command: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version", "command_id", "loop_id", "round", "correlation_id",
        "target", "action", "expected_repo", "expected_pr",
        "expected_target_head", "expected_target_tree", "preferred_work_title",
        "requires_live_model", "requires_github_write", "retry", "fallback",
        "expires_at",
    }
    if not isinstance(command, dict) or not required <= command.keys():
        raise ValueError("incomplete ChatGPT Web preflight command")
    if command["schema_version"] != 1 or command["action"] != ACTION:
        raise ValueError("unsupported ChatGPT Web preflight command")
    if command["target"] != "work" or command["expected_repo"] != TARGET_REPO or command["expected_pr"] != TARGET_PR:
        raise ValueError("wrong ChatGPT Web preflight target")
    if command["retry"] != 0 or command["fallback"] != "disabled":
        raise ValueError("retry/fallback policy violation")
    if command["requires_live_model"] is not False:
        raise ValueError("preflight must not start a target live model")
    if command["requires_github_write"] is not True:
        raise ValueError("preflight requires durable GitHub evidence")
    if not isinstance(command["preferred_work_title"], str) or not command["preferred_work_title"]:
        raise ValueError("preferred_work_title required")
    for key in ("expected_target_head", "expected_target_tree"):
        value = command[key]
        if not isinstance(value, str) or len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"invalid {key}")
    expiry = datetime.fromisoformat(command["expires_at"].replace("Z", "+00:00"))
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        raise ValueError("expires_at must include timezone")
    return command


def validate_evidence(command: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    validate_command(command)
    required = {
        "schema_version", "command_id", "correlation_id",
        "target_head_expected", "target_head_observed",
        "target_tree_expected", "target_tree_observed",
        "chatgpt_web_reachable", "chatgpt_auth_state", "chatgpt_ui_visible",
        "work_ui_visible", "existing_work_list_visible",
        "preferred_work_title_found", "existing_work_openable",
        "same_account_context_verified", "message_sent",
        "target_model_turn_started", "new_work_created",
        "browser_started", "human_auth_started", "jules_started",
        "credential_material_persisted", "chat_or_session_identifier_persisted",
        "retry_count", "fallback_used", "classification", "route_decision",
        "evidence_refs", "created_at",
    }
    if not isinstance(evidence, dict) or not required <= evidence.keys():
        raise ValueError("incomplete ChatGPT Web preflight evidence")
    bindings = {
        "command_id": command["command_id"],
        "correlation_id": command["correlation_id"],
        "target_head_expected": command["expected_target_head"],
        "target_tree_expected": command["expected_target_tree"],
    }
    for key, expected in bindings.items():
        if evidence.get(key) != expected:
            raise ValueError(f"evidence binding mismatch: {key}")
    if evidence["target_head_observed"] != command["expected_target_head"]:
        raise ValueError("observed target head mismatch")
    if evidence["target_tree_observed"] != command["expected_target_tree"]:
        raise ValueError("observed target tree mismatch")
    created_at = datetime.fromisoformat(evidence["created_at"].replace("Z", "+00:00"))
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must include timezone")
    for key in (
        "chatgpt_web_reachable", "chatgpt_ui_visible", "work_ui_visible",
        "existing_work_list_visible", "preferred_work_title_found",
        "existing_work_openable", "same_account_context_verified",
    ):
        if evidence[key] not in TRISTATE:
            raise ValueError(f"invalid tristate: {key}")
    if evidence["chatgpt_auth_state"] not in AUTH_STATES:
        raise ValueError("invalid chatgpt_auth_state")
    for key in (
        "message_sent", "target_model_turn_started", "new_work_created",
        "human_auth_started", "jules_started", "credential_material_persisted",
        "chat_or_session_identifier_persisted", "fallback_used",
    ):
        if evidence[key] is not False:
            raise ValueError(f"unsafe preflight evidence: {key}")
    if evidence["browser_started"] is not True:
        raise ValueError("browser_started must be true for live web preflight evidence")
    if evidence["retry_count"] != 0:
        raise ValueError("retry_count must be zero")
    if evidence["classification"] not in CLASSIFICATIONS:
        raise ValueError("invalid classification")
    if evidence["route_decision"] not in ROUTE_DECISIONS:
        raise ValueError("invalid route_decision")
    if evidence["classification"] == "PASS":
        for key in (
            "chatgpt_web_reachable", "chatgpt_ui_visible", "work_ui_visible",
            "existing_work_list_visible", "preferred_work_title_found",
            "existing_work_openable", "same_account_context_verified",
        ):
            if evidence[key] is not True:
                raise ValueError(f"PASS requires {key}=true")
        if evidence["chatgpt_auth_state"] != "AUTHENTICATED":
            raise ValueError("PASS requires authenticated ChatGPT Web")
        if evidence["route_decision"] != "EXISTING_WORK_UI_RELAY_CANDIDATE":
            raise ValueError("PASS route decision mismatch")
    if evidence["classification"] == "NO_SUITABLE_EXISTING_WORK":
        if evidence["existing_work_list_visible"] is not True or evidence["preferred_work_title_found"] is not False:
            raise ValueError("no-existing-work classification requires visible list and missing preferred title")
        if evidence["route_decision"] != "NEEDS_FIXED_WORK_PREPARE":
            raise ValueError("no-existing-work route decision mismatch")
    return evidence


def choose_route(evidence: dict[str, Any]) -> WebRouteDecision:
    if evidence.get("classification") == "PASS":
        return WebRouteDecision.EXISTING_WORK_UI_RELAY_CANDIDATE
    if evidence.get("classification") == "NO_SUITABLE_EXISTING_WORK":
        return WebRouteDecision.NEEDS_FIXED_WORK_PREPARE
    return WebRouteDecision.UNKNOWN
