"""Credential-free simulated GitHub for G6.1 (no network, ``static_only``).

Implements the subset the G6.1 readers/transport use, with the semantics the
official GraphQL schema documents for ``updateRefs``: every ``beforeOid`` is
checked first and either all updates apply or none do; ``force=false``
requires a fast-forward. Objects are real Git objects (SHA-1 over Git's
encoding), so local and "remote" identities are comparable.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone

from ..symphony_git_adoption import _git_oid
from ..symphony_github_git_transport import parse_commit_raw, parse_tree_raw, tree_raw
from ..symphony_result_manifest import FileEntry

REPO = "fixture/council"
REPO_ID = "R_fixture01"


class LostReply(RuntimeError):
    pass


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SimulatedGitHub:
    static_only = True

    def __init__(self, *, default_branch="main"):
        self.default_branch = default_branch
        self.objects: dict[str, tuple[str, bytes]] = {}
        self.refs: dict[str, str] = {}
        self.issues: dict[int, dict] = {}
        self.log: list[tuple[str, str]] = []
        self.update_refs_requests = 0
        self.ref_mutations = 0
        self.object_posts = 0
        # fault switches
        self.race_before_update_refs = None      # callable run inside the mutation, before beforeOid check
        self.lose_reply_after_apply = False
        self.lose_reply_before_apply = False
        self.fail_get = None                      # callable(path) -> bool
        self.tamper_created_sha = False
        self.truncate_trees = False
        self.strip_commit_newline = True
        self.tamper_blob_reads: dict[str, bytes] = {}

    # --- helpers for test setup -----------------------------------------
    def put(self, kind, raw):
        oid = _git_oid(kind, raw); self.objects[oid] = (kind, raw); return oid

    def commit_files(self, files: dict[str, FileEntry], *, parent=None, ts=1_700_000_000, message="fixture\n"):
        dirs: dict = {}
        for path, entry in files.items():
            parts = path.split("/"); d = dirs
            for p in parts[:-1]:
                d = d.setdefault(p, {})
            d[parts[-1]] = (entry.mode, entry.data.decode("ascii") if entry.mode == "160000" else self.put("blob", entry.data))
        def build(d):
            items = [("40000", n, build(v)) if isinstance(v, dict) else (v[0], n, v[1]) for n, v in d.items()]
            return self.put("tree", tree_raw(items))
        tree = build(dirs)
        who = f"Fixture <fixture@invalid> {ts} +0000"
        raw = f"tree {tree}\n" + (f"parent {parent}\n" if parent else "") + f"author {who}\ncommitter {who}\n\n{message}"
        return self.put("commit", raw.encode())

    def set_branch(self, branch, oid):
        self.refs["refs/heads/" + branch] = oid

    def head(self, branch):
        return self.refs.get("refs/heads/" + branch)

    def tree_files(self, commit):
        fields = parse_commit_raw(self.objects[commit][1]); files = {}
        def walk(oid, prefix):
            for mode, name, child in parse_tree_raw(self.objects[oid][1]):
                if mode == "40000":
                    walk(child, prefix + name + "/")
                elif mode == "160000":
                    files[prefix + name] = FileEntry(child.encode(), mode, "gitlink")
                else:
                    files[prefix + name] = FileEntry(self.objects[child][1], mode, "symlink" if mode == "120000" else "blob")
        walk(fields["tree"], ""); return files

    def advance(self, branch, files, ts=1_700_000_100):
        oid = self.commit_files(files, parent=self.head(branch), ts=ts, message="other writer\n")
        self.set_branch(branch, oid); return oid

    def _ancestors(self, oid):
        seen, stack = set(), [oid]
        while stack:
            o = stack.pop()
            if o in seen or o not in self.objects:
                continue
            seen.add(o)
            stack.extend(parse_commit_raw(self.objects[o][1])["parents"])
        return seen

    # --- REST -------------------------------------------------------------
    def request(self, method, path, body=None):
        self.log.append((method, path))
        prefix = f"repos/{REPO}"
        if not path.startswith(prefix):
            return 404, None
        rest = path[len(prefix):]
        if method == "GET" and self.fail_get and self.fail_get(rest):
            raise RuntimeError("simulated GET unavailable")
        if method == "GET":
            return self._get(rest)
        if method == "POST":
            return self._post(rest, body)
        return 405, None

    def _get(self, rest):
        if rest == "":
            return 200, {"full_name": REPO, "default_branch": self.default_branch}
        m = re.fullmatch(r"/git/ref/heads/(.+)", rest)
        if m:
            oid = self.head(m.group(1))
            return (200, {"ref": "refs/heads/" + m.group(1), "object": {"type": "commit", "sha": oid}}) if oid else (404, None)
        m = re.fullmatch(r"/git/commits/([0-9a-f]{40})", rest)
        if m and self.objects.get(m.group(1), ("",))[0] == "commit":
            f = parse_commit_raw(self.objects[m.group(1)][1])
            msg = f["message"][:-1] if self.strip_commit_newline and f["message"].endswith("\n") else f["message"]
            ident = lambda w: {"name": f[w]["name"], "email": f[w]["email"], "date": _iso(f[w]["ts"])}
            return 200, {"sha": m.group(1), "tree": {"sha": f["tree"]}, "parents": [{"sha": p} for p in f["parents"]],
                         "author": ident("author"), "committer": ident("committer"), "message": msg}
        m = re.fullmatch(r"/git/trees/([0-9a-f]{40})(\?recursive=1)?", rest)
        if m and self.objects.get(m.group(1), ("",))[0] == "tree":
            entries = []
            def walk(oid, prefix, recursive):
                for mode, name, child in parse_tree_raw(self.objects[oid][1]):
                    kind = "tree" if mode == "40000" else ("commit" if mode == "160000" else "blob")
                    item = {"path": prefix + name, "mode": "040000" if kind == "tree" else mode, "type": kind, "sha": child}
                    if kind == "blob":
                        item["size"] = len(self.objects[child][1])
                    entries.append(item)
                    if kind == "tree" and recursive:
                        walk(child, prefix + name + "/", True)
            walk(m.group(1), "", bool(m.group(2)))
            return 200, {"sha": m.group(1), "tree": entries, "truncated": self.truncate_trees}
        m = re.fullmatch(r"/git/blobs/([0-9a-f]{40})", rest)
        if m and self.objects.get(m.group(1), ("",))[0] == "blob":
            data = self.tamper_blob_reads.get(m.group(1), self.objects[m.group(1)][1])
            return 200, {"sha": m.group(1), "encoding": "base64", "size": len(data),
                         "content": base64.b64encode(data).decode()}
        return 404, None

    def _post(self, rest, body):
        self.object_posts += 1
        if rest == "/git/blobs":
            oid = self.put("blob", base64.b64decode(body["content"]))
        elif rest == "/git/trees":
            items = []
            for e in body["tree"]:
                if e["type"] != "commit" and e["sha"] not in self.objects:
                    return 422, {"message": "tree entry object missing"}
                items.append(("40000" if e["mode"] == "040000" else e["mode"], e["path"], e["sha"]))
            oid = self.put("tree", tree_raw(items))
        elif rest == "/git/commits":
            if body["tree"] not in self.objects or any(p not in self.objects for p in body["parents"]):
                return 422, {"message": "missing object"}
            def who(x):
                ts = int(datetime.fromisoformat(x["date"].replace("Z", "+00:00")).timestamp())
                return f"{x['name']} <{x['email']}> {ts} +0000"
            raw = f"tree {body['tree']}\n" + "".join(f"parent {p}\n" for p in body["parents"])
            raw += f"author {who(body['author'])}\ncommitter {who(body['committer'])}\n\n{body['message']}"
            oid = self.put("commit", raw.encode())
        else:
            return 404, None
        return 201, {"sha": ("f" * 40) if self.tamper_created_sha else oid}

    # --- GraphQL ----------------------------------------------------------
    def graphql(self, document, variables):
        self.log.append(("GRAPHQL", document.split("(")[0]))
        if document.lstrip().startswith("mutation"):
            return self._update_refs(variables["input"])
        if "SymphonyG61Repo" in document:
            return 200, {"data": {"repository": {"id": REPO_ID, "nameWithOwner": REPO, "viewerPermission": "WRITE",
                                                 "isArchived": False, "defaultBranchRef": {"name": self.default_branch}}}}
        if "SymphonyG61Issue" in document:
            issue = self.issues.get(variables["number"])
            return 200, {"data": {"repository": {"issue": issue}}}
        return 200, {"errors": [{"message": "unsupported query"}]}

    def _update_refs(self, data):
        self.update_refs_requests += 1
        if self.lose_reply_before_apply:
            raise LostReply("request lost before GitHub processed it")
        if self.race_before_update_refs:
            self.race_before_update_refs()
        if data.get("repositoryId") != REPO_ID:
            return 200, {"errors": [{"message": "repository not found"}]}
        updates = data["refUpdates"]
        for u in updates:  # validate all first: atomic all-or-nothing
            current = self.refs.get(u["name"])
            if u.get("beforeOid") is not None and current != u["beforeOid"]:
                return 200, {"data": {"updateRefs": None}, "errors": [{"message": "ref did not match beforeOid"}]}
            if self.objects.get(u["afterOid"], ("",))[0] != "commit":
                return 200, {"data": {"updateRefs": None}, "errors": [{"message": "afterOid missing"}]}
            if not u.get("force") and current and current not in self._ancestors(u["afterOid"]):
                return 200, {"data": {"updateRefs": None}, "errors": [{"message": "not a fast-forward"}]}
        for u in updates:
            self.refs[u["name"]] = u["afterOid"]; self.ref_mutations += 1
        if self.lose_reply_after_apply:
            raise LostReply("GitHub applied the update; response lost")
        return 200, {"data": {"updateRefs": {"clientMutationId": data.get("clientMutationId")}}}
