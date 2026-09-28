"""Validate Jules Create Session response timing for Semi-Auto presentation.

The Jules REST API Session resource exposes output-only createTime. A successful
Create Session response that also passes the existing session-name and starting-
branch checks may use that provider timestamp as the presentation source for
accepted_at.

This module does not call Jules, GitHub, or any provider. It only validates an
already-captured response file and normalizes createTime to UTC and JST.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SESSION_NAME = re.compile(r"^sessions/[0-9]+$")
_JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class JulesSessionAcceptance:
    source_kind: str
    session_name: str
    session_id: str
    starting_branch: str
    session_create_time: str
    accepted_at_jst: str


def extract_session_acceptance(
    response: dict[str, Any],
    *,
    expected_branch: str,
) -> JulesSessionAcceptance:
    if not isinstance(response, dict):
        raise ValueError("Jules Create Session response must be an object")
    if not isinstance(expected_branch, str) or not expected_branch:
        raise ValueError("expected starting branch is required")

    session_name = response.get("name")
    if not isinstance(session_name, str) or not _SESSION_NAME.fullmatch(session_name):
        raise ValueError("malformed Jules session name")

    try:
        starting_branch = response["sourceContext"]["githubRepoContext"]["startingBranch"]
    except (TypeError, KeyError) as exc:
        raise ValueError("Jules starting branch is unavailable") from exc
    if starting_branch != expected_branch:
        raise ValueError("Jules returned starting branch mismatch")

    create_time = _parse_provider_time(response.get("createTime"))
    create_utc = create_time.astimezone(timezone.utc)
    create_jst = create_time.astimezone(_JST)

    return JulesSessionAcceptance(
        source_kind="JULES_CREATE_SESSION_RESPONSE_CREATE_TIME",
        session_name=session_name,
        session_id=session_name.removeprefix("sessions/"),
        starting_branch=starting_branch,
        session_create_time=_canonical_utc(create_utc),
        accepted_at_jst=create_jst.isoformat(timespec="seconds"),
    )


def load_session_acceptance(
    response_path: str | Path,
    *,
    expected_branch: str,
) -> JulesSessionAcceptance:
    path = Path(response_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    return extract_session_acceptance(value, expected_branch=expected_branch)


def _parse_provider_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("Jules Session createTime is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Jules Session createTime is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Jules Session createTime must include timezone")
    return parsed


def _canonical_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit("usage: python -m automation.command_bus.jules_session_acceptance RESPONSE_JSON EXPECTED_BRANCH")
    result = load_session_acceptance(args[0], expected_branch=args[1])
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
