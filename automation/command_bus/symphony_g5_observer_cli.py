"""Opt-in G5 local observation sidecar. Importing this file has no side effects.

This process reads Symphony's signed local JSONL events and writes only the
separate non-default durable ledger branch. It cannot start or stop Symphony,
Codex, or a model, and has no Git result-adoption path.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .symphony_attempt_store import GitHubAutonomousAttemptStore
from .symphony_github_adapter import GitHubExecutorContentsClient
from .symphony_production_observer import ObservedIssue, SymphonyProductionObserver


def _observer(config_path: str) -> SymphonyProductionObserver:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if type(config) is not dict or set(config) != {"repository", "ledger_branch", "campaign_id", "issues"}:
        raise ValueError("invalid G5 observation configuration")
    if config["ledger_branch"] == "codex/symphony-inspired-minimal-controller":
        raise ValueError("G5 observations require a separate ledger branch from PR #320")
    issues = {}
    for issue_id, raw in config["issues"].items():
        if type(raw) is not dict or set(raw) != {
            "task_id", "generation", "expected_target_head", "runner_generation", "scope",
        }:
            raise ValueError("invalid issue binding")
        issues[issue_id] = ObservedIssue(**raw)
    key_hex = os.environ.get("SYMPHONY_G5_OBSERVER_KEY_HEX", "")
    key = bytes.fromhex(key_hex) if key_hex else b""
    token = os.environ.get("GITHUB_TOKEN", "")
    client = GitHubExecutorContentsClient(token, config["repository"])
    store = GitHubAutonomousAttemptStore(client, write_branch=config["ledger_branch"])
    return SymphonyProductionObserver(store, campaign_id=config["campaign_id"], issues=issues, key=key)


def observe_file(observer: SymphonyProductionObserver, path: str, *, follow: bool,
                 poll_seconds: float = 0.5) -> list[str]:
    """Read complete records; leave an unfinished final line for the next poll."""
    statuses = []
    offset = 0
    while True:
        try:
            source = open(path, "rb")
        except FileNotFoundError:
            if not follow:
                raise
            time.sleep(poll_seconds)
            continue
        with source:
            source.seek(0, os.SEEK_END)
            if source.tell() < offset:
                raise RuntimeError("G5 event file was truncated; readback required")
            source.seek(offset)
            while True:
                start = source.tell()
                line = source.readline()
                if not line or not line.endswith(b"\n"):
                    source.seek(start)
                    break
                result = observer.capture_line(line.decode("utf-8"))
                statuses.append(result.status)
                print(f"{result.status} {result.kind} {result.attempt_id}", flush=True)
                offset = source.tell()
        if not follow:
            return statuses
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe signed G5 worker events only")
    parser.add_argument("--config", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--follow", action="store_true")
    args = parser.parse_args()
    observer = _observer(args.config)
    try:
        observe_file(observer, args.events, follow=args.follow)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
