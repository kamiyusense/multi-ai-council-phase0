#!/usr/bin/env python3
"""Run Claude Code against a loopback-only fake Messages API.

This program is intended to run only inside the workflow's Docker
``--network none`` container. It refuses to start Claude unless the network
namespace has only loopback, has no routes, and external IPv4/DNS probes fail.
It never reads or mounts host Claude configuration and never records API-key
values or request bodies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any


CASES = ("A", "B", "C", "D", "E", "F", "G", "H")
CASE_DESCRIPTIONS = {
    "A": "single successful response",
    "B": "max_tokens output truncation",
    "C": "no response / API timeout",
    "D": "mid-stream disconnect",
    "E": "retryable 5xx response",
    "F": "429 response",
    "G": "401 authentication failure then recovery response",
    "H": "interrupt while request is in flight",
}
FAKE_KEY = "sk-ant-api03-fake-local-only-not-a-credential"
EXPECTED_VERSION = "2.1.283"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def safe_headers(headers: Any) -> dict[str, Any]:
    """Select useful non-secret headers; never retain credential values."""
    wanted = (
        "anthropic-version",
        "anthropic-beta",
        "content-type",
        "user-agent",
        "x-claude-code-prompt-id",
        "x-claude-code-request-class",
        "x-claude-code-agent-type",
        "retry-after",
    )
    result = {name: headers.get(name) for name in wanted if headers.get(name)}
    result["x-api-key-present"] = bool(headers.get("x-api-key"))
    result["authorization-present"] = bool(headers.get("authorization"))
    return result


def classify_case(case: dict[str, Any]) -> str:
    """Fail on observed duplicate requests; require complete observation to pass."""
    count = case.get("fake_provider_request_count")
    if isinstance(count, int) and count > 1:
        return "FAIL"
    if (
        case.get("controller_dispatch_count") == 1
        and count == 1
        and case.get("process_observation_complete") is True
        and case.get("retry_or_continuation_indication") is False
        and case.get("fallback_indication") is False
    ):
        return "PASS"
    return "UNKNOWN"


def network_preflight() -> dict[str, Any]:
    interfaces = sorted(p.name for p in Path("/sys/class/net").iterdir())
    result: dict[str, Any] = {
        "checked_at": now(),
        "docker_network_driver": os.environ.get("PROBE_DOCKER_NETWORK_DRIVER"),
        "interfaces": interfaces,
        "ip_addr_output": None,
        "ip_route_output": None,
        "proc_net_route": Path("/proc/net/route").read_text(errors="replace"),
        "proc_net_dev": Path("/proc/net/dev").read_text(errors="replace"),
        "external_ipv4_probe": None,
        "external_dns_probe": None,
    }

    if result["docker_network_driver"] != "null":
        result["error"] = "host did not attest Docker's none/null network driver"
        return result

    ip = shutil.which("ip")
    if ip:
        addr = subprocess.run([ip, "addr"], capture_output=True, text=True, timeout=5)
        route = subprocess.run([ip, "route"], capture_output=True, text=True, timeout=5)
        result["ip_addr_output"] = addr.stdout + addr.stderr
        result["ip_route_output"] = route.stdout + route.stderr
        if addr.returncode or route.returncode:
            result["error"] = "ip addr/ip route command failed"
            return result
        addr_lines = [line.strip() for line in addr.stdout.splitlines() if line.strip()]
        current_interface = None
        for line in addr_lines:
            if re.match(r"^\d+:\s", line):
                current_interface = line.split(":", 2)[1].split("@", 1)[0].strip()
                if current_interface != "lo":
                    result["error"] = f"unexpected interface: {current_interface}"
                    return result
            elif line.startswith("inet ") or line.startswith("inet6 "):
                raw_address = line.split()[1].split("/", 1)[0]
                try:
                    address = ipaddress.ip_address(raw_address)
                except ValueError:
                    result["error"] = "unparseable address in network namespace"
                    return result
                if current_interface != "lo" or not address.is_loopback:
                    result["error"] = f"non-loopback address found: {raw_address}"
                    return result
        if route.stdout.strip():
            result["error"] = "route table is not empty"
            return result
    else:
        # Minimal official Python images may omit iproute2. The kernel procfs
        # views are used instead; the network-none driver is independently
        # checked by the host workflow before entering this container.
        route_lines = [line for line in result["proc_net_route"].splitlines()[1:] if line.strip()]
        dev_lines = [line for line in result["proc_net_dev"].splitlines()[2:] if line.strip()]
        dev_names = sorted(line.split(":", 1)[0].strip() for line in dev_lines)
        result["fallback_interface_names"] = dev_names
        if route_lines or dev_names != ["lo"]:
            result["error"] = "procfs shows a route or non-loopback interface"
            return result

    if interfaces != ["lo"]:
        result["error"] = "expected loopback-only interface list"
        return result

    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=2):
            result["external_ipv4_probe"] = {"blocked": False, "detail": "TCP connection succeeded"}
            return result
    except OSError as exc:
        result["external_ipv4_probe"] = {"blocked": True, "detail": f"{type(exc).__name__}: {exc}"}

    try:
        socket.setdefaulttimeout(2)
        socket.getaddrinfo("example.com", 443, type=socket.SOCK_STREAM)
        result["external_dns_probe"] = {"blocked": False, "detail": "DNS resolution succeeded"}
        return result
    except OSError as exc:
        result["external_dns_probe"] = {"blocked": True, "detail": f"{type(exc).__name__}: {exc}"}
    finally:
        socket.setdefaulttimeout(None)
    result["passed"] = True
    return result


class ProviderState:
    def __init__(self, case_id: str):
        self.case_id = case_id
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.first_request = threading.Event()
        self.release_waiting_response = threading.Event()


def make_handler(state: ProviderState):
    class FakeMessagesHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _record(self, body: bytes) -> tuple[int, dict[str, Any]]:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except Exception:
                parsed = {}
            with state.lock:
                number = len(state.requests) + 1
                entry: dict[str, Any] = {
                    "sequence": number,
                    "timestamp": now(),
                    "path": self.path,
                    "method": self.command,
                    "endpoint": f"http://{self.headers.get('host', '127.0.0.1')}{self.path}",
                    "headers": safe_headers(self.headers),
                    "body_sha256": sha256(body),
                    "body_bytes": len(body),
                    "request_model": parsed.get("model"),
                    "stream": parsed.get("stream"),
                    "max_tokens": parsed.get("max_tokens"),
                    "message_count": len(parsed.get("messages", [])) if isinstance(parsed.get("messages"), list) else None,
                    "connection_lifecycle": ["request_received"],
                }
                state.requests.append(entry)
            state.first_request.set()
            return number, entry

        def _close_lifecycle(self, entry: dict[str, Any], event: str) -> None:
            with state.lock:
                entry["connection_lifecycle"].append(event)

        def _json_response(self, status: int, payload: dict[str, Any], entry: dict[str, Any], retry_after: str | None = None) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            entry["response_status"] = status
            entry["response_headers"] = {"content-type": "application/json", "connection": "close"}
            if retry_after is not None:
                entry["response_headers"]["retry-after"] = retry_after
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            if retry_after is not None:
                self.send_header("Retry-After", retry_after)
            self.end_headers()
            self._close_lifecycle(entry, f"response_started_{status}")
            try:
                self.wfile.write(body)
                self.wfile.flush()
                self._close_lifecycle(entry, "response_completed")
            except OSError:
                self._close_lifecycle(entry, "client_disconnected")
            self.close_connection = True

        def _sse_response(self, entry: dict[str, Any], stop_reason: str, text: str) -> None:
            entry["response_status"] = 200
            entry["response_headers"] = {"content-type": "text/event-stream", "connection": "close"}
            model = entry.get("request_model") or "claude-sonnet-4-5"
            message = {
                "id": f"msg_fake_{state.case_id}_{entry['sequence']}",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 8, "output_tokens": 2},
            }
            frames = [
                ("message_start", {"type": "message_start", "message": message}),
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
            ]
            if state.case_id == "D":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self._close_lifecycle(entry, "stream_started")
                try:
                    for name, value in frames:
                        self.wfile.write(f"event: {name}\ndata: {json.dumps(value, separators=(',', ':'))}\n\n".encode())
                        self.wfile.flush()
                    self._close_lifecycle(entry, "stream_disconnected_mid_response")
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    self._close_lifecycle(entry, "client_disconnected")
                self.close_connection = True
                return

            frames.extend([
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": 2}}),
                ("message_stop", {"type": "message_stop"}),
            ])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self._close_lifecycle(entry, "stream_started")
            try:
                for name, value in frames:
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(value, separators=(',', ':'))}\n\n".encode())
                    self.wfile.flush()
                self._close_lifecycle(entry, "stream_completed")
            except OSError:
                self._close_lifecycle(entry, "client_disconnected")
            self.close_connection = True

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
            except Exception:
                body = b""
            number, entry = self._record(body)
            if state.case_id == "C":
                state.release_waiting_response.wait(timeout=45)
                self._close_lifecycle(entry, "no_response_connection_closed")
                self.close_connection = True
                return
            if state.case_id == "H":
                state.release_waiting_response.wait(timeout=45)
                self._close_lifecycle(entry, "interrupted_connection_closed")
                self.close_connection = True
                return
            if state.case_id == "E":
                self._json_response(500, {"type": "error", "error": {"type": "api_error", "message": "fake retryable 5xx"}}, entry, retry_after="0")
                return
            if state.case_id == "F":
                self._json_response(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "fake 429"}}, entry, retry_after="0")
                return
            if state.case_id == "G" and number == 1:
                self._json_response(401, {"type": "error", "error": {"type": "authentication_error", "message": "fake auth failure"}}, entry)
                return
            stop = "max_tokens" if state.case_id == "B" else "end_turn"
            text = "partial" if state.case_id == "B" else "fake local response"
            if entry.get("stream") is False:
                model = entry.get("request_model") or "claude-sonnet-4-5"
                self._json_response(200, {
                    "id": f"msg_fake_{state.case_id}_{number}",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": text}],
                    "stop_reason": stop,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 8, "output_tokens": 2},
                }, entry)
            else:
                self._sse_response(entry, stop, text)

        def do_GET(self) -> None:
            _, entry = self._record(b"")
            self._json_response(404, {"type": "error", "error": {"type": "not_found_error", "message": "fake endpoint"}}, entry)

        def finish(self) -> None:
            try:
                super().finish()
            finally:
                # Connection closure is recorded on every request handled by this connection.
                with state.lock:
                    for item in state.requests:
                        if item["connection_lifecycle"] and "connection_closed" not in item["connection_lifecycle"]:
                            item["connection_lifecycle"].append("connection_closed")

    return FakeMessagesHandler


def run_command(args: list[str], env: dict[str, str], timeout: int) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        return {
            "exit_status": completed.returncode,
            "timed_out": False,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout": completed.stdout[-6000:],
            "stderr": completed.stderr[-6000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_status": None,
            "timed_out": True,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout": (exc.stdout or b"").decode(errors="replace")[-6000:] if isinstance(exc.stdout, bytes) else (exc.stdout or "")[-6000:],
            "stderr": (exc.stderr or b"").decode(errors="replace")[-6000:] if isinstance(exc.stderr, bytes) else (exc.stderr or "")[-6000:],
        }


def redact_text(value: str) -> str:
    return value.replace(FAKE_KEY, "<fake-credential-redacted>")


def make_base_env(home: Path, config: Path, tmp: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "CLAUDE_CONFIG_DIR": str(config),
        "CLAUDE_CODE_MAX_RETRIES": "0",
        "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK": "1",
        "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
        "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
        "CLAUDE_CODE_RESUME_INTERRUPTED_TURN": "0",
        "CLAUDE_CODE_SAFE_MODE": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
        "CLAUDE_CODE_DISABLE_FAST_MODE": "1",
        "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
        "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_UPDATES": "1",
        "API_TIMEOUT_MS": "4000",
        "RES_OPTIONS": "attempts:1 timeout:1",
    }


def run_case(case_id: str, claude: Path, out: Path, root: Path) -> dict[str, Any]:
    state = ProviderState(case_id)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    case_root = root / case_id
    home, config, tmp, cwd = (case_root / n for n in ("home", "config", "tmp", "cwd"))
    for directory in (home, config, tmp, cwd):
        directory.mkdir(parents=True, exist_ok=True)
    env = make_base_env(home, config, tmp)
    env.update({
        "ANTHROPIC_API_KEY": FAKE_KEY,
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
    })
    command = [
        str(claude), "--restricted", "--safe-mode", "-p", "Reply with one short word.",
        "--max-turns", "1", "--tools", "", "--no-session-persistence",
        "--permission-prompts", "none", "--output-format", "stream-json",
    ]
    case: dict[str, Any] = {
        "id": case_id,
        "scenario": CASE_DESCRIPTIONS[case_id],
        "controller_dispatch_count": 0,
        "fake_provider_request_count": 0,
        "runtime_identity": {
            "version": EXPECTED_VERSION,
            "executable_sha256": os.environ.get("EXPECTED_CLAUDE_SHA256"),
        },
        "command_flags": ["--restricted", "--safe-mode", "-p", "--max-turns 1", "--tools ''", "--no-session-persistence", "--permission-prompts none", "--output-format stream-json"],
    }
    process: subprocess.Popen[str] | None = None
    try:
        process_started = time.monotonic()
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   start_new_session=True)
        case["controller_dispatch_count"] = 1
        if case_id == "H":
            arrived = state.first_request.wait(timeout=15)
            case["interrupt_sent"] = arrived
            if arrived:
                os.killpg(process.pid, signal.SIGINT)
                state.release_waiting_response.set()
        try:
            stdout, stderr = process.communicate(timeout=30)
            case.update({"exit_status": process.returncode, "timed_out": False, "process_observation_complete": True,
                         "process_elapsed_seconds": round(time.monotonic() - process_started, 3)})
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate(timeout=5)
            case.update({"exit_status": process.returncode, "timed_out": True, "process_observation_complete": False,
                         "process_elapsed_seconds": round(time.monotonic() - process_started, 3)})
        time.sleep(3)
        case["stdout"] = redact_text(stdout[-6000:])
        case["stderr"] = redact_text(stderr[-6000:])
    except Exception as exc:
        case["launch_error"] = f"{type(exc).__name__}: {exc}"
        case["process_observation_complete"] = False
    finally:
        state.release_waiting_response.set()
        case["requests"] = state.requests
        case["fake_provider_request_count"] = len(state.requests)
        try:
            server.shutdown()
            server.server_close()
        finally:
            server_thread.join(timeout=2)

    combined = (case.get("stdout", "") + "\n" + case.get("stderr", "")).lower()
    case["retry_or_continuation_indication"] = bool(re.search(r"\b(retry|retrying|continu(?:e|ation)|resum(?:e|ing))\b", combined))
    request_models = [r.get("request_model") for r in state.requests if r.get("request_model")]
    case["model_indication"] = request_models
    case["fallback_indication"] = len(set(request_models)) > 1 or "fallback" in combined
    case["status"] = classify_case(case)
    (out / f"case-{case_id}.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    return case


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: probe.py /path/to/claude /out", file=sys.stderr)
        return 2
    claude = Path(sys.argv[1])
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "probe_date_utc": now(),
        "expected_version": EXPECTED_VERSION,
        "runtime_probe_status": "UNKNOWN",
        "literal_retry_zero": "UNKNOWN",
        "controller_dispatch_count": 0,
        "live_anthropic_requests": 0,
        "live_jules_requests": 0,
        "real_credentials_used": 0,
        "network_isolation": {},
        "runtime_identity": {},
        "runtime_settings": {},
        "cases": [],
    }
    if not claude.is_file() or not os.access(claude, os.X_OK):
        evidence["runtime_probe_status"] = "BLOCKED_BEFORE_EXECUTION"
        evidence["blocker"] = "official executable missing or not executable"
        (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return 3

    expected_hash = os.environ.get("EXPECTED_CLAUDE_SHA256", "")
    actual_hash = sha256(claude.read_bytes())
    evidence["runtime_identity"] = {"absolute_path": str(claude), "executable_sha256": actual_hash, "expected_sha256": expected_hash}
    if not expected_hash or actual_hash != expected_hash:
        evidence["runtime_probe_status"] = "BLOCKED_BEFORE_EXECUTION"
        evidence["blocker"] = "executable hash mismatch or expected hash absent"
        (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return 3

    network = network_preflight()
    evidence["network_isolation"] = network
    if network.get("passed") is not True:
        evidence["runtime_probe_status"] = "BLOCKED_BEFORE_EXECUTION"
        evidence["blocker"] = network.get("error", "network isolation could not be verified")
        (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return 4

    root = Path("/tmp/claude-retry-zero-probe")
    root.mkdir(parents=True, exist_ok=True)
    preflight_env = make_base_env(root / "home", root / "config", root / "tmp")
    for name in ("home", "config", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    version = run_command([str(claude), "--version"], preflight_env, 15)
    help_result = run_command([str(claude), "--help"], preflight_env, 15)
    help_text = help_result.get("stdout", "") + help_result.get("stderr", "")
    detected = {flag: flag in help_text for flag in ("--restricted", "--safe-mode", "--max-turns", "--tools", "--no-session-persistence", "--permission-prompts")}
    version_text = (version.get("stdout", "") + version.get("stderr", "")).strip()
    version_ok = version.get("exit_status") == 0 and EXPECTED_VERSION in version_text
    help_ok = help_result.get("exit_status") == 0 and all(detected.values())
    evidence["runtime_identity"].update({"version_stdout": version_text, "version_exit_status": version.get("exit_status"), "help_exit_status": help_result.get("exit_status"), "executable_sha256_verified": True})
    evidence["runtime_settings"] = {
        "CLAUDE_CODE_MAX_RETRIES": "0",
        "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK": "1",
        "CLAUDE_ENABLE_STREAM_WATCHDOG": "0",
        "CLAUDE_ENABLE_BYTE_WATCHDOG": "0",
        "CLAUDE_CODE_RESUME_INTERRUPTED_TURN": "0",
        "CLAUDE_CODE_SAFE_MODE": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_UPDATES": "1",
        "API_TIMEOUT_MS": "4000",
        "help_flags": detected,
        "settings_verified_from_runtime_help": help_ok,
        "session_persistence_disabled": "--no-session-persistence + CLAUDE_CODE_SKIP_PROMPT_HISTORY=1",
        "tools_disabled": "--tools empty string",
        "fallback_model_configured": False,
        "advisor_configured": False,
        "fast_mode_disabled": "CLAUDE_CODE_DISABLE_FAST_MODE=1",
        "background_tasks_disabled": "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1",
        "subagents_disabled": "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1; no agent/tool invocation",
        "resume_or_continue_flags_used": False,
    }
    evidence["runtime_probe_status"] = "PREFLIGHT_BLOCKED" if not (version_ok and help_ok) else "RUNNING_FAKE_PROVIDER_MATRIX"
    (out / "runtime-help.txt").write_text(redact_text(help_text[-12000:]), encoding="utf-8")
    if not (version_ok and help_ok):
        evidence["blocker"] = "version or required actual-binary CLI help verification failed"
        (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        return 5

    for case_id in CASES:
        case = run_case(case_id, claude, out, root)
        evidence["cases"].append(case)
        evidence["controller_dispatch_count"] += case.get("controller_dispatch_count", 0)
    statuses = [case["status"] for case in evidence["cases"]]
    if "FAIL" in statuses:
        evidence["literal_retry_zero"] = "FAIL"
    elif len(statuses) == len(CASES) and all(status == "PASS" for status in statuses):
        evidence["literal_retry_zero"] = "PASS"
    else:
        evidence["literal_retry_zero"] = "UNKNOWN"
    evidence["runtime_probe_status"] = "COMPLETE"
    evidence["fake_provider_request_count"] = sum(case["fake_provider_request_count"] for case in evidence["cases"])
    evidence["no_real_credentials"] = True
    evidence["no_real_provider_or_jules"] = True
    (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return 0 if evidence["literal_retry_zero"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
