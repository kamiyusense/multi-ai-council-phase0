"""Production GitHub adapters for the Claude x Jules AUTO loop (stage 6).

Implements the existing ``GitHubContentsClient`` and ref protocols used by the
dispatcher, result inbox, inspection store, adoption and owner ledger, so the
same controller that runs against the fake world runs against GitHub.

Transport (no new dependency, no credential handling in this module):
  * git CLI against the configured remote for contents and refs.  Reads fetch
    the branch tip into ``refs/claude-live/<branch>``; ref heads are always read
    fresh with ``git ls-remote``.
  * Writes are a plain, non-force ``git push`` of exactly one commit that adds
    exactly one file (create-only), or a non-force fast-forward of a ref.  The
    carrier workflow requires one added file per command commit, which this
    shape satisfies by construction.
  * A push that git *rejects* (remote moved, ``non-fast-forward``/``fetch
    first``) wrote nothing, so the single-file commit is rebuilt on the new tip
    (bounded).  Any other push failure is ambiguous: it is raised and the
    caller resolves it by readback only, never by resending.
  * The repository-scoped GitHub REST API (pull requests, workflow runs and
    job logs) is read through the environment's configured HTTPS proxy.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .github_backend import GitHubContent

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_PATH = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,299}$")
MAX_REJECTED_PUSH_REBUILDS = 3


class PushRejected(RuntimeError):
    """git refused the push: definitively nothing was written."""


def _safe_branch(branch: str) -> str:
    if not isinstance(branch, str) or not _BRANCH.fullmatch(branch) or ".." in branch or branch.endswith((".lock", "/")):
        raise ValueError(f"unsafe branch name: {branch!r}")
    return branch


def _safe_path(path: str) -> str:
    if not isinstance(path, str) or not _PATH.fullmatch(path) or ".." in path.split("/"):
        raise ValueError(f"unsafe repository path: {path!r}")
    return path


@dataclass
class _Tip:
    sha: str | None
    read_at: float


class GitLiveClient:
    """Contents + refs over git.  One instance per working clone."""

    def __init__(self, repo_dir: str, *, remote: str = "origin", tip_ttl_seconds: float = 5.0,
                 author_name: str = "Claude AUTO Loop A", author_email: str = "noreply@anthropic.com",
                 message_trailer: str = "", timeout: int = 180):
        self.repo_dir, self.remote = repo_dir, remote
        self.tip_ttl, self.timeout = tip_ttl_seconds, timeout
        self.trailer = message_trailer.strip()
        self.env = dict(os.environ, GIT_AUTHOR_NAME=author_name, GIT_AUTHOR_EMAIL=author_email,
                        GIT_COMMITTER_NAME=author_name, GIT_COMMITTER_EMAIL=author_email,
                        GIT_TERMINAL_PROMPT="0")
        self._tips: dict[str, _Tip] = {}
        self.pushes: list[tuple[str, str]] = []  # (dst ref, sha) audit for evidence

    # -- git plumbing ----------------------------------------------------------
    def _git(self, *args: str, input: str | None = None, check: bool = True,
             env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(["git", *args], cwd=self.repo_dir, input=input, text=True, capture_output=True,
                              encoding="utf-8", errors="replace", env=env or self.env, timeout=self.timeout)
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()[:300]}")
        return proc

    def remote_head(self, branch: str) -> str | None:
        branch = _safe_branch(branch)
        out = self._git("ls-remote", "--heads", self.remote, f"refs/heads/{branch}").stdout
        for line in out.splitlines():
            sha, _, ref = line.partition("\t")
            if ref == f"refs/heads/{branch}" and _SHA40.fullmatch(sha):
                return sha
        return None

    def _local_ref(self, branch: str) -> str:
        return f"refs/claude-live/{branch}"

    def _tip(self, branch: str, *, fresh: bool = False) -> str | None:
        branch = _safe_branch(branch)
        cached = self._tips.get(branch)
        if not fresh and cached is not None and time.monotonic() - cached.read_at < self.tip_ttl:
            return cached.sha
        if self.remote_head(branch) is None:
            self._tips[branch] = _Tip(None, time.monotonic())
            return None
        self._git("fetch", "--no-tags", "--quiet", self.remote, f"+refs/heads/{branch}:{self._local_ref(branch)}")
        sha = self._git("rev-parse", self._local_ref(branch)).stdout.strip()
        self._tips[branch] = _Tip(sha, time.monotonic())
        return sha

    def invalidate(self, branch: str | None = None) -> None:
        if branch is None:
            self._tips.clear()
        else:
            self._tips.pop(branch, None)

    def has_commit(self, sha: str) -> bool:
        return self._git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0

    def ensure_commit(self, sha: str) -> bool:
        if not isinstance(sha, str) or not _SHA40.fullmatch(sha):
            return False
        if self.has_commit(sha):
            return True
        self._git("fetch", "--no-tags", "--quiet", self.remote, sha, check=False)
        return self.has_commit(sha)

    def _push(self, src: str, branch: str) -> None:
        dst = f"refs/heads/{_safe_branch(branch)}"
        proc = self._git("push", "--porcelain", self.remote, f"{src}:{dst}", check=False)
        self.invalidate(branch)
        flags = [line.split("\t", 1)[0] for line in proc.stdout.splitlines() if "\t" in line and line[:1] in " +-*=!"]
        if proc.returncode == 0 and flags and flags[0] in {" ", "*", "="}:
            self.pushes.append((dst, src))
            return
        text = f"{proc.stdout}\n{proc.stderr}"
        if "!" in flags and re.search(r"non-fast-forward|fetch first|stale info|already exists|cannot lock ref", text):
            raise PushRejected(f"push to {dst} rejected: {text.strip()[:300]}")
        raise RuntimeError(f"push to {dst} outcome ambiguous: {text.strip()[:300]}")

    # -- GitHubContentsClient --------------------------------------------------
    def get(self, path: str, ref: str) -> GitHubContent | None:
        path = _safe_path(path)
        tip = self._tip(ref)
        if tip is None:
            return None
        blob = self._git("rev-parse", "--verify", "--quiet", f"{tip}:{path}", check=False)
        if blob.returncode != 0:
            return None
        text = self._git("cat-file", "blob", blob.stdout.strip()).stdout
        return GitHubContent(path=path, text=text, sha=blob.stdout.strip())

    def list(self, prefix: str, ref: str) -> list[GitHubContent]:
        directory = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
        tip = self._tip(ref)
        if tip is None:
            return []
        args = ["ls-tree", "-r", "--full-tree", "-z", tip]
        if directory:
            args += ["--", _safe_path(directory)]
        out = self._git(*args).stdout
        contents = []
        for entry in filter(None, out.split("\0")):
            meta, _, path = entry.partition("\t")
            kind, sha = meta.split()[1:3]
            if kind == "blob" and path.startswith(prefix):
                contents.append(GitHubContent(path=path, text=self._git("cat-file", "blob", sha).stdout, sha=sha))
        return sorted(contents, key=lambda c: c.path)

    def create(self, path: str, text: str, message: str, branch: str) -> GitHubContent:
        path = _safe_path(path)
        for _ in range(MAX_REJECTED_PUSH_REBUILDS):
            tip = self._tip(branch, fresh=True)
            if tip is None:
                raise RuntimeError(f"branch {branch} does not exist")
            if self._git("rev-parse", "--verify", "--quiet", f"{tip}:{path}", check=False).returncode == 0:
                raise RuntimeError("create-only conflict: path already exists")
            commit = self._single_file_commit(tip, path, text, message)
            try:
                self._push(commit, branch)
            except PushRejected:
                continue  # nothing was written; rebuild on the moved tip
            blob = self._git("rev-parse", f"{commit}:{path}").stdout.strip()
            return GitHubContent(path=path, text=text, sha=blob)
        raise PushRejected(f"branch {branch} kept moving; nothing written")

    def update(self, path: str, text: str, sha: str, message: str, branch: str) -> GitHubContent:
        raise RuntimeError("Claude AUTO durable records are create-only")

    def _single_file_commit(self, parent: str, path: str, text: str, message: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(self.env, GIT_INDEX_FILE=os.path.join(tmp, "index"))
            self._git("read-tree", parent, env=env)
            blob = self._git("hash-object", "-w", "--stdin", input=text, env=env).stdout.strip()
            self._git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
            tree = self._git("write-tree", env=env).stdout.strip()
        body = message if not self.trailer else f"{message}\n\n{self.trailer}"
        commit = self._git("commit-tree", tree, "-p", parent, input=body).stdout.strip()
        changed = self._git("diff-tree", "--no-commit-id", "--name-status", "-r", parent, commit).stdout.split()
        if changed != ["A", path]:
            raise RuntimeError("single-file commit invariant violated")
        return commit

    # -- refs -------------------------------------------------------------------
    def get_branch_head(self, branch: str) -> str | None:
        return self.remote_head(branch)

    def get_commit_tree(self, sha: str) -> str | None:
        if not self.ensure_commit(sha):
            return None
        return self._git("rev-parse", f"{sha}^{{tree}}").stdout.strip()

    def create_branch(self, branch: str, sha: str) -> dict[str, Any]:
        if self.remote_head(branch) is not None:
            raise RuntimeError("ref exists")
        if not self.ensure_commit(sha):
            raise RuntimeError("source commit unavailable")
        self._push(sha, branch)
        return {"status": "WRITTEN"}

    def fast_forward_branch(self, branch: str, expected_old: str, new_sha: str) -> dict[str, Any]:
        if self.remote_head(branch) != expected_old:
            raise RuntimeError("branch is not at the expected head")
        if not (self.ensure_commit(expected_old) and self.ensure_commit(new_sha)):
            raise RuntimeError("commits unavailable")
        if self._git("merge-base", "--is-ancestor", expected_old, new_sha, check=False).returncode != 0:
            raise RuntimeError("not a fast-forward")
        self._push(new_sha, branch)
        return {"status": "WRITTEN"}

    def compare(self, base: str, head: str) -> dict[str, Any] | None:
        """GitHub compare semantics (files from the merge base to head), from git."""
        if not (self.ensure_commit(base) and self.ensure_commit(head)):
            return None
        merge_base = self._git("merge-base", base, head, check=False).stdout.strip()
        if not _SHA40.fullmatch(merge_base):
            return None
        ahead = int(self._git("rev-list", "--count", f"{base}..{head}").stdout.strip())
        behind = int(self._git("rev-list", "--count", f"{head}..{base}").stdout.strip())
        status_names = {"A": "added", "M": "modified", "D": "removed", "T": "modified"}
        files = []
        for line in self._git("diff", "--no-renames", "--name-status", merge_base, head).stdout.splitlines():
            code, _, path = line.partition("\t")
            files.append({"path": path, "status": status_names.get(code[:1], "unknown")})
        return {"base_sha": base, "head_sha": head, "merge_base": merge_base,
                "ahead_by": ahead, "behind_by": behind, "files": files}

    def added_by(self, branch: str, path: str) -> list[str]:
        """Commits on ``branch`` that added ``path`` (newest first)."""
        tip = self._tip(branch)
        if tip is None:
            return []
        out = self._git("log", "--diff-filter=A", "--format=%H", tip, "--", _safe_path(path)).stdout
        return [line for line in out.split() if _SHA40.fullmatch(line)]

    def commit_time(self, sha: str) -> str | None:
        if not self.ensure_commit(sha):
            return None
        return self._git("show", "-s", "--format=%cI", sha).stdout.strip() or None

    def show(self, sha: str, path: str) -> str | None:
        if not self.ensure_commit(sha):
            return None
        proc = self._git("show", f"{sha}:{_safe_path(path)}", check=False)
        return proc.stdout if proc.returncode == 0 else None


class GitHubRestReader:
    """Repository-scoped, read-only GitHub REST access (paginated)."""

    def __init__(self, repo: str, *, api: str = "https://api.github.com", timeout: int = 30):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
            raise ValueError("invalid repository")
        self.repo, self.api, self.timeout = repo, api.rstrip("/"), timeout

    def get(self, path: str, params: dict[str, Any] | None = None, *, raw: bool = False) -> Any:
        url = f"{self.api}/repos/{self.repo}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(f"GitHub GET {path} -> HTTP {exc.code}") from exc
        return body if raw else json.loads(body)

    def paged(self, path: str, params: dict[str, Any] | None = None, *, key: str | None = None,
              max_pages: int = 20) -> list[Any]:
        items: list[Any] = []
        for page in range(1, max_pages + 1):
            data = self.get(path, dict(params or {}, per_page=100, page=page))
            batch = (data or {}).get(key, []) if key else (data or [])
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise RuntimeError(f"pagination limit reached for {path}; refusing a partial listing")

    def pulls_for_base(self, base: str) -> list[dict[str, Any]]:
        return self.paged("pulls", {"state": "all", "base": base})

    def pull(self, number: int) -> dict[str, Any] | None:
        return self.get(f"pulls/{int(number)}")

    def workflow_runs_for_commit(self, workflow_file: str, head_sha: str) -> list[dict[str, Any]]:
        return self.paged(f"actions/workflows/{workflow_file}/runs", {"head_sha": head_sha}, key="workflow_runs")

    def active_workflow_runs(self, workflow_file: str) -> list[dict[str, Any]]:
        """Every run of the workflow that has not finished (any not-completed status)."""
        runs: list[dict[str, Any]] = []
        for status in ("queued", "in_progress", "waiting", "requested", "pending"):
            runs.extend(self.paged(f"actions/workflows/{workflow_file}/runs", {"status": status},
                                   key="workflow_runs"))
        return runs

    def recent_workflow_runs(self, workflow_file: str, *, per_page: int = 30) -> list[dict[str, Any]]:
        data = self.get(f"actions/workflows/{workflow_file}/runs", {"per_page": per_page})
        return list((data or {}).get("workflow_runs", []))

    def run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        return self.paged(f"actions/runs/{int(run_id)}/jobs", key="jobs")

    def job_log(self, job_id: int) -> str | None:
        return self.get(f"actions/jobs/{int(job_id)}/logs", raw=True)


def pull_request_payload(pr: dict[str, Any], *, action: str = "synchronize") -> dict[str, Any]:
    """Shape a REST pull request like the ``pull_request`` webhook payload."""
    repo = pr["base"]["repo"]
    return {"action": action, "repository": {"full_name": repo["full_name"]}, "pull_request": {
        "number": pr["number"], "state": pr["state"], "merged": bool(pr.get("merged") or pr.get("merged_at")),
        "body": pr.get("body") or "",
        "base": {"ref": pr["base"]["ref"], "repo": {"full_name": pr["base"]["repo"]["full_name"]}},
        "head": {"ref": pr["head"]["ref"], "sha": pr["head"]["sha"],
                 "repo": {"full_name": (pr["head"].get("repo") or {}).get("full_name")}}}}


def fresh_pr_view(pr: dict[str, Any] | None) -> dict[str, Any] | None:
    if pr is None:
        return None
    return {"number": pr["number"], "state": pr["state"], "merged": bool(pr.get("merged") or pr.get("merged_at")),
            "base_ref": pr["base"]["ref"], "head_sha": pr["head"]["sha"], "head_ref": pr["head"]["ref"],
            "body": pr.get("body") or ""}
