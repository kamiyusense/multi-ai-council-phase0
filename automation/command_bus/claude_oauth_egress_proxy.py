"""Credential-blind OAuth control-plane CONNECT proxy for Phase 0 Claude.

Static safety boundary:
- accepts only HTTP CONNECT;
- permits exactly platform.claude.com:443;
- rejects model API and every other destination before opening a socket;
- does not terminate TLS or inspect OAuth credentials;
- performs one connect attempt only, with no retry or fallback.

This module does not launch Claude or perform an OAuth refresh by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import select
import socket
import sys
from typing import Callable


ALLOWED_CONNECT_HOST = "platform.claude.com"
ALLOWED_CONNECT_PORT = 443
EXPECTED_ALLOWED_CONNECT = f"{ALLOWED_CONNECT_HOST}:{ALLOWED_CONNECT_PORT}"
CONTAINER_BIND_IP = "172.29.247.3"
CONTAINER_PORT = 8081
BUFFER_BYTES = 16 * 1024
CONNECT_TIMEOUT_SECONDS = 10.0
RELAY_IDLE_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class ConnectDecision:
    allowed: bool
    host: str | None
    port: int | None
    reason: str


def evaluate_connect_authority(authority: str | None) -> ConnectDecision:
    """Return a fail-closed decision for a CONNECT authority value."""
    if not isinstance(authority, str) or not authority or authority != authority.strip():
        return ConnectDecision(False, None, None, "missing_or_noncanonical_authority")
    if any(ch in authority for ch in ("/", "?", "#", "@", "\\", " ", "\t", "\r", "\n")):
        return ConnectDecision(False, None, None, "authority_contains_forbidden_syntax")
    if authority.count(":") != 1:
        return ConnectDecision(False, None, None, "authority_must_be_host_colon_port")
    host, port_text = authority.split(":", 1)
    if host != ALLOWED_CONNECT_HOST:
        return ConnectDecision(False, host or None, None, "host_not_allowlisted")
    if port_text != str(ALLOWED_CONNECT_PORT):
        return ConnectDecision(False, host, None, "port_not_allowlisted")
    return ConnectDecision(True, host, ALLOWED_CONNECT_PORT, "exact_allowlist_match")


def validate_runtime_environment(env: dict[str, str] | os._Environ[str] = os.environ) -> dict:
    expected = {
        "PHASE0_OAUTH_PROXY_BIND": CONTAINER_BIND_IP,
        "PHASE0_OAUTH_PROXY_PORT": str(CONTAINER_PORT),
        "PHASE0_OAUTH_PROXY_ALLOWED_CONNECT": EXPECTED_ALLOWED_CONNECT,
    }
    observed_phase0 = {key: value for key, value in env.items() if key.startswith("PHASE0_OAUTH_PROXY_")}
    exact = observed_phase0 == expected
    return {
        "status": "PASS" if exact else "BLOCKED",
        "expected": expected,
        "unexpected_or_missing": sorted(set(observed_phase0) ^ set(expected))
        if set(observed_phase0) != set(expected)
        else sorted(key for key in expected if observed_phase0.get(key) != expected[key]),
        "retry": 0,
        "fallback": "disabled",
    }


def _default_connector(host: str, port: int, timeout: float) -> socket.socket:
    return socket.create_connection((host, port), timeout=timeout)


def open_allowed_tunnel(
    authority: str | None,
    *,
    connector: Callable[[str, int, float], socket.socket] = _default_connector,
) -> tuple[ConnectDecision, socket.socket | None]:
    """Open at most one socket after the exact allowlist decision passes."""
    decision = evaluate_connect_authority(authority)
    if not decision.allowed:
        return decision, None
    try:
        upstream = connector(decision.host or "", decision.port or 0, CONNECT_TIMEOUT_SECONDS)
    except OSError:
        return ConnectDecision(False, decision.host, decision.port, "single_connect_failed"), None
    return decision, upstream


def _relay_bidirectional(client: socket.socket, upstream: socket.socket) -> None:
    sockets = [client, upstream]
    while True:
        try:
            readable, _, _ = select.select(sockets, [], [], RELAY_IDLE_TIMEOUT_SECONDS)
        except (OSError, ValueError):
            return
        if not readable:
            return
        for source in readable:
            destination = upstream if source is client else client
            try:
                chunk = source.recv(BUFFER_BYTES)
            except OSError:
                return
            if not chunk:
                return
            try:
                destination.sendall(chunk)
            except OSError:
                return


def make_server(
    *,
    bind: str = CONTAINER_BIND_IP,
    port: int = CONTAINER_PORT,
    connector: Callable[[str, int, float], socket.socket] = _default_connector,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args) -> None:
            # Never log request headers or tunnel bytes.
            return

        def _reject_non_connect(self) -> None:
            self.send_response(405)
            self.send_header("Connection", "close")
            self.send_header("Content-Length", "0")
            self.end_headers()
            self.close_connection = True

        def do_CONNECT(self) -> None:
            decision, upstream = open_allowed_tunnel(self.path, connector=connector)
            if not decision.allowed or upstream is None:
                self.send_response(403 if decision.reason != "single_connect_failed" else 502)
                self.send_header("Connection", "close")
                self.send_header("Content-Length", "0")
                self.end_headers()
                self.close_connection = True
                return
            try:
                self.send_response(200, "Connection Established")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.flush()
                _relay_bidirectional(self.connection, upstream)
            finally:
                try:
                    upstream.close()
                except OSError:
                    pass
                self.close_connection = True

        do_GET = _reject_non_connect
        do_POST = _reject_non_connect
        do_PUT = _reject_non_connect
        do_PATCH = _reject_non_connect
        do_DELETE = _reject_non_connect
        do_OPTIONS = _reject_non_connect
        do_HEAD = _reject_non_connect

    return ThreadingHTTPServer((bind, port), Handler)


def main(argv: list[str] | None = None, env: dict[str, str] | os._Environ[str] = os.environ) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    validation = validate_runtime_environment(env)
    if argv != ["serve"] or validation["status"] != "PASS":
        print("BLOCKED: exact OAuth egress proxy configuration is required; no connection attempted", file=sys.stderr)
        return 78
    server = make_server(bind=CONTAINER_BIND_IP, port=CONTAINER_PORT)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
