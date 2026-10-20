"""Antigravity ONE-TURN runner (STATIC code; running it on the real binary needs a separate human approval).

Two subcommands, both for an interactive human console:

``declare``  the owner writes a short-lived, digest-bound *route declaration* file (provider google, personal Google
             account login, subscription billing, bound to one binary SHA-256, valid for at most four hours). The typed
             sentence is the owner's own statement; nothing here can verify it (billing cannot be read from outside).
``run``      checks the binary hash and that declaration, asks for a typed approval, then ONCE: starts the binary,
             ``initialize``, ``authenticate`` (``oauth-personal`` only), ``session/new``, ONE ``session/prompt`` with a
             fixed harmless text, and stops. The one-shot is consumed before the process starts; a second run is a
             NO-OP; nothing is retried, relaunched or sent to another provider/model.

Limits (UNKNOWN, cannot be stopped by this code): how many model calls Google makes inside the one prompt; what the
real server does on ``authenticate`` when a login is already saved; whether the agent asks for a tool permission (such a
request is never answered and ends the run). Relay does not decide the route: the declaration is host-owned input.
Same idea as ``automation/command_bus/claude_jules_provider_route.py`` (declaration + gate); Relay does not import
automation code, so the few checks needed are repeated here.

Exit codes: 0 finished or NO-OP; 1 ended without the expected terminal; 2 preflight/declaration stop; 3 already
consumed with no receipt (outcome UNKNOWN, never re-run); 5 approval not given.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from providers.policy import antigravity_launch_args

from .acp_client import _acp_exchange, _acp_initialize, _acp_new_session, _acp_prompt_text
from .acp_stdio_transport import default_environment, spawn_stdio_transport
from .antigravity_initialize_probe import (
    FORBIDDEN_ENV,
    Stop,
    _host_architecture,
    _host_platform,
    _now,
    _preflight_binary,
    summarize_initialize,
)
from .m9_live_state import canonical_sha256, read_json, write_exclusive

__all__ = ["PROBE_VERSION", "RECEIPT_FILE", "CONSUMED_FILE", "build_declaration", "check_declaration", "declare", "run"]

PROBE_VERSION = "antigravity-one-turn-v1"
RUN_PHRASE_PREFIX = "APPROVE_ANTIGRAVITY_ONE_TURN"
DECLARE_PHRASE_PREFIX = "DECLARE_ANTIGRAVITY_SUBSCRIPTION_ONLY"
RECEIPT_FILE = "antigravity_one_turn_receipt.json"
CONSUMED_FILE = "antigravity_one_turn_consumed.json"
DECLARATION_PROFILE = "ANTIGRAVITY_OWNER_ROUTE_DECLARATION_V1"
MAX_WINDOW = timedelta(hours=4)
ALLOWED_METHOD_ID = "oauth-personal"
PROMPT_TEXT = ("Reply with exactly the six characters AGY_OK and nothing else. "
               "Do not read or write files, do not run commands and do not use any tool.")
EXPECTED_TEXT = "AGY_OK"
INITIALIZE_TIMEOUT, AUTHENTICATE_TIMEOUT, SESSION_TIMEOUT, PROMPT_TIMEOUT = 20.0, 300.0, 30.0, 120.0
_AUTHENTICATE_ID = 10  # distinct from initialize (0), session/new (1) and session/prompt (2)
_KEYS = {"schema_version", "profile", "provider", "auth_method", "billing_route", "declared_by", "binary_sha256",
         "evidence_note", "declared_at", "expires_at", "declaration_sha256"}


def _parse_time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return parsed


def build_declaration(binary_sha256: str, evidence_note: str, declared_at: datetime, hours: float = 4.0) -> dict[str, Any]:
    if not 0 < hours <= MAX_WINDOW.total_seconds() / 3600:
        raise ValueError("declaration window must be 0 < hours <= 4")
    record = {"schema_version": 1, "profile": DECLARATION_PROFILE, "provider": "google", "auth_method": "account_oauth",
              "billing_route": "subscription", "declared_by": "owner", "binary_sha256": binary_sha256,
              "evidence_note": evidence_note[:400], "declared_at": declared_at.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
              "expires_at": (declared_at + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+00:00")}
    record["declaration_sha256"] = canonical_sha256(record)
    return record


def check_declaration(declaration: Any, binary_sha256: str, now: datetime) -> None:
    """Raise Stop(2) unless the declaration is intact, owner-made, current, short and bound to this binary."""
    def refuse(why: str) -> Stop:
        return Stop(2, "DECLARATION_" + why, "経路の宣言が使えません（" + why + "）。AIへの依頼は送らず停止します。")

    if not isinstance(declaration, dict) or set(declaration) != _KEYS:
        raise refuse("MALFORMED")
    body = {k: v for k, v in declaration.items() if k != "declaration_sha256"}
    if declaration["declaration_sha256"] != canonical_sha256(body):
        raise refuse("TAMPERED")
    if (declaration["schema_version"], declaration["profile"], declaration["provider"], declaration["auth_method"],
            declaration["billing_route"], declaration["declared_by"]) != (
            1, DECLARATION_PROFILE, "google", "account_oauth", "subscription", "owner"):
        raise refuse("ROUTE_NOT_SUBSCRIPTION_ACCOUNT")
    if declaration["binary_sha256"] != binary_sha256:
        raise refuse("OTHER_BINARY")
    try:
        start, end = _parse_time(declaration["declared_at"]), _parse_time(declaration["expires_at"])
    except ValueError:
        raise refuse("BAD_TIME")
    if not start <= now < end or end - start > MAX_WINDOW:
        raise refuse("NOT_CURRENT")


async def _one_turn(binary: Path, args: tuple[str, ...], cwd: Path, r: dict[str, Any]) -> None:
    """Fills ``r`` as it goes, so an exception still leaves the true stage and request counts behind."""
    env = default_environment()
    if FORBIDDEN_ENV & set(env):
        raise RuntimeError("forbidden credential/route variable present")
    r.update(stage="START", authenticate_count=0, session_new_count=0, prompt_count=0)
    async with spawn_stdio_transport(str(binary), *args, env=env, cwd=cwd, shutdown_timeout=3.0) as (stdout, stdin, _proc):
        r["initialize"] = summarize_initialize(await _acp_initialize(stdout, stdin, INITIALIZE_TIMEOUT))
        if ALLOWED_METHOD_ID not in r["initialize"]["auth_method_ids"]:
            r["stage"] = "METHOD_NOT_OFFERED"
            return
        r["stage"], r["authenticate_count"] = "AUTHENTICATE", 1
        await _acp_exchange(stdout, stdin, {"jsonrpc": "2.0", "id": _AUTHENTICATE_ID, "method": "authenticate",
                                            "params": {"methodId": ALLOWED_METHOD_ID}}, _AUTHENTICATE_ID,
                            AUTHENTICATE_TIMEOUT, "authenticate")
        r["stage"], r["session_new_count"] = "SESSION_NEW", 1
        session_id = await _acp_new_session(stdout, stdin, str(cwd), SESSION_TIMEOUT)
        r["stage"], r["prompt_count"] = "PROMPT", 1
        answer = await _acp_prompt_text(stdout, stdin, session_id, PROMPT_TEXT, PROMPT_TIMEOUT)
        text = answer["text"]
        r.update(stage="DONE", stop_reason=answer["stopReason"], response_chars=len(text.strip()),
                 response_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                 response_was_expected=text.strip() == EXPECTED_TEXT)


def run(binary: Path, expected_sha256: str, declaration_path: Path, state_dir: Path, *,
        confirm: Callable[[str], str] = input, out: Callable[[str], None] = print, platform_name: str | None = None,
        architecture: str | None = None, now: datetime | None = None) -> int:
    platform_name, architecture = platform_name or _host_platform(), architecture or _host_architecture()
    now = now or datetime.now(timezone.utc)
    out(f"Antigravity 1回だけ質問プローブ（{PROBE_VERSION}）")
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        digest, size = _preflight_binary(binary, expected_sha256, platform_name, architecture)
        if (state_dir / RECEIPT_FILE).exists():
            raise Stop(0, "NO_OP_ALREADY_FINISHED", "すでに1回実行済みです（NO-OP）。再実行しません。")
        if (state_dir / CONSUMED_FILE).exists():
            raise Stop(3, "PREVIOUS_RUN_UNKNOWN", "前回の実行が途中で止まりました（結果はUNKNOWN）。安全のため再実行しません。")
        try:
            declaration = read_json(declaration_path)
        except (OSError, ValueError):
            raise Stop(2, "DECLARATION_MISSING", "経路の宣言ファイルを読めません。AIへの依頼は送らず停止します。")
        check_declaration(declaration, digest, now)
        phrase = f"{RUN_PHRASE_PREFIX} {digest[:7]}"
        out("これから、指定されたバイナリを1回だけ起動し、次を1回ずつ行います。")
        out("  ・initialize → authenticate（oauth-personal）→ session/new → AIへの質問を1通（固定の短い文）")
        out("  ・質問は『AGY_OK とだけ返して。ファイルやコマンドやツールは使わないで』です。ブラウザが開いたら自分でログインします")
        out("  ・AIの回答の中身は保存しません（長さと照合結果とハッシュだけ）。APIキー・課金・設定の変更はしません")
        out("  ・1回の質問の中でGoogle側が何回AIを動かすかは数えられません（UNKNOWN）。成功でも失敗でも再実行はできません")
        if confirm(f"承認する場合は次の文字をそのまま入力して Enter: {phrase}\n> ").strip() != phrase:
            raise Stop(5, "APPROVAL_NOT_GIVEN", "承認の文字が一致しませんでした。起動せず停止します。")
        if not write_exclusive(state_dir / CONSUMED_FILE, {"binary_sha256": digest, "consumed_at": _now()}):
            raise Stop(3, "ALREADY_CONSUMED", "すでに承認が使用済みです（NO-OP）。")
    except Stop as stop:
        out(f"【停止】{stop.message}")
        out(f"  理由コード: {stop.reason}")
        return stop.code

    result: dict[str, Any] = {}
    state, error_class = "ONE_TURN_DONE", None
    try:
        asyncio.run(_one_turn(binary, antigravity_launch_args(platform_name, architecture), state_dir, result))
    except asyncio.TimeoutError:
        state, error_class = "TIMEOUT", "TimeoutError"
    except Exception as exc:  # classification only: the message could carry private text
        state, error_class = "UNKNOWN_ERROR", type(exc).__name__
    init = result.get("initialize", {}) if isinstance(result.get("initialize"), dict) else {}
    receipt = {
        "probe_version": PROBE_VERSION, "timestamp_utc": _now(), "platform": platform_name, "architecture": architecture,
        "binary_sha256": digest, "binary_size": size, "terminal_state": state, "error_class": error_class,
        "declaration_sha256": declaration["declaration_sha256"], "stage_reached": result.get("stage", "START"),
        "agent_version": init.get("agent_version"), "auth_method_ids": init.get("auth_method_ids", []),
        "stop_reason": result.get("stop_reason"), "response_chars": result.get("response_chars"),
        "response_text_sha256": result.get("response_text_sha256"), "response_was_expected": result.get("response_was_expected"),
        "authenticate_count": result.get("authenticate_count", 0), "session_new_count": result.get("session_new_count", 0),
        "prompt_count": result.get("prompt_count", 0), "retry_count": 0, "fallback_state": "disabled",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    write_exclusive(state_dir / RECEIPT_FILE, receipt)
    out(f"結果: {state}（到達した段階: {receipt['stage_reached']}）")
    out("  これで終了です。再実行はできません。")
    return 0 if state == "ONE_TURN_DONE" and result.get("stage") in ("DONE", "METHOD_NOT_OFFERED") else 1


def declare(binary: Path, expected_sha256: str, out_path: Path, evidence_note: str, hours: float, *,
            confirm: Callable[[str], str] = input, out: Callable[[str], None] = print, platform_name: str | None = None,
            architecture: str | None = None, now: datetime | None = None) -> int:
    platform_name, architecture = platform_name or _host_platform(), architecture or _host_architecture()
    try:
        digest, _size = _preflight_binary(binary, expected_sha256, platform_name, architecture)
        phrase = f"{DECLARE_PHRASE_PREFIX} {digest[:7]}"
        out("あなた自身の宣言を、期限つきのファイルに書きます（AIは動かしません）。")
        out("  宣言の内容: Googleの個人アカウントでのログイン／課金はサブスクの範囲のみ（追加課金・従量はOFF）／このバイナリ専用")
        out(f"  期限: {hours:g}時間（最大4時間）。この宣言が事実かどうかは、このツールでは確認できません")
        if confirm(f"宣言する場合は次の文字をそのまま入力して Enter: {phrase}\n> ").strip() != phrase:
            raise Stop(5, "DECLARATION_NOT_GIVEN", "宣言の文字が一致しませんでした。何も書かずに停止します。")
        record = build_declaration(digest, evidence_note, now or datetime.now(timezone.utc), hours)
        if not write_exclusive(out_path, record):
            raise Stop(2, "DECLARATION_FILE_EXISTS", "宣言ファイルがすでにあります。上書きしません。")
    except Stop as stop:
        out(f"【停止】{stop.message}")
        out(f"  理由コード: {stop.reason}")
        return stop.code
    except ValueError as exc:
        out(f"【停止】宣言を作れません: {exc}")
        return 2
    out(f"宣言ファイルを書きました（有効 {hours:g} 時間）。")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("declare", "run"):
        p = sub.add_parser(name)
        p.add_argument("--binary", required=True, type=Path)
        p.add_argument("--expected-sha256", required=True)
        p.add_argument("--declaration", required=True, type=Path)
        if name == "declare":
            p.add_argument("--evidence-note", required=True)
            p.add_argument("--hours", type=float, default=4.0)
        else:
            p.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if not sys.stdin or not sys.stdin.isatty():
        print("【停止】対話できる画面から実行されていないため、承認を受け付けられません。")
        return 5
    sha = args.expected_sha256.lower()
    if args.command == "declare":
        return declare(args.binary, sha, args.declaration, args.evidence_note, args.hours)
    return run(args.binary, sha, args.declaration, args.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
