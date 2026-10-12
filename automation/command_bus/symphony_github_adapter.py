"""One-request-per-operation GitHub Contents client for executor persistence.

The existing ``GitHubExecutorBackend`` remains responsible for ledger shape,
append-only records, recovery, and post-write readback. This transport has no
retry behavior and never logs its token.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .executor_backend import ExecutorContent

API = "https://api.github.com"
_MAX_RESPONSE = 2 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubExecutorContentsClient:
    """Concrete contents adapter; every write makes one request and no retry."""

    def __init__(self, token: str, repository: str):
        if not isinstance(token, str) or not token or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
            raise ValueError("GitHub token unavailable")
        if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("repository must be owner/name")
        self._token = token
        self.repository = repository

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        payload = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        request = Request(f"{API}/repos/{self.repository}/{path}", data=payload, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        })
        opener = build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=30) as response:
                status, raw = response.status, response.read(_MAX_RESPONSE + 1)
        except HTTPError as exc:
            status, raw = exc.code, exc.read(_MAX_RESPONSE + 1) if exc.fp else b""
        if len(raw) > _MAX_RESPONSE:
            raise RuntimeError("GitHub response too large")
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, None

    def get(self, path: str, ref: str) -> ExecutorContent | None:
        status, body = self._request("GET", f"contents/{quote(path)}?ref={quote(ref, safe='')}")
        if status == 404:
            return None
        if status != 200 or not isinstance(body, dict) or body.get("type") != "file":
            raise RuntimeError("GitHub contents read failed")
        try:
            text = base64.b64decode(body["content"], validate=False).decode("utf-8")
            sha = body["sha"]
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("GitHub contents response malformed") from exc
        return ExecutorContent(path, text, sha)

    def list(self, prefix: str, ref: str) -> list[ExecutorContent]:
        status, body = self._request("GET", f"contents/{quote(prefix.rstrip('/'))}?ref={quote(ref, safe='')}")
        if status == 404:
            return []
        if status != 200 or not isinstance(body, list):
            raise RuntimeError("GitHub contents listing failed")
        result: list[ExecutorContent] = []
        for item in body:
            if not isinstance(item, dict):
                raise RuntimeError("GitHub contents listing malformed")
            if item.get("type") == "file":
                found = self.get(item["path"], ref)
                if found is not None:
                    result.append(found)
            elif item.get("type") == "dir":
                result.extend(self.list(item["path"], ref))
        return sorted(result, key=lambda item: item.path)

    @staticmethod
    def _check_write(path: str, branch: str) -> None:
        if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/"):
            raise ValueError("unsafe GitHub contents path")
        if not isinstance(branch, str) or not branch or branch in {"main", "master"}:
            raise ValueError("default branch writes are forbidden")

    def create(self, path: str, text: str, message: str, branch: str) -> ExecutorContent:
        self._check_write(path, branch)
        status, body = self._request("PUT", f"contents/{quote(path)}", {
            "message": message, "branch": branch,
            "content": base64.b64encode(text.encode()).decode("ascii"),
        })
        if status not in {200, 201} or not isinstance(body, dict):
            raise RuntimeError("GitHub contents create outcome unavailable")
        return ExecutorContent(path, text, body["content"]["sha"])

    def update(self, path: str, text: str, sha: str, message: str, branch: str) -> ExecutorContent:
        self._check_write(path, branch)
        status, body = self._request("PUT", f"contents/{quote(path)}", {
            "message": message, "branch": branch, "sha": sha,
            "content": base64.b64encode(text.encode()).decode("ascii"),
        })
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError("GitHub contents update outcome unavailable")
        return ExecutorContent(path, text, body["content"]["sha"])
