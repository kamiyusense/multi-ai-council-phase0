"""Small stdlib-only ACP subprocess transport.

Behavior reference: agentclientprotocol/python-sdk
commit 9d07d7871ef4b220b8507e15fc4b1560f0950a64,
src/acp/transports.py (Apache-2.0).

This is an independent minimal implementation for the Phase 0 Relay seam.
It intentionally contains no retry, relaunch, fallback, or ACP protocol logic.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from pathlib import Path

__all__ = ["default_environment", "spawn_stdio_transport"]

_ENV_KEYS = (
    (
        "APPDATA",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "USERPROFILE",
    )
    if os.name == "nt"
    else ("HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER")
)


def default_environment() -> dict[str, str]:
    """Return only the small inherited environment needed to launch a child."""
    return {key: os.environ[key] for key in _ENV_KEYS if key in os.environ}


async def _shutdown(process: asyncio.subprocess.Process, timeout: float) -> None:
    writer = process.stdin
    if writer is not None:
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()

    try:
        await asyncio.wait_for(process.wait(), timeout)
        return
    except asyncio.TimeoutError:
        process.terminate()

    try:
        await asyncio.wait_for(process.wait(), timeout)
        return
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


@asynccontextmanager
async def spawn_stdio_transport(
    command: str,
    *args: str,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    shutdown_timeout: float = 2.0,
) -> AsyncIterator[
    tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.subprocess.Process]
]:
    """Spawn exactly one child and expose its stdout/stdin/process tuple."""
    if shutdown_timeout <= 0:
        raise ValueError("shutdown_timeout must be positive")

    child_env = default_environment()
    if env:
        child_env.update(env)

    process = await asyncio.create_subprocess_exec(
        command,
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=child_env,
        cwd=str(cwd) if cwd is not None else None,
    )
    if process.stdout is None or process.stdin is None:
        process.kill()
        await process.wait()
        raise RuntimeError("stdio transport requires stdin/stdout pipes")

    try:
        yield process.stdout, process.stdin, process
    finally:
        await _shutdown(process, shutdown_timeout)
