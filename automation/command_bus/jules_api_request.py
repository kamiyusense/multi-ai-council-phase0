from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any

PROFILE = "JULES_CHAT_SEMIAUTO_V1"
TARGET_REPO = "kamiyusense/multi-ai-council-phase0"
MAX_PROMPT_CHARS = 12000
MAX_LIFETIME = timedelta(hours=2)
COMMAND_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
REQUIRED_KEYS = {
    "schema_version",
    "profile",
    "command_id",
    "target_repo",
    "target_branch",
    "expected_target_head",
    "expected_target_tree",
    "allowed_paths",
    "prompt",
    "created_at",
    "expires_at",
    "retry",
    "fallback",
    "merge_allowed",
    "force_push_allowed",
}


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _validate_branch(branch: Any) -> str:
    if not isinstance(branch, str) or not branch:
        raise ValueError("target_branch required")
    if branch in {"main", "master"}:
        raise ValueError("default branch dispatch is forbidden")
    if not BRANCH_RE.fullmatch(branch) or branch.startswith("/") or branch.endswith("/"):
        raise ValueError("invalid target_branch")
    if ".." in branch or "\\" in branch or branch.startswith("refs/"):
        raise ValueError("unsafe target_branch")
    return branch


def _validate_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("allowed path must be non-empty")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("./"):
        raise ValueError("unsafe allowed path")
    if "\\" in value or value.endswith("/"):
        raise ValueError("unsafe allowed path")
    return value


def validate_request(request: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    keys = set(request)
    if keys != REQUIRED_KEYS:
        missing = sorted(REQUIRED_KEYS - keys)
        extra = sorted(keys - REQUIRED_KEYS)
        raise ValueError(f"request keys mismatch missing={missing} extra={extra}")
    if request["schema_version"] != 1 or request["profile"] != PROFILE:
        raise ValueError("unsupported request profile")
    command_id = request["command_id"]
    if not isinstance(command_id, str) or not COMMAND_ID_RE.fullmatch(command_id):
        raise ValueError("invalid command_id")
    if request["target_repo"] != TARGET_REPO:
        raise ValueError("unexpected target_repo")
    _validate_branch(request["target_branch"])
    for field in ("expected_target_head", "expected_target_tree"):
        value = request[field]
        if not isinstance(value, str) or not SHA_RE.fullmatch(value):
            raise ValueError(f"invalid {field}")
    paths = request["allowed_paths"]
    if not isinstance(paths, list) or not paths or len(paths) > 20:
        raise ValueError("allowed_paths must contain 1..20 paths")
    normalized_paths = [_validate_path(item) for item in paths]
    if len(set(normalized_paths)) != len(normalized_paths):
        raise ValueError("duplicate allowed path")
    prompt = request["prompt"]
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS or "\x00" in prompt:
        raise ValueError("invalid prompt")
    created = _parse_time(request["created_at"], "created_at")
    expires = _parse_time(request["expires_at"], "expires_at")
    if expires <= created or expires - created > MAX_LIFETIME:
        raise ValueError("invalid request lifetime")
    check_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if check_now >= expires:
        raise ValueError("request expired")
    if request["retry"] != 0 or request["fallback"] != "disabled":
        raise ValueError("retry/fallback policy mismatch")
    if request["merge_allowed"] is not False or request["force_push_allowed"] is not False:
        raise ValueError("dangerous publication permission")
    return request


def build_jules_prompt(request: dict[str, Any]) -> str:
    validate_request(request)
    allowed = "\n".join(f"- {path}" for path in request["allowed_paths"])
    return f"""Multi-AI Council Phase 0 — bounded Chat->Jules API task.

Command ID: {request['command_id']}
Target repository: {request['target_repo']}
Exact starting branch: {request['target_branch']}
Expected starting HEAD: {request['expected_target_head']}
Expected starting tree: {request['expected_target_tree']}

Before editing, verify the checked-out starting HEAD is exactly the expected HEAD above. If it is not exact, make no edits and report the mismatch.

Allowed changed paths only:
{allowed}

Hard bounds:
- do not modify any path outside the allowlist
- do not merge
- do not force push
- do not delete branches
- do not change repository settings, permissions, billing, credits, secrets, or API keys
- do not retry or use fallback if an external action is ambiguous
- create the normal Jules pull request when the bounded task is complete

Task:
{request['prompt'].strip()}
"""


def _write_github_output(path: str, request: dict[str, Any]) -> None:
    prompt = build_jules_prompt(request)
    marker = "JULES_PROMPT_EOF_31D95F04"
    if marker in prompt:
        raise ValueError("prompt contains reserved output marker")
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(f"command_id={request['command_id']}\n")
        stream.write(f"target_branch={request['target_branch']}\n")
        stream.write(f"expected_target_head={request['expected_target_head']}\n")
        stream.write(f"expected_target_tree={request['expected_target_tree']}\n")
        stream.write(f"prompt<<{marker}\n{prompt}\n{marker}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request_path")
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args()
    with open(args.request_path, encoding="utf-8") as stream:
        request = json.load(stream)
    validate_request(request)
    _write_github_output(args.github_output, request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
