import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

CLAUDE_AUTO_ORIGIN_BINDING_PROFILE = "CLAUDE_AUTO_ORIGIN_BINDING_V1"

REQUIRED_KEYS = {
    "schema_version",
    "profile",
    "origin_loop_id",
    "origin_round",
    "origin_correlation_id",
    "origin_generation",
    "carrier_request_schema_version",
    "carrier_request_profile",
    "carrier_claim_schema_version",
    "command_id",
    "claim_loop_id",
    "target_repo",
    "target_branch",
    "work_branch",
    "expected_target_head",
    "expected_target_tree",
    "created_at",
    "expires_at",
    "retry",
    "fallback",
    "binding_sha256",
}

SAFE_STRING_RE = re.compile(r"^[\x21-\x7E](?:[\x20-\x7E]*[\x21-\x7E])?$")
COMMAND_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BINDING_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

MAX_LIFETIME = timedelta(hours=2)


def _check_string(val: Any, name: str, regex: re.Pattern | None = None) -> None:
    if not isinstance(val, str):
        raise ValueError(f"{name} must be a string")
    if not val:
        raise ValueError(f"{name} cannot be empty")
    if not SAFE_STRING_RE.match(val):
        raise ValueError(f"{name} contains control characters or ambiguous whitespace")
    if regex and not regex.match(val):
        raise ValueError(f"{name} format is invalid")


def _check_int(val: Any, name: str) -> None:
    if type(val) is bool or not isinstance(val, int):
        raise ValueError(f"{name} must be a real integer")
    if val < 1:
        raise ValueError(f"{name} must be >= 1")


def _parse_time(val: Any, name: str) -> datetime:
    _check_string(val, name)
    try:
        parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def compute_binding_sha256(record: dict[str, Any]) -> str:
    temp = {k: v for k, v in record.items() if k != "binding_sha256"}
    payload = json.dumps(temp, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_binding_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("record must be a dict")

    keys = set(record)
    if keys != REQUIRED_KEYS:
        missing = sorted(REQUIRED_KEYS - keys)
        extra = sorted(keys - REQUIRED_KEYS)
        raise ValueError(f"record keys mismatch: missing={missing} extra={extra}")

    if record["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    if record["profile"] != CLAUDE_AUTO_ORIGIN_BINDING_PROFILE:
        raise ValueError("invalid profile")

    if record["carrier_request_schema_version"] != 2:
        raise ValueError("carrier_request_schema_version must be 2")
    if record["carrier_request_profile"] != "JULES_CHAT_SEMIAUTO_V2":
        raise ValueError("carrier_request_profile must be JULES_CHAT_SEMIAUTO_V2")
    if record["carrier_claim_schema_version"] != 3:
        raise ValueError("carrier_claim_schema_version must be 3")

    _check_string(record["origin_loop_id"], "origin_loop_id")
    _check_string(record["origin_correlation_id"], "origin_correlation_id")
    _check_int(record["origin_round"], "origin_round")
    _check_int(record["origin_generation"], "origin_generation")

    _check_string(record["command_id"], "command_id", COMMAND_ID_RE)
    _check_string(record["claim_loop_id"], "claim_loop_id")
    _check_string(record["target_repo"], "target_repo", REPO_RE)
    _check_string(record["target_branch"], "target_branch", BRANCH_RE)
    _check_string(record["work_branch"], "work_branch", BRANCH_RE)
    _check_string(record["expected_target_head"], "expected_target_head", SHA_RE)
    _check_string(record["expected_target_tree"], "expected_target_tree", SHA_RE)

    created_dt = _parse_time(record["created_at"], "created_at")
    expires_dt = _parse_time(record["expires_at"], "expires_at")

    if expires_dt <= created_dt:
        raise ValueError("expires_at must be after created_at")
    if expires_dt - created_dt > MAX_LIFETIME:
        raise ValueError("lifetime exceeds maximum allowed")

    if record["retry"] != 0:
        raise ValueError("retry must be 0")
    if record["fallback"] != "disabled":
        raise ValueError("fallback must be disabled")

    _check_string(record["binding_sha256"], "binding_sha256", BINDING_SHA_RE)

    computed_sha = compute_binding_sha256(record)
    if computed_sha != record["binding_sha256"]:
        raise ValueError("binding_sha256 digest mismatch")

    return dict(record)


def build_binding_record(
    origin_loop_id: str,
    origin_round: int,
    origin_correlation_id: str,
    origin_generation: int,
    carrier_request: dict[str, Any],
    carrier_claim: dict[str, Any],
) -> dict[str, Any]:
    try:
        if carrier_request.get("command_id") != carrier_claim.get("command_id"):
            raise ValueError("request/claim command_id mismatch")
        if carrier_request.get("target_branch") != carrier_claim.get("target_branch"):
            raise ValueError("request/claim target_branch mismatch")
        if carrier_request.get("expected_target_head") != carrier_claim.get("expected_target_head"):
            raise ValueError("request/claim expected_target_head mismatch")
        if carrier_request.get("expected_target_tree") != carrier_claim.get("expected_target_tree"):
            raise ValueError("request/claim expected_target_tree mismatch")
        if carrier_request.get("work_branch") != carrier_claim.get("work_branch"):
            raise ValueError("request/claim work_branch mismatch")
        if carrier_request.get("retry") != carrier_claim.get("retry"):
            raise ValueError("request/claim retry mismatch")
        if carrier_request.get("fallback") != carrier_claim.get("fallback"):
            raise ValueError("request/claim fallback mismatch")

        record = {
            "schema_version": 1,
            "profile": CLAUDE_AUTO_ORIGIN_BINDING_PROFILE,
            "origin_loop_id": origin_loop_id,
            "origin_round": origin_round,
            "origin_correlation_id": origin_correlation_id,
            "origin_generation": origin_generation,
            "carrier_request_schema_version": carrier_request["schema_version"],
            "carrier_request_profile": carrier_request["profile"],
            "carrier_claim_schema_version": carrier_claim["schema_version"],
            "command_id": carrier_request["command_id"],
            "claim_loop_id": carrier_claim["loop_id"],
            "target_repo": carrier_request["target_repo"],
            "target_branch": carrier_request["target_branch"],
            "work_branch": carrier_request["work_branch"],
            "expected_target_head": carrier_request["expected_target_head"],
            "expected_target_tree": carrier_request["expected_target_tree"],
            "created_at": carrier_request["created_at"],
            "expires_at": carrier_request["expires_at"],
            "retry": carrier_request["retry"],
            "fallback": carrier_request["fallback"],
        }
    except KeyError as exc:
        raise ValueError(f"missing required field in carrier request/claim: {exc.args[0]}") from None

    record["binding_sha256"] = compute_binding_sha256(record)
    return validate_binding_record(record)


def verify_binding_record(
    record: dict[str, Any],
    carrier_request: dict[str, Any],
    carrier_claim: dict[str, Any],
) -> dict[str, Any]:
    validated = validate_binding_record(record)

    try:
        if validated["carrier_request_schema_version"] != carrier_request["schema_version"]:
            raise ValueError("request schema mismatch")
        if validated["carrier_request_profile"] != carrier_request["profile"]:
            raise ValueError("request profile mismatch")
        if validated["carrier_claim_schema_version"] != carrier_claim["schema_version"]:
            raise ValueError("claim schema mismatch")

        if validated["command_id"] != carrier_request["command_id"]:
            raise ValueError("request command_id mismatch")
        if validated["command_id"] != carrier_claim["command_id"]:
            raise ValueError("claim command_id mismatch")

        if validated["claim_loop_id"] != carrier_claim["loop_id"]:
            raise ValueError("claim loop_id mismatch")

        if validated["target_repo"] != carrier_request["target_repo"]:
            raise ValueError("request target_repo mismatch")

        if validated["target_branch"] != carrier_request["target_branch"]:
            raise ValueError("request target_branch mismatch")
        if validated["target_branch"] != carrier_claim["target_branch"]:
            raise ValueError("claim target_branch mismatch")

        if validated["work_branch"] != carrier_request["work_branch"]:
            raise ValueError("request work_branch mismatch")
        if validated["work_branch"] != carrier_claim["work_branch"]:
            raise ValueError("claim work_branch mismatch")

        if validated["expected_target_head"] != carrier_request["expected_target_head"]:
            raise ValueError("request expected_target_head mismatch")
        if validated["expected_target_head"] != carrier_claim["expected_target_head"]:
            raise ValueError("claim expected_target_head mismatch")

        if validated["expected_target_tree"] != carrier_request["expected_target_tree"]:
            raise ValueError("request expected_target_tree mismatch")
        if validated["expected_target_tree"] != carrier_claim["expected_target_tree"]:
            raise ValueError("claim expected_target_tree mismatch")

        if validated["created_at"] != carrier_request["created_at"]:
            raise ValueError("request created_at mismatch")
        if validated["expires_at"] != carrier_request["expires_at"]:
            raise ValueError("request expires_at mismatch")

        if validated["retry"] != carrier_request["retry"]:
            raise ValueError("request retry mismatch")
        if validated["retry"] != carrier_claim["retry"]:
            raise ValueError("claim retry mismatch")

        if validated["fallback"] != carrier_request["fallback"]:
            raise ValueError("request fallback mismatch")
        if validated["fallback"] != carrier_claim["fallback"]:
            raise ValueError("claim fallback mismatch")
    except KeyError as exc:
        raise ValueError(f"missing field in carrier request/claim: {exc.args[0]}") from None

    return validated
