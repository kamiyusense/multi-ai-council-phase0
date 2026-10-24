"""V4 read-only board (docs/RELAY_TOWER_DIRECTION_V4.md, step S4b).

Renders a Japanese status board for the owner from two records:

* the V4 lane catalog (``config/lane_catalog_v4.json``, validated by ``lane_catalog``), and
* the Claude x Jules loop checkpoints on its control Issue (#346), written by the loop itself.

The board is display only.  It never decides anything, never changes a record and never starts a provider.  It
flags three things the owner may need to act on: a checkpoint that stopped arriving (the hourly loop may be
stuck), a MERGE_WAIT that has lasted too long, and tasks whose checkpoint says ``human_required``.

Pure functions only; the GitHub reads and the one Issue body write live in ``v4_board_cli``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .approval_comment import check_ai_write, load_policy
from .claude_closed_loop_protocol import _block
from .claude_jules_loop import CHECKPOINT_MARKER

__all__ = ["BoardConfig", "Checkpoint", "load_config", "checkpoints_from_comments", "render_board",
           "replace_board_block", "BoardError", "BOARD_START", "BOARD_END"]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "v4_board.json"
BOARD_START = "<!-- v4-board:start -->"
BOARD_END = "<!-- v4-board:end -->"
_JST = timezone(timedelta(hours=9))
_INT_KEYS = {"board_issue", "checkpoint_issue", "checkpoint_writer_id", "stale_checkpoint_hours",
             "merge_wait_alert_hours"}
_CONFIG_KEYS = _INT_KEYS | {"schema_version", "record_branch", "record_path", "resume_phrases"}
_BRANCH = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_RECORD_PATH = re.compile(r"[a-z0-9_]+(/[a-z0-9_]+)*\.json")
_STATUS_JA = {"ACTIVE": "動いてる", "FROZEN": "凍結（止めてある）", "MANUAL": "手動（相棒が動かす）",
              "PLANNED": "準備中"}
_OUTCOME_JA = {"CONTINUE": "作業中", "MERGE_WAIT": "人のマージ待ち", "NO_SAFE_TASK": "安全にできる仕事なし",
               "GOAL_COMPLETE": "目標達成", "DEFER": "いったん保留", "HARD_STOP_PROVIDER": "停止（提供元の都合）"}


class BoardError(ValueError):
    """Malformed input or board body (fail closed: the board is left as it is)."""


@dataclass(frozen=True)
class BoardConfig:
    board_issue: int
    checkpoint_issue: int
    checkpoint_writer_id: int
    stale_checkpoint_hours: int
    merge_wait_alert_hours: int
    record_branch: str
    record_path: str
    resume_phrases: Mapping[str, str]


@dataclass(frozen=True)
class Checkpoint:
    at: datetime
    record: Mapping[str, Any]


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> BoardConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != _CONFIG_KEYS or raw["schema_version"] != 1:
        raise BoardError("CONFIG_SHAPE")
    values = {k: raw[k] for k in _INT_KEYS}
    if not all(isinstance(v, int) and not isinstance(v, bool) and 0 < v < 10**9 for v in values.values()):
        raise BoardError("CONFIG_VALUES")
    if not isinstance(raw["record_branch"], str) or not _BRANCH.fullmatch(raw["record_branch"]) \
            or raw["record_branch"] == "main" or not isinstance(raw["record_path"], str) \
            or not _RECORD_PATH.fullmatch(raw["record_path"]):
        raise BoardError("CONFIG_RECORD")
    phrases = raw["resume_phrases"]
    if not isinstance(phrases, dict) or not phrases or not all(
            isinstance(k, str) and k.strip() == k and k and isinstance(v, str) and v for k, v in phrases.items()):
        raise BoardError("CONFIG_PHRASES")
    return BoardConfig(**values, record_branch=raw["record_branch"], record_path=raw["record_path"],
                       resume_phrases=dict(phrases))


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise BoardError("TIME")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BoardError("TIME") from exc
    if parsed.tzinfo is None:
        raise BoardError("TIME")
    return parsed


def checkpoints_from_comments(comments: Iterable[Mapping[str, Any]], writer_id: int) -> list[Checkpoint]:
    """Loop checkpoints written by ``writer_id``, oldest first.  Other comments are ignored; a malformed
    checkpoint block from the writer raises, so the board never shows a half-read record."""
    found: list[Checkpoint] = []
    for comment in comments:
        body = comment.get("body") or ""
        if CHECKPOINT_MARKER not in body or (comment.get("user") or {}).get("id") != writer_id:
            continue
        try:
            record = _block(body, CHECKPOINT_MARKER)[0]
        except (ValueError, json.JSONDecodeError, IndexError) as exc:
            raise BoardError("CHECKPOINT_MALFORMED") from exc
        if not isinstance(record, dict) or not isinstance(record.get("outcome"), str):
            raise BoardError("CHECKPOINT_MALFORMED")
        found.append(Checkpoint(_time(comment.get("created_at")), record))
    return sorted(found, key=lambda c: c.at)


def _jst(at: datetime) -> str:
    return at.astimezone(_JST).strftime("%m/%d %H:%M")


def _hours(delta: timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    return f"{hours}時間" if hours < 48 else f"{hours // 24}日"


def _merge_wait_since(points: Sequence[Checkpoint]) -> datetime | None:
    """Start of the current unbroken MERGE_WAIT run with the same state digest, or None."""
    if not points or points[-1].record.get("outcome") != "MERGE_WAIT":
        return None
    digest = points[-1].record.get("state_digest")
    since = points[-1].at
    for point in reversed(points):
        if point.record.get("outcome") != "MERGE_WAIT" or point.record.get("state_digest") != digest:
            break
        since = point.at
    return since


def _cell(text: Any) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def _record_lines(record: Mapping[str, Any] | None, alerts: list[str]) -> list[str]:
    lines = ["", "## 提案と相棒の返事", ""]
    if record is None:
        return lines + ["記録：UNKNOWN（読めない）"]
    proposals = record.get("proposals") or {}
    pending = [(pid, p) for pid, p in proposals.items() if p.get("state") == "PENDING"]
    for pid, p in pending:
        lines.append(f"- ⏳ 返事待ち：{_cell(p.get('summary_ja'))}（{pid}）")
    if len(pending) == 1:
        lines.append("  - OK なら、この掲示板に「承認」の2文字だけをコメント（署名なし・あとで編集しない）")
    elif len(pending) > 1:
        lines.append("  - 返事待ちが複数あるので、承認コメントはどれにも付かない（AI が1件ずつに直す）")
        alerts.append("返事待ちの提案が複数ある")
    for pid, p in proposals.items():
        if p.get("state") == "APPROVED":
            lines.append(f"- ✅ OK 済み：{_cell(p.get('summary_ja'))}（{pid}）")
        elif p.get("state") == "CHANGED_AFTER_APPROVAL":
            lines.append(f"- ⚠ OK のあとで書き換えられた：{_cell(p.get('summary_ja'))}（{pid}・OK は無効）")
            alerts.append(f"提案 {pid} が OK のあとで書き換えられた")
    if not proposals:
        lines.append("- 提案はまだない")
    for ai, entry in sorted((record.get("resume") or {}).items()):
        lines.append(f"- ▶ {ai}：「続けて OK」を受け取った（{_cell(entry.get('at'))}）")
    for item in (record.get("rejected") or [])[-3:]:
        lines.append(f"- ✖ 使えなかったコメント（{_cell(item.get('reason'))}・{_cell(item.get('at'))}）")
    return lines


def render_board(lanes: Sequence[Mapping[str, Any]], points: Sequence[Checkpoint], *, now: datetime,
                 config: BoardConfig, record: Mapping[str, Any] | None = None) -> str:
    """The managed board block (markers included), checked against the AI signature rule."""
    alerts: list[str] = []
    lines = [BOARD_START, "## レーン一覧（読むだけ・自動で作り直し）", "",
             f"更新：{_jst(now)} JST", "", "| レーン | V4 の状態 | 詳しい場所 |", "|---|---|---|"]
    for lane in lanes:
        lines.append(f"| {_cell(lane['display_name_ja'])} | {_STATUS_JA.get(lane['v4_status'], 'UNKNOWN')} "
                     f"| {_cell(lane['detail_ref'].replace('issue:', '#').replace('pr:', '#'))} |")
    lines += ["", f"## Claude × Jules（#{config.checkpoint_issue}）", ""]
    if not points:
        lines.append("最新の記録：UNKNOWN（記録が読めない）")
        alerts.append(f"#{config.checkpoint_issue} に Loop の記録が見つからない")
    else:
        last = points[-1]
        latest = last.record
        outcome = latest["outcome"]
        lines.append(f"最新の記録：{_OUTCOME_JA.get(outcome, outcome)}（{_jst(last.at)} JST・{_hours(now - last.at)}前）")
        if now - last.at > timedelta(hours=config.stale_checkpoint_hours):
            alerts.append(f"Loop の記録が {_hours(now - last.at)} 来てない（1時間ごとの見回りが止まってるかも）")
        since = _merge_wait_since(points)
        if since is not None:
            tasks = sorted({t for a in latest.get("human_actions") or [] if isinstance(a, dict)
                            and a.get("action") == "merge" for t in a.get("prs_of_tasks") or []})
            lines.append(f"マージ待ち：{_hours(now - since)}（{_jst(since)} JST から）・タスク {', '.join(tasks) or 'UNKNOWN'}")
            if now - since > timedelta(hours=config.merge_wait_alert_hours):
                alerts.append(f"マージ待ちが {_hours(now - since)} 続いてる")
        human = sorted(str(i.get("task_id", "UNKNOWN")) for i in latest.get("isolated") or []
                       if isinstance(i, dict) and i.get("human_required"))
        if human:
            alerts.append(f"相棒の判断が必要なタスク：{', '.join(human)}")
    lines += _record_lines(record, alerts)
    lines += ["", "## 気にしてほしいこと", ""]
    lines += [f"- 🟠 {a}" for a in alerts] or ["- 🟢 今はなし"]
    lines += ["", "このボードは記録を読んで表示するだけ。ここを書き換えても記録は変わらない。", "",
              "AI-Agent: claude", BOARD_END]
    return check_ai_write("\n".join(lines), load_policy())


def replace_board_block(body: str, block: str) -> str:
    """Swap the managed block in an Issue body, keeping everything outside the markers."""
    body = body or ""
    if body.count(BOARD_START) != 1 or body.count(BOARD_END) != 1 or body.index(BOARD_START) > body.index(BOARD_END):
        raise BoardError("BOARD_MARKERS")
    head, rest = body.split(BOARD_START, 1)
    _, tail = rest.split(BOARD_END, 1)
    return head + block + tail
