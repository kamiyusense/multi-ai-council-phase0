"""Path B (STATIC, pure function): the CLI arguments the official Claude adapter may pass into the gated container.

The official ``claude-agent-acp`` starts the Claude CLI in an interactive stream-json mode. The proven Gate runtime
launcher only accepts one prompt in ``-p`` mode, so a Path B launcher must take the adapter's argv, accept only the
exact shape recorded below, and force the Phase 0 hardening flags. Anything else is refused (fail closed).

Observed argv (claude-agent-acp 0.85.1 with a tripwire CLI, ``tests/relay/test_claude_acp_static_boundary.py``):
``--output-format stream-json --verbose --input-format stream-json --permission-prompt-tool stdio
--disallowedTools AskUserQuestion --tools default --setting-sources=user,project,local --permission-mode default
--include-partial-messages --session-id=<uuid> --replay-user-messages ""``. The adapter also runs the exact probe
``auth status --json`` once before the session.

This module starts nothing: no process, no Docker, no network, no account read.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

__all__ = ["prepare_container_claude_argv", "AUTH_PROBE_ARGV"]

AUTH_PROBE_ARGV = ("auth", "status", "--json")

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.IGNORECASE)
_FLAGS_NO_VALUE = frozenset({"--verbose", "--include-partial-messages", "--replay-user-messages"})
_FLAGS_FIXED_VALUE = {
    "--output-format": "stream-json",
    "--input-format": "stream-json",
    "--permission-prompt-tool": "stdio",
    "--disallowedTools": "AskUserQuestion",
    "--permission-mode": "default",
}
_TOOLS_FLAG = "--tools"  # adapter value "default" enables every built-in tool; it is replaced, never forwarded
_FIXED_JOINED = frozenset({"--setting-sources=user,project,local"})
_JOINED_UUID_PREFIX = "--session-id="
# Forced Phase 0 hardening (same values as the proven runtime launcher's contract).
_FORCED = (
    "--safe-mode",
    "--max-turns", "1",
    "--tools", "",
    "--mcp-config", json.dumps({"mcpServers": {}}),
    "--strict-mcp-config",
)


def prepare_container_claude_argv(argv: Sequence[str]) -> list[str]:
    """Return the argv to run in the container, or raise ``ValueError`` (nothing is started either way)."""
    if not isinstance(argv, (list, tuple)) or any(not isinstance(a, str) for a in argv):
        raise ValueError("argv must be a sequence of strings")
    items = list(argv)
    if tuple(items) == AUTH_PROBE_ARGV:
        return list(AUTH_PROBE_ARGV)  # read-only probe, answered by the CLI inside the container

    # The adapter ends with one empty string argument (no prompt text on the command line).
    if not items or items[-1] != "":
        raise ValueError("expected the adapter's trailing empty argument; refusing an unknown argv shape")
    body, out, seen, i = items[:-1], [], set(), 0
    while i < len(body):
        arg = body[i]
        if arg in _FLAGS_NO_VALUE:
            name, step = arg, 1
        elif arg in _FLAGS_FIXED_VALUE:
            if i + 1 >= len(body) or body[i + 1] != _FLAGS_FIXED_VALUE[arg]:
                raise ValueError(f"{arg}: value not allowed")
            name, step = arg, 2
        elif arg == _TOOLS_FLAG:
            if i + 1 >= len(body) or body[i + 1] != "default":
                raise ValueError("--tools: only the adapter default is expected (it is replaced)")
            name, step = arg, 2
        elif arg in _FIXED_JOINED:
            name, step = arg, 1
        elif arg.startswith(_JOINED_UUID_PREFIX):
            if not _UUID.match(arg[len(_JOINED_UUID_PREFIX):]):
                raise ValueError("--session-id: not a UUID")
            name, step = _JOINED_UUID_PREFIX, 1
        else:
            raise ValueError(f"argument not allowed in the gated container: {arg!r}")
        if name in seen:
            raise ValueError(f"duplicate argument: {name}")
        seen.add(name)
        if name != _TOOLS_FLAG:
            out.extend(body[i:i + step])
        i += step
    return out + list(_FORCED)
