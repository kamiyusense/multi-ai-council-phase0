"""STATIC-only RelayTransport that maps Relay lifecycle onto ACP lifecycle.

One transport = one ACP stdio child kept alive across the Relay calls:

    Relay initialize   -> spawn child + ACP ``initialize``
    Relay open_session -> ACP ``session/new``
    Relay prompt       -> ACP ``session/prompt`` (+ text updates) -> phase0 mapper
    Relay cancel       -> ACP ``session/cancel`` notification (no reply expected)
    Relay close        -> ACP ``session/close`` (if advertised), then child teardown

It reuses the existing stdlib ``spawn_stdio_transport`` and the ``_acp_*`` wire
helpers in ``acp_client``. No retry, no relaunch, no fallback; one prompt only.

Two launch modes, both STATIC:

* injected fake agent command (known official adapter names are refused; this
  name guard is fail-closed for known identities but is not a sandbox);
* ``OfficialAdapterLaunch``: an official adapter whose backend is replaced, through
  the adapter's own documented option, by the Relay one-generation gate wrapping a
  repository fixture. Only
  providers with a verified seam are accepted (openai: ``CODEX_PATH``; anthropic:
  ``CLAUDE_CODE_EXECUTABLE``, see below). Others fail closed as UNKNOWN /
  LIVE_BOUNDARY. The adapter process is started; no provider/model backend can be
  reached because the backend is the fixture.

  anthropic (Path B) has no fixture variant: its seam is the Relay container
  launcher, which always talks to Docker, so the launch is accepted only with a
  consumed Claude one-shot approval (``claude_live_state``) that the launcher
  itself re-checks from the same state directory and hash.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from providers.base import ProviderStaticProfile

from .acp_client import (
    _acp_exchange,
    _acp_initialize,
    _acp_await_auth_status,
    _acp_new_session,
    _IGNORABLE_SESSION_UPDATES,
    _acp_prompt_text,
    acp_mock_text_to_phase0_raw,
)
from .acp_stdio_transport import spawn_stdio_transport
from .claude_live_state import verify_claude_live_authorization
from .m9_live_state import LiveAuthorization, verify_live_authorization
from .transport import AdmissionRefused, RouteViolationCancelled

__all__ = ["AcpStdioStaticTransport", "OfficialAdapterLaunch", "LiveAuthorization", "LIVE_ADAPTER_MARKERS"]

# Official adapter identities that must never be launched from the injected-fake mode.
LIVE_ADAPTER_MARKERS = (
    "codex-acp",
    "claude-agent-acp",
    "agy_acp_server",
    "antigravity-acp",
    "@agentclientprotocol/",
)

# provider_id -> env key through which the official adapter accepts a replacement backend
# (here: the one-generation gate, which wraps the real/fixture backend).
_VERIFIED_BACKEND_SEAMS = {"openai": "CODEX_PATH", "anthropic": "CLAUDE_CODE_EXECUTABLE"}

_REPO_ROOT = Path(__file__).resolve().parents[2]
# anthropic: the only executable the adapter may run as "claude", and the files it mounts into the container.
_CLAUDE_LAUNCHER = Path(__file__).with_name("claude_container_launcher.py").resolve()
_CLAUDE_RUNTIME_DIR = _REPO_ROOT / "automation" / "command_bus" / "docker" / "claude-runtime"
_CLAUDE_LAUNCH_FILES = {
    "RELAY_CLAUDE_ENTRYPOINT_HOST_PATH": (_CLAUDE_RUNTIME_DIR / "claude_adapter_entrypoint.mjs").resolve(),
    "RELAY_CLAUDE_SECCOMP_HOST_PATH": (_CLAUDE_RUNTIME_DIR / "claude-bwrap-seccomp-amd64.json").resolve(),
}

# Credential / route variables that must not reach an adapter in STATIC mode.
_FORBIDDEN_ENV = frozenset({
    "OPENAI_API_KEY", "CODEX_API_KEY", "MODEL_PROVIDER", "CODEX_CONFIG", "DEFAULT_AUTH_REQUEST",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
})

_DEFAULT_TIMEOUT_SECONDS = 5
_STARTUP_TIMEOUT_SECONDS = 15.0  # adapter start (node, cmd.exe, gate) can be slow, e.g. on Windows
_TEARDOWN_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class OfficialAdapterLaunch:
    """Official adapter command + fixture backend (proof of no live backend)."""

    command: tuple[str, ...]
    env: Mapping[str, str]
    fixture_root: Path
    # Only a consumed one-shot approval (see m9_live_state) unlocks a backend outside fixture_root.
    live_authorization: LiveAuthorization | None = None


def _refuse_live_command(command: tuple[str, ...], profile: ProviderStaticProfile) -> None:
    markers = LIVE_ADAPTER_MARKERS + ((profile.binary_name,) if profile.binary_name else ())
    for part in command:
        if not isinstance(part, str) or not part:
            raise ValueError("command parts must be non-empty strings")
        lowered = (part.lower(), os.path.basename(part.replace("\\", "/")).lower())
        if any(marker.lower() in text for marker in markers for text in lowered):
            raise ValueError("official live adapter launch is blocked in STATIC mode")


def _validate_official_launch(launch: OfficialAdapterLaunch, profile: ProviderStaticProfile) -> None:
    seam = _VERIFIED_BACKEND_SEAMS.get(profile.provider_id)
    if seam is None:
        raise ValueError(
            "UNKNOWN / LIVE_BOUNDARY: no verified static backend seam for provider "
            f"{profile.provider_id!r}; official adapter not launched"
        )
    if not isinstance(launch.command, tuple) or not launch.command:
        raise ValueError("command must be a non-empty tuple")
    if any(not isinstance(p, str) or not p for p in launch.command):
        raise ValueError("command parts must be non-empty strings")
    if profile.binary_name is None or not any(profile.binary_name in p for p in launch.command):
        raise ValueError("command does not name the official adapter of this profile")
    forbidden = _FORBIDDEN_ENV.intersection(launch.env)
    if forbidden:
        raise ValueError(f"credential/route env not allowed in STATIC mode: {sorted(forbidden)}")
    if profile.provider_id == "anthropic":
        _validate_claude_container_launch(launch, seam)
        return
    # codex-acp may start a second (title-generation) turn on its own. The outer
    # one-generation gate must therefore sit between the adapter and its backend.
    gates = {
        Path(__file__).with_name("codex_turn_gate.py").resolve(),
        Path(__file__).with_name("codex_turn_gate.cmd").resolve(),  # Windows launcher
    }
    if not launch.env.get(seam) or Path(launch.env[seam]).resolve() not in gates:
        raise ValueError(f"{seam} must be the Relay one-generation gate (codex_turn_gate.py/.cmd)")
    backend = launch.env.get("RELAY_GATE_BACKEND")
    if not backend:
        raise ValueError("RELAY_GATE_BACKEND must be set")
    backend_path = Path(backend).resolve()
    if not backend_path.is_file():
        raise ValueError("RELAY_GATE_BACKEND must be an existing file")
    root = Path(launch.fixture_root).resolve()
    if root in backend_path.parents:
        if launch.live_authorization is not None:
            raise ValueError("a fixture backend must not carry a live authorization")
        return
    # Backend outside the fixture root = potentially real/live: fail closed unless one-shot approved.
    verify_live_authorization(launch.live_authorization, profile.provider_id)
    if backend_path in gates:
        raise ValueError("RELAY_GATE_BACKEND must not be the gate itself")


def _validate_claude_container_launch(launch: OfficialAdapterLaunch, seam: str) -> None:
    """Path B: the adapter may only run the Relay launcher, bound to one consumed Claude approval."""
    if not launch.env.get(seam) or Path(launch.env[seam]).resolve() != _CLAUDE_LAUNCHER:
        raise ValueError(f"{seam} must be the Relay container launcher (claude_container_launcher.py)")
    if "RELAY_GATE_BACKEND" in launch.env:
        raise ValueError("RELAY_GATE_BACKEND is the Codex gate setting; not allowed for anthropic")
    for key, expected in _CLAUDE_LAUNCH_FILES.items():
        value = launch.env.get(key)
        if not value or Path(value).resolve() != expected or not expected.is_file():
            raise ValueError(f"{key} must be the repository file {expected.name}")
    auth = launch.live_authorization
    verify_claude_live_authorization(auth, "anthropic")
    # The launcher re-verifies from its own environment; it must see exactly this approval.
    if launch.env.get("RELAY_CLAUDE_STATE_DIR") is None or (
        Path(launch.env["RELAY_CLAUDE_STATE_DIR"]).resolve() != Path(auth.state_dir).resolve()
    ):
        raise ValueError("RELAY_CLAUDE_STATE_DIR must be the live authorization's state directory")
    if launch.env.get("RELAY_CLAUDE_APPROVAL_SHA256") != auth.approval_sha256:
        raise ValueError("RELAY_CLAUDE_APPROVAL_SHA256 must be the live authorization's approval hash")


class AcpStdioStaticTransport:
    """RelayTransport-compatible; one ACP stdio child per transport instance."""

    def __init__(
        self,
        profile: ProviderStaticProfile,
        command: tuple[str, ...] | None = None,
        *,
        official: OfficialAdapterLaunch | None = None,
        route_admission: Callable[[Sequence[Mapping[str, Any]]], tuple[bool, str]] | None = None,
        route_admission_wait_seconds: float = 6.0,
        route_midturn: Callable[[Mapping[str, Any]], str | None] | None = None,
    ) -> None:
        if not isinstance(profile, ProviderStaticProfile):
            raise TypeError("profile must be a ProviderStaticProfile")
        if profile.live_ready is not False or profile.retry_count != 0 or profile.fallback_state != "disabled":
            raise ValueError("profile must be static: live_ready=False, retry=0, fallback=disabled")
        if (command is None) == (official is None):
            raise ValueError("provide exactly one of command or official")
        if official is not None:
            _validate_official_launch(official, profile)
            self.command, self._env = official.command, dict(official.env)
            self._live = official.live_authorization is not None
        else:
            if not isinstance(command, tuple) or not command:
                raise ValueError("command must be a non-empty tuple")
            _refuse_live_command(command, profile)
            self.command, self._env = command, None
            self._live = False
        if route_admission is not None and profile.provider_id != "anthropic":
            raise ValueError("route_admission is the Claude auth-status extension; other providers must not set it")
        if route_midturn is not None and profile.provider_id != "anthropic":
            raise ValueError("route_midturn is the Claude auth-status extension; other providers must not set it")
        self._route_midturn = route_midturn
        self.route_midturn_decisions: list[str | None] = []
        self._route_admission = route_admission
        self._route_wait = float(route_admission_wait_seconds)
        self.route_admission_decisions: list[tuple[bool, str]] = []
        self.profile = profile
        self.live = self._live
        self._startup_timeout = 45.0 if self._live else _STARTUP_TIMEOUT_SECONDS
        self.spawn_count = 0
        self.prompt_count = 0
        self.cancel_sent = 0
        self.close_requests = 0
        self.agent_capabilities: dict[str, Any] = {}
        # Sanitized classifications of official ``_auth/status_update`` pushes (never the raw account data).
        self.auth_status_evidence: list[dict[str, Any]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cm: AbstractAsyncContextManager | None = None
        self._streams: tuple[asyncio.StreamReader, asyncio.StreamWriter] | None = None
        self._session_id: str | None = None
        self._state = "new"  # new -> initialized -> open -> cancelled -> closed

    # -- helpers -----------------------------------------------------------
    def _check_provider(self, provider_id: str) -> None:
        if provider_id != self.profile.provider_id:
            raise ValueError("provider_id does not match profile")

    def _run(self, coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            coro.close()
            raise RuntimeError("sync transport cannot run inside an event loop")
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    async def _spawn(self) -> dict[str, Any]:
        self._cm = spawn_stdio_transport(*self.command, env=self._env, shutdown_timeout=_TEARDOWN_TIMEOUT_SECONDS)
        stdout, stdin, _process = await self._cm.__aenter__()
        self._streams = (stdout, stdin)
        auth_sink = self.auth_status_evidence if self.profile.provider_id == "anthropic" else None
        return await _acp_initialize(stdout, stdin, self._startup_timeout, auth_sink)

    async def _teardown(self) -> None:
        cm, self._cm, self._streams = self._cm, None, None
        if cm is not None:
            await cm.__aexit__(None, None, None)

    def _dispose_loop(self) -> None:
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    # -- RelayTransport ----------------------------------------------------
    def initialize(self, provider_id: str) -> dict[str, Any]:
        self._check_provider(provider_id)
        if self._state != "new":
            raise ValueError("transport already initialized")
        self.spawn_count += 1
        self._state = "initialized"
        try:
            result = self._run(self._spawn())
        except BaseException:
            self._run(self._teardown())
            self._dispose_loop()
            self._state = "closed"
            raise
        caps = result.get("agentCapabilities")
        self.agent_capabilities = dict(caps) if isinstance(caps, dict) else {}
        # The adapter/fake-agent process runs; its backend is a fixture (validated at
        # construction), so no live provider process exists.
        return {
            "protocol_version": 1,
            "provider_id": provider_id,
            "mode": "acp_stdio_static",
            "adapter_process_started": True,
            "live_process_started": self._live,
        }

    def _admit(self) -> None:
        """Ask the injected policy (``providers.policy.claude_route_admission``); refuse before any prompt."""
        allowed, reason = self._route_admission(tuple(self.auth_status_evidence))
        self.route_admission_decisions.append((allowed, reason))
        if not allowed:
            self._run(self._teardown())
            self._dispose_loop()
            self._state = "closed"
            raise AdmissionRefused(f"route admission refused before any prompt: {reason}")

    def open_session(self, provider_id: str, *, cwd: str) -> str:
        self._check_provider(provider_id)
        if self._state != "initialized" or self._streams is None:
            raise ValueError("transport is not initialized")
        stdout, stdin = self._streams
        auth_sink = self.auth_status_evidence if self.profile.provider_id == "anthropic" else None
        if self._route_admission is not None:
            # The adapter pushes its identity right after `initialize`; wait for it (bounded) and drain what
            # follows immediately, then decide before `session/new` starts the Claude CLI. A late or missing
            # push is refused (fail closed). Any failure here must not leave the adapter child running.
            try:
                self._run(_acp_await_auth_status(stdout, self._route_wait, self.auth_status_evidence))
            except BaseException:
                self._run(self._teardown())
                self._dispose_loop()
                self._state = "closed"
                raise
            self._admit()
        try:
            session_id = self._run(_acp_new_session(
                stdout, stdin, cwd, self._startup_timeout, self.profile.session_meta, auth_sink))
        except BaseException:
            # No session id exists, so the lifecycle will not close; do not leave the adapter child running.
            self._run(self._teardown())
            self._dispose_loop()
            self._state = "closed"
            raise
        if self._route_admission is not None:
            self._admit()  # observations that arrived while session/new was answered count too
        self._session_id, self._state = session_id, "open"
        return session_id

    def _on_auth(self, evidence: dict[str, Any]) -> None:
        """Ask the injected mid-turn rule about a classification that arrived during the turn."""
        reason = self._route_midturn(evidence)
        self.route_midturn_decisions.append(reason)
        if reason:
            raise RouteViolationCancelled(f"route violation reported mid-turn ({reason}); turn cancelled")

    def prompt(
        self,
        provider_id: str,
        session_id: str,
        payload: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> bytes:
        self._check_provider(provider_id)
        if self._state != "open" or session_id != self._session_id or self._streams is None:
            raise ValueError("Session is not open")
        if self.prompt_count:
            raise ValueError("Session already prompted")
        self.prompt_count = 1

        text = payload.get("prompt") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("payload['prompt'] must be a non-empty string")
        stdout, stdin = self._streams
        total = float(timeout_seconds or _DEFAULT_TIMEOUT_SECONDS)
        if self._live:
            # Real streaming: many small text deltas and metadata updates are normal; the whole
            # prompt (not each read) is bounded by timeout_seconds. Tool calls etc. still fail closed.
            auth_sink = self.auth_status_evidence if self.profile.provider_id == "anthropic" else None
            coro = _acp_prompt_text(
                stdout, stdin, session_id, text, total, max_chunks=2000, max_ignored=2000,
                ignorable=_IGNORABLE_SESSION_UPDATES | {"agent_thought_chunk"}, auth_sink=auth_sink,
                on_auth=self._on_auth if self._route_midturn is not None else None,
            )
        else:
            auth_sink = self.auth_status_evidence if self.profile.provider_id == "anthropic" else None
            coro = _acp_prompt_text(
                stdout, stdin, session_id, text, total, auth_sink=auth_sink,
                on_auth=self._on_auth if self._route_midturn is not None else None,
            )
        result = self._run(asyncio.wait_for(coro, timeout=total))
        # Non end_turn / empty text raises -> lifecycle reports UNKNOWN, never success.
        return acp_mock_text_to_phase0_raw(result)

    def cancel(self, provider_id: str, session_id: str) -> None:
        self._check_provider(provider_id)
        if session_id != self._session_id or self._state not in ("open", "cancelled"):
            raise ValueError("Unknown or closed session")
        if self._state == "cancelled":
            raise ValueError("Session already cancelled")
        if self._streams is not None:
            _stdout, stdin = self._streams
            note = {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": session_id}}

            async def _send() -> None:
                stdin.write(json.dumps(note).encode("utf-8") + b"\n")
                await stdin.drain()

            try:
                self._run(_send())
                self.cancel_sent += 1
            except Exception:
                pass  # child already gone; teardown happens in close()
        self._state = "cancelled"

    def close(self, provider_id: str, session_id: str) -> None:
        self._check_provider(provider_id)
        if session_id != self._session_id:
            raise ValueError("Unknown session")
        if self._state == "closed":
            raise ValueError("Session already closed")
        try:
            if (
                self._state == "open"
                and self._streams is not None
                and "close" in (self.agent_capabilities.get("sessionCapabilities") or {})
            ):
                stdout, stdin = self._streams
                self.close_requests += 1
                req = {"jsonrpc": "2.0", "id": 3, "method": "session/close", "params": {"sessionId": session_id}}
                try:
                    self._run(_acp_exchange(stdout, stdin, req, 3, 2.0, "session/close"))
                except Exception:
                    pass  # best effort; teardown below is authoritative
            self._run(self._teardown())
        finally:
            self._dispose_loop()
            self._state = "closed"
