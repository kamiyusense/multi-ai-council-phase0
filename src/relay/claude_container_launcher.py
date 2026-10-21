"""Host-side launcher for Path B (gated Claude container via official claude-agent-acp).

Runs the Claude CLI inside the proven gated container as ``CLAUDE_CODE_EXECUTABLE``.
This module handles authorization verification, environment safety checks, docker container create/start,
signal propagation (SIGTERM/SIGINT), and cleanup for auth probe containers.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import uuid
from collections.abc import Sequence
from typing import Any

from relay.claude_container_argv import AUTH_PROBE_ARGV
from relay.claude_container_docker import (
    build_docker_create_argv,
    build_docker_start_argv,
    container_name,
)
from relay.claude_live_state import LiveAuthorization, verify_claude_live_authorization

__all__ = [
    "LauncherRunner",
    "launch_claude_container",
    "FORBIDDEN_ENV_KEYS",
]

FORBIDDEN_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


class LauncherRunner:
    """Subprocess runner for Docker commands. Injectable for testing."""

    def run_create(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            shell=False,
            check=False,
        )

    def start_process(self, argv: list[str]) -> subprocess.Popen:
        return subprocess.Popen(
            argv,
            stdin=None,
            stdout=None,
            stderr=sys.stderr,
            shell=False,
        )

    def run_kill(self, name: str, timeout: float = 5.0) -> None:
        try:
            subprocess.run(
                ["docker", "kill", name],
                stdout=subprocess.DEVNULL,
                stderr=sys.stderr,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except Exception:
            pass

    def run_rm_force(self, name: str, timeout: float = 5.0) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "-f", name],
                stdout=subprocess.DEVNULL,
                stderr=sys.stderr,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except Exception:
            pass


def launch_claude_container(
    argv: Sequence[str] | None = None,
    env: dict[str, str] | None = None,
    runner: Any | None = None,
) -> int:
    """Validate environment and authorization, create and start the gated container once."""
    if os.name == "nt":
        print("BLOCKED: Path B launcher is not supported on Windows (os.name == 'nt')", file=sys.stderr)
        return 78

    current_env = dict(os.environ) if env is None else env

    for key in FORBIDDEN_ENV_KEYS:
        if key in current_env:
            print(f"BLOCKED: forbidden environment variable present: {key}", file=sys.stderr)
            return 78

    state_dir = current_env.get("RELAY_CLAUDE_STATE_DIR")
    approval_sha = current_env.get("RELAY_CLAUDE_APPROVAL_SHA256")
    entrypoint_path = current_env.get("RELAY_CLAUDE_ENTRYPOINT_HOST_PATH")
    seccomp_path = current_env.get("RELAY_CLAUDE_SECCOMP_HOST_PATH")

    if not state_dir or not approval_sha or not entrypoint_path or not seccomp_path:
        print("BLOCKED: missing required environment variable(s)", file=sys.stderr)
        return 78

    try:
        auth = LiveAuthorization(state_dir=state_dir, approval_sha256=approval_sha)
        dispatch_id = verify_claude_live_authorization(auth, "anthropic")
    except ValueError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 78

    adapter_argv = list(sys.argv[1:] if argv is None else argv)
    is_probe = (tuple(adapter_argv) == AUTH_PROBE_ARGV)

    if is_probe:
        probe_uuid = uuid.uuid5(uuid.NAMESPACE_URL, "phase0-claude-auth-probe:" + dispatch_id)
        effective_dispatch_id = str(probe_uuid)
    else:
        effective_dispatch_id = dispatch_id

    try:
        create_argv = build_docker_create_argv(
            effective_dispatch_id,
            adapter_argv,
            entrypoint_host_path=entrypoint_path,
            seccomp_host_path=seccomp_path,
        )
        start_argv = build_docker_start_argv(effective_dispatch_id)
        c_name = container_name(effective_dispatch_id)
    except ValueError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 78

    active_runner = LauncherRunner() if runner is None else runner

    res = active_runner.run_create(create_argv)
    returncode = getattr(res, "returncode", 1)
    if returncode != 0:
        return 1

    start_proc: Any = None
    killed_code: int | None = None
    rm_done = False

    def _cleanup_probe() -> None:
        nonlocal rm_done
        if is_probe and not rm_done:
            rm_done = True
            active_runner.run_rm_force(c_name, timeout=5.0)

    def _sig_handler(signum: int, _frame: Any) -> None:
        nonlocal killed_code
        if killed_code is not None:
            return
        killed_code = 143 if signum == signal.SIGTERM else 130
        active_runner.run_kill(c_name, timeout=5.0)
        if start_proc is not None:
            try:
                if hasattr(start_proc, "wait"):
                    start_proc.wait(timeout=5.0)
            except Exception:
                pass
        _cleanup_probe()
        sys.exit(killed_code)

    old_term = None
    old_int = None
    try:
        if hasattr(signal, "SIGTERM"):
            old_term = signal.signal(signal.SIGTERM, _sig_handler)
        if hasattr(signal, "SIGINT"):
            old_int = signal.signal(signal.SIGINT, _sig_handler)
    except (ValueError, OSError):
        pass

    try:
        start_proc = active_runner.start_process(start_argv)
        if hasattr(start_proc, "wait"):
            exit_code = start_proc.wait()
        else:
            exit_code = getattr(start_proc, "returncode", 0)
    finally:
        if old_term is not None:
            signal.signal(signal.SIGTERM, old_term)
        if old_int is not None:
            signal.signal(signal.SIGINT, old_int)
        _cleanup_probe()

    return exit_code


def _main() -> None:
    code = launch_claude_container()
    sys.exit(code)


if __name__ == "__main__":
    _main()
