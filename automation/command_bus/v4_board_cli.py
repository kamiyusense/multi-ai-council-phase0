"""Regenerate the V4 board Issue and apply its comments to the board record (steps S4b, S5).  Run by .github/workflows/v4-board.yml.

Reads: the lane catalog and registry (repository files), the checkpoint Issue's comments, the board Issue, its
comments and the board record (step S5) on its own branch.
Writes, in this order: the board record (only when the board comments changed it; the branch is created from
main on first use), then the board Issue body between the board markers (only when it changed).  A read or parse
failure stops the run before any write (fail closed); a write is never retried, and a failed record write stops
the run before the board write.  The next run re-reads everything.

Usage: python -m automation.command_bus.v4_board_cli [--dry-run]
Environment: GITHUB_TOKEN, GITHUB_REPOSITORY.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from . import lane_catalog, v4_board, v4_board_input
from .approval_comment import load_policy

API = "https://api.github.com"
MAX_COMMENT_PAGES = 20
_REPOSITORY = "kamiyusense/multi-ai-council-phase0"

Transport = Callable[[str, str, Any], Any]


class NotFound(Exception):
    """GitHub answered 404 (a missing record file or branch)."""


def http_transport(token: str) -> Transport:
    def call(method: str, path: str, payload: Any) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(f"{API}/{path}", data=data, method=method, headers={
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and method == "GET":
                raise NotFound(path) from exc
            raise v4_board.BoardError(f"HTTP_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise v4_board.BoardError("NETWORK") from exc
    return call


def read_record(call: Transport, repo: str, config: v4_board.BoardConfig) -> tuple[dict[str, Any], str | None, bool]:
    """(record, file sha or None, branch exists)."""
    try:
        call("GET", f"repos/{repo}/branches/{config.record_branch}", None)
    except NotFound:
        return v4_board_input.empty_record(config.board_issue), None, False
    try:
        found = call("GET", f"repos/{repo}/contents/{config.record_path}?ref={config.record_branch}", None)
    except NotFound:
        return v4_board_input.empty_record(config.board_issue), None, True
    if not isinstance(found, dict) or found.get("encoding") != "base64" or not isinstance(found.get("sha"), str):
        raise v4_board.BoardError("RECORD_UNREADABLE")
    try:
        record = json.loads(base64.b64decode(found["content"]).decode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise v4_board.BoardError("RECORD_UNREADABLE") from exc
    try:
        return v4_board_input.validate_record(record, config.board_issue), found["sha"], True
    except v4_board_input.InputError as exc:
        raise v4_board.BoardError(str(exc)) from exc


def write_record(call: Transport, repo: str, config: v4_board.BoardConfig, record: dict[str, Any],
                 sha: str | None, branch_exists: bool) -> None:
    if not branch_exists:
        main = call("GET", f"repos/{repo}/git/ref/heads/main", None)
        call("POST", f"repos/{repo}/git/refs", {"ref": f"refs/heads/{config.record_branch}",
                                                "sha": main["object"]["sha"]})
    text = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    payload = {"message": "V4 board record: apply board comments\n\nAI-Agent: claude\n",
               "content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "branch": config.record_branch}
    if sha is not None:
        payload["sha"] = sha
    call("PUT", f"repos/{repo}/contents/{config.record_path}", payload)


def read_comments(call: Transport, repo: str, issue: int) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        batch = call("GET", f"repos/{repo}/issues/{issue}/comments?per_page=100&page={page}", None)
        if not isinstance(batch, list):
            raise v4_board.BoardError("COMMENTS_UNREADABLE")
        comments.extend(batch)
        if len(batch) < 100:
            return comments
    raise v4_board.BoardError("TOO_MANY_COMMENTS")


def run(call: Transport, repo: str, now: datetime, *, dry_run: bool = False) -> str:
    """Returns UPDATED, UNCHANGED or DRY_RUN."""
    if repo != _REPOSITORY:
        raise v4_board.BoardError("WRONG_REPOSITORY")
    config = v4_board.load_config()
    lanes = lane_catalog.load_catalog()
    points = v4_board.checkpoints_from_comments(read_comments(call, repo, config.checkpoint_issue),
                                                config.checkpoint_writer_id)
    board = call("GET", f"repos/{repo}/issues/{config.board_issue}", None)
    if not isinstance(board, dict) or board.get("state") != "open" or "pull_request" in board:
        raise v4_board.BoardError("BOARD_ISSUE_NOT_OPEN")
    record, sha, branch_exists = read_record(call, repo, config)
    board_comments = read_comments(call, repo, config.board_issue)
    new_record = v4_board_input.fold_comments(record, board_comments, resume_phrases=config.resume_phrases,
                                              policy=load_policy())
    old = board.get("body") or ""
    new = v4_board.replace_board_block(old, v4_board.render_board(lanes, points, now=now, config=config,
                                                                  record=new_record))
    if dry_run:
        print(new)
        return "DRY_RUN"
    if new_record != record:
        write_record(call, repo, config, new_record, sha, branch_exists)
    if new == old:
        return "UNCHANGED"
    call("PATCH", f"repos/{repo}/issues/{config.board_issue}", {"body": new})
    return "UPDATED"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN is missing", file=sys.stderr)
        return 2
    try:
        result = run(http_transport(token), os.environ.get("GITHUB_REPOSITORY", ""), datetime.now(timezone.utc),
                     dry_run=args.dry_run)
    except v4_board.BoardError as exc:
        print(f"board left unchanged: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
