"""Antigravity initialize-only probe (STATIC code; running it on the real binary needs a separate human approval).

What it does, once: check the human-supplied ``agy_acp_server`` binary against a human-supplied SHA-256, ask for a
typed approval, start that one binary with the registry launch arguments, send ONE ACP ``initialize`` and stop.
It never sends ``authenticate``, ``session/new`` or ``session/prompt``, so no model turn and no login happen.
The one-shot is consumed before the process starts; a second run is a NO-OP; nothing is retried or relaunched.

Why this exists: ``initialize`` only lists the *available* auth methods and the agent version, which is the
first read-only fact the Antigravity route needs (see docs/RELAY_REMAINING_LIVE_DECISIONS_PREP.md, item 3).
It does not prove the logged-in account or billing route, and it does not give a one-generation gate.

Exit codes: 0 probe finished or NO-OP; 1 probe ended without a valid ``initialize``; 2 preflight stop;
3 already consumed with no receipt (outcome UNKNOWN, never re-run); 5 approval not given.
"""

from __future__ import annotations

import asyncio
import hashlib
import platform
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from providers.policy import antigravity_binary_name, antigravity_launch_args

from .acp_client import _acp_initialize
from .acp_stdio_transport import default_environment, spawn_stdio_transport
from .m9_live_state import canonical_sha256, write_exclusive

__all__ = ["PROBE_VERSION", "PHRASE_PREFIX", "RECEIPT_FILE", "CONSUMED_FILE", "Stop", "run"]

PROBE_VERSION = "antigravity-initialize-probe-v1"
PHRASE_PREFIX = "APPROVE_ANTIGRAVITY_INITIALIZE_PROBE"
RECEIPT_FILE = "antigravity_initialize_probe_receipt.json"
CONSUMED_FILE = "antigravity_initialize_probe_consumed.json"
TIMEOUT_SECONDS = 20.0
_MAX_TEXT = 80
# Credential / route variables that must never reach the binary (default_environment() does not pass them either).
FORBIDDEN_ENV = frozenset({
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_USE_VERTEXAI",
})


class Stop(Exception):
    def __init__(self, code: int, reason: str, message: str) -> None:
        super().__init__(reason)
        self.code, self.reason, self.message = code, reason, message


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _host_platform() -> str:
    return "windows" if sys.platform.startswith("win") else "linux" if sys.platform.startswith("linux") else sys.platform


def _host_architecture() -> str:
    return "aarch64" if platform.machine().lower() in ("aarch64", "arm64") else "x86_64"


def _sha256_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _text(value: Any) -> str | None:
    return value[:_MAX_TEXT] if isinstance(value, str) else None


def summarize_initialize(result: dict[str, Any]) -> dict[str, Any]:
    """Classifications only: protocol version, agent name/version, auth method ids, boolean capability flags."""
    info = result.get("agentInfo") if isinstance(result.get("agentInfo"), dict) else {}
    methods = result.get("authMethods") if isinstance(result.get("authMethods"), list) else []
    caps = result.get("agentCapabilities") if isinstance(result.get("agentCapabilities"), dict) else {}
    return {
        "protocol_version": result.get("protocolVersion"),
        "agent_name": _text(info.get("name")),
        "agent_version": _text(info.get("version")),
        "auth_method_ids": sorted(m["id"][:_MAX_TEXT] for m in methods if isinstance(m, dict) and isinstance(m.get("id"), str)),
        "capability_flags": {k[:_MAX_TEXT]: v for k, v in sorted(caps.items()) if isinstance(v, bool)},
    }


def _preflight(binary: Path, expected_sha256: str, state_dir: Path, platform_name: str, architecture: str) -> tuple[str, int]:
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise Stop(2, "PREFLIGHT_EXPECTED_SHA256", "期待するSHA-256（64桁の小文字16進）が正しくありません。停止します。")
    try:
        expected_name = antigravity_binary_name(platform_name, architecture)
    except ValueError:
        raise Stop(2, "PREFLIGHT_PLATFORM", "このOS/CPUはAntigravityの対象外です。停止します。")
    if binary.name != expected_name or not binary.is_file():
        raise Stop(2, "PREFLIGHT_BINARY", f"{expected_name} が見つかりません。停止します。")
    digest, size = _sha256_file(binary)
    if digest != expected_sha256:
        raise Stop(2, "PREFLIGHT_BINARY_HASH_MISMATCH", "バイナリのSHA-256が、指定された値と違います。起動せず停止します。")
    if (state_dir / RECEIPT_FILE).exists():
        raise Stop(0, "NO_OP_ALREADY_FINISHED", "すでに1回実行済みです（NO-OP）。再実行しません。")
    if (state_dir / CONSUMED_FILE).exists():
        raise Stop(3, "PREVIOUS_RUN_UNKNOWN", "前回の実行が途中で止まりました（結果はUNKNOWN）。安全のため再実行しません。")
    return digest, size


async def _initialize_once(binary: Path, args: tuple[str, ...], cwd: Path, timeout: float) -> dict[str, Any]:
    env = default_environment()
    if FORBIDDEN_ENV & set(env):
        raise RuntimeError("forbidden credential/route variable present")
    async with spawn_stdio_transport(str(binary), *args, env=env, cwd=cwd, shutdown_timeout=3.0) as (stdout, stdin, _proc):
        return await _acp_initialize(stdout, stdin, timeout)


def run(
    binary: Path,
    expected_sha256: str,
    state_dir: Path,
    *,
    confirm: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
    platform_name: str | None = None,
    architecture: str | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> int:
    platform_name = platform_name or _host_platform()
    architecture = architecture or _host_architecture()
    out(f"Antigravity initialize 専用プローブ（{PROBE_VERSION}）")
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        digest, size = _preflight(binary, expected_sha256, state_dir, platform_name, architecture)
        phrase = f"{PHRASE_PREFIX} {digest[:7]}"
        out("これから、指定されたバイナリを1回だけ起動し、ACP initialize を1回だけ送ります。")
        out("  ・ログイン(authenticate)・session/new・モデルへの依頼は行いません。APIキー・課金・設定の変更もしません")
        out("  ・成功でも失敗でも、その1回で終了し、再実行はできません")
        if confirm(f"承認する場合は次の文字をそのまま入力して Enter: {phrase}\n> ").strip() != phrase:
            raise Stop(5, "APPROVAL_NOT_GIVEN", "承認の文字が一致しませんでした。起動せず停止します。")
        if not write_exclusive(state_dir / CONSUMED_FILE, {"binary_sha256": digest, "consumed_at": _now()}):
            raise Stop(3, "ALREADY_CONSUMED", "すでに承認が使用済みです（NO-OP）。")
    except Stop as stop:
        out(f"【停止】{stop.message}")
        out(f"  理由コード: {stop.reason}")
        return stop.code

    state, error_class, summary = "INITIALIZE_OK", None, {}
    try:
        summary = summarize_initialize(asyncio.run(_initialize_once(
            binary, antigravity_launch_args(platform_name, architecture), state_dir, timeout)))
    except asyncio.TimeoutError:
        state, error_class = "TIMEOUT", "TimeoutError"
    except Exception as exc:  # classification only: the message could carry private text
        state, error_class = "UNKNOWN_ERROR", type(exc).__name__
    receipt = {
        "probe_version": PROBE_VERSION, "timestamp_utc": _now(), "platform": platform_name, "architecture": architecture,
        "binary_sha256": digest, "binary_size": size, "terminal_state": state, "error_class": error_class,
        **summary,
        "authenticate_count": 0, "session_new_count": 0, "prompt_count": 0, "model_generations": 0,
        "retry_count": 0, "fallback_state": "disabled",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    write_exclusive(state_dir / RECEIPT_FILE, receipt)
    out(f"結果: {state}")
    out(f"  利用できるログイン方式: {', '.join(summary.get('auth_method_ids', [])) or '（取得できず）'}")
    out("  これで終了です。再実行はできません。")
    return 0 if state == "INITIALIZE_OK" else 1


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
