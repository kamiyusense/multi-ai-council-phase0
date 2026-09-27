"""Canonical durable provider observation used by Loop-owner projection."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_OWNER_ROLES = {"SEMI_AUTO", "AUTO"}
_ROOT = "automation/command_bus/loop_owner_observations"
_KEYS = {
    "schema_version", "observation_id", "loop_id", "owner_role", "holder_id",
    "generation", "fencing_token", "expected_repo", "expected_pr",
    "expected_target_head", "state", "evidence_ref", "observed_at", "expires_at",
    "verified",
}


def provider_observation_path(loop_id: str, generation: int) -> str:
    if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
        raise ValueError("unsafe loop_id")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("generation must be a positive integer")
    return f"{_ROOT}/{loop_id}/{generation:06d}.json"


def validate_provider_observation(observation: dict[str, Any]) -> None:
    if not isinstance(observation, dict) or set(observation) != _KEYS:
        raise ValueError("provider observation is malformed")
    if isinstance(observation["schema_version"], bool) or observation["schema_version"] != 1:
        raise ValueError("unsupported provider observation schema")
    if not _COMPONENT.fullmatch(observation["observation_id"]):
        raise ValueError("unsafe observation_id")
    if not _LOOP_ID.fullmatch(observation["loop_id"]):
        raise ValueError("unsafe loop_id")
    if observation["owner_role"] not in _OWNER_ROLES:
        raise ValueError("invalid owner_role")
    if not _COMPONENT.fullmatch(observation["holder_id"]):
        raise ValueError("unsafe holder_id")
    generation = observation["generation"]
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("invalid generation")
    if isinstance(observation["fencing_token"], bool) or observation["fencing_token"] != generation:
        raise ValueError("fencing token must equal generation")
    if not isinstance(observation["expected_repo"], str) or "/" not in observation["expected_repo"]:
        raise ValueError("invalid expected_repo")
    if isinstance(observation["expected_pr"], bool) or not isinstance(observation["expected_pr"], int) or observation["expected_pr"] < 1:
        raise ValueError("invalid expected_pr")
    if not isinstance(observation["expected_target_head"], str) or not _HEX40.fullmatch(observation["expected_target_head"]):
        raise ValueError("invalid expected_target_head")
    if not isinstance(observation["state"], str) or not observation["state"].strip():
        raise ValueError("provider state is missing")
    if not isinstance(observation["evidence_ref"], str) or not observation["evidence_ref"].strip():
        raise ValueError("provider evidence_ref is missing")
    observed = _time(observation["observed_at"])
    expires = _time(observation["expires_at"])
    if expires <= observed:
        raise ValueError("provider observation expiry must follow observation time")
    if not isinstance(observation["verified"], bool):
        raise ValueError("verified must be boolean")


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed
