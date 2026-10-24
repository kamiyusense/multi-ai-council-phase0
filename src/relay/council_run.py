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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .council import ANSWER_MARKER, CouncilError, CouncilPlan, plan_council, summary_markdown
from .council_grok import GrokLaunchError, child_env, headless_launch

__all__ = ["MemberCall", "member_prompt", "build_calls", "plan_digest", "approval_phrase", "run_council",
           "RunStop", "main"]

DECISION = "APPROVE_COUNCIL"
TIMEOUT_SECONDS = 300
_MAX_OUTPUT = 20_000
_SHELL_SHIMS = (".cmd", ".bat")

Runner = Callable[[tuple[str, ...], Mapping[str, str], str | None, int], tuple[int | None, str]]


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


def member_prompt(question: str) -> str:
    return (
        "次の質問に、日本語で、30行以内で答えてください。最初に結論、次に理由、最後にリスク。"
        "わからないことは推測せず UNKNOWN と書いてください。ファイルの変更やコマンドの実行はしないでください。\n\n"
        f"質問：{question}"
    )


def _binary_name(binary: str) -> str:
    return binary.replace("\\", "/").rsplit("/", 1)[-1].lower()


def build_calls(plan: CouncilPlan, parent_env: Mapping[str, str], binaries: Mapping[str, str]) -> list[MemberCall]:
    """One call per member in ``plan.ask``.  A member whose binary is missing or not accepted stops the run."""
    prompt = member_prompt(plan.question)
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
            calls.append(MemberCall(ai, launch.argv, launch.env, None))
        elif ai == "claude":
            if name not in {"claude", "claude.exe", "claude.cmd"}:
                raise RunStop("NOT_THE_CLAUDE_CLI", "claude の CLI ではないので止めた")
            env = dict(child_env(parent_env), CLAUDE_CODE_MAX_RETRIES="0")
            calls.append(MemberCall(ai, (binary, "-p", "--output-format", "text"), env, prompt))
        elif ai == "codex":
            if name not in {"codex", "codex.exe", "codex.cmd"}:
                raise RunStop("NOT_THE_CODEX_CLI", "codex の CLI ではないので止めた")
            argv = (binary, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "-")
            calls.append(MemberCall(ai, argv, child_env(parent_env), prompt))
        else:
            raise RunStop("NOT_AUTOMATIC", f"{ai} は自動では聞かない")
    return calls


def plan_digest(plan: CouncilPlan, calls: list[MemberCall]) -> str:
    """Hash of what the owner approves: id, question, members and argv shapes (prompt excluded from argv)."""
    shape = [{"ai": c.ai, "argv": [a if a != member_prompt(plan.question) else "<prompt>" for a in c.argv[1:]],
              "binary": _binary_name(c.argv[0]), "stdin": c.stdin is not None} for c in calls]
    body = json.dumps({"council_id": plan.council_id, "question": plan.question, "ask": list(plan.ask),
                       "skipped": plan.skipped, "calls": shape}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def approval_phrase(plan: CouncilPlan, digest: str) -> str:
    return f"{DECISION} {plan.council_id} {digest[:12]}"


def answer_comment(council_id: str, ai: str, text: str) -> str:
    marker = json.dumps({"council_id": council_id, "from": ai})
    return f"{ANSWER_MARKER} {marker} -->\n\n{text.strip()}\n\nAI-Agent: {ai}\n"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def run_council(plan: CouncilPlan, calls: list[MemberCall], *, out_dir: Path, runner: Runner,
                confirm: Callable[[str], str], timeout: int = TIMEOUT_SECONDS,
                now: Callable[[], str] | None = None) -> dict[str, Any]:
    """Ask, once, after the typed approval.  Returns the receipt (also written to ``out_dir``)."""
    now = now or (lambda: datetime.now(timezone.utc).isoformat())
    out = out_dir / plan.council_id
    receipt_path = out / "receipt.json"
    if receipt_path.exists() or (out / "started").exists():
        raise RunStop("ALREADY_RUN", "この Council はもう一度実行済み（または途中）なので、再実行しない")
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
            code, text = runner(call.argv, call.env, call.stdin, timeout)
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
        members[call.ai] = {"state": "ANSWERED", "exit_code": 0, "started_at": started, "chars": len(text),
                            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    notes = [f"{ai}: {m['state']}" for ai, m in members.items() if m["state"] not in {"ANSWERED", "SKIPPED"}]
    _atomic_write(out / "summary.md", summary_markdown(plan, answers, notes))
    receipt = {"council_id": plan.council_id, "decision": DECISION, "plan_digest": digest, "retry": 0,
               "fallback": "disabled", "github_write": False, "finished_at": now(), "members": members,
               "antigravity": "MANUAL"}
    _atomic_write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return receipt


def subprocess_runner(argv: tuple[str, ...], env: Mapping[str, str], stdin: str | None,
                      timeout: int) -> tuple[int | None, str]:
    """The only place a process starts.  No shell; output decoded as UTF-8."""
    try:
        done = subprocess.run(list(argv), input=stdin, env=dict(env), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, shell=False)
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
    args = parser.parse_args(argv)
    try:
        quota = {k: tuple(v) for k, v in json.loads(args.quota_file.read_text(encoding="utf-8")).items()
                 if isinstance(v, list)}
        plan = plan_council(args.council_id, args.question_file.read_text(encoding="utf-8"), quota)
        binaries = {ai: shutil.which(ai) or "" for ai in plan.ask}
        calls = build_calls(plan, os.environ, binaries)
        print(f"Council {plan.council_id}：聞く相手 {', '.join(plan.ask) or 'なし'}／聞かない {plan.skipped or 'なし'}")
        print("各 AI に1回だけ聞く。再実行・自動切り替え・API キーなし。GitHub には書かない。")
        receipt = run_council(plan, calls, out_dir=args.out, runner=subprocess_runner,
                              confirm=lambda p: input(f"実行してよければ次の文字をそのまま入力して Enter: {p}\n> "))
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
