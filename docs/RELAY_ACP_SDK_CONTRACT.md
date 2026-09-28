# ACP Python SDK Contract for Phase 0 Relay

Updated: 2026-09-21
Audited SDK checkpoint: `agentclientprotocol/python-sdk@9d07d7871ef4b220b8507e15fc4b1560f0950a64`
Package version: `agent-client-protocol==0.12.1`

## Confirmed API surface

The SDK exports:

```python
from acp import PROTOCOL_VERSION, spawn_agent_process
```

Pinned implementation signature:

```python
async def spawn_agent_process(
    to_client,
    command: str,
    *args: str,
    env=None,
    cwd=None,
    transport_kwargs=None,
    **connection_kwargs,
)
```

The async context manager yields:

```text
(ClientSideConnection, asyncio.subprocess.Process)
```

Canonical sequence from the pinned quickstart:

```python
async with spawn_agent_process(client, command, *args, env=env, cwd=cwd) as (conn, process):
    await conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities=...)
    session = await conn.new_session(cwd=workspace, mcp_servers=[])
    await conn.prompt(session_id=session.session_id, prompt=[...])
```

The context manager manages child-process stdio and closes the ACP connection on exit.

## Windows

The pinned SDK has an explicit Windows stdio implementation using a background stdin feeder and custom stdout transport. This reduces the need for Phase 0 to write its own Windows stdio framing layer.

This is source-level support evidence only. It is not a claim that the final three-provider Relay has been exercised on the user's Windows machine.

## Phase 0 client policy

A future Phase 0 ACP Client implementation must not silently approve provider requests.

Before live, it must implement explicit handlers for:

- permission requests
- file read/write requests
- terminal requests
- elicitation/user input
- session update capture
- extension methods/notifications

Unrecognized or unsupported capabilities must fail closed or surface UNKNOWN according to Core policy.

## Static branch rule

The current Relay skeleton does not call `spawn_agent_process` and therefore cannot start a provider process.

The first code that can invoke `spawn_agent_process` must remain behind:

1. static tests;
2. dependency/version pin verification;
3. provider command allowlist;
4. auth-route gate;
5. retry/fallback proof;
6. timeout and abort policy;
7. explicit live-provider approval.

## Why this replaces self-built plumbing

The SDK already owns:

- ACP protocol models
- JSON-RPC framing
- stdio transport
- child-process lifecycle
- connection close
- Windows stdio differences

Phase 0 should therefore own only the thin safety/evidence wrapper and provider policy.
