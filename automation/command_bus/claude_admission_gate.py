"""Host-owned, one-generation admission gate for a Claude Code dispatch.

This module is a static transport implementation; it never launches Claude,
registers dispatches over HTTP, or selects credentials. The host must register
an opaque dispatch ID through the Python API before starting its client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPConnection, HTTPSConnection, HTTPException
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import Callable
from urllib.parse import urlsplit
import uuid
from contextlib import contextmanager


DISPATCH_HEADER = "X-Phase0-Dispatch-ID"
MAX_REQUEST_BYTES = 16 * 1024 * 1024
CHUNK_BYTES = 16 * 1024
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}


@dataclass(frozen=True)
class Admission:
    decision: str
    ordinal: int | None
    dispatch_id: str | None
    reason: str


class DispatchStore:
    """SQLite-backed write-ahead slot claim; use a private, durable local file."""

    def __init__(self, path: str):
        self.path = path
        self._init_lock = Lock()
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS dispatches (
                dispatch_id TEXT PRIMARY KEY, expires_at TEXT NOT NULL,
                terminal INTEGER NOT NULL DEFAULT 0, claimed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT, dispatch_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL, decision TEXT NOT NULL, timestamp TEXT NOT NULL,
                body_sha256 TEXT NOT NULL, body_bytes INTEGER NOT NULL,
                prompt_id TEXT, session_id TEXT, request_class TEXT, upstream_status INTEGER)""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def _db(self):
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    def register(self, dispatch_id: str, expires_at: str) -> None:
        if not _UUID.fullmatch(dispatch_id):
            raise ValueError("dispatch_id must be a UUID")
        expiry = _parse_time(expires_at)
        if expiry <= datetime.now(timezone.utc):
            raise ValueError("dispatch expiry must be in the future")
        with self._db() as db:
            try:
                db.execute("INSERT INTO dispatches(dispatch_id,expires_at,created_at) VALUES(?,?,?)",
                           (str(uuid.UUID(dispatch_id)), expiry.isoformat(), _now()))
            except sqlite3.IntegrityError as exc:
                raise ValueError("dispatch_id already exists; replay refused") from exc

    def mark_terminal(self, dispatch_id: str) -> bool:
        if _UUID.fullmatch(dispatch_id or ""):
            dispatch_id = str(uuid.UUID(dispatch_id))
        with self._db() as db:
            cur = db.execute("UPDATE dispatches SET terminal=1 WHERE dispatch_id=? AND terminal=0",
                             (dispatch_id,))
            return cur.rowcount == 1

    def claim(self, dispatch_id: str | None, body: bytes, headers) -> Admission:
        if not dispatch_id or not _UUID.fullmatch(dispatch_id):
            return Admission("DENIED_BEFORE_UPSTREAM", None, dispatch_id, "missing_or_malformed_dispatch_id")
        canonical = str(uuid.UUID(dispatch_id))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT expires_at,terminal,claimed FROM dispatches WHERE dispatch_id=?",
                             (canonical,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                return Admission("DENIED_BEFORE_UPSTREAM", None, canonical, "unknown_dispatch")
            expiry, terminal, claimed = row
            if _parse_time(expiry) <= datetime.now(timezone.utc):
                db.execute("ROLLBACK")
                return Admission("DENIED_BEFORE_UPSTREAM", None, canonical, "expired_dispatch")
            if terminal:
                db.execute("ROLLBACK")
                return Admission("DENIED_BEFORE_UPSTREAM", None, canonical, "terminal_dispatch")
            if claimed:
                db.execute("ROLLBACK")
                return Admission("DENIED_BEFORE_UPSTREAM", None, canonical, "generation_budget_exhausted")
            db.execute("UPDATE dispatches SET claimed=1 WHERE dispatch_id=? AND claimed=0", (canonical,))
            timestamp = _now()
            db.execute("""INSERT INTO evidence(dispatch_id,ordinal,decision,timestamp,body_sha256,
                         body_bytes,prompt_id,session_id,request_class)
                         VALUES(?,1,'ADMITTED',?,?,?,?,?,?)""", (
                canonical, timestamp, sha256(body).hexdigest(), len(body),
                _safe_header(headers, "x-claude-code-prompt-id"),
                _safe_header(headers, "x-claude-code-session-id"),
                _safe_header(headers, "x-claude-code-request-class")))
            db.execute("COMMIT")
            return Admission("ADMITTED", 1, canonical, "single_generation_slot_claimed")

    def record_upstream_status(self, dispatch_id: str, status: int) -> None:
        with self._db() as db:
            db.execute("UPDATE evidence SET upstream_status=? WHERE dispatch_id=? AND ordinal=1",
                       (status, dispatch_id))

    def record_denial(self, dispatch_id: str | None, body: bytes, headers, reason: str) -> None:
        if not dispatch_id or not _UUID.fullmatch(dispatch_id):
            return
        canonical = str(uuid.UUID(dispatch_id))
        with self._db() as db:
            row = db.execute("SELECT 1 FROM dispatches WHERE dispatch_id=?", (canonical,)).fetchone()
            if row is None:
                return
            db.execute("""INSERT INTO evidence(dispatch_id,ordinal,decision,timestamp,body_sha256,
                         body_bytes,prompt_id,session_id,request_class)
                         VALUES(?,2,?,?,?,?,?,?,?)""", (
                canonical, "DENIED_BEFORE_UPSTREAM:" + reason, _now(), sha256(body).hexdigest(),
                len(body), _safe_header(headers, "x-claude-code-prompt-id"),
                _safe_header(headers, "x-claude-code-session-id"),
                _safe_header(headers, "x-claude-code-request-class")))

    def evidence(self, dispatch_id: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""SELECT ordinal,decision,timestamp,body_sha256,body_bytes,
                       prompt_id,session_id,request_class,upstream_status
                       FROM evidence WHERE dispatch_id=? ORDER BY id""", (dispatch_id,)).fetchall()
        fields = ("ordinal", "decision", "timestamp", "body_sha256", "body_bytes",
                  "prompt_id", "session_id", "request_class", "upstream_status")
        return [dict(zip(fields, row)) for row in rows]


def prepare_transport(*, dispatch_id: str, gate_base_url: str, retry: int = 0,
                      fallback: str = "disabled", live_model: bool = False,
                      external_send: bool = False) -> dict:
    """Return a non-launching env contract for future host integration."""
    parsed = urlsplit(gate_base_url)
    if retry != 0 or fallback != "disabled" or live_model or external_send:
        return {"status": "BLOCKED", "reason": "live/retry/fallback request rejected"}
    if not _UUID.fullmatch(dispatch_id) or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"status": "BLOCKED", "reason": "invalid dispatch ID or gateway URL"}
    return {"status": "PREPARED", "launch": False, "retry": 0, "fallback": "disabled",
            "env": {"ANTHROPIC_BASE_URL": gate_base_url.rstrip("/"),
                    "ANTHROPIC_CUSTOM_HEADERS": f"{DISPATCH_HEADER}: {str(uuid.UUID(dispatch_id))}",
                    "CLAUDE_CODE_GATEWAY_HINT_HEADERS": "1",
                    "CLAUDE_CODE_MAX_RETRIES": "0"}}


def make_server(*, store: DispatchStore, upstream_url: str, bind_host: str = "127.0.0.1",
                connect_timeout: float = 5.0, upstream_factory: Callable | None = None):
    """Create a loopback-only HTTP gateway; upstream URL is explicit and never retried."""
    if bind_host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("gate must bind to loopback")
    upstream = urlsplit(upstream_url)
    if upstream.scheme not in {"http", "https"} or not upstream.hostname or upstream.username or upstream.password:
        raise ValueError("invalid upstream URL")
    conn_factory = upstream_factory or (HTTPSConnection if upstream.scheme == "https" else HTTPConnection)
    prefix = upstream.path.rstrip("/")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        server_version = "Phase0AdmissionGate/1"

        def log_message(self, fmt, *args):
            # Never let standard access logs expose header/body values.
            return

        def do_HEAD(self):
            if urlsplit(self.path).path == "/api/hello":
                self.send_response(204)
                self.send_header("Connection", "close")
                self.end_headers()
            else:
                self._deny(404, "UNKNOWN_ENDPOINT")

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == "/v1/messages/count_tokens":
                self._deny(403, "AUXILIARY_ENDPOINT_DENIED_LOCALLY")
                return
            if path != "/v1/messages":
                self._deny(404, "UNKNOWN_ENDPOINT")
                return
            raw_len = self.headers.get("Content-Length")
            if raw_len is None or not raw_len.isdigit() or int(raw_len) > MAX_REQUEST_BYTES:
                self._deny(413, "INVALID_OR_OVERSIZE_BODY")
                return
            body = self.rfile.read(int(raw_len))
            if len(body) != int(raw_len):
                self._deny(400, "INCOMPLETE_BODY")
                return
            admission = store.claim(self.headers.get(DISPATCH_HEADER), body, self.headers)
            if admission.decision != "ADMITTED":
                store.record_denial(admission.dispatch_id, body, self.headers, admission.reason)
                self._deny(429, admission.reason, retry_suppression=True)
                return
            target = prefix + "/v1/messages" + (("?" + urlsplit(self.path).query) if urlsplit(self.path).query else "")
            connection = None
            response_started = False
            try:
                connection = conn_factory(upstream.hostname, upstream.port,
                                          timeout=connect_timeout)
                forward_headers = _forward_headers(self.headers)
                connection.request("POST", target, body=body, headers=forward_headers)
                response = connection.getresponse()
                store.record_upstream_status(admission.dispatch_id, response.status)
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in _HOP_HEADERS | {"content-length", "connection", "server", "date"}:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                response_started = True
                while True:
                    chunk = response.read1(CHUNK_BYTES)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (OSError, HTTPException, TimeoutError) as exc:
                # Slot remains consumed; never retry or select a fallback.
                try:
                    if not response_started and not self.wfile.closed:
                        self._deny(502, "UPSTREAM_TRANSPORT_ERROR")
                except (OSError, ConnectionError):
                    pass
            finally:
                if connection is not None:
                    connection.close()

        def _deny(self, status: int, reason: str, retry_suppression: bool = False):
            payload = json.dumps({"type": "error", "error": {"type": "phase0_gate_error",
                                                                   "message": reason}},
                                 separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            if retry_suppression:
                self.send_header("x-should-retry", "false")
                self.send_header("retry-after", "61")
            self.end_headers()
            self.wfile.write(payload)

    return ThreadingHTTPServer((bind_host, 0), Handler)


def _forward_headers(headers) -> dict[str, str]:
    connection_tokens = {token.strip().lower() for value in headers.get_all("Connection", [])
                         for token in value.split(",")}
    blocked = _HOP_HEADERS | connection_tokens | {"host", "content-length", DISPATCH_HEADER.lower()}
    forwarded = {}
    for name, value in headers.items():
        if name.lower() not in blocked:
            forwarded[name] = value
    return forwarded


def _safe_header(headers, name: str) -> str | None:
    value = headers.get(name)
    if value is None or len(value) > 256 or any(ord(ch) < 32 or ord(ch) > 126 for ch in value):
        return None
    return value


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
