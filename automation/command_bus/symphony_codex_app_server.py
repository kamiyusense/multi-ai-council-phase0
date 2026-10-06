"""One-turn Codex app-server adapter for the Symphony Phase 0 controller.

This is an explicit opt-in boundary. Construct with ``live_enabled=True`` only
for a reviewed one-command proof. The adapter never retries a request; once a
turn/start write is attempted, transport uncertainty is terminal UNKNOWN.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from .symphony_controller import Command


MAX_CONCURRENT_AGENTS = 1
MAX_TURNS = 1
MAX_MODEL_STARTS = 1
RETRY = 0
FALLBACK = "disabled"
PROOF_PATH = "evidence/symphony_live_one_round_v1.txt"
PROOF_CONTENT = "SYMPHONY_LIVE_ONE_ROUND_V1_PASS"


@dataclass(frozen=True)
class PreparedCodexCommand:
    command: Command
    cwd: str
    prompt: str
    head_before: str
    tree_before: str


@dataclass(frozen=True)
class CodexDispatchResult:
    status: str
    dispatch_attempted: bool
    model_started: bool | None
    thread_id: str | None
    turn_id: str | None
    events: tuple[dict[str, Any], ...]
    reason: str | None = None
    verification: dict[str, Any] | None = None
    changed_paths: tuple[str, ...] = ()
    proof_commit_sha: str | None = None


class AppServer(Protocol):
    def execute_one_turn(self, *, cwd: str, prompt: str) -> CodexDispatchResult: ...


class WorkspaceVerifier(Protocol):
    def prepare(self, command: Command, cwd: str) -> tuple[str, str]: ...
    def verify(self, prepared: PreparedCodexCommand) -> tuple[dict[str, Any], tuple[str, ...], str]: ...


class GitWorkspaceVerifier:
    """Read-only pre/post checks around the single Codex turn."""

    @staticmethod
    def _git(cwd: str, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                                timeout=15, check=False)
        if result.returncode != 0:
            raise RuntimeError("git preflight/readback failed")
        return result.stdout.strip()

    @classmethod
    def prepare(cls, command: Command, cwd: str) -> tuple[str, str]:
        payload = command.payload
        branch_expected = payload.get("target_branch")
        repository_expected = payload.get("target_repository")
        if not isinstance(branch_expected, str) or not isinstance(repository_expected, str):
            raise ValueError("LIVE command target identity is incomplete")
        head = cls._git(cwd, "rev-parse", "HEAD")
        tree = cls._git(cwd, "rev-parse", "HEAD^{tree}")
        branch = cls._git(cwd, "branch", "--show-current")
        dirty = cls._git(cwd, "status", "--porcelain", "--untracked-files=all")
        remote = cls._git(cwd, "remote", "get-url", "origin")
        if branch != branch_expected or head != command.expected_target_head or dirty:
            raise ValueError("LIVE workspace does not match clean target identity")
        expected_tree = command.expected_target_tree
        if expected_tree not in {None, "UNKNOWN"} and tree != expected_tree:
            raise ValueError("LIVE workspace target tree mismatch")
        parsed = urlsplit(remote if "://" in remote else "")
        if parsed.scheme:
            remote_repo = parsed.path.strip("/")
            host = parsed.hostname
        else:
            match = re.fullmatch(r"(?:[^@]+@)?github\.com:([^/]+/[^/]+?)(?:\.git)?", remote)
            remote_repo = match.group(1) if match else ""
            host = "github.com" if match else None
        if host != "github.com" or remote_repo.removesuffix(".git").lower() != repository_expected.lower():
            raise ValueError("LIVE workspace repository mismatch")
        return head, tree

    @classmethod
    def verify(cls, prepared: PreparedCodexCommand) -> tuple[dict[str, Any], tuple[str, ...], str]:
        cwd = prepared.cwd
        command = prepared.command
        head_after = cls._git(cwd, "rev-parse", "HEAD")
        branch_after = cls._git(cwd, "branch", "--show-current")
        dirty = cls._git(cwd, "status", "--porcelain", "--untracked-files=all")
        parents = cls._git(cwd, "rev-list", "--parents", "-n", "1", head_after).split()
        changed = tuple(filter(None, cls._git(cwd, "diff", "--name-only", "--no-renames",
                                             prepared.head_before, head_after).splitlines()))
        commit_count = cls._git(cwd, "rev-list", "--count", f"{prepared.head_before}..{head_after}")
        path = "evidence/symphony_live_one_round_v1.txt"
        proof = (Path(cwd) / path).read_text(encoding="utf-8")
        if (branch_after != command.payload.get("target_branch") or dirty
                or parents != [head_after, prepared.head_before] or commit_count != "1"
                or changed != (path,) or proof != "SYMPHONY_LIVE_ONE_ROUND_V1_PASS"):
            raise RuntimeError("Codex output failed exact proof verification")
        evidence = {
            "status": "LOCAL_PASS", "proof_path": path,
            "proof_content": "SYMPHONY_LIVE_ONE_ROUND_V1_PASS",
            "commit_parent": prepared.head_before, "normal_commit": True,
            "max_turns": 1, "force_push_count": None, "merge_count": None,
            "default_branch_mutation_count": None, "remote_readback": "PENDING",
        }
        return evidence, changed, head_after


class JsonlCodexAppServer:
    """Minimal JSON-RPC 2.0 JSONL client; one process and one turn, no retry."""

    def __init__(self, executable: str = "codex", *, timeout_seconds: float = 900):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if Path(executable).name.lower() not in {"codex", "codex.exe"}:
            raise ValueError("only the Codex executable is allowed")
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def execute_one_turn(self, *, cwd: str, prompt: str) -> CodexDispatchResult:
        proc: subprocess.Popen[str] | None = None
        attempted = False
        model_started: bool | None = False
        events: list[dict[str, Any]] = []
        request_id = 0
        thread_id: str | None = None
        turn_id: str | None = None
        turn_status: str | None = None
        output: queue.Queue[str | None] = queue.Queue()
        deadline = time.monotonic() + self.timeout_seconds
        try:
            proc = subprocess.Popen(
                [self.executable, "app-server"], cwd=cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                encoding="utf-8", bufsize=1,
            )

            def pump_output() -> None:
                assert proc is not None and proc.stdout is not None
                try:
                    for output_line in proc.stdout:
                        output.put(output_line)
                finally:
                    output.put(None)

            threading.Thread(target=pump_output, name="codex-app-server-output", daemon=True).start()

            def next_message() -> dict[str, Any]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("app-server response timed out")
                try:
                    line = output.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError("app-server response timed out") from exc
                if line is None:
                    raise RuntimeError("app-server closed its output")
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise RuntimeError("invalid app-server message")
                return item

            def capture_event(item: dict[str, Any]) -> None:
                nonlocal model_started, turn_id, turn_status
                if not item.get("method"):
                    return
                events.append(item)
                params_obj = item.get("params") or {}
                if item.get("method") == "turn/started":
                    model_started = True
                    turn = params_obj.get("turn", {})
                    turn_id = turn.get("id") or params_obj.get("turnId") or turn_id
                elif item.get("method") == "turn/completed":
                    finished = params_obj.get("turn") or params_obj
                    finished_id = finished.get("id") or finished.get("turnId")
                    if turn_id and finished_id and finished_id != turn_id:
                        raise RuntimeError("completion event turn id mismatch")
                    turn_status = finished.get("status")
                    turn_id = finished_id or turn_id
                    if turn_status and model_started is False:
                        model_started = None

            def call(method: str, params: dict[str, Any], *, dispatch: bool = False) -> dict[str, Any]:
                nonlocal request_id, attempted, model_started, turn_id
                request_id += 1
                ident = request_id
                message = {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}
                if dispatch:
                    # Set before writing: a broken pipe is ambiguous and must not be resent.
                    attempted = True
                assert proc is not None and proc.stdin is not None
                proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                proc.stdin.flush()
                while True:
                    item = next_message()
                    if item.get("method"):
                        capture_event(item)
                        continue
                    if item.get("id") != ident:
                        raise RuntimeError("unexpected app-server response id")
                    if "error" in item:
                        raise RuntimeError("app-server request rejected")
                    result = item.get("result")
                    if not isinstance(result, dict):
                        raise RuntimeError("invalid app-server response")
                    return result

            call("initialize", {"clientInfo": {"name": "phase0-symphony-controller", "version": "1"}})
            assert proc.stdin is not None
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}) + "\n")
            proc.stdin.flush()
            started = call("thread/start", {"cwd": cwd, "approvalPolicy": "never",
                                             "sandboxPolicy": {"type": "workspaceWrite"}})
            thread = started.get("thread") or started
            thread_id = thread.get("id") if isinstance(thread, dict) else None
            if not isinstance(thread_id, str) or not thread_id:
                raise RuntimeError("thread/start returned no thread id")
            completed = call("turn/start", {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "workspaceWrite"},
            }, dispatch=True)
            turn = completed.get("turn") or completed
            turn_id = turn.get("id") if isinstance(turn, dict) else turn_id
            status = turn.get("status") if isinstance(turn, dict) else None
            if turn_status is not None:
                status = turn_status
            # turn/start acknowledges submission; wait for the matching terminal
            # notification instead of mistaking acknowledgement for completion.
            while status not in {"completed", "failed", "interrupted"}:
                capture_event(next_message())
                if turn_status is not None:
                    status = turn_status
            if status == "completed":
                if model_started is not True:
                    return CodexDispatchResult("UNKNOWN", attempted, None, thread_id,
                                               turn_id, tuple(events), "model start event was not observed")
                return CodexDispatchResult("DONE", attempted, model_started, thread_id,
                                           turn_id, tuple(events))
            return CodexDispatchResult("UNKNOWN", attempted, model_started, thread_id,
                                       turn_id, tuple(events), "turn completion was not verified")
        except Exception as exc:
            if attempted and model_started is False:
                model_started = None
            return CodexDispatchResult("UNKNOWN", attempted, model_started, thread_id,
                                       turn_id, tuple(events), type(exc).__name__)
        finally:
            if proc is not None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass


class CodexAppServerAgentRunner:
    """Concrete live runner admitted by exact type in the controller."""

    live_enabled = False

    def __init__(self, *, cwd: str | Path, app_server: AppServer | None = None,
                 live_enabled: bool = False, workspace_verifier: WorkspaceVerifier | None = None):
        if type(live_enabled) is not bool:
            raise ValueError("live_enabled must be a boolean")
        self.cwd = str(Path(cwd).resolve())
        if not Path(self.cwd).is_dir():
            raise ValueError("Codex app-server cwd must be an existing directory")
        if app_server is not None and type(app_server) is not JsonlCodexAppServer:
            raise ValueError("only the built-in Codex JSONL app-server transport is admitted")
        if workspace_verifier is not None and type(workspace_verifier) is not GitWorkspaceVerifier:
            raise ValueError("only the built-in Git workspace verifier is admitted")
        self._app_server = app_server or JsonlCodexAppServer(os.environ.get("CODEX_BIN", "codex"))
        self._workspace_verifier = workspace_verifier or GitWorkspaceVerifier()
        self._live_enabled = live_enabled
        self._start_attempts = 0
        self._dispatch_lock = threading.Lock()
        self._last: CodexDispatchResult | None = None

    @property
    def live_enabled(self) -> bool:
        return self._live_enabled

    def prepare(self, command: Command) -> PreparedCodexCommand:
        if not self.live_enabled:
            raise RuntimeError("Codex LIVE flag is off")
        if self._start_attempts >= MAX_MODEL_STARTS:
            raise RuntimeError("maximum model starts reached")
        if (command.payload.get("retry") != RETRY or command.payload.get("fallback") != FALLBACK
                or type(command.payload.get("concurrency")) is not int
                or command.payload.get("concurrency") != MAX_CONCURRENT_AGENTS
                or type(command.payload.get("max_turns")) is not int
                or command.payload.get("max_turns") != MAX_TURNS
                or type(command.payload.get("max_model_starts")) is not int
                or command.payload.get("max_model_starts") != MAX_MODEL_STARTS):
            raise ValueError("unsafe retry/fallback policy")
        if (command.payload.get("allowed_paths") != [PROOF_PATH]
                or command.payload.get("verification", {}).get("exact_content") != PROOF_CONTENT):
            raise ValueError("unsafe Symphony LIVE proof scope")
        prompt = command.payload.get("task") or command.payload.get("objective")
        if (not isinstance(prompt, str) or not prompt.strip()
                or PROOF_PATH not in prompt or PROOF_CONTENT not in prompt):
            raise ValueError("command task must bind the exact proof path and content")
        head_before, tree_before = self._workspace_verifier.prepare(command, self.cwd)
        return PreparedCodexCommand(command, self.cwd, prompt, head_before, tree_before)

    def dispatch(self, prepared: PreparedCodexCommand) -> CodexDispatchResult:
        if not self.live_enabled:
            raise RuntimeError("Codex LIVE flag is off")
        if not self._dispatch_lock.acquire(blocking=False):
            raise RuntimeError("Codex concurrency limit is one")
        try:
            if self._start_attempts >= MAX_MODEL_STARTS:
                raise RuntimeError("maximum model starts reached")
            # Count the sole permitted submission attempt before entering transport.
            self._start_attempts += 1
            result = self._app_server.execute_one_turn(cwd=prepared.cwd, prompt=prepared.prompt)
            if result.status == "DONE":
                try:
                    verification, paths, commit_sha = self._workspace_verifier.verify(prepared)
                    result = CodexDispatchResult(
                        result.status, result.dispatch_attempted, result.model_started, result.thread_id,
                        result.turn_id, result.events, result.reason, verification, paths, commit_sha,
                    )
                except Exception as exc:
                    result = CodexDispatchResult(
                        "UNKNOWN", result.dispatch_attempted, result.model_started, result.thread_id,
                        result.turn_id, result.events, type(exc).__name__, {"status": "UNKNOWN"}, (), None,
                    )
            self._last = result
            return self._last
        finally:
            self._dispatch_lock.release()

    def classify_result(self, result: CodexDispatchResult) -> str:
        if not isinstance(result, CodexDispatchResult):
            return "UNKNOWN"
        return result.status if result.status in {"DONE", "BLOCKED", "FAILED", "UNKNOWN"} else "UNKNOWN"

    def readback(self) -> CodexDispatchResult | None:
        """Return in-process protocol evidence; durable evidence is written by Tracker."""
        return self._last
