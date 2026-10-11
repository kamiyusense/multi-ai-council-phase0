"""Jules API route: find the Jules session id of a Jules PR, pure helpers only.

Placeholder for objective o2-jules-api-requests (docs/CLAUDE_JULES_API_ROUTE_V1.md).  No network, no key.
"""
from __future__ import annotations

import re

_URL_PATTERN = re.compile(r"([a-zA-Z0-9+.-]+://[^\s\)\],>\"']+)")


def session_id_of_pr(body: str | None) -> str | None:
    """Return the numeric session id as a string when body contains exactly one distinct id
    in https://jules.google.com/task/ links; return None for no link, two different ids,
    a non-digit id, a non-https or other host URL, or None/empty input.
    """
    if not body or not isinstance(body, str):
        return None

    urls = _URL_PATTERN.findall(body)
    task_urls = []
    for u in urls:
        cleaned = u.rstrip(".,;:!?")
        if "/task/" in cleaned:
            task_urls.append(cleaned)

    if not task_urls:
        return None

    ids = set()
    for u in task_urls:
        if not u.startswith("https://"):
            return None
        if not u.startswith("https://jules.google.com/task/"):
            return None
        rest = u[len("https://jules.google.com/task/"):]
        if not rest or not rest.isdigit():
            return None
        ids.add(rest)

    if len(ids) == 1:
        return next(iter(ids))
    return None
