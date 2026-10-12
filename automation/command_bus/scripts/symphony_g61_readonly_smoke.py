"""G6.1 read-only qualification of the authenticated readers against GitHub.

Only GET / GraphQL queries through ``ReadOnlyGitHubHttp``; no write, no
mutation, no model/provider. The token comes from the existing ``gh`` login,
is held in memory only and never printed. Output is a JSON evidence document
comparing GitHub's answers with the local Git object database.

Usage: python -m automation.command_bus.scripts.symphony_g61_readonly_smoke OUT.json
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys

from ..symphony_github_git_transport import UPDATE_REFS_DOCUMENT, TransportIntegrityError, commit_raw_from_api
from ..symphony_github_readers import (GitHubTargetReader, GitHubTaskValidityReader, ReadOnlyGitHubHttp,
                                       read_repository_identity)

REPOSITORY = "kamiyusense/multi-ai-council-phase0"
SMALL_BRANCH = "jules-work/relay-dev-loop-061-model-verification-proof-contract"
UTC_COMMIT = "2f6d2dcc1d9761797a19aad10263a5025ae8300b"
ISSUE = 342


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def local_inventory(ref: str) -> dict:
    out = {}
    for line in git("ls-tree", "-r", "-z", ref).split(b"\0"):
        if not line:
            continue
        meta, path = line.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        out[path.decode()] = {"mode": mode, "sha256": hashlib.sha256(git("cat-file", kind, oid)).hexdigest()}
    return out


def main(out_path: str) -> int:
    token = subprocess.run(["gh", "auth", "token"], check=True, capture_output=True, text=True).stdout.strip()
    http = ReadOnlyGitHubHttp(token); del token
    evidence: dict = {"protocol": "SYMPHONY_G61_READONLY_SMOKE_V1", "repository": REPOSITORY,
                      "writes": 0, "graphql_mutations": 0, "model_provider_live": 0}
    ident = read_repository_identity(http, REPOSITORY)
    evidence["repository_identity"] = ident

    main_head = git("rev-parse", "origin/main").decode().strip()
    # main itself is the default branch, so the reader refuses it as a target:
    try:
        GitHubTargetReader(http, repository=REPOSITORY, branch="main", default_branch="main")
        evidence["default_branch_target_refused"] = False
    except ValueError:
        evidence["default_branch_target_refused"] = True

    pr_branch = "codex/symphony-inspired-minimal-controller"
    limited = GitHubTargetReader(http, repository=REPOSITORY, branch=pr_branch, default_branch="main", max_files=100).read()
    evidence["large_branch_limited_read"] = {"branch": pr_branch, "head": limited.head,
        "local_head": git("rev-parse", "origin/" + pr_branch).decode().strip(),
        "complete": limited.complete, "files_returned": len(limited.files),
        "tree_hashes_verified": True}

    small = GitHubTargetReader(http, repository=REPOSITORY, branch=SMALL_BRANCH, default_branch="main").read()
    remote = {p: {"mode": e.mode, "sha256": e.sha256} for p, e in small.files.items()}
    local = local_inventory("origin/" + SMALL_BRANCH)
    evidence["small_branch_full_read"] = {"branch": SMALL_BRANCH, "head": small.head,
        "local_head": git("rev-parse", "origin/" + SMALL_BRANCH).decode().strip(),
        "complete": small.complete, "trustworthy": small.trustworthy, "file_count": len(remote),
        "matches_local_git_bytes": remote == local,
        "inventory_sha256": hashlib.sha256(json.dumps(remote, sort_keys=True).encode()).hexdigest()}

    status, body = http.request("GET", f"repos/{REPOSITORY}/git/commits/{UTC_COMMIT}")
    try:
        raw = commit_raw_from_api(body, UTC_COMMIT)
        evidence["commit_reconstruction"] = {"commit": UTC_COMMIT, "status": status,
            "matches_local_cat_file": raw == git("cat-file", "commit", UTC_COMMIT),
            "message_echo_has_trailing_newline": (body.get("message") or "").endswith("\n")}
    except TransportIntegrityError as exc:
        evidence["commit_reconstruction"] = {"commit": UTC_COMMIT, "status": status, "error": str(exc)}

    reader = GitHubTaskValidityReader(http, repository=REPOSITORY, trusted_logins={"kamiyusense"})
    v = reader.read(limited, issue_id=f"{REPOSITORY}#{ISSUE}", task_id="g61-readonly-smoke")
    evidence["issue_validity_query"] = {"issue": ISSUE, "graphql_query_accepted": True,
        "trustworthy": v.trustworthy, "valid": v.valid,
        "expected": "untrusted: historical Issue has no symphony-task block"}

    before = http.requests
    refused = []
    for attempt in (lambda: http.graphql(UPDATE_REFS_DOCUMENT, {}), lambda: http.request("PATCH", "repos/x/y/git/refs/heads/z", {})):
        try:
            attempt(); refused.append(False)
        except PermissionError:
            refused.append(True)
    evidence["write_refusal"] = {"all_refused_offline": all(refused) and http.requests == before}
    evidence["http_requests"] = http.requests
    evidence["origin_main_local"] = main_head
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(evidence, handle, indent=2, sort_keys=True); handle.write("\n")
    ok = (evidence["default_branch_target_refused"] and not limited.complete
          and evidence["large_branch_limited_read"]["head"] == evidence["large_branch_limited_read"]["local_head"]
          and small.complete and evidence["small_branch_full_read"]["matches_local_git_bytes"]
          and evidence["commit_reconstruction"].get("matches_local_cat_file") is True
          and v.trustworthy is False and evidence["write_refusal"]["all_refused_offline"])
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
