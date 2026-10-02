"""One read-only Jules Session GET -> sanitized evidence (SF-8 transport proof).

Runs once inside a GitHub Actions job. The API key comes only from the
JULES_API_KEY environment variable (an existing Actions secret), is handed to the
reader through a provider callable, and is never printed, stored or put into an
exception. The evidence holds only non-secret session facts and bound context.
It does not prove owner authority, durable ownership, or active-provider state.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .jules_session_api_reader import JulesSessionApiReader

_SHA = re.compile(r"^[0-9a-f]{40}$")
_STATE = re.compile(r"^[A-Z_]{1,48}$")


def _second(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def build_evidence(
    *, session: dict[str, Any] | None, session_id: str, repository: str,
    expected_branch: str, expected_create_time: str, run_id: str, run_attempt: str,
    commit_sha: str, observed_at: str,
) -> dict[str, Any]:
    context = (session or {}).get("sourceContext") if isinstance(session, dict) else None
    repo_context = context.get("githubRepoContext") if isinstance(context, dict) else None
    state = (session or {}).get("state") if isinstance(session, dict) else None
    checks = {
        "name_match": isinstance(session, dict) and session.get("name") == f"sessions/{session_id}",
        "source_match": isinstance(context, dict) and context.get("source") == f"sources/github/{repository}",
        "branch_match": isinstance(repo_context, dict) and repo_context.get("startingBranch") == expected_branch,
        "create_time_match": isinstance(session, dict)
        and _second(session.get("createTime")) is not None
        and _second(session.get("createTime")) == _second(expected_create_time),
    }
    if session is None:
        status, category = "UNKNOWN", "READ_FAILED"
    elif all(checks.values()):
        status, category = "PASS", "NONE"
    else:
        status, category = "UNKNOWN", "BINDING_MISMATCH"
    body = {
        "schema_version": 1,
        "proof_kind": "JULES_SESSION_GET_READBACK",
        "status": status,
        "error_category": category,
        "http_method": "GET",
        "retry_count": 0,
        "repository": repository,
        "session_id": session_id,
        "raw_state": state if isinstance(state, str) and _STATE.fullmatch(state) else "UNKNOWN",
        "create_time": (session or {}).get("createTime") if isinstance(session, dict) and isinstance(session.get("createTime"), str) else None,
        "update_time": (session or {}).get("updateTime") if isinstance(session, dict) and isinstance(session.get("updateTime"), str) else None,
        "source": context.get("source") if isinstance(context, dict) and isinstance(context.get("source"), str) else None,
        "starting_branch": repo_context.get("startingBranch") if isinstance(repo_context, dict) and isinstance(repo_context.get("startingBranch"), str) else None,
        "binding_checks": checks,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "exact_commit_sha": commit_sha,
        "observed_at": observed_at,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {**body, "evidence_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def run(
    env: dict[str, str], *, reader_factory: Callable[[Callable[[], str]], Any] | None = None,
    now: Callable[[], str] | None = None,
) -> tuple[dict[str, Any], int]:
    session_id = env.get("SF8_SESSION_ID", "")
    if not (session_id.isascii() and session_id.isdigit()):
        raise ValueError("invalid session id")
    run_id, attempt, sha = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", ""), env.get("GITHUB_SHA", "")
    if not run_id.isdigit() or attempt != "1" or not _SHA.fullmatch(sha):
        raise ValueError("invalid runner context")
    factory = reader_factory or (lambda provider: JulesSessionApiReader(api_key_provider=provider))
    reader = factory(lambda: env.get("JULES_API_KEY", ""))
    session = reader.read_session(session_id)  # exactly one GET; no retry
    observed_at = (now or (lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))()
    evidence = build_evidence(
        session=session, session_id=session_id, repository=env.get("GITHUB_REPOSITORY", ""),
        expected_branch=env.get("SF8_EXPECTED_BRANCH", ""), expected_create_time=env.get("SF8_EXPECTED_CREATE_TIME", ""),
        run_id=run_id, run_attempt=attempt, commit_sha=sha, observed_at=observed_at,
    )
    return evidence, 0 if evidence["status"] == "PASS" else 1


def main() -> int:
    try:
        evidence, code = run(dict(os.environ))
    except Exception:
        sys.stdout.write("JULES_GET_UNKNOWN error_category=INVALID_INPUT\n")
        return 1
    out = Path(os.environ.get("RUNNER_TEMP", ".")) / "jules-get-evidence.json"
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write("JULES_GET_EVIDENCE " + json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
