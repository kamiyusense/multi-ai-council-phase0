"""Bounded Jules Session GET transport for ``JulesDirectReadbackAuthenticator``.

Implements only the ``JulesSessionReader.read_session`` protocol. It performs
one GET, no retry, no redirect, bounded time/size, rejects duplicate JSON keys,
and returns only the whitelisted fields the authenticator checks. Any failure
returns ``None`` (fail closed). It never stores or reports the credential: the
key comes from an injected provider and is read per call.

Nothing in the repository wires this to a real key or opener; using it live
needs the separately approved trust-source/secret decision.
"""
from __future__ import annotations

import json
from typing import Any, Callable
from urllib.request import HTTPRedirectHandler, Request, build_opener

_BASE_URL = "https://jules.googleapis.com/v1alpha/sessions/"
_MAX_BYTES = 1024 * 1024
_TIMEOUT_SECONDS = 30


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect blocked; no credential forwarding")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class JulesSessionApiReader:
    def __init__(self, *, api_key_provider: Callable[[], str], opener: Any = None):
        if not callable(api_key_provider):
            raise ValueError("api_key_provider must be callable")
        self._key_provider = api_key_provider
        self._opener = opener if opener is not None else build_opener(_NoRedirect())

    def __repr__(self) -> str:
        return "JulesSessionApiReader(credential=<hidden>)"

    def read_session(self, session_id: str) -> dict[str, Any] | None:
        try:
            if not isinstance(session_id, str) or not session_id.isascii() or not session_id.isdigit():
                return None
            key = self._key_provider()
            if not isinstance(key, str) or not key or "\r" in key or "\n" in key:
                return None
            request = Request(
                _BASE_URL + session_id, method="GET", headers={"X-Goog-Api-Key": key}
            )
            with self._opener.open(request, timeout=_TIMEOUT_SECONDS) as response:
                if getattr(response, "status", None) != 200:
                    return None
                raw = response.read(_MAX_BYTES + 1)
            if not isinstance(raw, (bytes, bytearray)) or len(raw) > _MAX_BYTES:
                return None
            data = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
            if not isinstance(data, dict) or data.get("name") != f"sessions/{session_id}":
                return None
            return _whitelist(data)
        except Exception:
            # Deliberately broad and silent: no retry, no credential-bearing detail.
            return None


def _whitelist(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only identity/time/state/source fields; drop outputs and private URLs."""
    result: dict[str, Any] = {"name": data["name"]}
    for field in ("id", "createTime", "updateTime", "state"):
        value = _str_or_none(data.get(field))
        if value is not None:
            result[field] = value
    context = data.get("sourceContext")
    if isinstance(context, dict):
        safe: dict[str, Any] = {}
        source = _str_or_none(context.get("source"))
        if source is not None:
            safe["source"] = source
        repo_context = context.get("githubRepoContext")
        if isinstance(repo_context, dict):
            branch = _str_or_none(repo_context.get("startingBranch"))
            if branch is not None:
                safe["githubRepoContext"] = {"startingBranch": branch}
        result["sourceContext"] = safe
    return result
