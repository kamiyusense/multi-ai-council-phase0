"""Jules API route: the message request file (sendMessage), pure helpers only.

Standard library only.  The request format is the one
`.github/workflows/jules-session-message.yml` reads.  No network, no key.
"""

from __future__ import annotations

import re
from typing import Any

SESSION_ID_RE = re.compile(r"^[0-9]+$")
REQUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ALLOWED_EXPECTED_STATES = {"AWAITING_USER_FEEDBACK", "COMPLETED"}
REQUIRED_KEYS = {"session_id", "expected_state", "prompt"}


def validate_message_request(obj: Any) -> list[str]:
    """Validates a message request object. Returns a list of problem strings (empty if valid)."""
    problems: list[str] = []

    if not isinstance(obj, dict):
        return ["request must be a dict"]

    obj_keys = set(obj.keys())
    if obj_keys != REQUIRED_KEYS:
        missing = sorted(REQUIRED_KEYS - obj_keys)
        extra = sorted(obj_keys - REQUIRED_KEYS)
        if missing:
            problems.append(f"missing required key(s): {', '.join(missing)}")
        if extra:
            problems.append(f"unexpected extra key(s): {', '.join(extra)}")

    session_id = obj.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID_RE.match(session_id):
        problems.append("session_id must be a numeric string matching ^[0-9]+$")

    expected_state = obj.get("expected_state")
    if expected_state not in ALLOWED_EXPECTED_STATES:
        problems.append("expected_state must be 'AWAITING_USER_FEEDBACK' or 'COMPLETED'")

    prompt = obj.get("prompt")
    if not isinstance(prompt, str) or len(prompt) == 0 or len(prompt) > 4000:
        problems.append("prompt must be a non-empty string of at most 4000 characters")

    return problems


def build_message_request(session_id: Any, prompt: Any, expected_state: Any) -> dict[str, Any]:
    """Builds and validates a message request dictionary.

    Raises ValueError if the resulting request is invalid.
    """
    req = {
        "session_id": session_id,
        "expected_state": expected_state,
        "prompt": prompt,
    }
    problems = validate_message_request(req)
    if problems:
        raise ValueError("; ".join(problems))
    return req


def message_request_path(request_id: str) -> str:
    """Returns the carrier request file path for a request_id.

    Raises ValueError if request_id does not match the workflow's path rule.
    """
    if not isinstance(request_id, str) or not REQUEST_ID_RE.match(request_id):
        raise ValueError(f"invalid request_id: {request_id!r}")
    return f"automation/command_bus/jules_api_message_requests/{request_id}.json"
