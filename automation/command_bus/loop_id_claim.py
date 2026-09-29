from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

LOOP_COMMAND_RE = re.compile(
    r"^relay-dev-loop-(?P<loop_id>[0-9]{3,6})-(?P<task_id>[a-z0-9][a-z0-9._-]{0,63})$"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LEGACY_LANE_ID_RE = re.compile(r"^J-[A-Z0-9][A-Z0-9-]{0,15}$")
LEGACY_LANE_DISPLAYS = {"🟥", "🟦", "🟩", "🟨"}
LANE_DISPLAY_BY_ID = {
    "J-RED": "❤️",
    "J-BLUE": "💙",
    "J-YELLOW": "💛",
    "J-GREEN": "💚",
}
LANE_ALIASES = {
    "JA": "J-RED",
    "JB": "J-BLUE",
    "JC": "J-YELLOW",
    "RED": "J-RED",
    "BLUE": "J-BLUE",
    "YELLOW": "J-YELLOW",
    "GREEN": "J-GREEN",
    "❤️": "J-RED",
    "💙": "J-BLUE",
    "💛": "J-YELLOW",
    "💚": "J-GREEN",
}
DISPATCH_CLAIM_SCHEMA_VERSION = 3
DUPLICATE_GUARD = "one file per loop number; create-only; if exists choose a new number"

V1_REQUIRED_KEYS = {
    "schema_version",
    "loop_number",
    "loop_id",
    "task_id",
    "command_id",
    "target_branch",
    "expected_target_head",
    "work_branch",
    "state",
    "claimed_at",
    "duplicate_guard",
    "retry",
    "fallback",
}

V2_REQUIRED_KEYS = V1_REQUIRED_KEYS | {
    "lane_id",
    "lane_display",
    "expected_target_tree",
}
V3_REQUIRED_KEYS = V2_REQUIRED_KEYS

DISPATCHABLE_STATE = "CLAIMED"
ARCHIVAL_STATES = {"CLAIMED", "HISTORICAL_BACKFILL"}


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed


def _validate_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def normalize_lane_alias(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("lane alias must be a non-empty string")
    normalized = value.strip().upper()
    if value.strip() in LANE_ALIASES:
        return LANE_ALIASES[value.strip()]
    if normalized in LANE_ALIASES:
        return LANE_ALIASES[normalized]
    if normalized in LANE_DISPLAY_BY_ID:
        return normalized
    raise ValueError("unknown Jules lane alias")


def lane_display_for(lane_id: str) -> str:
    try:
        return LANE_DISPLAY_BY_ID[lane_id]
    except KeyError as exc:
        raise ValueError("unknown Jules lane_id") from exc


def extract_numbered_loop(command_id: Any) -> tuple[str, str] | None:
    if not isinstance(command_id, str):
        return None
    match = LOOP_COMMAND_RE.fullmatch(command_id)
    if match is None:
        return None
    return match.group("loop_id"), match.group("task_id")


def claim_filename(loop_id: str) -> str:
    if not isinstance(loop_id, str) or not re.fullmatch(r"[0-9]{3,6}", loop_id):
        raise ValueError("invalid loop_id")
    return f"{loop_id}.json"


def validate_claim(claim: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(claim, dict):
        raise ValueError("claim must be an object")

    schema_version = claim.get("schema_version")
    if schema_version == 1:
        required = V1_REQUIRED_KEYS
    elif schema_version == 2:
        required = V2_REQUIRED_KEYS
    elif schema_version == 3:
        required = V3_REQUIRED_KEYS
    else:
        raise ValueError("unsupported claim schema_version")

    keys = set(claim)
    if keys != required:
        missing = sorted(required - keys)
        extra = sorted(keys - required)
        raise ValueError(f"claim keys mismatch missing={missing} extra={extra}")

    loop_number = claim["loop_number"]
    if isinstance(loop_number, bool) or not isinstance(loop_number, int) or loop_number < 0:
        raise ValueError("invalid loop_number")

    loop_id = claim["loop_id"]
    if not isinstance(loop_id, str) or not re.fullmatch(r"[0-9]{3,6}", loop_id):
        raise ValueError("invalid loop_id")
    if int(loop_id) != loop_number:
        raise ValueError("loop_number/loop_id mismatch")

    command_id = claim["command_id"]
    parsed = extract_numbered_loop(command_id)
    if parsed is None:
        raise ValueError("claim command_id must be a numbered Relay loop")
    command_loop_id, command_task_id = parsed
    if command_loop_id != loop_id:
        raise ValueError("claim loop_id/command_id mismatch")
    if claim["task_id"] != command_task_id:
        raise ValueError("claim task_id/command_id mismatch")

    expected_work_branch = f"jules-work/{command_id}"
    if claim["work_branch"] != expected_work_branch:
        raise ValueError("claim work_branch/command_id mismatch")
    if not isinstance(claim["target_branch"], str) or not claim["target_branch"]:
        raise ValueError("claim target_branch required")

    _validate_sha(claim["expected_target_head"], "expected_target_head")
    if schema_version in {2, 3}:
        _validate_sha(claim["expected_target_tree"], "expected_target_tree")

    if schema_version == 2:
        if (
            not isinstance(claim["lane_id"], str)
            or not LEGACY_LANE_ID_RE.fullmatch(claim["lane_id"])
        ):
            raise ValueError("invalid legacy lane_id")
        if claim["lane_display"] not in LEGACY_LANE_DISPLAYS:
            raise ValueError("invalid legacy lane_display")

    if schema_version == 3:
        lane_id = claim["lane_id"]
        if lane_id not in LANE_DISPLAY_BY_ID:
            raise ValueError("invalid lane_id")
        if claim["lane_display"] != lane_display_for(lane_id):
            raise ValueError("lane_id/lane_display mismatch")

    if claim["state"] not in ARCHIVAL_STATES:
        raise ValueError("invalid claim state")
    _parse_time(claim["claimed_at"], "claimed_at")

    if claim["duplicate_guard"] != DUPLICATE_GUARD:
        raise ValueError("duplicate_guard mismatch")
    if claim["retry"] != 0 or claim["fallback"] != "disabled":
        raise ValueError("claim retry/fallback policy mismatch")

    return claim


def verify_command_claim(
    request: dict[str, Any],
    claim: dict[str, Any],
    *,
    require_dispatchable_current: bool = True,
) -> dict[str, Any]:
    parsed = extract_numbered_loop(request.get("command_id"))
    if parsed is None:
        raise ValueError("request is not a numbered Relay loop")

    validated = validate_claim(claim)
    loop_id, _ = parsed

    if validated["loop_id"] != loop_id:
        raise ValueError("command/claim loop_id mismatch")
    if validated["command_id"] != request.get("command_id"):
        raise ValueError("command/claim command_id mismatch")
    if validated["target_branch"] != request.get("target_branch"):
        raise ValueError("command/claim target_branch mismatch")
    if validated["expected_target_head"] != request.get("expected_target_head"):
        raise ValueError("command/claim expected_target_head mismatch")
    if validated["work_branch"] != request.get("work_branch"):
        raise ValueError("command/claim work_branch mismatch")
    if validated["retry"] != request.get("retry") or validated["fallback"] != request.get("fallback"):
        raise ValueError("command/claim retry/fallback mismatch")

    if require_dispatchable_current:
        if validated["schema_version"] != DISPATCH_CLAIM_SCHEMA_VERSION:
            raise ValueError(
                f"numbered dispatch requires claim schema_version "
                f"{DISPATCH_CLAIM_SCHEMA_VERSION}"
            )
        if validated["state"] != DISPATCHABLE_STATE:
            raise ValueError("numbered dispatch requires a pre-dispatch CLAIMED claim")
        if validated["expected_target_tree"] != request.get("expected_target_tree"):
            raise ValueError("command/claim expected_target_tree mismatch")

    return validated


def verify_claim_file(
    request_path: str | Path,
    claims_dir: str | Path,
    *,
    require_dispatchable_current: bool = True,
) -> dict[str, Any] | None:
    request_path = Path(request_path)
    claims_dir = Path(claims_dir)

    with request_path.open(encoding="utf-8") as stream:
        request = json.load(stream)

    parsed = extract_numbered_loop(request.get("command_id"))
    if parsed is None:
        return None

    loop_id, _ = parsed
    path = claims_dir / claim_filename(loop_id)
    if not path.is_file():
        raise ValueError(f"missing durable Loop claim: {path.as_posix()}")

    with path.open(encoding="utf-8") as stream:
        claim = json.load(stream)

    return verify_command_claim(
        request,
        claim,
        require_dispatchable_current=require_dispatchable_current,
    )


def _write_github_output(path: str, claim: dict[str, Any] | None) -> None:
    with open(path, "a", encoding="utf-8") as stream:
        if claim is None:
            stream.write("loop_claim_required=false\n")
            stream.write("loop_id=\n")
            stream.write("lane_id=\n")
            stream.write("lane_display=\n")
            return
        stream.write("loop_claim_required=true\n")
        stream.write(f"loop_id={claim['loop_id']}\n")
        stream.write(f"lane_id={claim.get('lane_id', '')}\n")
        stream.write(f"lane_display={claim.get('lane_display', '')}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request_path")
    parser.add_argument(
        "--claims-dir",
        default="automation/command_bus/loop_id_claims",
    )
    parser.add_argument("--github-output")
    parser.add_argument(
        "--allow-legacy-or-backfill",
        action="store_true",
        help="archive/readback mode only; never use for live dispatch",
    )
    args = parser.parse_args()

    claim = verify_claim_file(
        args.request_path,
        args.claims_dir,
        require_dispatchable_current=not args.allow_legacy_or_backfill,
    )
    if args.github_output:
        _write_github_output(args.github_output, claim)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
