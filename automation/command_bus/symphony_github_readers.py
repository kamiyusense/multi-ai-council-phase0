"""G6.1 authenticated GitHub readers: target HEAD/inventory and task validity.

Readers only GET (REST) or run GraphQL *queries*. ``ReadOnlyGitHubHttp`` is the
sole concrete network client in G6.1 and refuses every write method and every
GraphQL mutation document before any bytes leave the process. It is
deliberately ``static_only = False`` so it can never be passed to the G6
adoption bridge's write transport.

Every object a reader returns is re-hashed with Git's object format: the root
tree, every subtree and every blob must hash to the OIDs GitHub reported. A
truncated tree or a limit overrun is reported as ``complete=False`` (the
inspector then holds), never as a smaller "complete" inventory.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any, Callable, Iterable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .symphony_git_adoption import _git_oid
from .symphony_github_git_transport import GitHubHttp, REPOSITORY, TransportIntegrityError, tree_raw
from .symphony_result_manifest import CanonicalTarget, FileEntry, SHA, TaskValidity, digest, safe_branch

API = "https://api.github.com"
_MAX_RESPONSE = 8 * 1024 * 1024
TASK_BLOCK = re.compile(r"```symphony-task\r?\n(.*?)\r?\n```", re.S)
ISSUE_ID = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]{0,9})$")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ReadOnlyGitHubHttp:
    """GET/GraphQL-query only. Token supplied by caller; never logged or stored
    in evidence. No retry: one request per call.
    """
    static_only = False

    def __init__(self, token: str, *, timeout: float = 30):
        if not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("GitHub token unavailable")
        self._token, self._timeout = token, timeout
        self.requests = 0

    def __repr__(self) -> str:
        return "ReadOnlyGitHubHttp(<redacted>)"

    def _send(self, method: str, url: str, body: dict | None) -> tuple[int, Any]:
        payload = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        request = Request(url, data=payload, method=method, headers={
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        self.requests += 1
        try:
            with build_opener(_NoRedirect()).open(request, timeout=self._timeout) as response:
                status, raw = response.status, response.read(_MAX_RESPONSE + 1)
        except HTTPError as exc:
            status, raw = exc.code, exc.read(_MAX_RESPONSE + 1) if exc.fp else b""
        if len(raw) > _MAX_RESPONSE:
            raise RuntimeError("GitHub response too large")
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, None

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        if method != "GET" or body is not None:
            raise PermissionError("read-only GitHub client: write method refused")
        return self._send("GET", f"{API}/{path}", None)

    def graphql(self, document: str, variables: dict) -> tuple[int, Any]:
        stripped = re.sub(r"#[^\n]*", "", document).strip()
        if not stripped.startswith(("query", "{")) or re.search(r"\bmutation\b|\bsubscription\b", stripped):
            raise PermissionError("read-only GitHub client: GraphQL mutation refused")
        return self._send("POST", f"{API}/graphql", {"query": document, "variables": variables})


def _get(http: GitHubHttp, path: str, *, allow_404: bool = False) -> Any:
    status, body = http.request("GET", path)
    if status == 404 and allow_404:
        return None
    if status != 200:
        raise RuntimeError(f"GitHub read status {status}")
    return body


def read_repository_identity(http: GitHubHttp, repository: str) -> dict:
    """GraphQL query: node id (needed for updateRefs), default branch, permission."""
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("repository must be owner/name")
    owner, name = repository.split("/")
    status, body = http.graphql(
        "query SymphonyG61Repo($owner: String!, $name: String!) { repository(owner: $owner, name: $name) "
        "{ id nameWithOwner viewerPermission isArchived defaultBranchRef { name } } }",
        {"owner": owner, "name": name})
    repo = (body or {}).get("data", {}).get("repository") if status == 200 and isinstance(body, dict) else None
    if not isinstance(repo, dict) or repo.get("nameWithOwner", "").lower() != repository.lower() or body.get("errors"):
        raise RuntimeError("repository identity unavailable")
    return {"repository_id": repo["id"], "default_branch": (repo.get("defaultBranchRef") or {}).get("name"),
            "viewer_permission": repo.get("viewerPermission"), "archived": repo.get("isArchived")}


class GitHubTargetReader:
    """Fresh canonical HEAD and complete hash-verified inventory of one branch."""

    def __init__(self, http: GitHubHttp, *, repository: str, branch: str, default_branch: str,
                 max_files: int = 2000, max_bytes: int = 32 * 1024 * 1024):
        if not REPOSITORY.fullmatch(repository) or not safe_branch(branch, default_branch):
            raise ValueError("non-default canonical target required")
        self.http, self.repository, self.branch, self.default_branch = http, repository, branch, default_branch
        self.max_files, self.max_bytes = max_files, max_bytes
        self._blobs: dict[str, bytes] = {}

    def _blob(self, oid: str) -> bytes:
        if oid not in self._blobs:
            body = _get(self.http, f"repos/{self.repository}/git/blobs/{oid}")
            if not isinstance(body, dict) or body.get("encoding") != "base64" or body.get("sha") != oid:
                raise TransportIntegrityError("blob response malformed")
            data = base64.b64decode(str(body.get("content", "")).replace("\n", ""), validate=True)
            if _git_oid("blob", data) != oid:
                raise TransportIntegrityError("blob bytes do not hash to OID")
            self._blobs[oid] = data
        return self._blobs[oid]

    def read(self) -> CanonicalTarget:
        repo = _get(self.http, f"repos/{self.repository}")
        if not isinstance(repo, dict) or repo.get("full_name", "").lower() != self.repository.lower():
            raise RuntimeError("repository identity mismatch")
        if repo.get("default_branch") != self.default_branch:
            # A changed default branch can make the configured target unsafe.
            raise RuntimeError("default branch differs from configured default")
        ref = _get(self.http, f"repos/{self.repository}/git/ref/heads/{quote(self.branch, safe='/')}")
        obj = ref.get("object") if isinstance(ref, dict) else None
        if (not isinstance(ref, dict) or ref.get("ref") != "refs/heads/" + self.branch
                or not isinstance(obj, dict) or obj.get("type") != "commit" or not SHA.fullmatch(obj.get("sha", ""))):
            raise RuntimeError("target ref malformed")
        return self._inventory(obj["sha"])

    def read_at(self, commit: str) -> CanonicalTarget:
        """Inventory at a fixed commit (the attempt's expected HEAD) for
        manifest generation. Not a fresh canonical read: the bridge always
        re-reads the branch itself before deciding."""
        if not SHA.fullmatch(commit or ""):
            raise ValueError("full commit OID required")
        return self._inventory(commit)

    def _inventory(self, head: str) -> CanonicalTarget:
        commit = _get(self.http, f"repos/{self.repository}/git/commits/{head}")
        if not isinstance(commit, dict) or commit.get("sha") != head or not SHA.fullmatch(commit.get("tree", {}).get("sha", "")):
            raise RuntimeError("target commit malformed")
        root = commit["tree"]["sha"]
        listing = _get(self.http, f"repos/{self.repository}/git/trees/{root}?recursive=1")
        if not isinstance(listing, dict) or listing.get("sha") != root or not isinstance(listing.get("tree"), list):
            raise RuntimeError("target tree malformed")
        def incomplete():
            return CanonicalTarget(self.repository, self.branch, self.default_branch, head, {}, True, False)
        if listing.get("truncated") is not False:
            return incomplete()
        entries = listing["tree"]
        # Rebuild every directory object from the flattened listing and hash it.
        dirs: dict[str, list] = {"": []}; trees = {"": root}
        for e in entries:
            if type(e) is not dict or type(e.get("path")) is not str or not SHA.fullmatch(e.get("sha") or ""):
                raise TransportIntegrityError("tree entry malformed")
            if e.get("type") == "tree":
                if e["path"] in dirs:
                    raise TransportIntegrityError("duplicate tree path")
                dirs[e["path"]] = []; trees[e["path"]] = e["sha"]
        for e in entries:
            parent, _, name = e["path"].rpartition("/")
            if parent not in dirs:
                raise TransportIntegrityError("tree entry without listed parent")
            dirs[parent].append(("40000" if e["type"] == "tree" else e.get("mode"), name, e["sha"]))
        for path, items in dirs.items():
            if _git_oid("tree", tree_raw(items)) != trees[path]:
                raise TransportIntegrityError("tree entries do not hash to OID")
        if sum(1 for e in entries if e.get("type") != "tree") > self.max_files:
            return incomplete()  # listing verified above; blob bytes not fetched
        files: dict[str, FileEntry] = {}; total = 0
        for e in entries:
            kind, mode, path = e["type"], e.get("mode"), e["path"]
            if kind == "tree":
                continue
            if kind == "commit" and mode == "160000":
                files[path] = FileEntry(e["sha"].encode(), "160000", "gitlink"); continue
            if kind != "blob" or mode not in {"100644", "100755", "120000"}:
                raise TransportIntegrityError("unsupported target tree entry")
            total += int(e.get("size") or 0)
            if total > self.max_bytes:
                return incomplete()
            files[path] = FileEntry(self._blob(e["sha"]), mode, "symlink" if mode == "120000" else "blob")
        return CanonicalTarget(self.repository, self.branch, self.default_branch, head, files, True, True)


ISSUE_QUERY = ("query SymphonyG61Issue($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) "
               "{ issue(number: $number) { number title body state stateReason locked "
               "author { login } editor { login } lastEditedAt labels(first: 50) { totalCount nodes { name } } } } }")


def parse_task_block(body: str) -> dict:
    """Exactly one ```symphony-task fenced JSON block defines task/request/scope."""
    blocks = TASK_BLOCK.findall(body or "")
    if len(blocks) != 1:
        raise ValueError("exactly one symphony-task block required")
    task = json.loads(blocks[0])
    if (type(task) is not dict or set(task) != {"protocol", "task_id", "request", "scope"}
            or task["protocol"] != "SYMPHONY_G61_TASK_V1" or type(task["task_id"]) is not str
            or type(task["scope"]) is not dict or task["scope"].get("request_digest") != digest(task["request"])):
        raise ValueError("symphony-task block schema/request digest")
    return task


class GitHubTaskValidityReader:
    """Task relevance and request/scope revision from the authoritative Issue.

    Trust: the Issue author and any last editor must be in ``trusted_logins``.
    Validity: an OPEN, unlocked Issue is still requested unless labelled with
    an invalidating label. A CLOSED Issue is valid only with the explicit
    ``adopt_after_close_label`` (closing the proof Issue never implies validity);
    ``NOT_PLANNED``/``DUPLICATE`` or an invalidating label is invalid. Anything
    else returns ``valid=None`` and the inspector holds.
    """
    INVALID_LABELS = frozenset({"symphony:invalid", "symphony:superseded", "symphony:done-elsewhere"})

    def __init__(self, http: GitHubHttp, *, repository: str, trusted_logins: Iterable[str],
                 adopt_after_close_label: str = "symphony:adopt-after-close"):
        if not REPOSITORY.fullmatch(repository):
            raise ValueError("repository must be owner/name")
        self.http, self.repository = http, repository
        self.trusted = frozenset(trusted_logins)
        if not self.trusted:
            raise ValueError("trusted Issue authors required")
        self.adopt_after_close_label = adopt_after_close_label

    def read(self, target: CanonicalTarget, *, issue_id: str, task_id: str) -> TaskValidity:
        m = ISSUE_ID.fullmatch(issue_id or "")
        untrusted = TaskValidity(task_id, issue_id, getattr(target, "head", ""), "", "", None, False)
        if not m or m.group(1).lower() != self.repository.lower() or type(target) is not CanonicalTarget:
            return untrusted
        owner, name = self.repository.split("/")
        status, body = self.http.graphql(ISSUE_QUERY, {"owner": owner, "name": name, "number": int(m.group(2))})
        if status != 200 or not isinstance(body, dict) or body.get("errors"):
            raise RuntimeError("Issue read unavailable")
        issue = ((body.get("data") or {}).get("repository") or {}).get("issue")
        if not isinstance(issue, dict) or issue.get("number") != int(m.group(2)):
            raise RuntimeError("Issue missing")
        logins = {(issue.get("author") or {}).get("login")} | ({(issue.get("editor") or {}).get("login")} if issue.get("editor") else set())
        labels = issue.get("labels") or {}
        names = {n.get("name") for n in labels.get("nodes") or []}
        if not logins <= self.trusted or labels.get("totalCount", 0) > len(names):
            return untrusted
        try:
            task = parse_task_block(issue.get("body") or "")
        except (ValueError, TypeError, json.JSONDecodeError):
            return untrusted
        if task["task_id"] != task_id or task["scope"].get("issue") != issue_id:
            return untrusted
        state, reason = issue.get("state"), issue.get("stateReason")
        if names & self.INVALID_LABELS or (state == "CLOSED" and reason in {"NOT_PLANNED", "DUPLICATE"}):
            valid: bool | None = False
        elif state == "OPEN" and not issue.get("locked"):
            valid = True
        elif state == "CLOSED" and self.adopt_after_close_label in names:
            valid = True
        else:
            valid = None
        return TaskValidity(task_id, issue_id, target.head, digest(task["scope"]),
                            task["scope"]["request_digest"], valid, valid is not None)


def bind_validity_reader(reader: GitHubTaskValidityReader, *, issue_id: str, task_id: str) -> Callable[[CanonicalTarget], TaskValidity]:
    if type(task_id) is not str or not task_id:
        raise ValueError("task id required")
    return lambda target: reader.read(target, issue_id=issue_id, task_id=task_id)
