"""Path B (STATIC, pure functions): the exact ``docker`` arguments for the gated Claude container.

Builds argument lists only. This module starts nothing: no process, no Docker, no network, no account read, and it does
not import ``subprocess``. A human on the PC reviews the printed lists (``--dry-run``) before anything is ever run.

Names and values come from the human's PC (WSL, read-only measurements of 2026-10-14) and from the proven Path A
configuration (repo commit 751a694): image ``phase0-claude-runtime:2.1.283``, internal-only network
``command_bus_internal``, auth volume ``command_bus_claude-auth``, user 1000:1000, the ``claude`` service environment
(``fixtures/relay/claude_runtime_env_proven_751a694.json``). The proxy variant on current ``main`` is not used.

Preconditions the caller must satisfy outside this module (Path A runbook R1/R3): the Gate is running
(``OPEN_EXISTING_ONLY``, reachable as ``gate:8080`` on that network) and this dispatch id is registered in it.
``--rm`` is deliberately absent: the container is kept for evidence, like in Path A.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence

from relay.claude_container_argv import prepare_container_claude_argv

__all__ = [
    "RUNTIME_IMAGE",
    "NETWORK",
    "AUTH_VOLUME",
    "RUNTIME_ENV",
    "build_docker_create_argv",
    "build_docker_start_argv",
    "container_name",
]

RUNTIME_IMAGE = "phase0-claude-runtime:2.1.283"
NETWORK = "command_bus_internal"  # internal-only: no route out except through the Gate
AUTH_VOLUME = "command_bus_claude-auth"
ENTRYPOINT_IN_CONTAINER = "/opt/phase0/claude_adapter_entrypoint.mjs"
SECCOMP_IN_COMPOSE = "claude-bwrap-seccomp-amd64.json"

# Environment of the proven ``claude`` compose service (verbatim; no proxy variables).
RUNTIME_ENV = {
    "ANTHROPIC_BASE_URL": "http://gate:8080",
    "PHASE0_TRANSPORT_MODE": "CONTAINER_INTERNAL",
    "CLAUDE_CODE_MAX_RETRIES": "0",
    "CLAUDE_CODE_MAX_TURNS": "1",
    "CLAUDE_CONFIG_DIR": "/home/node/.claude",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
    "CLAUDE_CODE_RESUME_INTERRUPTED_TURN": "0",
    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
    "CLAUDE_CODE_DISABLE_AGENT_VIEW": "1",
    "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",
    "CLAUDE_CODE_DISABLE_FAST_MODE": "1",
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1",
    "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_UPDATES": "1",
}

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
# Host paths are mounted with --mount key=value pairs: refuse anything that could add a key or an option.
_SAFE_ABS_PATH = re.compile(r"^/[A-Za-z0-9._@+/-]+$")


def _dispatch_id(value: object) -> str:
    if not isinstance(value, str) or not _UUID.match(value.lower()):
        raise ValueError("dispatch id must be a UUID")
    return value.lower()


def _host_path(value: object, what: str, *, suffix: str) -> str:
    if not isinstance(value, str) or not _SAFE_ABS_PATH.match(value) or ".." in value.split("/"):
        raise ValueError(f"{what}: expected a plain absolute path (letters, digits, . _ @ + - /)")
    if not value.endswith(suffix):
        raise ValueError(f"{what}: unexpected file name (expected a path ending in {suffix})")
    return value


def container_name(dispatch_id: str) -> str:
    return f"phase0-claude-acp-{_dispatch_id(dispatch_id)}"


def build_docker_create_argv(
    dispatch_id: str,
    adapter_argv: Sequence[str],
    *,
    entrypoint_host_path: str,
    seccomp_host_path: str,
) -> list[str]:
    """``docker create`` arguments for one named, not-yet-started container, or ``ValueError`` (nothing is run).

    ``adapter_argv`` is what the official adapter would pass to the Claude CLI. It is checked on the host with
    ``prepare_container_claude_argv`` and handed unchanged to the container entrypoint, which filters it again.
    """
    dispatch = _dispatch_id(dispatch_id)
    prepare_container_claude_argv(adapter_argv)  # raises ValueError for any shape that is not exactly expected
    entrypoint = _host_path(entrypoint_host_path, "entrypoint", suffix="/claude_adapter_entrypoint.mjs")
    seccomp = _host_path(seccomp_host_path, "seccomp profile", suffix=f"/{SECCOMP_IN_COMPOSE}")

    argv = [
        "docker", "create",
        "--interactive",
        "--name", container_name(dispatch),
        "--pull", "never",
        "--restart", "no",
        "--user", "1000:1000",
        "--network", NETWORK,
        "--security-opt", f"seccomp={seccomp}",
        "--volume", f"{AUTH_VOLUME}:/home/node/.claude",
        "--mount", f"type=bind,source={entrypoint},target={ENTRYPOINT_IN_CONTAINER},readonly",
    ]
    for name, value in RUNTIME_ENV.items():
        argv += ["--env", f"{name}={value}"]
    argv += ["--env", "PHASE0_LIVE_EXECUTION=1", "--env", f"PHASE0_DISPATCH_ID={dispatch}"]
    argv += ["--entrypoint", "node", RUNTIME_IMAGE, ENTRYPOINT_IN_CONTAINER, *adapter_argv]
    return argv


def build_docker_start_argv(dispatch_id: str) -> list[str]:
    """Attach stdin/stdout to the created container and start it once (the adapter's stdio goes through this)."""
    return ["docker", "start", "--attach", "--interactive", container_name(dispatch_id)]


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the docker arguments for review. Never runs anything.")
    parser.add_argument("--dry-run", action="store_true", required=True, help="required: this tool only prints")
    parser.add_argument("--dispatch-id", required=True)
    parser.add_argument("--entrypoint-host-path", required=True)
    parser.add_argument("--seccomp-host-path", required=True)
    parser.add_argument("--adapter-argv-json", required=True, help="JSON list of the CLI arguments the adapter passes")
    args = parser.parse_args(argv)
    try:
        adapter_argv = json.loads(args.adapter_argv_json)
        create = build_docker_create_argv(
            args.dispatch_id,
            adapter_argv,
            entrypoint_host_path=args.entrypoint_host_path,
            seccomp_host_path=args.seccomp_host_path,
        )
        start = build_docker_start_argv(args.dispatch_id)
    except (ValueError, TypeError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 78
    print(json.dumps({"create": create, "start": start, "executed": False}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
