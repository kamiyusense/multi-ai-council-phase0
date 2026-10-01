import asyncio
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from relay.acp_stdio_transport import default_environment, spawn_stdio_transport


class TestACPStdioTransport(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_env_and_cwd(self):
        code = (
            "import os,sys\n"
            "line=sys.stdin.readline().strip()\n"
            "sys.stdout.write('|'.join([line.upper(), os.environ['PHASE0_TEST'], os.getcwd()]))\n"
            "sys.stdout.flush()\n"
        )
        with TemporaryDirectory() as tmpdir:
            async with spawn_stdio_transport(
                sys.executable,
                "-c",
                code,
                env={"PHASE0_TEST": "overlay"},
                cwd=tmpdir,
            ) as (stdout, stdin, process):
                stdin.write(b"hello\n")
                await stdin.drain()
                parts = (await stdout.read()).decode().split("|")
            self.assertEqual(parts[0], "HELLO")
            self.assertEqual(parts[1], "overlay")
            self.assertEqual(Path(parts[2]).resolve(), Path(tmpdir).resolve())
            self.assertEqual(process.returncode, 0)

    async def test_environment_is_trimmed(self):
        os.environ["PHASE0_SHOULD_NOT_LEAK"] = "secret"
        try:
            self.assertNotIn("PHASE0_SHOULD_NOT_LEAK", default_environment())
            code = (
                "import os,sys\n"
                "sys.stdout.write(os.environ.get('PHASE0_SHOULD_NOT_LEAK','absent'))\n"
                "sys.stdout.flush()\n"
            )
            async with spawn_stdio_transport(sys.executable, "-c", code) as (stdout, _, process):
                result = await stdout.read()
            self.assertEqual(result, b"absent")
            self.assertEqual(process.returncode, 0)
        finally:
            del os.environ["PHASE0_SHOULD_NOT_LEAK"]

    async def test_graceful_eof_shutdown(self):
        code = "import sys; sys.exit(0 if sys.stdin.read() == 'done' else 2)"
        async with spawn_stdio_transport(sys.executable, "-c", code) as (_, stdin, process):
            stdin.write(b"done")
            await stdin.drain()
        self.assertEqual(process.returncode, 0)

    async def test_cleanup_escalates_without_relaunch(self):
        process = mock.Mock()
        process.stdout = object()
        process.stdin = mock.Mock()
        process.stdin.wait_closed = mock.AsyncMock()
        process.wait = mock.AsyncMock(
            side_effect=[asyncio.TimeoutError(), asyncio.TimeoutError(), -9]
        )
        process.terminate = mock.Mock()
        process.kill = mock.Mock()

        create = mock.AsyncMock(return_value=process)
        with mock.patch("asyncio.create_subprocess_exec", new=create):
            async with spawn_stdio_transport("fake-agent", shutdown_timeout=0.01):
                pass

        create.assert_awaited_once()
        process.stdin.close.assert_called_once()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.await_count, 3)

    async def test_missing_stdio_fails_closed(self):
        process = mock.Mock()
        process.stdout = None
        process.stdin = None
        process.kill = mock.Mock()
        process.wait = mock.AsyncMock(return_value=-9)
        create = mock.AsyncMock(return_value=process)

        with mock.patch("asyncio.create_subprocess_exec", new=create):
            with self.assertRaisesRegex(RuntimeError, "stdin/stdout pipes"):
                async with spawn_stdio_transport("fake-agent"):
                    pass

        create.assert_awaited_once()
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()

    async def test_invalid_command_is_not_retried(self):
        create = mock.AsyncMock(side_effect=FileNotFoundError("missing"))
        with mock.patch("asyncio.create_subprocess_exec", new=create):
            with self.assertRaises(FileNotFoundError):
                async with spawn_stdio_transport("missing-agent"):
                    pass
        create.assert_awaited_once()

    async def test_shutdown_timeout_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            async with spawn_stdio_transport(sys.executable, shutdown_timeout=0):
                pass


if __name__ == "__main__":
    unittest.main()
