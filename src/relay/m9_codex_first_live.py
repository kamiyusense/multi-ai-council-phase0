"""M9 first Codex LIVE proof: one-shot runner (to be run on the USER's PC, never in the cloud).

Fixed order (any failure/UNKNOWN stops; nothing is retried):
  1 preflight   existence/availability checks only (never reads credentials)
  2 approval    typed, interactive, bound to the exact HEAD and code hash
  3 account     ONE read-only `account/read` (refreshToken=false), sanitized; only CHATGPT_ACCOUNT continues
  4 live turn   official codex-acp -> CODEX_PATH -> Relay one-generation gate -> real Codex backend,
                1 dispatch, 1 prompt, <=1 generation, timeout 60 s, then STOP
Evidence is a sanitized terminal receipt only (no raw account response, token, email, account id).

Safety notes
* Existing durable-provenance chain (`live_approval_receipt` ...) needs proof records for ALL providers
  and a GitHub readback that does not exist yet; it cannot approve the current state and is NOT bypassed
  by pretending. This runner uses a narrower, explicit LOCAL approval and records
  existing_chain_provenance=NOT_VERIFIED in the receipt.
* The real backend path is reachable only through `LiveAuthorization` (see m9_live_state).
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from providers.codex_acp import build_codex_profile

from .acp_stdio_relay_transport import AcpStdioStaticTransport, OfficialAdapterLaunch
from .acp_stdio_transport import default_environment
from .codex_account_readonly import assert_read_only, read_only_requests, summarize_account_evidence
from .duplicate_guard import DuplicateDecision, DuplicateGuard
from .envelope import DispatchEnvelope, DispatchSlot
from .m9_live_state import (
    APPROVAL_FILE, CONSUMED_FILE, DECISION, PROVIDER, SCOPE, TERMINAL_FILE, LiveAuthorization,
    canonical_sha256, read_json, verify_approval_record, write_exclusive,
)

RUNNER_VERSION = "m9-codex-first-live-runner-v1"
PROMPT = "M9_OK とだけ返答してください。ファイルを読まない、ファイルを書かない、commandを実行しない、toolを使用しない。"
EXPECTED_TEXT = "M9_OK"
TIMEOUT_SECONDS = 60
EXPECTED_BRANCH = "feature/relay-m9-local-runner-v4"
ADAPTER_VERSION = "2.1.1"
GENERATION_METHODS = ("turn/start", "turn/steer", "review/start", "thread/compact/start", "thread/goal/set")
CHECKLIST_REL = Path("fixtures") / "relay" / "m9_codex_first_live_checklist.json"
_CODE_FILES = (
    "src/relay/m9_codex_first_live.py", "src/relay/m9_live_state.py", "src/relay/codex_turn_gate.py",
    "src/relay/codex_turn_gate.cmd", "src/relay/acp_stdio_relay_transport.py", "src/relay/acp_client.py",
    "src/relay/codex_account_readonly.py", "fixtures/relay/m9_codex_first_live_checklist.json",
)
_SECRET_LIKE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|sk-[A-Za-z0-9]{8,}|eyJ[A-Za-z0-9_-]{10,}|tok-|acct-", re.I)

TERMINAL_STATES = (
    "SUCCESS_M9_OK", "COMPLETED_UNEXPECTED_TEXT", "TIMEOUT", "UNKNOWN_ERROR", "FAIL_MULTI_GENERATION",
)


class Stop(Exception):
    """A fail-closed stop before/after the live turn; `code` is the process exit code."""

    def __init__(self, code: int, reason: str, message_ja: str):
        super().__init__(reason)
        self.code, self.reason, self.message_ja = code, reason, message_ja


# --------------------------------------------------------------------------- config
def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError("git failed")
    return done.stdout.strip()


def default_git_probe(repo: Path, branch: str) -> dict[str, Any]:
    """HEAD/branch cleanliness plus fresh remote branch and current-main ancestry."""
    _git(repo, "fetch", "--quiet", "origin", branch)
    _git(repo, "fetch", "--quiet", "origin", "main")
    head = _git(repo, "rev-parse", "HEAD")
    remote_head = _git(repo, "rev-parse", f"origin/{branch}")
    main_head = _git(repo, "rev-parse", "origin/main")
    ancestor = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", main_head, head],
        capture_output=True, text=True, timeout=60,
    ).returncode == 0
    return {
        "head": head,
        "branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "clean": _git(repo, "status", "--porcelain", "--untracked-files=no") == "",
        "remote_head": remote_head,
        "main_head": main_head,
        "main_is_ancestor": ancestor,
    }


@dataclass
class Config:
    repo_root: Path
    state_dir: Path
    codex_path: str | None
    codex_home: Path
    node_path: str | None
    npm_path: str | None
    gate_launcher: Path
    python_exe: str = sys.executable
    timeout_seconds: int = TIMEOUT_SECONDS
    expected_branch: str = EXPECTED_BRANCH
    git_probe: Callable[[Path, str], dict[str, Any]] = default_git_probe
    confirm: Callable[[str], str] | None = None
    out: Callable[[str], None] = print
    adapter_dir: Path | None = None
    install_adapter: bool = True
    extra_env: dict[str, str] = field(default_factory=dict)  # test hook only; the CLI never sets it

    def adapter_path(self) -> Path:
        return self.adapter_dir or (self.state_dir / "adapter" / "node_modules" / "@agentclientprotocol" / "codex-acp")


def default_config(repo_root: Path) -> Config:
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    launcher = repo_root / "src" / "relay" / ("codex_turn_gate.cmd" if os.name == "nt" else "codex_turn_gate.py")
    return Config(
        repo_root=repo_root, state_dir=repo_root / ".m9_live", codex_path=shutil.which("codex"),
        codex_home=codex_home, node_path=shutil.which("node"), npm_path=shutil.which("npm"),
        gate_launcher=launcher, confirm=_console_confirm,
    )


def _console_confirm(prompt: str) -> str:
    if not sys.stdin or not sys.stdin.isatty():
        raise Stop(5, "NO_INTERACTIVE_CONSOLE", "対話できる画面から実行されていないため、承認を受け付けられません。停止します。")
    return input(prompt)


# --------------------------------------------------------------------------- helpers
def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def code_sha256(repo: Path) -> str:
    """Hash of the files that implement the one-shot (CRLF-normalized for Windows checkouts)."""
    digest = hashlib.sha256()
    for rel in _CODE_FILES:
        data = (repo / rel).read_bytes().replace(b"\r\n", b"\n")
        digest.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def load_checklist(repo: Path) -> dict[str, Any]:
    data = read_json(repo / CHECKLIST_REL)
    scope = data.get("scope", {})
    expected = {"dispatches": 1, "prompts": 1, "max_generations": 1, "retry": 0, "fallback": "disabled"}
    if data.get("provider") != PROVIDER or any(scope.get(k) != v for k, v in expected.items()):
        raise ValueError("checklist scope does not match the runner contract")
    if not data.get("items"):
        raise ValueError("checklist has no items")
    return data


def _atomic_write(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _assert_no_secret(value: Any) -> None:
    if _SECRET_LIKE.search(json.dumps(value, ensure_ascii=False)):
        raise ValueError("refusing to persist secret-like content")


def count_gate_decisions(gate_log: Path) -> dict[str, int]:
    counts = {"allowed": 0, "blocked": 0}
    if gate_log.exists():
        for line in gate_log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("method") in GENERATION_METHODS and row.get("decision") in counts:
                counts[row["decision"]] += 1
    return counts


# --------------------------------------------------------------------------- stage 1
def preflight(cfg: Config) -> dict[str, Any]:
    """Existence/availability checks only. Raises Stop on the first failed/UNKNOWN check."""
    out = cfg.out
    checks: list[tuple[str, str]] = []

    def need(ok: bool, name: str, ng_message: str, code: int = 2) -> None:
        if not ok:
            raise Stop(code, f"PREFLIGHT_{name}", ng_message)
        checks.append((name, "OK"))

    try:
        checklist = load_checklist(cfg.repo_root)
    except (OSError, ValueError):
        raise Stop(2, "PREFLIGHT_CHECKLIST", "M9 チェックリストを読めない、または内容が契約と一致しません。停止します。")
    checks.append(("CHECKLIST", "OK"))
    try:
        git = cfg.git_probe(cfg.repo_root, cfg.expected_branch)
    except Exception:
        raise Stop(2, "PREFLIGHT_GIT_UNKNOWN", "git の状態（HEAD・最新かどうか）を確認できません。git が使えるか、ネットワークに接続しているか確認してください。停止します。")
    need(git.get("branch") == cfg.expected_branch, "BRANCH",
         f"ブランチが違います（必要: {cfg.expected_branch}）。ブランチを切り替えてから再実行してください。")
    need(git.get("clean") is True, "CLEAN", "リポジトリに未保存の変更があります。変更を戻してから再実行してください。")
    need(bool(git.get("head")) and git.get("head") == git.get("remote_head"), "HEAD_LATEST",
         "手元のコードが GitHub の最新ではありません。`git pull` で最新にしてから再実行してください。")
    need(git.get("main_is_ancestor") is True, "CURRENT_MAIN",
         "この M9 branch は現在の main を含んでいません。LIVE は行わず停止します。最新 main 起点の検証済み successor を用意してください。")
    need(sys.version_info >= (3, 11), "PYTHON", "Python 3.11 以上が必要です。")
    need(bool(cfg.node_path), "NODE", "Node.js が見つかりません。Node.js をインストールしてから再実行してください（自動ではインストールしません）。"
         "例: PowerShell で `winget install -e --id OpenJS.NodeJS.LTS` のあと PowerShell を開き直す。")
    need(bool(cfg.codex_path) and Path(cfg.codex_path).exists(), "CODEX_EXE",
         "Codex の実行ファイル（codex）が見つかりません。この PC に Codex がインストールされていないようです。ログインや導入は自動では行いません。停止します。"
         "例: `npm.cmd install -g @openai/codex`（PowerShell が npm.ps1 を拒否する場合は npm.cmd を使う）のあと PowerShell を開き直す。")
    need(Path(cfg.codex_home).is_dir(), "CODEX_HOME",
         "Codex のログイン情報の置き場所（CODEX_HOME / ~/.codex）が見つかりません。この PC では Codex にログインしていないようです。自動ログインは行いません。停止します。"
         "ログインはあなた自身が `codex.cmd login`（ChatGPT アカウント）で行ってください。")
    need(Path(cfg.gate_launcher).is_file() and (cfg.repo_root / "src/relay/codex_turn_gate.py").is_file(),
         "GATE", "1 回生成ゲート（codex_turn_gate）が見つかりません。リポジトリを最新にしてください。")
    need(not (cfg.state_dir / TERMINAL_FILE).exists(), "NOT_FINISHED", "すでに 1 回実行済みです。再実行しません。")
    need(not (cfg.state_dir / CONSUMED_FILE).exists(), "NOT_CONSUMED", "前回の実行が途中で止まりました（結果は UNKNOWN）。安全のため再実行しません。", 3)
    out("  [OK] 事前確認: " + ", ".join(name for name, _ in checks))
    return {"head": git["head"], "branch": git["branch"], "checklist": checklist}


def ensure_adapter(cfg: Config) -> Path:
    """Official codex-acp 2.1.1, installed without scripts and without optional (native) packages."""
    adapter = cfg.adapter_path()
    index = adapter / "dist" / "index.js"
    if not index.is_file():
        if not cfg.install_adapter or not cfg.npm_path:
            raise Stop(2, "ADAPTER_MISSING", "公式 codex-acp（アダプタ）が用意できません（npm が見つかりません）。停止します。")
        base = adapter.parents[2]
        base.mkdir(parents=True, exist_ok=True)
        if not (base / "package.json").exists():
            (base / "package.json").write_text('{"name":"m9-adapter","version":"1.0.0","private":true}\n', encoding="utf-8")
        cfg.out("  公式 codex-acp %s を導入します（スクリプト実行なし・ネイティブ版 Codex なし）..." % ADAPTER_VERSION)
        done = subprocess.run(
            [cfg.npm_path, "install", "--ignore-scripts", "--omit=optional", "--no-audit", "--no-fund",
             f"@agentclientprotocol/codex-acp@{ADAPTER_VERSION}"],
            cwd=str(base), capture_output=True, text=True, timeout=600)
        if done.returncode != 0 or not index.is_file():
            raise Stop(2, "ADAPTER_INSTALL_FAILED", "公式 codex-acp の導入に失敗しました。ネットワークを確認してください。停止します。")
    version = json.loads((adapter / "package.json").read_text(encoding="utf-8")).get("version")
    openai_dir = adapter.parents[1] / "@openai"
    if version != ADAPTER_VERSION or (openai_dir.is_dir() and sorted(p.name for p in openai_dir.iterdir()) != ["codex"]):
        raise Stop(2, "ADAPTER_VERSION", f"codex-acp のバージョンが {ADAPTER_VERSION} ではない、または想定外のパッケージがあります。停止します。")
    return index


# --------------------------------------------------------------------------- stage 2
def child_env(cfg: Config, gate_log: Path, app_logs: Path) -> dict[str, str]:
    """Explicit environment for the adapter / account probe (no API-key or provider variables)."""
    env = {
        "CODEX_HOME": str(cfg.codex_home),
        "CODEX_PATH": str(cfg.gate_launcher),
        "RELAY_GATE_BACKEND": str(cfg.codex_path),
        "RELAY_GATE_LOG": str(gate_log),
        "APP_SERVER_LOGS": str(app_logs),  # codex-acp logs raw JSON-RPC here; deleted after the run
        "INITIAL_AGENT_MODE": "read-only",
        "NO_BROWSER": "1",
    }
    if os.name == "nt":
        env["RELAY_GATE_PYTHON"] = cfg.python_exe
    env.update(cfg.extra_env)
    return env


class _Rpc:
    """Tiny newline-JSON-RPC client over the gate launcher (account probe only)."""

    def __init__(self, cfg: Config, env: dict[str, str]):
        full = {**default_environment(), **env}
        if os.name == "nt":
            args: Any = f'"{cfg.gate_launcher}" app-server'
            self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=full, shell=True)
        else:
            self.proc = subprocess.Popen([str(cfg.gate_launcher), "app-server"], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=full)
        self.lines: queue.Queue[bytes] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in iter(self.proc.stdout.readline, b""):
            self.lines.put(line)
        self.lines.put(b"")

    def call(self, request: dict[str, Any], timeout: float) -> Any:
        self.proc.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
        self.proc.stdin.flush()
        while True:
            try:
                line = self.lines.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError("backend did not answer")
            if not line:
                raise EOFError("backend closed")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == request["id"]:
                if "error" in msg:
                    raise RuntimeError("backend returned an error")
                return msg.get("result")

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        try:
            self.proc.stdout.close()
        except Exception:
            pass


def probe_account(cfg: Config, env: dict[str, str]) -> dict[str, Any]:
    """ONE read-only account/read (refreshToken=false). Returns ONLY the sanitized summary."""
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "capabilities": {"experimentalApi": True, "requestAttestation": False},
        "clientInfo": {"name": "relay-m9-runner", "version": "1", "title": "Relay M9 runner"}}}
    account_request = read_only_requests(first_id=2)[0]
    assert_read_only(account_request["method"])
    rpc = _Rpc(cfg, env)
    try:
        rpc.call(init, 30)
        raw = rpc.call(account_request, 30)
    finally:
        rpc.close()
    summary = summarize_account_evidence(raw, None)  # raw is dropped right here
    del raw
    return {"auth_state": summary["auth_state"], "plan_type": summary["plan_type"], "side_effects": 0}


# --------------------------------------------------------------------------- approval
def request_approval(cfg: Config, pre: dict[str, Any]) -> dict[str, Any]:
    head = pre["head"]
    phrase = f"{DECISION} {head[:7]}"
    cfg.out("")
    cfg.out("================ M9 初回 LIVE（Codex・1 回だけ）================")
    cfg.out("これから、あなたの PC の Codex（ChatGPT ログイン）で、次の操作を「1 回だけ」行います。")
    cfg.out("  ・保存されたログイン情報の置き場所を Codex に渡します（中身は表示・保存しません）")
    cfg.out("  ・まず事前確認用 account/read を 1 回だけ実行（読み取り専用）。ChatGPT アカウント経路でなければモデルは呼ばず停止")
    cfg.out("  ・その後、固定版 codex-acp 2.1.1 が session 準備中に追加の read-only account/read を行う場合があります（fixture では 2 回観測）。生成ではなく、retry もしません")
    cfg.out(f"  ・ChatGPT アカウントなら、モデルに「{PROMPT}」と 1 回だけ依頼（最大 {cfg.timeout_seconds} 秒）")
    cfg.out("  ・成功でも失敗でも、その 1 回で終了し、再実行はできません")
    cfg.out("  ・API キー・login/logout・課金/設定の変更は一切行いません")
    cfg.out("【注意】既存の承認チェーン（全プロバイダ分の証拠と GitHub での本人確認）は、まだ満たせません。")
    cfg.out("  今回は、あなたがこの画面で入力する確認を承認の根拠にします（結果に『既存チェーン未検証』と記録されます）。")
    answer = (cfg.confirm or _console_confirm)(f"承認する場合は次の文字をそのまま入力して Enter: {phrase}\n> ")
    if answer.strip() != phrase:
        raise Stop(5, "APPROVAL_NOT_GIVEN", "承認の文字が一致しませんでした。LIVE は行わず停止します（モデル呼び出し 0 回）。")
    record = {
        "decision": DECISION, "scope": SCOPE, "one_shot": True, "provider": PROVIDER,
        "max_dispatches": 1, "max_prompts": 1, "max_generations": 1, "retry": 0, "fallback": "disabled",
        "timeout_seconds": cfg.timeout_seconds, "head": head, "branch": pre["branch"],
        "code_sha256": code_sha256(cfg.repo_root),
        "checklist_sha256": canonical_sha256(pre["checklist"]),
        "correlation_id": str(uuid.uuid4()), "nonce": uuid.uuid4().hex, "recorded_at": now_utc(),
        "provenance_basis": "LOCAL_INTERACTIVE_CONSOLE_CONFIRMATION",
        "existing_chain_provenance": "NOT_VERIFIED",
        "account_read_scope": "one explicit preflight read plus pinned codex-acp 2.1.1 internal read-only account reads during the single session setup; no retries",
        "runner_version": RUNNER_VERSION,
    }
    approval = {"record": record, "approval_sha256": canonical_sha256(record)}
    verify_approval_record(approval)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(cfg.state_dir / APPROVAL_FILE, approval)
    return approval


# --------------------------------------------------------------------------- stage 3
def run_live_turn(cfg: Config, approval: dict[str, Any], adapter_index: Path, env: dict[str, str]) -> dict[str, Any]:
    record = approval["record"]
    auth = LiveAuthorization(state_dir=cfg.state_dir, approval_sha256=approval["approval_sha256"])
    profile = build_codex_profile("account", {
        "api_key_present": False, "gateway_configured": False, "external_cloud_configured": False,
        "custom_model_provider_configured": False, "arbitrary_codex_config_present": False})
    launch = OfficialAdapterLaunch(
        command=(str(cfg.node_path), str(adapter_index)), env=env,
        fixture_root=cfg.repo_root / "fixtures" / "relay", live_authorization=auth)
    transport = AcpStdioStaticTransport(profile, official=launch)
    envelope = DispatchEnvelope.build(
        slot=DispatchSlot("m9-first-live", PROVIDER, 0), correlation_id=record["correlation_id"],
        payload={"prompt": PROMPT}, timeout_seconds=cfg.timeout_seconds)
    guard = DuplicateGuard()
    first, second = guard.reserve(envelope), guard.reserve(envelope)  # 2nd identical reserve must be a NO-OP
    if first is not DuplicateDecision.RESERVED or second is not DuplicateDecision.SAME_REQUEST:
        raise Stop(1, "DUPLICATE_GUARD", "重複防止の確認に失敗しました。停止します。")
    result: dict[str, Any] = {"state": "UNKNOWN_ERROR", "text": None, "prompt_attempts": 0, "error_class": None}
    workdir = Path(tempfile.mkdtemp(prefix="m9_cwd_"))  # empty directory: nothing for the model to see
    session_id: str | None = None
    try:
        transport.initialize(PROVIDER)
        session_id = transport.open_session(PROVIDER, cwd=str(workdir))
        result["prompt_attempts"] = 1
        raw = transport.prompt(PROVIDER, session_id, envelope.payload, timeout_seconds=cfg.timeout_seconds)
        text = json.loads(raw.decode("utf-8")).get("answer_text", "")
        result["text"] = text
        result["state"] = "SUCCESS_M9_OK" if text.strip() == EXPECTED_TEXT else "COMPLETED_UNEXPECTED_TEXT"
    except TimeoutError:
        result["state"] = "TIMEOUT"
        _best_effort_cancel(transport, session_id)
    except Exception as exc:  # fail closed; never retried
        result["state"], result["error_class"] = "UNKNOWN_ERROR", type(exc).__name__
        _best_effort_cancel(transport, session_id)
    finally:
        try:
            if session_id is not None:
                transport.close(PROVIDER, session_id)
        except Exception:
            pass
        shutil.rmtree(workdir, ignore_errors=True)
    result["spawn_count"] = transport.spawn_count
    result["prompt_count"] = transport.prompt_count
    return result


def _best_effort_cancel(transport: AcpStdioStaticTransport, session_id: str | None) -> None:
    if session_id is not None:
        try:
            transport.cancel(PROVIDER, session_id)
        except Exception:
            pass


def response_shape(text: Any) -> dict[str, Any]:
    """Secret-free shape of the reply (never the text itself) so an unexpected reply can be diagnosed later."""
    if not isinstance(text, str):
        return {"response_stripped_char_count": None, "response_line_count": None, "response_starts_with_M9_OK": None,
                "response_contains_M9_OK": None, "response_text_sha256": None}
    stripped = text.strip()
    return {
        "response_stripped_char_count": len(stripped), "response_line_count": len(stripped.splitlines()),
        "response_starts_with_M9_OK": stripped.startswith(EXPECTED_TEXT),
        "response_contains_M9_OK": EXPECTED_TEXT in text,
        "response_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def build_terminal_receipt(cfg: Config, approval: dict[str, Any], pre: dict[str, Any], account: dict[str, Any],
                           live: dict[str, Any], gate: dict[str, int]) -> dict[str, Any]:
    state = live["state"]
    if gate["allowed"] > 1:
        state = "FAIL_MULTI_GENERATION"
    text = live.get("text")
    receipt = {
        "runner_version": RUNNER_VERSION, "timestamp_utc": now_utc(), "provider": PROVIDER,
        "head": pre["head"], "branch": pre["branch"],
        "approval_sha256": approval["approval_sha256"], "correlation_id": approval["record"]["correlation_id"],
        "code_sha256": approval["record"]["code_sha256"], "checklist_sha256": approval["record"]["checklist_sha256"],
        "approval_basis": approval["record"]["provenance_basis"], "existing_chain_provenance": "NOT_VERIFIED",
        "account_read_scope": approval["record"].get("account_read_scope"),
        "account_auth_state": account["auth_state"], "account_plan_type": account["plan_type"], "account_side_effects": 0,
        "dispatch_count": 1, "prompt_count": live["prompt_count"], "adapter_process_count": live["spawn_count"],
        "gate_allowed_generations": gate["allowed"], "gate_blocked_generations": gate["blocked"],
        "backend_generations_reached": gate["allowed"], "timeout_seconds": cfg.timeout_seconds,
        "terminal_state": state, "error_class": live.get("error_class"),
        "response_was_M9_OK": isinstance(text, str) and text.strip() == EXPECTED_TEXT,
        "response_char_count": len(text) if isinstance(text, str) else None,
        **response_shape(text),
        "retry_count": 0, "fallback_state": "disabled",
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    _assert_no_secret(receipt)
    return receipt


# --------------------------------------------------------------------------- orchestration
def run(cfg: Config) -> int:
    out = cfg.out
    state = cfg.state_dir
    out(f"M9 初回 LIVE ランナー（{RUNNER_VERSION}）")
    terminal = state / TERMINAL_FILE
    if terminal.exists():
        out("すでに 1 回実行済みです（NO-OP）。再実行しません。記録された結果:")
        out(terminal.read_text(encoding="utf-8"))
        return 0
    try:
        pre = preflight(cfg)
        adapter_index = ensure_adapter(cfg)
        approval = request_approval(cfg, pre)
        state.mkdir(parents=True, exist_ok=True)
        app_logs = Path(tempfile.mkdtemp(prefix="m9_applogs_"))
        gate_log = state / "gate.log"
        account_log = state / "account_probe_gate.log"
        try:
            gate_log.unlink(missing_ok=True)
            env = child_env(cfg, gate_log, app_logs)
            if not write_exclusive(state / CONSUMED_FILE, {
                    "approval_sha256": approval["approval_sha256"], "correlation_id": approval["record"]["correlation_id"],
                    "consumed_at": now_utc()}):
                raise Stop(3, "ALREADY_CONSUMED", "すでに承認が使用済みです（NO-OP）。")
            out("  アカウント確認（明示的な読み取り専用 account/read はこの 1 回だけ）...")
            try:
                account = probe_account(cfg, {**env, "RELAY_GATE_LOG": str(account_log)})
            except Exception:
                raise Stop(4, "ACCOUNT_UNKNOWN", "アカウント状態を確認できませんでした（UNKNOWN）。モデルは呼ばず停止します（モデル呼び出し 0 回）。")
            if account["auth_state"] != "CHATGPT_ACCOUNT":
                raise Stop(4, f"ACCOUNT_{account['auth_state']}",
                           f"ChatGPT アカウント経路ではありません（判定: {account['auth_state']}）。モデルは呼ばず停止します（モデル呼び出し 0 回）。")
            out(f"  [OK] ChatGPT アカウント経路（プラン: {account['plan_type']}）")
            out(f"  モデルへ 1 回だけ依頼します（最大 {cfg.timeout_seconds} 秒）...")
            live = run_live_turn(cfg, approval, adapter_index, env)
            receipt = build_terminal_receipt(cfg, approval, pre, account, live, count_gate_decisions(gate_log))
            write_exclusive(terminal, receipt)
        finally:
            shutil.rmtree(app_logs, ignore_errors=True)  # raw adapter logs may contain account/model text
    except Stop as stop:
        out(f"【停止】{stop.message_ja}")
        out(f"  理由コード: {stop.reason}")
        try:
            state.mkdir(parents=True, exist_ok=True)
            _atomic_write(state / "last_stop.json", {"timestamp_utc": now_utc(), "reason": stop.reason, "model_turns": 0})
        except OSError:
            pass
        return stop.code
    out("")
    out(f"結果: {receipt['terminal_state']}（M9_OK が返ったか: {'はい' if receipt['response_was_M9_OK'] else 'いいえ'}）")
    out(f"  モデルへ届いた生成: {receipt['backend_generations_reached']} 回 / ゲートが止めた生成: {receipt['gate_blocked_generations']} 回")
    out("  これで終了です。再実行はできません。次の内容（秘密情報なし）を Claude に貼ってください:")
    out("-----8<-----")
    out(json.dumps(receipt, indent=2, ensure_ascii=False))
    out("----->8-----")
    out(f"  保存先: {terminal}")
    return 0 if receipt["terminal_state"] == "SUCCESS_M9_OK" else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    repo = Path(__file__).resolve().parents[2]
    return run(default_config(repo))


if __name__ == "__main__":
    sys.exit(main())
