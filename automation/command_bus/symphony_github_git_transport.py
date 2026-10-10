"""G6.1 GitHub Git transport for the G6 adoption bridge: STATIC/prepare-only.

Ref publication uses the official GraphQL ``updateRefs`` mutation. Its schema
(read by introspection, 2026-10-10) states that all updates are atomic and that
``RefUpdate.beforeOid`` is the value the ref must point to before the update.
That is the server-side expected-old-head compare this bridge requires. The
REST ``PATCH git/refs`` sha/force API has no supplied old value and is not used.

This module contains no network code. Every request goes through an injected
``GitHubHttp``. ``GitHubGitTransport`` refuses any HTTP object that is not
``static_only``; the read-only urllib client in ``symphony_github_readers``
cannot be passed in, so no LIVE Git write is wired by this batch.

Rules kept from G6: one ref request per call, no retry, no force, no default
branch, no create/delete via zero OIDs; an unclear reply is resolved by GET only.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from typing import Any, Protocol

from .symphony_git_adoption import GitCandidate, _git_oid, construct_candidate
from .symphony_result_manifest import FileEntry, SHA, digest, safe_branch

ZERO_OID = "0" * 40
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NODE_ID = re.compile(r"^[A-Za-z0-9_=-]{4,100}$")

UPDATE_REFS_DOCUMENT = (
    "mutation SymphonyG61UpdateRefs($input: UpdateRefsInput!) "
    "{ updateRefs(input: $input) { clientMutationId } }"
)


class GitHubHttp(Protocol):
    static_only: bool

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, Any]: ...
    def graphql(self, document: str, variables: dict) -> tuple[int, Any]: ...


class TransportIntegrityError(RuntimeError):
    """GitHub returned bytes/identities that do not hash to the requested object."""


def prepare_update_refs(*, repository_id: str, branch: str, default_branch: str,
                        before_oid: str, after_oid: str, client_mutation_id: str) -> dict:
    """Build exactly one expected-head ref update; sends nothing.

    ``beforeOid`` is mandatory here although the schema makes it optional:
    omitting it would turn the request into an unconditional fast-forward.
    """
    if type(repository_id) is not str or not NODE_ID.fullmatch(repository_id):
        raise ValueError("repository node id required")
    if not safe_branch(branch, default_branch):
        raise ValueError("non-default canonical branch required")
    for oid in (before_oid, after_oid):
        if type(oid) is not str or not SHA.fullmatch(oid) or oid == ZERO_OID:
            raise ValueError("full non-zero before/after OIDs required; create/delete forbidden")
    if before_oid == after_oid:
        raise ValueError("no-op ref update")
    if type(client_mutation_id) is not str or not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", client_mutation_id):
        raise ValueError("client mutation id required")
    variables = {"input": {"clientMutationId": client_mutation_id, "repositoryId": repository_id,
                           "refUpdates": [{"name": "refs/heads/" + branch, "beforeOid": before_oid,
                                           "afterOid": after_oid, "force": False}]}}
    return {"protocol": "SYMPHONY_G61_UPDATE_REFS_V1", "document": UPDATE_REFS_DOCUMENT,
            "variables": variables, "request_digest": digest({"document": UPDATE_REFS_DOCUMENT, "variables": variables})}


def classify_update_refs_reply(status: Any, body: Any, client_mutation_id: str) -> str:
    """Reply classification only. Even SUCCESS_REPLY is confirmed by ref GET."""
    if status != 200 or not isinstance(body, dict):
        return "UNKNOWN_REPLY"
    if body.get("errors"):
        return "REJECTED_REPLY"
    data = body.get("data")
    if (isinstance(data, dict) and isinstance(data.get("updateRefs"), dict)
            and data["updateRefs"].get("clientMutationId") == client_mutation_id):
        return "SUCCESS_REPLY"
    return "UNKNOWN_REPLY"


# --- Git object encoding shared by readers/transport ------------------------

def tree_raw(entries: list[tuple[str, str, str]]) -> bytes:
    """``entries`` are (mode, name, oid); mode uses Git's object form (40000)."""
    def key(e):
        return (e[1] + ("/" if e[0] == "40000" else "")).encode()
    return b"".join(m.encode() + b" " + n.encode() + b"\0" + bytes.fromhex(o) for m, n, o in sorted(entries, key=key))


def parse_tree_raw(raw: bytes) -> list[tuple[str, str, str]]:
    entries, i = [], 0
    while i < len(raw):
        sp = raw.index(b" ", i); nul = raw.index(b"\0", sp)
        entries.append((raw[i:sp].decode(), raw[sp + 1:nul].decode(), raw[nul + 1:nul + 21].hex()))
        i = nul + 21
    return entries


def parse_commit_raw(raw: bytes) -> dict:
    head, _, message = raw.partition(b"\n\n")
    fields: dict = {"parents": []}
    for line in head.decode().split("\n"):
        name, _, value = line.partition(" ")
        if name == "parent":
            fields["parents"].append(value)
        elif name in {"tree", "author", "committer"} and name not in fields:
            fields[name] = value
        else:
            raise ValueError("unsupported commit header")
    for who in ("author", "committer"):
        m = re.fullmatch(r"(.+) <([^<>]*)> (\d+) ([+-]\d{4})", fields[who])
        if not m:
            raise ValueError("commit identity")
        fields[who] = {"name": m.group(1), "email": m.group(2), "ts": int(m.group(3)), "tz": m.group(4)}
    fields["message"] = message.decode()
    return fields


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_iso(value: str) -> int:
    clock = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if clock.utcoffset() is None or clock.utcoffset().total_seconds() != 0:
        raise ValueError("only UTC candidate identities are reconstructible")
    return int(clock.timestamp())


def _blob_bytes(body: Any) -> bytes:
    if not isinstance(body, dict) or body.get("encoding") != "base64" or type(body.get("content")) is not str:
        raise TransportIntegrityError("blob response malformed")
    return base64.b64decode(body["content"].replace("\n", ""), validate=True)


def commit_raw_from_api(body: dict, commit: str) -> bytes:
    """Rebuild an unsigned single-parent UTC commit object from REST fields.

    GitHub may or may not echo a trailing newline in ``message``; only the
    variant that hashes to ``commit`` is accepted, so the bytes are proven.
    Signed, merge or non-UTC commits are not reconstructible and raise.
    """
    try:
        def who(x):
            return f"{x['name']} <{x['email']}> {_from_iso(x['date'])} +0000"
        if len(body["parents"]) != 1:
            raise ValueError("single parent required")
        head = (f"tree {body['tree']['sha']}\nparent {body['parents'][0]['sha']}\n"
                f"author {who(body['author'])}\ncommitter {who(body['committer'])}\n\n").encode()
        message = body.get("message") or ""
    except (KeyError, TypeError, ValueError) as exc:
        raise TransportIntegrityError("commit fields not reconstructible") from exc
    for variant in (message, message + "\n"):
        if _git_oid("commit", head + variant.encode()) == commit:
            return head + variant.encode()
    raise TransportIntegrityError("commit bytes do not hash to OID (signed/foreign commit?)")


def prepare_candidate_requests(candidate: GitCandidate) -> list[dict]:
    """Pure, deterministic Git Database requests. All objects verified before send."""
    if type(candidate) is not GitCandidate:
        raise TransportIntegrityError("candidate type")
    for oid, (kind, raw) in candidate.objects.items():
        if kind not in {"blob", "tree", "commit"} or _git_oid(kind, raw) != oid:
            raise TransportIntegrityError("candidate object SHA mismatch")
    if (candidate.objects.get(candidate.commit) != ("commit", candidate.commit_bytes)
            or _git_oid("commit", candidate.commit_bytes) != candidate.commit):
        raise TransportIntegrityError("candidate commit bytes mismatch")
    rebuilt = construct_candidate(parent=candidate.parent, files=candidate.files,
                                  created_at="2026-10-10T00:00:00Z", adoption_id="prepare-validation")
    if rebuilt.tree != candidate.tree:
        raise TransportIntegrityError("candidate file inventory/tree mismatch")
    requests: list[dict] = []
    def created(kind, raw, body):
        oid = _git_oid(kind, raw)
        requests.append({"method": "POST", "path": f"git/{kind}s", "body": body, "expected_oid": oid})
    blobs = {o: raw for o, (k, raw) in candidate.objects.items() if k == "blob"}
    trees = {o: raw for o, (k, raw) in candidate.objects.items() if k == "tree"}
    for oid, raw in sorted(blobs.items()):
        created("blob", raw, {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"})
    done: set[str] = set()
    def make_tree(oid):
        if oid in done:
            return
        entries = parse_tree_raw(trees[oid])
        for mode, _, child in entries:
            if mode == "40000":
                make_tree(child)
        body = {"tree": [{"path": n, "mode": "040000" if m == "40000" else m,
                          "type": "tree" if m == "40000" else ("commit" if m == "160000" else "blob"),
                          "sha": o} for m, n, o in entries]}
        created("tree", trees[oid], body); done.add(oid)
    make_tree(candidate.tree)
    c = parse_commit_raw(candidate.commit_bytes)
    if c["tree"] != candidate.tree or c["parents"] != [candidate.parent]:
        raise TransportIntegrityError("candidate commit header mismatch")
    ident = lambda who: {"name": c[who]["name"], "email": c[who]["email"], "date": _iso(c[who]["ts"])}
    if c["author"]["tz"] != "+0000" or c["committer"]["tz"] != "+0000":
        raise TransportIntegrityError("candidate identity must be UTC")
    created("commit", candidate.commit_bytes, {"message": c["message"], "tree": c["tree"],
            "parents": c["parents"], "author": ident("author"), "committer": ident("committer")})

    return requests


class GitHubGitTransport:
    """Implements the G6 ``StaticGitTransport`` contract over GitHub's Git DB API.

    ``static_only`` mirrors the injected HTTP object. The G6 bridge accepts
    only ``True``; a live HTTP client is rejected here already.
    """
    atomic_expected_head = True

    def __init__(self, http: GitHubHttp, *, repository: str, repository_id: str,
                 target_branch: str, default_branch: str, target_reader):
        if getattr(http, "static_only", None) is not True:
            raise ValueError("G6.1: live GitHub Git write transport NOT_WIRED")
        if not REPOSITORY.fullmatch(repository) or not NODE_ID.fullmatch(repository_id or ""):
            raise ValueError("repository identity required")
        if not safe_branch(target_branch, default_branch):
            raise ValueError("non-default target branch required")
        self.http, self.repository, self.repository_id = http, repository, repository_id
        self.target_branch, self.default_branch = target_branch, default_branch
        self.target_reader = target_reader
        self.ref_requests: list[dict] = []
        self.ref_replies: list[str] = []
        self.integrity_failures: list[str] = []

    @property
    def static_only(self) -> bool:
        return getattr(self.http, "static_only", None) is True

    def _rest(self, method: str, path: str, body: dict | None = None, ok=(200,)) -> Any:
        status, data = self.http.request(method, f"repos/{self.repository}/{path}", body)
        if status not in ok:
            raise RuntimeError(f"GitHub {method} status {status}")
        return data

    def read_target(self):
        return self.target_reader.read()

    def put_candidate(self, candidate: GitCandidate) -> None:
        for request in prepare_candidate_requests(candidate):
            reply = self._rest(request["method"], request["path"], request["body"], ok=(201,))
            if not isinstance(reply, dict) or reply.get("sha") != request["expected_oid"]:
                raise TransportIntegrityError("object identity differs from local Git object")

    def read_candidate(self, commit: str) -> GitCandidate | None:
        """GET-only reconstruction; every object is re-hashed before return.

        Bytes that do not hash to their OID return ``None`` (not verified), and
        the reason is kept in ``integrity_failures``. Read failures still raise.
        """
        try:
            return self._read_candidate(commit)
        except TransportIntegrityError as exc:
            self.integrity_failures.append(str(exc))
            return None

    def _read_candidate(self, commit: str) -> GitCandidate | None:
        if not SHA.fullmatch(commit or ""):
            return None
        status, body = self.http.request("GET", f"repos/{self.repository}/git/commits/{commit}")
        if status == 404:
            return None
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError("candidate commit read unavailable")
        if body.get("sha") != commit or len(body.get("parents") or []) != 1:
            raise TransportIntegrityError("candidate commit shape")
        raw = commit_raw_from_api(body, commit)
        objects: dict[str, tuple[str, bytes]] = {commit: ("commit", raw)}
        files: dict[str, FileEntry] = {}
        def walk(tree_oid, prefix):
            tree = self._rest("GET", f"git/trees/{tree_oid}")
            if not isinstance(tree, dict) or tree.get("sha") != tree_oid or tree.get("truncated"):
                raise TransportIntegrityError("candidate tree response")
            entries = []
            for item in tree.get("tree", []):
                mode = "40000" if item["type"] == "tree" else item["mode"]
                entries.append((mode, item["path"], item["sha"]))
                path = prefix + item["path"]
                if item["type"] == "tree":
                    walk(item["sha"], path + "/")
                elif item["type"] == "commit" and mode == "160000":
                    files[path] = FileEntry(item["sha"].encode(), "160000", "gitlink")
                elif item["type"] == "blob" and mode in {"100644", "100755", "120000"}:
                    data = _blob_bytes(self._rest("GET", f"git/blobs/{item['sha']}"))
                    if _git_oid("blob", data) != item["sha"]:
                        raise TransportIntegrityError("blob bytes do not hash to OID")
                    objects[item["sha"]] = ("blob", data)
                    files[path] = FileEntry(data, mode, "symlink" if mode == "120000" else "blob")
                else:
                    raise TransportIntegrityError("unsupported tree entry")
            raw_tree = tree_raw(entries)
            if _git_oid("tree", raw_tree) != tree_oid:
                raise TransportIntegrityError("tree entries do not hash to OID")
            objects[tree_oid] = ("tree", raw_tree)
        walk(body["tree"]["sha"], "")
        return GitCandidate(body["parents"][0]["sha"], body["tree"]["sha"], commit, raw, files, objects)

    def compare_and_swap(self, *, branch: str, expected_head: str, candidate_head: str) -> None:
        """Exactly one GraphQL updateRefs request; raises on anything but success.

        The bridge resolves every outcome, including SUCCESS_REPLY, by GET.
        """
        if branch != self.target_branch:
            raise ValueError("CAS branch differs from configured target")
        status, repository = self.http.request("GET", f"repos/{self.repository}")
        if (status != 200 or not isinstance(repository, dict)
                or repository.get("full_name") != self.repository
                or repository.get("default_branch") != self.default_branch
                or not safe_branch(branch, repository.get("default_branch"))):
            raise ValueError("fresh non-default repository binding unavailable before CAS")
        request = prepare_update_refs(repository_id=self.repository_id, branch=branch,
            default_branch=self.default_branch, before_oid=expected_head, after_oid=candidate_head,
            client_mutation_id="sym-g61-" + candidate_head[:16])
        self.ref_requests.append(request)
        try:
            status, body = self.http.graphql(request["document"], request["variables"])
        except Exception:
            self.ref_replies.append("LOST_REPLY")
            raise
        reply = classify_update_refs_reply(status, body, request["variables"]["input"]["clientMutationId"])
        self.ref_replies.append(reply)
        if reply != "SUCCESS_REPLY":
            raise RuntimeError("updateRefs not confirmed: " + reply)
