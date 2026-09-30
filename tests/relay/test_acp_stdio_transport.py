import asyncio
import os
import sys
import unittest
import contextlib
from pathlib import Path
from tempfile import TemporaryDirectory

from relay.acp_stdio_transport import spawn_stdio_transport, default_environment


class TestACPStdioTransport(unittest.IsolatedAsyncioTestCase):
    async def test_child_stdio_pipes_usable(self):
        code = (
            "import sys\n"
            "for line in sys.stdin:\n"
            "    sys.stdout.write(line.upper())\n"
            "    sys.stdout.flush()\n"
        )
        async with spawn_stdio_transport(sys.executable, "-c", code) as (stdout, stdin, process):
            stdin.write(b"hello world\n")
            await stdin.drain()
            response = await stdout.readline()
            self.assertEqual(response, b"HELLO WORLD\n")

        self.assertEqual(process.returncode, 0)

    async def test_explicit_env_overlay_reaches_child(self):
        code = (
            "import os, sys\n"
            "sys.stdout.write(os.environ.get('CUSTOM_ENV_VAR', 'MISSING'))\n"
            "sys.stdout.flush()\n"
        )
        env = {"CUSTOM_ENV_VAR": "PRESENT_AND_CORRECT"}
        async with spawn_stdio_transport(sys.executable, "-c", code, env=env) as (stdout, stdin, process):
            response = await stdout.readline()
            self.assertEqual(response, b"PRESENT_AND_CORRECT")

        self.assertEqual(process.returncode, 0)

    async def test_inherited_env_is_limited(self):
        code = (
            "import os, sys\n"
            "sys.stdout.write(os.environ.get('UNSAFE_SENSITIVE_VAR', 'CLEARED'))\n"
            "sys.stdout.flush()\n"
        )
        os.environ["UNSAFE_SENSITIVE_VAR"] = "LEAKED"
        try:
            # First, check default_environment helper output
            env_out = default_environment()
            self.assertNotIn("UNSAFE_SENSITIVE_VAR", env_out)

            # Check inside child process
            async with spawn_stdio_transport(sys.executable, "-c", code) as (stdout, stdin, process):
                response = await stdout.readline()
                self.assertEqual(response, b"CLEARED")

            self.assertEqual(process.returncode, 0)
        finally:
            del os.environ["UNSAFE_SENSITIVE_VAR"]

    async def test_cwd_is_honored(self):
        code = (
            "import os, sys\n"
            "sys.stdout.write(os.getcwd())\n"
            "sys.stdout.flush()\n"
        )
        with TemporaryDirectory() as tmpdir:
            real_tmpdir = os.path.realpath(tmpdir)
            async with spawn_stdio_transport(sys.executable, "-c", code, cwd=tmpdir) as (stdout, stdin, process):
                response = await stdout.readline()
                self.assertEqual(response.decode().strip(), real_tmpdir)

            self.assertEqual(process.returncode, 0)

    async def test_graceful_child_exit_via_eof(self):
        code = (
            "import sys\n"
            "data = sys.stdin.read()\n"
            "sys.exit(0 if data == 'EOF_SEEN' else 1)\n"
        )
        async with spawn_stdio_transport(sys.executable, "-c", code) as (stdout, stdin, process):
            stdin.write(b"EOF_SEEN")
            await stdin.drain()
            # Stdin will be closed on exit gracefully

        self.assertEqual(process.returncode, 0)

    async def test_fallback_termination_on_stubborn_process(self):
        code = (
            "import sys, time\n"
            "try:\n"
            "    sys.stdin.read()\n"
            "except KeyboardInterrupt:\n"
            "    pass\n"
            "while True:\n"
            "    time.sleep(1)\n"
        )
        async with spawn_stdio_transport(sys.executable, "-c", code, shutdown_timeout=0.1) as (stdout, stdin, process):
            pass

        # Depending on platform, the process will either be terminated or killed
        self.assertNotEqual(process.returncode, 0)

    async def test_fallback_kill_on_extremely_stubborn_process(self):
        # A process that traps SIGTERM as well as SIGINT
        code = (
            "import sys, time, signal\n"
            "def handler(signum, frame): pass\n"
            "signal.signal(signal.SIGTERM, handler)\n"
            "signal.signal(signal.SIGINT, handler)\n"
            "while True:\n"
            "    time.sleep(0.1)\n"
        )
        async with spawn_stdio_transport(sys.executable, "-c", code, shutdown_timeout=0.2) as (stdout, stdin, process):
            pass

        self.assertNotEqual(process.returncode, 0)
        self.assertNotEqual(process.returncode, None) # Ensure it has actually died

    async def test_invalid_missing_stdio_fails(self):
        import unittest.mock as mock

        # Mock asyncio.create_subprocess_exec to return a mock process without stdout
        mock_process = mock.Mock() # Using regular Mock since kill() is not async in Process
        mock_process.stdout = None
        mock_process.stdin = None
        mock_process.wait = mock.AsyncMock() # wait() IS async

        # We need an AsyncMock for the return value of create_subprocess_exec
        mock_create = mock.AsyncMock(return_value=mock_process)

        with mock.patch('asyncio.create_subprocess_exec', new=mock_create):
            with self.assertRaisesRegex(RuntimeError, "spawn_stdio_transport requires stdout/stderr pipes"):
                async with spawn_stdio_transport(sys.executable, "-c", "pass", limit=1) as (stdout, stdin, process):
                    pass

        mock_process.kill.assert_called_once()
        mock_process.wait.assert_awaited_once()


    async def test_invalid_command_fails(self):
        with self.assertRaises(FileNotFoundError):
            async with spawn_stdio_transport("invalid_nonexistent_command_12345") as (stdout, stdin, process):
                pass
