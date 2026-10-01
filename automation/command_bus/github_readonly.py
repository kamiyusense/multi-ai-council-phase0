"""Bounded GitHub GET transport and complete pagination. No write or retry API.

Use Link headers, not the length of the first page. Fail closed on a cycle,
changed endpoint/query, count disagreement, duplicate row, cap or failed GET.
Credentials never cross an origin or redirect. Inject a fake reader in tests.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .blue_jules_result_event import EXPECTED_REPOSITORY
from .blue_work_reconcile_prepare import _pairs

ROOT = "https://api.github.com/repos/" + EXPECTED_REPOSITORY


@dataclass(frozen=True)
class ReadResponse:
    data: Any
    headers: dict[str, str]


class Reader(Protocol):
    def get(self, url: str) -> ReadResponse: ...


def checked_url(url: str) -> str:
    if not isinstance(url, str) or any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("URL contains control characters")
    value = urlsplit(url)
    pairs = parse_qsl(value.query, keep_blank_values=True)
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("duplicate URL query field")
    sha_comparison = re.fullmatch(r"/repos/" + re.escape(EXPECTED_REPOSITORY) + r"/compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}", value.path)
    if (value.scheme != "https" or value.netloc != "api.github.com" or value.fragment
            or not value.path.startswith("/repos/" + EXPECTED_REPOSITORY + "/")
            or "%" in value.path or (".." in value.path and sha_comparison is None) or "\\" in value.path):
        raise ValueError("GitHub read scope violation")
    suffix = value.path[len("/repos/" + EXPECTED_REPOSITORY + "/"):]
    if suffix.split("/", 1)[0] not in {"pulls", "issues", "git", "contents", "commits", "actions", "compare", "branches"}:
        raise ValueError("unsupported read endpoint")
    return url


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect blocked; no credential forwarding")


class GitHubGetReader:
    def __init__(self, token: str):
        if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
            raise ValueError("existing read token unavailable")
        self._token = token
        self._opener = build_opener(_NoRedirect())

    def get(self, url: str) -> ReadResponse:
        checked_url(url)
        request = Request(url, method="GET", headers={
            "Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "phase0-prepare-only",
        })
        with self._opener.open(request, timeout=30) as response:
            if response.status != 200:
                raise ValueError("GitHub GET did not return 200")
            raw = response.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                raise ValueError("GitHub response size limit")
            return ReadResponse(json.loads(raw, object_pairs_hook=_pairs), {k.lower(): v for k, v in response.headers.items()})


def read_all(reader: Reader, url: str, *, array_key: str | None = None,
             identity_key: str = "id", max_pages: int = 100,
             total_key: str = "total_count") -> list[dict[str, Any]]:
    checked_url(url)
    if type(max_pages) is not int or max_pages < 1:
        raise ValueError("invalid pagination bound")
    original = urlsplit(url)
    original_query = dict(parse_qsl(original.query))
    visited: set[str] = set()
    rows: list[dict[str, Any]] = []
    identities: set[Any] = set()
    declared_total: int | None = None
    while url:
        checked_url(url)
        current = urlsplit(url)
        query = dict(parse_qsl(current.query))
        if current.path != original.path or {k: v for k, v in query.items() if k != "page"} != {
                k: v for k, v in original_query.items() if k != "page"}:
            raise ValueError("pagination changed endpoint or filter")
        if url in visited or len(visited) >= max_pages:
            raise ValueError("pagination cycle or bound reached; incomplete")
        visited.add(url)
        response = reader.get(url)
        if not isinstance(response, ReadResponse) or not isinstance(response.headers, dict):
            raise ValueError("read response/headers unavailable")
        data = response.data
        if array_key == "check_runs" and isinstance(data, dict) and data.get("total_count", 0) > 1000:
            raise ValueError("GitHub check-suite collection limit; completeness UNKNOWN")
        if array_key:
            if not isinstance(data, dict) or data.get("incomplete_results", False) is not False:
                raise ValueError("incomplete collection")
            total = data.get(total_key)
            if type(total) is not int or total < 0 or (declared_total is not None and declared_total != total):
                raise ValueError("collection count unavailable/changed")
            declared_total = total
            data = data.get(array_key)
        if not isinstance(data, list):
            raise ValueError("collection is not an array")
        for row in data:
            if not isinstance(row, dict) or identity_key not in row:
                raise ValueError("collection identity missing")
            identity = row[identity_key]
            if not isinstance(identity, (str, int)) or isinstance(identity, bool) or identity in identities:
                raise ValueError("duplicate/malformed collection identity")
            identities.add(identity)
            rows.append(row)
        headers = {k.lower(): v for k, v in response.headers.items() if isinstance(k, str)}
        if len(headers) != len(response.headers):
            raise ValueError("duplicate/malformed HTTP header names")
        link = headers.get("link", "")
        if not isinstance(link, str):
            raise ValueError("Link header unreadable")
        next_urls = []
        if link:
            for part in link.split(","):
                match = re.fullmatch(r'\s*<([^<>]+)>;\s*rel="(next|prev|first|last)"\s*', part)
                if match is None:
                    raise ValueError("malformed pagination Link")
                if match[2] == "next":
                    next_urls.append(match[1])
        if len(next_urls) > 1:
            raise ValueError("multiple next pages")
        url = next_urls[0] if next_urls else ""
    if declared_total is not None and len(rows) != declared_total:
        raise ValueError("pagination total_count mismatch")
    return rows


def content_at(reader: Reader, path: str, ref: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", path) or ".." in path or path.startswith("/"):
        raise ValueError("unsafe content path")
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError("content must be pinned to commit")
    row = reader.get(ROOT + "/contents/" + path + "?" + urlencode({"ref": ref})).data
    if not isinstance(row, dict) or row.get("encoding") != "base64" or row.get("type") != "file":
        raise ValueError("file content unavailable")
    raw = base64.b64decode("".join(row["content"].split()), validate=True)
    sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if row.get("sha") != sha:
        raise ValueError("Git blob content mismatch")
    return raw.decode("utf-8")


def recursive_tree(reader: Reader, sha: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("tree commit identity unavailable")
    row = reader.get(ROOT + "/git/trees/" + sha + "?recursive=1").data
    if not isinstance(row, dict) or row.get("truncated") is not False or not isinstance(row.get("tree"), list):
        raise ValueError("incomplete recursive tree")
    paths = [x.get("path") for x in row["tree"] if isinstance(x, dict)]
    if len(paths) != len(row["tree"]) or any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths):
        raise ValueError("malformed/duplicate tree paths")
    return row


def result_files(reader: Reader, pr: dict) -> list[dict]:
    number, count = pr.get("number"), pr.get("changed_files")
    head = pr.get("head", {}).get("sha")
    if type(number) is not int or number < 1 or type(count) is not int or count < 0 or count >= 3000:
        raise ValueError("result changed-file count unavailable/API limit")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("result HEAD unavailable")
    detail_url = ROOT + f"/pulls/{number}"
    def binding(value):
        if not isinstance(value, dict):
            raise ValueError("result detail unavailable")
        return (value.get("number"), value.get("changed_files"), value.get("state"), value.get("merged"),
                tuple((value.get(side, {}).get("sha"), value.get(side, {}).get("ref"),
                       value.get(side, {}).get("repo", {}).get("full_name")) for side in ("head", "base")))
    expected = binding(pr)
    if binding(reader.get(detail_url).data) != expected:
        raise ValueError("result moved before changed-file collection")
    rows = read_all(reader, ROOT + f"/pulls/{number}/files?per_page=100", identity_key="filename")
    if len(rows) != count:
        raise ValueError("changed-file pagination incomplete")
    tree = recursive_tree(reader, head)
    modes = {x["path"]: x.get("mode") for x in tree["tree"]}
    result = []
    for row in rows:
        row = dict(row)
        mode = modes.get(row["filename"])
        if row.get("status") in {"added", "modified"} and mode not in {"100644", "100755"}:
            raise ValueError("result regular-file mode unverified")
        row["symlink"] = mode == "120000"
        result.append(row)
    if binding(reader.get(detail_url).data) != expected:
        raise ValueError("result moved during changed-file collection; no retry")
    return result


def compare_ancestry(reader: Reader, base: str, head: str) -> dict:
    if not all(isinstance(s, str) and re.fullmatch(r"[0-9a-f]{40}", s) for s in (base, head)):
        raise ValueError("comparison SHA identity unavailable")
    url = ROOT + f"/compare/{base}...{head}?per_page=100"
    comparison = reader.get(url).data
    if not isinstance(comparison, dict):
        raise ValueError("comparison unavailable")
    commits = read_all(reader, url, array_key="commits", identity_key="sha", total_key="total_commits")
    if len(commits) != comparison.get("total_commits"):
        raise ValueError("comparison readbacks disagree")
    result = dict(comparison)
    result["commits"] = commits
    return result
