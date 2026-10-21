"""Unit tests for the Path B host-side launcher (src/relay/claude_container_launcher.py)."""

import ast
import contextlib
import io
import os
import signal
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from relay import claude_live_state as st
from relay import m9_live_state as m9
from relay.claude_container_argv import AUTH_PROBE_ARGV
from relay.claude_container_docker import (
    build_docker_create_argv,
    build_docker_start_argv,
    container_name,
)
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

    # Finding 4: Assert zero runner calls for missing env / forbidden env / Windows / invalid approval state / rejected argv
    def test_missing_environment_variables_exit_78_and_zero_runner_calls(self):
        for key in ("RELAY_CLAUDE_STATE_DIR", "RELAY_CLAUDE_APPROVAL_SHA256", "RELAY_CLAUDE_ENTRYPOINT_HOST_PATH", "RELAY_CLAUDE_SECCOMP_HOST_PATH"):
            env = dict(self.valid_env)
            del env[key]
            runner = FakeRunner()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = launch_claude_container(argv=OBSERVED, env=env, runner=runner)
            self.assertEqual(code, 78)
            self.assertIn("BLOCKED: missing required environment variable(s)", err.getvalue())
            self.assertEqual(runner.create_calls, [])
            self.assertEqual(runner.start_calls, [])

    def test_forbidden_environment_variables_exit_78_and_zero_runner_calls(self):
        for key in FORBIDDEN_ENV_KEYS:
            env = {**self.valid_env, key: "secret"}
            runner = FakeRunner()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = launch_claude_container(argv=OBSERVED, env=env, runner=runner)
            self.assertEqual(code, 78)
            self.assertIn(f"forbidden environment variable present: {key}", err.getvalue())
            self.assertEqual(runner.create_calls, [])
            self.assertEqual(runner.start_calls, [])

    def test_refuses_on_windows_and_zero_runner_calls(self):
        with patch("os.name", "nt"):
            runner = FakeRunner()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = launch_claude_container(argv=OBSERVED, env=self.valid_env, runner=runner)
            self.assertEqual(code, 78)
            self.assertIn("not supported on Windows", err.getvalue())
            self.assertEqual(runner.create_calls, [])
            self.assertEqual(runner.start_calls, [])

    def test_approval_state_failures_exit_78_and_zero_runner_calls(self):
        # 1. Wrong approval sha256
        env_wrong_sha = dict(self.valid_env)
        env_wrong_sha["RELAY_CLAUDE_APPROVAL_SHA256"] = "0" * 64
        runner = FakeRunner()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = launch_claude_container(argv=OBSERVED, env=env_wrong_sha, runner=runner)
        self.assertEqual(code, 78)
        self.assertEqual(runner.create_calls, [])
        self.assertEqual(runner.start_calls, [])

        # 2. Approval missing
        tmp_empty = Path(tempfile.mkdtemp(prefix="claude_launcher_empty_"))
        self.addCleanup(shutil.rmtree, tmp_empty, True)
        env_missing_approval = {**self.valid_env, "RELAY_CLAUDE_STATE_DIR": str(tmp_empty)}
        runner = FakeRunner()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = launch_claude_container(argv=OBSERVED, env=env_missing_approval, runner=runner)
        self.assertEqual(code, 78)
        self.assertEqual(runner.create_calls, [])
        self.assertEqual(runner.start_calls, [])

        # 3. Consumed file missing
        tmp_unconsumed = Path(tempfile.mkdtemp(prefix="claude_launcher_unconsumed_"))
        self.addCleanup(shutil.rmtree, tmp_unconsumed, True)
        approval_u = st.build_approval(self.dispatch_id)
        (tmp_unconsumed / st.APPROVAL_FILE).write_text(m9.canonical_json(approval_u), encoding="utf-8")
        env_unconsumed = {
            **self.valid_env,
            "RELAY_CLAUDE_STATE_DIR": str(tmp_unconsumed),
            "RELAY_CLAUDE_APPROVAL_SHA256": approval_u["approval_sha256"],
        }
        runner = FakeRunner()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = launch_claude_container(argv=OBSERVED, env=env_unconsumed, runner=runner)
        self.assertEqual(code, 78)
        self.assertEqual(runner.create_calls, [])
        self.assertEqual(runner.start_calls, [])

        # 4. Terminal receipt present
        (self.tmp / st.TERMINAL_FILE).write_text(m9.canonical_json({"state": "DONE"}), encoding="utf-8")
        runner = FakeRunner()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = launch_claude_container(argv=OBSERVED, env=self.valid_env, runner=runner)
        self.assertEqual(code, 78)
        self.assertEqual(runner.create_calls, [])
        self.assertEqual(runner.start_calls, [])

    def test_rejected_argv_exit_78_and_zero_runner_calls(self):
        bad_argvs = [
            ["--dangerously-skip-permissions"],
            [*OBSERVED[:-1], "--dangerously-skip-permissions", ""],
            ["-p", "hello"],
            [],
        ]
        for bad_argv in bad_argvs:
            runner = FakeRunner()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = launch_claude_container(argv=bad_argv, env=self.valid_env, runner=runner)
            self.assertEqual(code, 78)
            self.assertEqual(runner.create_calls, [])
            self.assertEqual(runner.start_calls, [])

    # Finding 5: Assert exact argv builders match and non-zero exit code returned unchanged
    def test_successful_session_run_exact_argv_and_nonzero_exit_code(self):
        runner = FakeRunner(start_returncode=42)
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = launch_claude_container(argv=OBSERVED, env=self.valid_env, runner=runner)
        self.assertEqual(code, 42)
        self.assertEqual(stdout.getvalue(), "")  # Container ID must never reach launcher's stdout
        self.assertEqual(len(runner.create_calls), 1)
        self.assertEqual(len(runner.start_calls), 1)

        expected_create = build_docker_create_argv(
            self.dispatch_id,
            OBSERVED,
            entrypoint_host_path=ENTRYPOINT,
            seccomp_host_path=SECCOMP,
        )
        expected_start = build_docker_start_argv(self.dispatch_id)

        self.assertEqual(runner.create_calls[0], expected_create)
        self.assertEqual(runner.start_calls[0], expected_start)
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
        self.assertEqual(runner.create_calls[0], build_docker_create_argv(
            probe_uuid, list(AUTH_PROBE_ARGV), entrypoint_host_path=ENTRYPOINT, seccomp_host_path=SECCOMP
        ))
        self.assertEqual(runner.start_calls[0], build_docker_start_argv(probe_uuid))
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

    # Finding 1 Regression Test: Script execution without PYTHONPATH and missing approval exits 78 with zero docker calls
    @unittest.skipIf(os.name == "nt", "POSIX test with fake docker executable on PATH")
    def test_finding1_script_execution_without_pythonpath(self):
        fake_bin_dir = Path(tempfile.mkdtemp(prefix="fake_docker_bin_"))
        self.addCleanup(shutil.rmtree, fake_bin_dir, True)
        docker_log = fake_bin_dir / "docker.log"
        fake_docker = fake_bin_dir / "docker"
        fake_docker.write_text(f"""#!/bin/sh
echo "$@" >> "{docker_log}"
exit 0
""", encoding="utf-8")
        fake_docker.chmod(0o755)

        script_path = Path(__file__).resolve().parents[2] / "src" / "relay" / "claude_container_launcher.py"
        new_env = dict(os.environ)
        new_env["PATH"] = f"{fake_bin_dir}:{new_env.get('PATH', '')}"
        new_env.pop("PYTHONPATH", None)

        # Run with empty environment / missing approval variables
        res = subprocess.run(
            [sys.executable, str(script_path), *OBSERVED],
            env=new_env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 78)
        self.assertFalse(docker_log.exists(), "No docker call should have happened")

    # Finding 2 Regression Test: stdio passthrough with fake docker on PATH
    @unittest.skipIf(os.name == "nt", "POSIX stdio passthrough test with fake docker")
    def test_finding2_stdio_passthrough_with_fake_docker(self):
        fake_bin_dir = Path(tempfile.mkdtemp(prefix="fake_docker_bin_"))
        self.addCleanup(shutil.rmtree, fake_bin_dir, True)
        docker_log = fake_bin_dir / "docker.log"
        fake_docker = fake_bin_dir / "docker"
        # fake docker:
        # if 'create', output dummy container id to stdout
        # if 'start', read stdin and copy to stdout, exit with 15
        fake_docker.write_text(f"""#!/bin/sh
echo "$@" >> "{docker_log}"
if [ "$1" = "create" ]; then
    echo "dummy-container-id-12345"
    exit 0
elif [ "$1" = "start" ]; then
    cat
    exit 15
fi
exit 0
""", encoding="utf-8")
        fake_docker.chmod(0o755)

        script_path = Path(__file__).resolve().parents[2] / "src" / "relay" / "claude_container_launcher.py"
        new_env = {**self.valid_env, **os.environ}
        new_env["PATH"] = f"{fake_bin_dir}:{os.environ.get('PATH', '')}"

        input_bytes = b"hello stream-json stdin passthrough\n"
        res = subprocess.run(
            [sys.executable, str(script_path), *OBSERVED],
            input=input_bytes,
            env=new_env,
            capture_output=True,
            check=False,
        )
        self.assertEqual(res.returncode, 15)
        self.assertEqual(res.stdout, input_bytes)
        self.assertNotIn(b"dummy-container-id-12345", res.stdout)

    # Finding 3 Regression Test: SIGTERM / SIGINT signal handling with blocking start
    @unittest.skipIf(os.name == "nt", "POSIX signal handling test with fake docker")
    def test_finding3_sigterm_handling(self):
        fake_bin_dir = Path(tempfile.mkdtemp(prefix="fake_docker_bin_"))
        self.addCleanup(shutil.rmtree, fake_bin_dir, True)
        docker_log = fake_bin_dir / "docker.log"
        start_pid_file = fake_bin_dir / "start.pid"
        fake_docker = fake_bin_dir / "docker"
        sleep_bin = shutil.which("sleep") or "/bin/sleep"
        # fake docker:
        # create: echo container ID
        # start: sleep in background via exec
        # kill: terminates start process using kill -9
        fake_docker.write_text(f"""#!/bin/sh
echo "$@" >> "{docker_log}"
if [ "$1" = "create" ]; then
    echo "dummy-container-id-12345"
    exit 0
elif [ "$1" = "start" ]; then
    echo $$ > "{start_pid_file}"
    exec {sleep_bin} 30
elif [ "$1" = "kill" ]; then
    if [ -f "{start_pid_file}" ]; then
        kill -9 $(cat "{start_pid_file}") 2>/dev/null || true
    fi
    exit 0
fi
exit 0
""", encoding="utf-8")
        fake_docker.chmod(0o755)

        script_path = Path(__file__).resolve().parents[2] / "src" / "relay" / "claude_container_launcher.py"
        new_env = {**self.valid_env, **os.environ}
        new_env["PATH"] = f"{fake_bin_dir}:{os.environ.get('PATH', '')}"

        proc = subprocess.Popen(
            [sys.executable, str(script_path), *OBSERVED],
            env=new_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Wait until start call is logged and start.pid exists
        for _ in range(50):
            if start_pid_file.exists() and docker_log.exists() and "start" in docker_log.read_text(encoding="utf-8"):
                break
            time.sleep(0.1)

        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 143)

        log_lines = [line.strip() for line in docker_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        kill_lines = [line for line in log_lines if line.startswith("kill")]
        self.assertEqual(len(kill_lines), 1)
        expected_container_name = container_name(self.dispatch_id)
        self.assertIn(expected_container_name, kill_lines[0])

    # Finding 6: Static AST guard test
    def test_finding6_static_ast_subprocess_guards(self):
        source_path = Path(__file__).resolve().parents[2] / "src" / "relay" / "claude_container_launcher.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for shell=True
                for keyword in node.keywords:
                    if keyword.arg == "shell" and getattr(keyword.value, "value", None) is True:
                        self.fail("Found shell=True in claude_container_launcher.py")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name, ("os.system", "os.exec"), f"Forbidden import {alias.name}")


if __name__ == "__main__":
    unittest.main()
