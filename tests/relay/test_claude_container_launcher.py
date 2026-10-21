"""Unit tests for the Path B host-side launcher (src/relay/claude_container_launcher.py)."""

import contextlib
import io
import subprocess
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from relay import claude_live_state as st
from relay import m9_live_state as m9
from relay.claude_container_argv import AUTH_PROBE_ARGV
from relay.claude_container_docker import container_name
from relay.claude_container_launcher import (
    FORBIDDEN_ENV_KEYS,
    LauncherRunner,
    launch_claude_container,
)

OBSERVED = [
    "--output-format", "stream-json", "--verbose", "--input-format", "stream-json",
    "--permission-prompt-tool", "stdio", "--disallowedTools", "AskUserQuestion", "--tools", "default",
    "--setting-sources=user,project,local", "--permission-mode", "default", "--include-partial-messages",
    "--session-id=3d01e114-c91d-423f-b792-13e2c2242c3f", "--replay-user-messages", "",
]
ENTRYPOINT = "/home/yuuki/phase0-runs/path-b/claude_adapter_entrypoint.mjs"
SECCOMP = "/home/yuuki/work/multi-ai-council-phase0/automation/command_bus/docker/claude-runtime/claude-bwrap-seccomp-amd64.json"


class MockProcess:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode


class FakeRunner:
    def __init__(self, create_returncode: int = 0, start_returncode: int = 0):
        self.create_returncode = create_returncode
        self.start_returncode = start_returncode
        self.create_calls: list[list[str]] = []
        self.start_calls: list[list[str]] = []
        self.kill_calls: list[str] = []
        self.rm_calls: list[str] = []

    def run_create(self, argv: list[str]):
        self.create_calls.append(argv)
        return MockProcess(self.create_returncode)

    def start_process(self, argv: list[str]):
        self.start_calls.append(argv)
        return MockProcess(self.start_returncode)

    def run_kill(self, name: str, timeout: float = 5.0) -> None:
        self.kill_calls.append(name)

    def run_rm_force(self, name: str, timeout: float = 5.0) -> None:
        self.rm_calls.append(name)


class TestClaudeContainerLauncher(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="claude_launcher_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dispatch_id = str(uuid.uuid4()).lower()

        approval = st.build_approval(self.dispatch_id)
        (self.tmp / st.APPROVAL_FILE).write_text(m9.canonical_json(approval), encoding="utf-8")
        m9.write_exclusive(self.tmp / st.CONSUMED_FILE, {"approval_sha256": approval["approval_sha256"]})

        self.valid_env = {
            "RELAY_CLAUDE_STATE_DIR": str(self.tmp),
            "RELAY_CLAUDE_APPROVAL_SHA256": approval["approval_sha256"],
            "RELAY_CLAUDE_ENTRYPOINT_HOST_PATH": ENTRYPOINT,
            "RELAY_CLAUDE_SECCOMP_HOST_PATH": SECCOMP,
        }

    def test_missing_environment_variables_exit_78(self):
        for key in ("RELAY_CLAUDE_STATE_DIR", "RELAY_CLAUDE_APPROVAL_SHA256", "RELAY_CLAUDE_ENTRYPOINT_HOST_PATH", "RELAY_CLAUDE_SECCOMP_HOST_PATH"):
            env = dict(self.valid_env)
            del env[key]
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = launch_claude_container(argv=OBSERVED, env=env)
            self.assertEqual(code, 78)
            self.assertIn("BLOCKED: missing required environment variable(s)", err.getvalue())

    def test_invalid_authorization_exit_78(self):
        env = dict(self.valid_env)
        env["RELAY_CLAUDE_APPROVAL_SHA256"] = "0" * 64
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = launch_claude_container(argv=OBSERVED, env=env)
        self.assertEqual(code, 78)
        self.assertIn("BLOCKED:", err.getvalue())

    def test_forbidden_environment_variables_exit_78(self):
        for key in FORBIDDEN_ENV_KEYS:
            env = {**self.valid_env, key: "secret"}
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = launch_claude_container(argv=OBSERVED, env=env)
            self.assertEqual(code, 78)
            self.assertIn(f"forbidden environment variable present: {key}", err.getvalue())

    def test_refuses_on_windows(self):
        with patch("os.name", "nt"):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = launch_claude_container(argv=OBSERVED, env=self.valid_env)
            self.assertEqual(code, 78)
            self.assertIn("not supported on Windows", err.getvalue())

    def test_successful_session_run_kept_for_evidence(self):
        runner = FakeRunner()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = launch_claude_container(argv=OBSERVED, env=self.valid_env, runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "")  # Container ID must never reach launcher's stdout
        self.assertEqual(len(runner.create_calls), 1)
        self.assertEqual(len(runner.start_calls), 1)
        expected_name = container_name(self.dispatch_id)
        self.assertIn(expected_name, runner.create_calls[0])
        self.assertIn(expected_name, runner.start_calls[0])
        self.assertEqual(runner.rm_calls, [])  # Session container is NOT removed

    def test_auth_probe_run_cleaned_up_with_derived_id(self):
        runner = FakeRunner()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = launch_claude_container(argv=list(AUTH_PROBE_ARGV), env=self.valid_env, runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(len(runner.create_calls), 1)
        self.assertEqual(len(runner.start_calls), 1)
        self.assertEqual(len(runner.rm_calls), 1)

        probe_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, "phase0-claude-auth-probe:" + self.dispatch_id))
        probe_name = container_name(probe_uuid)
        self.assertIn(probe_name, runner.create_calls[0])
        self.assertIn(probe_name, runner.start_calls[0])
        self.assertEqual(runner.rm_calls[0], probe_name)

    def test_docker_create_failure_exits_1_without_start(self):
        runner = FakeRunner(create_returncode=1)
        code = launch_claude_container(argv=OBSERVED, env=self.valid_env, runner=runner)
        self.assertEqual(code, 1)
        self.assertEqual(len(runner.create_calls), 1)
        self.assertEqual(len(runner.start_calls), 0)

    def test_never_runs_second_create_or_start(self):
        runner = FakeRunner()
        launch_claude_container(argv=OBSERVED, env=self.valid_env, runner=runner)
        self.assertEqual(len(runner.create_calls), 1)
        self.assertEqual(len(runner.start_calls), 1)

    def test_default_launcher_runner_methods(self):
        runner = LauncherRunner()
        with patch("subprocess.run") as mock_run:
            runner.run_kill("test-container")
            mock_run.assert_called_once_with(
                ["docker", "kill", "test-container"],
                stdout=subprocess.DEVNULL, stderr=unittest.mock.ANY, shell=False, timeout=5.0, check=False,
            )
        with patch("subprocess.run") as mock_run:
            runner.run_rm_force("test-container")
            mock_run.assert_called_once_with(
                ["docker", "rm", "-f", "test-container"],
                stdout=subprocess.DEVNULL, stderr=unittest.mock.ANY, shell=False, timeout=5.0, check=False,
            )


if __name__ == "__main__":
    unittest.main()
