"""Antigravity Sidecar: answer new Council questions on the Drive "AI掲示板" board (owner's PC only).

Antigravity's own Sidecars feature (https://antigravity.google/docs/sidecars) runs this file on a schedule
(``sidecar.json``: builtin ``schedule``).  One run is one short pass; nothing here loops or waits for a model.

Why this is not "wrapping" Antigravity: Antigravity starts this script, and the only way it reaches a model is
Antigravity's own ``agentapi new-conversation`` (documented for sidecars).  It never starts ``agy``, never speaks
ACP, never reads ``~/.gemini`` or any credential, and never touches GitHub.  The use was lifted for this purpose
only, under the V4 exception (owner approval, 2026-10-25; ``docs/ANTIGRAVITY_SIDECAR_JA.md``).

One pass does, in order:

1. Stops at once when ``STOP`` is in the inbox folder or ``STOP_ANTIGRAVITY`` is in the board folder.
2. Collects answers: a started topic whose ``answer.md`` has appeared (and stopped changing) is copied to the
   topic folder as ``r<round>_Gemini.md`` with the board header and ``AI-Agent: antigravity``.  An existing board
   file is never overwritten.  A topic with no answer after ``answer_timeout_minutes`` ends as TIMED_OUT.
3. Only when ``armed`` is true: picks at most one new topic (``00_お題.md`` present, newer than ``since``,
   no ``r<round>_Gemini.md`` yet, never seen before), records the claim first, copies only the question into the
   inbox (blind: Antigravity never sees the other members' answers), and calls ``agentapi new-conversation``
   once.  A failed or unknown start is recorded and never sent again (retry 0).  At most ``daily_cap`` starts in
   any 24 hours.

The process runner is injected, so tests use a fake and never start anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

QUESTION_FILE = "00_お題.md"
BOARD_STOP = "STOP_ANTIGRAVITY"
INBOX_STOP = "STOP"
STATE_FILE = "state.json"
LOG_FILE = "watch_log.jsonl"
LOCK_FILE = ".lock"
SIGNATURE = "AI-Agent: antigravity"
MAX_QUESTION_BYTES = 200_000
MAX_ANSWER_BYTES = 400_000
STABLE_SECONDS = 30
STALE_LOCK_MINUTES = 30
AGENTAPI_TIMEOUT = 120
OUTPUT_TAIL = 300
_JST = timezone(timedelta(hours=9))

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class WatchStop(Exception):
    """A reason to end the pass without doing anything more."""


@dataclass(frozen=True)
class Config:
    board_dir: Path
    inbox_dir: Path
    since: datetime
    armed: bool = False
    round_no: int = 1
    daily_cap: int = 3
    answer_timeout_minutes: int = 120
    board_name: str = "Gemini"


def load_config(path: Path) -> Config:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise WatchStop("CONFIG: not a JSON object")
    known = {"board_dir", "inbox_dir", "since", "armed", "round", "daily_cap", "answer_timeout_minutes"}
    extra = sorted(set(raw) - known - {"_comment"})
    if extra:
        raise WatchStop(f"CONFIG: unknown keys {extra}")
    try:
        board_dir, inbox_dir = Path(raw["board_dir"]), Path(raw["inbox_dir"])
        since = datetime.fromisoformat(str(raw["since"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise WatchStop(f"CONFIG: {exc}") from None
    if not (board_dir.is_absolute() and inbox_dir.is_absolute()):
        raise WatchStop("CONFIG: board_dir and inbox_dir must be absolute paths")
    if board_dir.resolve() == inbox_dir.resolve() or board_dir.resolve() in inbox_dir.resolve().parents \
            or inbox_dir.resolve() in board_dir.resolve().parents:
        raise WatchStop("CONFIG: the inbox must be a separate folder, outside the board")
    if since.tzinfo is None:
        raise WatchStop("CONFIG: since needs a time zone, e.g. 2026-10-26T00:00:00+09:00")
    armed = raw.get("armed", False)
    round_no = raw.get("round", 1)
    daily_cap = raw.get("daily_cap", 3)
    timeout = raw.get("answer_timeout_minutes", 120)
    if not isinstance(armed, bool):
        raise WatchStop("CONFIG: armed must be true or false")
    for name, value, low, high in (("round", round_no, 1, 9), ("daily_cap", daily_cap, 1, 5),
                                   ("answer_timeout_minutes", timeout, 10, 1440)):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise WatchStop(f"CONFIG: {name} must be an integer from {low} to {high}")
    return Config(board_dir, inbox_dir, since, armed, round_no, daily_cap, timeout)


def run_agentapi(argv: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(argv, shell=False, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=AGENTAPI_TIMEOUT, check=False)


def topic_key(folder_name: str, round_no: int) -> str:
    return f"r{round_no}-{hashlib.sha256(folder_name.encode('utf-8')).hexdigest()[:12]}"


def build_prompt(question: Path, answer: Path) -> str:
    return ("あなたは Council の4人目の回答者（Gemini / Antigravity）です。\n"
            f"1. 次のファイルだけを読んでください: {question}\n"
            "2. その質問に日本語で答えてください。確かでないことは UNKNOWN と書き、推測で埋めないでください。\n"
            f"3. 答えを Markdown（UTF-8）で次のファイルに書いてください: {answer}\n"
            "4. ほかのファイルやフォルダは読まない・書かない。ほかの AI の答えも探さない。\n"
            "5. コマンドは実行しない。Web 検索もしない。\n"
            f"6. 答えの最後の行に `{SIGNATURE}` と書き、書き終えたら終わってください。\n")


def board_body(cfg: Config, folder_name: str, answer: str, at: datetime) -> str:
    text = answer.strip()
    if not text.endswith(SIGNATURE):
        text += f"\n\n{SIGNATURE}"
    return (f"作成者: {cfg.board_name}（Antigravity・相棒の PC・Sidecar 経由）\n"
            f"ラウンド: R{cfg.round_no}\n"
            f"作成時刻（JST）: {at.astimezone(_JST).strftime('%Y-%m-%d %H:%M')} JST\n"
            "確信度: 本文を参照\n"
            f"お題フォルダ: {folder_name}\n\n"
            f"{text}\n")


def _stable(path: Path, now: datetime) -> bool:
    return now.timestamp() - path.stat().st_mtime >= STABLE_SECONDS


def _write_new(path: Path, text: str) -> None:
    """Create ``path`` with ``text``; fails if it already exists (never overwrite)."""
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _save_state(inbox: Path, state: dict[str, Any]) -> None:
    tmp = inbox / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, inbox / STATE_FILE)


def _load_state(inbox: Path) -> dict[str, Any]:
    path = inbox / STATE_FILE
    if not path.exists():
        return {"topics": {}, "starts": []}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("topics"), dict) \
            or not isinstance(state.get("starts"), list):
        raise WatchStop("STATE: state.json is damaged; nothing was done (fix or remove it by hand)")
    return state


def _log(inbox: Path, now: datetime, event: str, **fields: Any) -> None:
    line = json.dumps({"at": now.isoformat(), "event": event, **fields}, ensure_ascii=False)
    with open(inbox / LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _collect(cfg: Config, state: dict[str, Any], now: datetime) -> list[str]:
    events = []
    for key, topic in sorted(state["topics"].items()):
        if topic.get("state") != "STARTED":
            continue
        answer = cfg.inbox_dir / key / "answer.md"
        target = cfg.board_dir / topic["folder"] / f"r{cfg.round_no}_{cfg.board_name}.md"
        if answer.exists() and _stable(answer, now):
            data = answer.read_bytes()
            if len(data) > MAX_ANSWER_BYTES:
                topic.update(state="ANSWER_TOO_LARGE", ended_at=now.isoformat())
            elif target.exists():
                topic.update(state="BOARD_FILE_EXISTS", ended_at=now.isoformat())
            elif not target.parent.is_dir():
                topic.update(state="TOPIC_FOLDER_GONE", ended_at=now.isoformat())
            else:
                _write_new(target, board_body(cfg, topic["folder"], data.decode("utf-8-sig", "replace"), now))
                topic.update(state="PUBLISHED", ended_at=now.isoformat(),
                             answer_sha256=hashlib.sha256(data).hexdigest())
            events.append(f"{key}:{topic['state']}")
        elif now - datetime.fromisoformat(topic["started_at"]) > timedelta(minutes=cfg.answer_timeout_minutes):
            topic.update(state="TIMED_OUT", ended_at=now.isoformat())
            events.append(f"{key}:TIMED_OUT")
    return events


def _candidates(cfg: Config, state: dict[str, Any], now: datetime) -> list[Path]:
    found = []
    for folder in sorted(p for p in cfg.board_dir.iterdir() if p.is_dir()):
        question = folder / QUESTION_FILE
        if not question.is_file() or topic_key(folder.name, cfg.round_no) in state["topics"]:
            continue
        if (folder / f"r{cfg.round_no}_{cfg.board_name}.md").exists():
            continue
        mtime = datetime.fromtimestamp(question.stat().st_mtime, timezone.utc)
        if mtime >= cfg.since and _stable(question, now):
            found.append(folder)
    return found


def _start(cfg: Config, state: dict[str, Any], folder: Path, now: datetime, runner: Runner) -> str:
    key = topic_key(folder.name, cfg.round_no)
    data = (folder / QUESTION_FILE).read_bytes()
    topic: dict[str, Any] = {"folder": folder.name, "claimed_at": now.isoformat(),
                             "question_sha256": hashlib.sha256(data).hexdigest()}
    state["topics"][key] = topic
    if len(data) > MAX_QUESTION_BYTES:
        topic.update(state="QUESTION_TOO_LARGE")
        _save_state(cfg.inbox_dir, state)
        return f"{key}:QUESTION_TOO_LARGE"
    # The claim is durable before anything is sent, so a crash below never leads to a second start.
    topic.update(state="CLAIMED")
    state["starts"].append(now.isoformat())
    _save_state(cfg.inbox_dir, state)
    work = cfg.inbox_dir / key
    work.mkdir(exist_ok=False)
    question, answer = work / "question.md", work / "answer.md"
    question.write_bytes(data)
    argv = ["agentapi", "new-conversation", build_prompt(question, answer)]
    try:
        done = runner(argv)
    except (OSError, subprocess.SubprocessError) as exc:
        topic.update(state="START_UNKNOWN", error=type(exc).__name__)
    else:
        topic.update(state="STARTED" if done.returncode == 0 else "START_FAILED", returncode=done.returncode,
                     output_tail=((done.stdout or "") + (done.stderr or ""))[-OUTPUT_TAIL:])
    topic["started_at"] = now.isoformat()
    _save_state(cfg.inbox_dir, state)
    return f"{key}:{topic['state']}"


def watch_once(cfg: Config, *, runner: Runner = run_agentapi, now: datetime | None = None,
               dry_run: bool = False) -> dict[str, Any]:
    """One pass.  Returns what happened (also appended to ``watch_log.jsonl`` in the inbox)."""
    now = now or datetime.now(timezone.utc)
    if not cfg.board_dir.is_dir():
        raise WatchStop("BOARD_DIR: the board folder was not found")
    if not cfg.inbox_dir.is_dir():
        raise WatchStop("INBOX_DIR: the inbox folder was not found")
    if (cfg.inbox_dir / INBOX_STOP).exists() or (cfg.board_dir / BOARD_STOP).exists():
        return {"result": "STOPPED", "events": []}
    state = _load_state(cfg.inbox_dir)
    if dry_run:
        picks = [p.name for p in _candidates(cfg, state, now)]
        return {"result": "DRY_RUN", "armed": cfg.armed, "would_start": picks[:1], "candidates": picks}
    lock = cfg.inbox_dir / LOCK_FILE
    if lock.exists() and now.timestamp() - lock.stat().st_mtime > STALE_LOCK_MINUTES * 60:
        lock.unlink()
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"result": "BUSY", "events": []}
    os.close(fd)
    try:
        events = _collect(cfg, state, now)
        _save_state(cfg.inbox_dir, state)
        recent = [t for t in state["starts"] if now - datetime.fromisoformat(t) < timedelta(hours=24)]
        if not cfg.armed:
            result = "NOT_ARMED"
        elif len(recent) >= cfg.daily_cap:
            result = "DAILY_CAP"
        else:
            picks = _candidates(cfg, state, now)
            result = "IDLE"
            if picks:
                events.append(_start(cfg, state, picks[0], now, runner))
                result = "STARTED_ONE"
        _log(cfg.inbox_dir, now, result, events=events)
        return {"result": result, "events": events}
    finally:
        lock.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Antigravity Sidecar: answer new AI掲示板 questions (one pass)")
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().with_name("watch_config.json"))
    parser.add_argument("--dry-run", action="store_true", help="show what would start; send and write nothing")
    args = parser.parse_args(argv)
    try:
        outcome = watch_once(load_config(args.config), dry_run=args.dry_run)
    except (WatchStop, OSError, ValueError) as exc:
        print(f"STOPPED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(outcome, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
