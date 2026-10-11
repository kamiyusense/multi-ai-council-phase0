"""Jules API route: the session status request file (one GET), pure helpers only.

Placeholder for objective o2-jules-api-requests (docs/CLAUDE_JULES_API_ROUTE_V1.md).  The request format is the
one `.github/workflows/jules-session-readback.yml` reads.  No network, no key.
"""
from __future__ import annotations

import re
from typing import Any

SESSION_ID_RE = re.compile(r"^[0-9]+$")
REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def validate_status_request(obj: Any) -> list[str]:
    """Validate a session status request object, returning a list of problem strings.

    An empty list indicates the object is valid.
    Rules mirror `.github/workflows/jules-session-readback.yml`:
    - `obj` must be a dict
    - `session_id`: required str matching ^[0-9]+$
    - `include_activities`: when present, must be a bool (not str or int)
    - no other keys allowed
    """
    if not isinstance(obj, dict):
        return ["request must be a dict"]

    problems: list[str] = []
    allowed_keys = {"session_id", "include_activities"}
    extra_keys = sorted(set(obj.keys()) - allowed_keys)
    if extra_keys:
        problems.append(f"unexpected keys: {', '.join(extra_keys)}")

    if "session_id" not in obj:
        problems.append("missing required key: session_id")
    else:
        session_id = obj["session_id"]
        if not isinstance(session_id, str):
            problems.append("session_id must be a str")
        elif not SESSION_ID_RE.fullmatch(session_id):
            problems.append(f"invalid session_id: {session_id!r}")

    if "include_activities" in obj:
        include_activities = obj["include_activities"]
        if type(include_activities) is not bool:
            problems.append("include_activities must be a bool")

    return problems


def build_status_request(session_id: str, include_activities: bool = True) -> dict[str, Any]:
    """Build a session status request dict and validate it.

    Raises ValueError if the constructed request is invalid.
    """
    req = {
        "session_id": session_id,
        "include_activities": include_activities,
    }
    problems = validate_status_request(req)
    if problems:
        raise ValueError(f"invalid status request: {'; '.join(problems)}")
    return req


def status_request_path(request_id: str) -> str:
    """Return the relative file path for a status request.

    Raises ValueError if request_id does not match ^[a-z0-9][a-z0-9._-]{0,63}$.
    """
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError(f"invalid request_id: {request_id!r}")
    return f"automation/command_bus/jules_api_status_requests/{request_id}.json"
