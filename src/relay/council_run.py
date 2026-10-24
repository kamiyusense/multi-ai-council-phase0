"""Council runner for the owner's PC (docs/RELAY_TOWER_DIRECTION_V4.md section 4, step S9).

One run asks one question, once, to each automatic member the quota allows (Grok, Claude, Codex) through its
official CLI in headless mode, signed in with the owner's subscription.  Nothing here runs until ``main`` is started
by hand on the PC and the owner types the approval phrase on that console.

Rules kept here:

* No API key: every child gets an allowlisted environment (``council_grok.child_env``); keys never pass.
* One call per member, sequential, retry 0, a timeout, and a stop file checked before each call.
* The prompt goes through stdin where the CLI documents it (Claude ``-p``, Codex ``exec -``), so no shell parsing.
  Grok takes it as an argument, so a ``.cmd``/``.bat`` shim is refused (cmd.exe would parse the text).
* Single use per Council id: an existing receipt stops the run, so an unknown outcome is never resent.
* No GitHub write: answers and the summary are written as local files with the Council marker and signature; the
  owner (or a thread, with the owner's OK) posts them.
* The receipt holds states, lengths and hashes, never environment values.

The process runner is injected, so tests use a fake and never start a CLI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .council import ANSWER_MARKER, CouncilError, CouncilPlan, plan_council, summary_markdown
from .council_grok import GrokLaunchError, child_env, headless_launch

__all__ = ["MemberCall", "member_prompt", "build_calls", "plan_digest", "approval_phrase", "run_council",
           "board_file", "RunStop", "main"]

DECISION = "APPROVE_COUNCIL"
BOARD_NAMES = {"grok": "Grok", "claude": "Claude", "codex": "Codex"}
_JST = timezone(timedelta(hours=9), "JST")
TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 1_800
_MAX_OUTPUT = 60_000
_READ_TOOLS_CLAUDE = "Read,Grep,Glob"
_DENY_TOOLS_CLAUDE = "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch"
_SHELL_SHIMS = (".cmd", ".bat")

Runner = Callable[[tuple[str, ...], Mapping[str, str], str | None, int, str | None], tuple[int | None, str]]


class RunStop(Exception):
    def __init__(self, code: str, message_ja: str):
        super().__init__(code)
        self.code, self.message_ja = code, message_ja


@dataclass(frozen=True)
class MemberCall:
    ai: str
    argv: tuple[str, ...]
    env: Mapping[str, str]
    stdin: str | None
    cwd: str | None = None


def member_prompt(question: str, reference_dir: str | None = None) -> str:
    """Without ``reference_dir`` the member reads only the question; with it, it may read (never change) that folder."""
    if reference_dir is None:
        return (
            "次の質問に、日本語で、30行以内で答えてください。最初に結論、次に理由、最後にリスク。"
            "わからないことは推測せず UNKNOWN と書いてください。ファイルの変更やコマンドの実行はしないでください。\n\n"
            f"質問：{question}"
        )
    return (
        "次の質問に日本語で答えてください。質問に回答形式の指定があればそれに従ってください。"
        "今いる作業フォルダは、質問で調べる対象のリポジトリの複製です。GitHub の内容はこのフォルダのファイルで確認してください。"
        "ファイルは読むだけにして、作成・変更・削除、コマンドでの書き込み、外部への送信や書き込みは一切しないでください。"
        "確認できないことは推測せず UNKNOWN と書いてください。\n\n"
        f"質問：{question}"
    )


def _binary_name(binary: str) -> str:
    return binary.replace("\\", "/").rsplit("/", 1)[-1].lower()


def build_calls(plan: CouncilPlan, parent_env: Mapping[str, str], binaries: Mapping[str, str],
                reference_dir: str | None = None) -> list[MemberCall]:
    """One call per member in ``plan.ask``.  A member whose binary is missing or not accepted stops the run.

    ``reference_dir`` (a local clone the question is about) becomes each member's working folder with read-only
    tools: Claude ``--allowedTools Read,Grep,Glob`` and edits/shell/web denied, Codex ``--sandbox read-only -C``,
    Grok ``--cwd`` with ``--allow Read/Grep`` and ``--deny Edit/Bash``.
    """
    if reference_dir is not None and (not isinstance(reference_dir, str) or not os.path.isabs(reference_dir)):
        raise RunStop("REFERENCE_DIR", "調べるフォルダは絶対パスで指定して")
    prompt = member_prompt(plan.question, reference_dir)
    calls = []
    for ai in plan.ask:
        binary = binaries.get(ai)
        if not isinstance(binary, str) or not binary:
            raise RunStop("BINARY_MISSING", f"{ai} の CLI が見つからないので止めた（呼び出し 0 回）")
        name = _binary_name(binary)
        if ai == "grok":
            if name.endswith(_SHELL_SHIMS):
                raise RunStop("GROK_SHELL_SHIM", "grok が .cmd/.bat 形式なので、質問文を安全に渡せない。止めた")
            launch = headless_launch(prompt, parent_env, binary)
            argv = launch.argv
            if reference_dir is not None:
                argv += ("--cwd", reference_dir, "--allow", "Read", "--allow", "Grep", "--deny", "Edit",
                         "--deny", "Bash")
            calls.append(MemberCall(ai, argv, launch.env, None, reference_dir))
        elif ai == "claude":
            if name not in {"claude", "claude.exe", "claude.cmd"}:
                raise RunStop("NOT_THE_CLAUDE_CLI", "claude の CLI ではないので止めた")
            env = dict(child_env(parent_env), CLAUDE_CODE_MAX_RETRIES="0")
            argv = (binary, "-p", "--output-format", "text")
            if reference_dir is not None:
                argv += ("--allowedTools", _READ_TOOLS_CLAUDE, "--disallowedTools", _DENY_TOOLS_CLAUDE)
            calls.append(MemberCall(ai, argv, env, prompt, reference_dir))
        elif ai == "codex":
            if name not in {"codex", "codex.exe", "codex.cmd"}:
                raise RunStop("NOT_THE_CODEX_CLI", "codex の CLI ではないので止めた")
            argv = (binary, "exec", "--sandbox", "read-only", "--skip-git-repo-check")
            if reference_dir is not None:
                argv += ("-C", reference_dir)
            calls.append(MemberCall(ai, argv + ("-",), child_env(parent_env), prompt, reference_dir))
        else:
            raise RunStop("NOT_AUTOMATIC", f"{ai} は自動では聞かない")
    return calls


def plan_digest(plan: CouncilPlan, calls: list[MemberCall]) -> str:
    """Hash of what the owner approves: id, question, members and argv shapes (prompt excluded from argv)."""
    shape = [{"ai": c.ai, "argv": ["<prompt>" if plan.question in a else a for a in c.argv[1:]], "cwd": c.cwd,
              "binary": _binary_name(c.argv[0]), "stdin": c.stdin is not None} for c in calls]
    body = json.dumps({"council_id": plan.council_id, "question": plan.question, "ask": list(plan.ask),
                       "skipped": plan.skipped, "calls": shape}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def approval_phrase(plan: CouncilPlan, digest: str) -> str:
    return f"{DECISION} {plan.council_id} {digest[:12]}"


def answer_comment(council_id: str, ai: str, text: str) -> str:
    marker = json.dumps({"council_id": council_id, "from": ai})
    return f"{ANSWER_MARKER} {marker} -->\n\n{text.strip()}\n\nAI-Agent: {ai}\n"


def board_file(council_id: str, ai: str, text: str, round_no: int, at: datetime) -> tuple[str, str]:
    """(file name, body) in the Drive "AI掲示板" layout: ``r<round>_<AI名>.md`` with the board's header lines."""
    name = BOARD_NAMES[ai]
    body = (f"作成者: {name}（{ai} CLI・相棒の PC・Council 伝言係経由）\n"
            f"ラウンド: R{round_no}\n"
            f"作成時刻（JST）: {at.astimezone(_JST).strftime('%Y-%m-%d %H:%M')} JST\n"
            "確信度: 本文を参照\n"
            "読んだファイル: なし（質問文だけを読んで回答）\n"
            f"Council: {council_id}\n\n"
            f"{text.strip()}\n\nAI-Agent: {ai}\n")
    return f"r{round_no}_{name}.md", body


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def run_council(plan: CouncilPlan, calls: list[MemberCall], *, out_dir: Path, runner: Runner,
                confirm: Callable[[str], str], timeout: int = TIMEOUT_SECONDS,
                now: Callable[[], str] | None = None, board_dir: Path | None = None,
                round_no: int = 1) -> dict[str, Any]:
    """Ask, once, after the typed approval.  Returns the receipt (also written to ``out_dir``).

    With ``board_dir`` (a Google Drive for desktop folder of the "AI掲示板"), each answer is also written there as
    ``r<round>_<AI名>.md``; an existing file of that name stops the run before any call (never overwrite).
    """
    now = now or (lambda: datetime.now(timezone.utc).isoformat())
    out = out_dir / plan.council_id
    receipt_path = out / "receipt.json"
    if receipt_path.exists() or (out / "started").exists():
        raise RunStop("ALREADY_RUN", "この Council はもう一度実行済み（または途中）なので、再実行しない")
    if board_dir is not None:
        if isinstance(round_no, bool) or not isinstance(round_no, int) or not 1 <= round_no <= 9:
            raise RunStop("ROUND", "ラウンド番号は 1〜9")
        if not board_dir.is_dir():
            raise RunStop("BOARD_DIR", "掲示板のフォルダが見つからないので止めた（呼び出し 0 回）")
        taken = [f"r{round_no}_{BOARD_NAMES[c.ai]}.md" for c in calls
                 if (board_dir / f"r{round_no}_{BOARD_NAMES[c.ai]}.md").exists()]
        if taken:
            raise RunStop("BOARD_FILE_EXISTS", f"掲示板にもう {', '.join(taken)} があるので、上書きせず止めた")
    digest = plan_digest(plan, calls)
    phrase = approval_phrase(plan, digest)
    if confirm(phrase).strip() != phrase:
        raise RunStop("APPROVAL_NOT_GIVEN", "確認の文字が一致しなかったので止めた（呼び出し 0 回）")
    out.mkdir(parents=True, exist_ok=True)
    _atomic_write(out / "started", now())
    stop_file = out / "STOP"
    members: dict[str, dict[str, Any]] = {ai: {"state": "SKIPPED", "reason": r} for ai, r in plan.skipped.items()}
    answers: dict[str, str] = {}
    for call in calls:
        if stop_file.exists():
            members[call.ai] = {"state": "STOPPED"}
            continue
        started = now()
        try:
            code, text = runner(call.argv, call.env, call.stdin, timeout, call.cwd)
        except Exception as exc:  # outcome unknown: record, never retry
            members[call.ai] = {"state": "ERROR", "error": type(exc).__name__, "started_at": started}
            continue
        if code is None:
            members[call.ai] = {"state": "TIMEOUT", "started_at": started}
            continue
        text = (text or "")[:_MAX_OUTPUT]
        if code != 0 or not text.strip():
            members[call.ai] = {"state": "FAILED", "exit_code": code, "started_at": started}
            continue
        answers[call.ai] = text
        _atomic_write(out / f"answer-{call.ai}.md", answer_comment(plan.council_id, call.ai, text))
        if board_dir is not None:
            name, body = board_file(plan.council_id, call.ai, text, round_no, datetime.now(timezone.utc))
            _atomic_write(board_dir / name, body)
        members[call.ai] = {"state": "ANSWERED", "exit_code": 0, "started_at": started, "chars": len(text),
                            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    notes = [f"{ai}: {m['state']}" for ai, m in members.items() if m["state"] not in {"ANSWERED", "SKIPPED"}]
    _atomic_write(out / "summary.md", summary_markdown(plan, answers, notes))
    receipt = {"council_id": plan.council_id, "decision": DECISION, "plan_digest": digest, "retry": 0,
               "fallback": "disabled", "github_write": False,
               "board_round": round_no if board_dir else None, "finished_at": now(), "members": members,
               "antigravity": "MANUAL"}
    _atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return receipt


def subprocess_runner(argv: tuple[str, ...], env: Mapping[str, str], stdin: str | None,
                      timeout: int, cwd: str | None = None) -> tuple[int | None, str]:
    """The only place a process starts.  No shell; output decoded as UTF-8."""
    try:
        done = subprocess.run(list(argv), input=stdin, env=dict(env), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, shell=False, cwd=cwd)
    except subprocess.TimeoutExpired:
        return None, ""
    return done.returncode, done.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Council: ask Grok/Claude/Codex once (owner's PC only)")
    parser.add_argument("--council-id", required=True)
    parser.add_argument("--question-file", required=True, type=Path)
    parser.add_argument("--quota-file", required=True, type=Path,
                        help='JSON {"grok": [true, "QUOTA_OK"], ...} from the S7 quota gate')
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--board-dir", type=Path, help="AI掲示板 topic folder (Google Drive for desktop)")
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--reference-dir", help="absolute path of a local clone the members may read (read-only)")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS, help=f"seconds per member, max {MAX_TIMEOUT_SECONDS}")
    args = parser.parse_args(argv)
    try:
        quota = {k: tuple(v) for k, v in json.loads(args.quota_file.read_text(encoding="utf-8")).items()
                 if isinstance(v, list)}
        plan = plan_council(args.council_id, args.question_file.read_text(encoding="utf-8"), quota)
        binaries = {ai: shutil.which(ai) or "" for ai in plan.ask}
        if not 30 <= args.timeout <= MAX_TIMEOUT_SECONDS:
            raise RunStop("TIMEOUT", f"待ち時間は 30〜{MAX_TIMEOUT_SECONDS} 秒")
        if args.reference_dir is not None and not Path(args.reference_dir).is_dir():
            raise RunStop("REFERENCE_DIR", "調べるフォルダが見つからないので止めた（呼び出し 0 回）")
        calls = build_calls(plan, os.environ, binaries, args.reference_dir)
        print(f"Council {plan.council_id}：聞く相手 {', '.join(plan.ask) or 'なし'}／聞かない {plan.skipped or 'なし'}")
        print("各 AI に1回だけ聞く。再実行・自動切り替え・API キーなし。GitHub には書かない。")
        receipt = run_council(plan, calls, out_dir=args.out, runner=subprocess_runner,
                              confirm=lambda p: input(f"実行してよければ次の文字をそのまま入力して Enter: {p}\n> "),
                              board_dir=args.board_dir, round_no=args.round, timeout=args.timeout)
    except RunStop as stop:
        print(stop.message_ja, file=sys.stderr)
        return 2
    except (CouncilError, GrokLaunchError, ValueError, OSError) as exc:
        print(f"入力に問題があるので止めた：{type(exc).__name__} {exc}", file=sys.stderr)
        return 2
    print(json.dumps(receipt["members"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
