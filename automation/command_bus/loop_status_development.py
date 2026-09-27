"""Render repository development progress into the human-facing status Issue.

This module is metadata-only. It performs no network calls, does not infer live
provider/model activity, and never starts or controls a loop.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .loop_status_issue import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    replace_managed_block,
)

_SHA = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_PRS = {4: "Relay", 25: "Claude Loop"}


def _single_line(value: Any, *, fallback: str = "UNKNOWN", max_len: int = 120) -> str:
    if value is None:
        return fallback
    text = " ".join(str(value).split()).replace(chr(96), "'")
    if not text:
        return fallback
    return text[:max_len]


def _validate_lane(lane: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(lane, dict):
        raise ValueError("development lane must be an object")
    pr = lane.get("pr")
    if pr not in _ALLOWED_PRS:
        raise ValueError("unexpected development PR")
    head_sha = lane.get("head_sha")
    if not isinstance(head_sha, str) or not _SHA.fullmatch(head_sha):
        raise ValueError("invalid development head SHA")
    state = lane.get("state")
    if state not in {"open", "closed"}:
        raise ValueError("invalid development PR state")
    merged = lane.get("merged")
    if not isinstance(merged, bool):
        raise ValueError("invalid merged flag")
    mergeable = lane.get("mergeable")
    if mergeable not in {True, False, None}:
        raise ValueError("invalid mergeable flag")
    commits = lane.get("commits")
    if not isinstance(commits, int) or isinstance(commits, bool) or commits < 0:
        raise ValueError("invalid commit count")
    return lane


def render_development_section(snapshot: dict[str, Any]) -> str:
    if not isinstance(snapshot, dict):
        raise ValueError("development snapshot must be an object")
    main_sha = snapshot.get("main_sha")
    if not isinstance(main_sha, str) or not _SHA.fullmatch(main_sha):
        raise ValueError("invalid main SHA")
    raw_lanes = snapshot.get("lanes")
    if not isinstance(raw_lanes, list) or len(raw_lanes) != len(_ALLOWED_PRS):
        raise ValueError("development snapshot must contain exactly two lanes")

    lanes = [_validate_lane(item) for item in raw_lanes]
    if {item["pr"] for item in lanes} != set(_ALLOWED_PRS):
        raise ValueError("development snapshot lanes are incomplete")

    rows = []
    for lane in sorted(lanes, key=lambda item: item["pr"]):
        pr = lane["pr"]
        label = _ALLOWED_PRS[pr]
        state = "MERGED" if lane["merged"] else lane["state"].upper()
        mergeable = (
            "YES" if lane["mergeable"] is True
            else "NO" if lane["mergeable"] is False
            else "UNKNOWN"
        )
        head = lane["head_sha"][:12]
        updated_at = _single_line(lane.get("updated_at"))
        rows.append(
            f"| {label} | #{pr} | {state} | {mergeable} | {lane['commits']} | "
            f"`{head}` | {updated_at} |"
        )

    return (
        "## 🛠 Development progress — GitHub evidence\n\n"
        "この欄はPR/commitのGitHub readbackだけを表示します。"
        "**Claude/Jules/モデルが今この瞬間に実行中だという証明には使いません。**\n\n"
        "| Lane | PR | PR state | Mergeable | Commits | Head | GitHub updated |\n"
        "| --- | ---: | --- | --- | ---: | --- | --- |\n"
        + "\n".join(rows)
        + "\n\n"
        f"- main: `{main_sha[:12]}`\n"
        "- Runtime ownership/livenessは上のRuntime信号だけを正本として扱います。\n"
        "- PR更新だけを理由に SEMI_AUTO / AUTO を推測しません。\n"
        "- この欄の更新ではIssueコメントや@mention通知を作成しません。\n"
    )


def render_development_body(existing_body: str, snapshot: dict[str, Any]) -> str:
    section = render_development_section(snapshot)
    return replace_managed_block(
        existing_body,
        DEVELOPMENT_START,
        DEVELOPMENT_END,
        section,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_body_file")
    parser.add_argument("snapshot_file")
    parser.add_argument("--body-out", required=True)
    args = parser.parse_args()

    existing_body = Path(args.issue_body_file).read_text(encoding="utf-8")
    snapshot = json.loads(Path(args.snapshot_file).read_text(encoding="utf-8"))
    body = render_development_body(existing_body, snapshot)
    Path(args.body_out).write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
