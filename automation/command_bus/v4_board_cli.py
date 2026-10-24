"""Regenerate the V4 read-only board Issue (step S4b).  Run by .github/workflows/v4-board.yml.

Reads: the lane catalog and registry (repository files), the checkpoint Issue's comments and the board Issue.
Writes: only the board Issue body, only between the board markers, and only when it changed.  A read or parse
failure stops the run before any write (fail closed); a write is never retried.

Usage: python -m automation.command_bus.v4_board_cli [--dry-run]
Environment: GITHUB_TOKEN, GITHUB_REPOSITORY.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from . import lane_catalog, v4_board

API = "https://api.github.com"
MAX_COMMENT_PAGES = 20
_REPOSITORY = "kamiyusense/multi-ai-council-phase0"

Transport = Callable[[str, str, Any], Any]


def http_transport(token: str) -> Transport:
    def call(method: str, path: str, payload: Any) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(f"{API}/{path}", data=data, method=method, headers={
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    return call


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
    old = board.get("body") or ""
    new = v4_board.replace_board_block(old, v4_board.render_board(lanes, points, now=now, config=config))
    if dry_run:
        print(new)
        return "DRY_RUN"
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
