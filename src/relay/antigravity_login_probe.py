"""Antigravity login-only probe (STATIC code; running it on the real binary needs a separate human approval).

What it does, once: check the human-supplied ``agy_acp_server`` binary against a human-supplied SHA-256, ask for a
typed approval, start that one binary with the registry launch arguments, send ONE ACP ``initialize`` and then ONE
``authenticate`` with the method ``oauth-personal`` (the only method Relay's route admission allows), and stop.
It never sends ``session/new`` or ``session/prompt``, so no model turn happens. The Google sign-in itself is done by
the human in their own browser; nothing typed there is seen by this code.
The one-shot is consumed before the process starts; a second run is a NO-OP; nothing is retried or relaunched.

Why this exists: the account route (which Google account class signs in) cannot be observed without a sign-in
(docs/RELAY_ANTIGRAVITY_ACCOUNT_ROUTE_READONLY_CHECKLIST.md). This is the smallest step that signs in and nothing more.
It does not prove the billing route and it does not give a one-generation gate. Where the server keeps the login is
UNKNOWN; the receipt records classifications only (no account id, e-mail, token or server text).

Exit codes: 0 finished (any terminal state except failure) or NO-OP; 1 ended without a valid initialize/authenticate;
2 preflight stop; 3 already consumed with no receipt (outcome UNKNOWN, never re-run); 5 approval not given.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from providers.policy import antigravity_launch_args

from .acp_client import _acp_exchange, _acp_initialize
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
from .m9_live_state import canonical_sha256, write_exclusive

__all__ = ["PROBE_VERSION", "PHRASE_PREFIX", "RECEIPT_FILE", "CONSUMED_FILE", "run"]

PROBE_VERSION = "antigravity-login-probe-v1"
PHRASE_PREFIX = "APPROVE_ANTIGRAVITY_LOGIN_ONLY"
RECEIPT_FILE = "antigravity_login_probe_receipt.json"
CONSUMED_FILE = "antigravity_login_probe_consumed.json"
INITIALIZE_TIMEOUT_SECONDS = 20.0
AUTHENTICATE_TIMEOUT_SECONDS = 300.0  # the human signs in through a browser
ALLOWED_METHOD_ID = "oauth-personal"


async def _login_once(binary: Path, args: tuple[str, ...], cwd: Path, init_timeout: float, auth_timeout: float) -> dict[str, Any]:
    env = default_environment()
    if FORBIDDEN_ENV & set(env):
        raise RuntimeError("forbidden credential/route variable present")
    out: dict[str, Any] = {"authenticate_count": 0, "authenticate_state": "NOT_SENT"}
    async with spawn_stdio_transport(str(binary), *args, env=env, cwd=cwd, shutdown_timeout=3.0) as (stdout, stdin, _proc):
        out["initialize"] = summarize_initialize(await _acp_initialize(stdout, stdin, init_timeout))
        if ALLOWED_METHOD_ID not in out["initialize"]["auth_method_ids"]:
            out["authenticate_state"] = "METHOD_NOT_OFFERED"
            return out
        request = {"jsonrpc": "2.0", "id": 1, "method": "authenticate", "params": {"methodId": ALLOWED_METHOD_ID}}
        out["authenticate_count"] = 1
        try:
            await _acp_exchange(stdout, stdin, request, 1, auth_timeout, "authenticate")
            out["authenticate_state"] = "AUTHENTICATE_OK"
        except asyncio.TimeoutError:
            out["authenticate_state"] = "AUTHENTICATE_TIMEOUT"
        except TimeoutError:
            out["authenticate_state"] = "AUTHENTICATE_TIMEOUT"
        except Exception as exc:  # classification only: the message could carry private text
            out["authenticate_state"] = "AUTHENTICATE_FAILED"
            out["error_class"] = type(exc).__name__
    return out


def run(
    binary: Path,
    expected_sha256: str,
    state_dir: Path,
    *,
    confirm: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
    platform_name: str | None = None,
    architecture: str | None = None,
    init_timeout: float = INITIALIZE_TIMEOUT_SECONDS,
    auth_timeout: float = AUTHENTICATE_TIMEOUT_SECONDS,
) -> int:
    platform_name = platform_name or _host_platform()
    architecture = architecture or _host_architecture()
    out(f"Antigravity ログインだけ プローブ（{PROBE_VERSION}）")
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        digest, size = _preflight_binary(binary, expected_sha256, platform_name, architecture)
        if (state_dir / RECEIPT_FILE).exists():
            raise Stop(0, "NO_OP_ALREADY_FINISHED", "すでに1回実行済みです（NO-OP）。再実行しません。")
        if (state_dir / CONSUMED_FILE).exists():
            raise Stop(3, "PREVIOUS_RUN_UNKNOWN", "前回の実行が途中で止まりました（結果はUNKNOWN）。安全のため再実行しません。")
        phrase = f"{PHRASE_PREFIX} {digest[:7]}"
        out("これから、指定されたバイナリを1回だけ起動し、initialize のあと authenticate（oauth-personal）を1回だけ送ります。")
        out("  ・ブラウザが開いたら、あなた自身が個人のGoogleアカウントでログインします（このツールはその入力を見ません）")
        out("  ・session/new・モデルへの依頼（AIへの質問）は行いません。APIキー・課金・設定の変更もしません")
        out("  ・ログインの記録をAntigravity側が自分で保存する場合があります（保存先は不明＝UNKNOWN）")
        out("  ・成功でも失敗でも、その1回で終了し、再実行はできません。最大5分で止まります")
        if confirm(f"承認する場合は次の文字をそのまま入力して Enter: {phrase}\n> ").strip() != phrase:
            raise Stop(5, "APPROVAL_NOT_GIVEN", "承認の文字が一致しませんでした。起動せず停止します。")
        if not write_exclusive(state_dir / CONSUMED_FILE, {"binary_sha256": digest, "consumed_at": _now()}):
            raise Stop(3, "ALREADY_CONSUMED", "すでに承認が使用済みです（NO-OP）。")
    except Stop as stop:
        out(f"【停止】{stop.message}")
        out(f"  理由コード: {stop.reason}")
        return stop.code

    result: dict[str, Any] = {}
    state, error_class = "LOGIN_PROBE_DONE", None
    try:
        result = asyncio.run(_login_once(
            binary, antigravity_launch_args(platform_name, architecture), state_dir, init_timeout, auth_timeout))
    except asyncio.TimeoutError:
        state, error_class = "INITIALIZE_TIMEOUT", "TimeoutError"
    except Exception as exc:  # classification only
        state, error_class = "UNKNOWN_ERROR", type(exc).__name__
    init = result.get("initialize", {}) if isinstance(result.get("initialize"), dict) else {}
    auth_state = result.get("authenticate_state", "NOT_SENT")
    receipt = {
        "probe_version": PROBE_VERSION, "timestamp_utc": _now(), "platform": platform_name, "architecture": architecture,
        "binary_sha256": digest, "binary_size": size, "terminal_state": state, "error_class": error_class or result.get("error_class"),
        "authenticate_state": auth_state, "authenticate_method_id": ALLOWED_METHOD_ID,
        "auth_method_ids": init.get("auth_method_ids", []), "agent_name": init.get("agent_name"),
        "agent_version": init.get("agent_version"),
        "authenticate_count": result.get("authenticate_count", 0), "session_new_count": 0, "prompt_count": 0,
        "model_generations": 0, "retry_count": 0, "fallback_state": "disabled",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    write_exclusive(state_dir / RECEIPT_FILE, receipt)
    out(f"結果: {state} / ログイン: {auth_state}")
    out("  これで終了です。再実行はできません。")
    return 0 if state == "LOGIN_PROBE_DONE" and auth_state in ("AUTHENTICATE_OK", "METHOD_NOT_OFFERED") else 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if not sys.stdin or not sys.stdin.isatty():
        print("【停止】対話できる画面から実行されていないため、承認を受け付けられません。")
        return 5
    return run(args.binary, args.expected_sha256.lower(), args.state_dir)


if __name__ == "__main__":
    raise SystemExit(main())
