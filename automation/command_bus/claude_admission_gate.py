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
import ipaddress
import re
import os
import sqlite3
import stat
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


DISPATCH_HEADER = "X-Phase0-Dispatch-ID"
MAX_REQUEST_BYTES = 16 * 1024 * 1024
CHUNK_BYTES = 16 * 1024
PRODUCTION_UPSTREAM_HOST = "api.anthropic.com"
CONTAINER_GATE_BIND_IP = "172.29.247.2"
CONTAINER_AUTH_PROXY_BIND_IP = "172.29.247.3"
CONTAINER_GATE_SERVICE = "gate"
CONTAINER_GATE_PORT = 8080
HOST_LOOPBACK = "HOST_LOOPBACK"
CONTAINER_INTERNAL = "CONTAINER_INTERNAL"
COMPOSE_MANIFEST = Path(__file__).with_name("claude_gate_compose.yaml")
CONTAINER_ARTIFACT_ROOT = Path(__file__).with_name("docker")
RUNTIME_SECCOMP_RELATIVE_PATH = "./docker/claude-runtime/claude-bwrap-seccomp-amd64.json"
RUNTIME_SECCOMP_PROFILE = CONTAINER_ARTIFACT_ROOT / "claude-runtime" / "claude-bwrap-seccomp-amd64.json"
# Docker Engine 29.8.0 (moby/moby 3ce5872b7950c63ba2ffbc5123101019ff3e6682)
# vendors moby/profiles default.json at Git blob ea5a494afb8d64898fa0f4f47ae0c4f5ba9cbbc9.
# The pinned profile adds only the amd64 bubblewrap syscalls observed by strace.
RUNTIME_SECCOMP_SHA256 = "b4516f39b519c306068c7507f3be555e039fa691c2527c96594d7ecffaebe759"
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

    def __init__(self, path: str, *, _production_open: bool = False,
                 _initialize_schema: bool = True):
        self.path = path
        self.production = _production_open
        if not _initialize_schema:
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                row = db.execute("SELECT value FROM store_meta WHERE key='store_id'").fetchone()
                required = {"dispatches", "evidence", "store_meta", "terminal_receipts"}
                tables = {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if row is None or not required.issubset(tables):
                    raise ValueError("production database schema/identity incomplete; refuse repair")
                columns = {item[1] for item in db.execute("PRAGMA table_info(dispatches)")}
                if not {"dispatch_id", "expires_at", "terminal", "claimed", "loop_id",
                        "correlation_id", "backend", "target_head", "generation"}.issubset(columns):
                    raise ValueError("production dispatch schema incomplete; refuse migration")
                self.store_id = row[0]
            return
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS dispatches (
                dispatch_id TEXT PRIMARY KEY, expires_at TEXT NOT NULL,
                terminal INTEGER NOT NULL DEFAULT 0, claimed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL)""")
            self._ensure_column(db, "dispatches", "loop_id", "TEXT")
            self._ensure_column(db, "dispatches", "correlation_id", "TEXT")
            self._ensure_column(db, "dispatches", "backend", "TEXT")
            self._ensure_column(db, "dispatches", "target_head", "TEXT")
            self._ensure_column(db, "dispatches", "generation", "INTEGER")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS dispatch_context_unique ON dispatches(loop_id,correlation_id,generation)")
            db.execute("""CREATE TABLE IF NOT EXISTS evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT, dispatch_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL, decision TEXT NOT NULL, timestamp TEXT NOT NULL,
                body_sha256 TEXT NOT NULL, body_bytes INTEGER NOT NULL,
                prompt_id TEXT, session_id TEXT, request_class TEXT, upstream_status INTEGER)""")
            db.execute("CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS terminal_receipts (dispatch_id TEXT PRIMARY KEY, receipt_json TEXT NOT NULL, created_at TEXT NOT NULL)")
            if db.execute("SELECT 1 FROM store_meta WHERE key='store_id'").fetchone() is None:
                db.execute("INSERT INTO store_meta(key,value) VALUES('store_id',?)", (str(uuid.uuid4()),))
            self.store_id = db.execute("SELECT value FROM store_meta WHERE key='store_id'").fetchone()[0]

    @staticmethod
    def _ensure_column(db, table: str, column: str, declaration: str) -> None:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @classmethod
    def open_production(cls, path: str, *, state_dir: str, expected_store_id: str) -> "DispatchStore":
        """Open only an existing, host-owned durable store with expected identity."""
        validate_production_store_path(path, state_dir=state_dir)
        if not _UUID.fullmatch(expected_store_id or ""):
            raise ValueError("external expected store identity is required")
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True)) as db:
                row = db.execute("SELECT value FROM store_meta WHERE key='store_id'").fetchone()
        except sqlite3.Error as exc:
            raise ValueError("existing store identity is unreadable; refuse new store") from exc
        if row is None or row[0] != expected_store_id:
            raise ValueError("store identity mismatch; possible replacement or rollback")
        store = cls(path, _production_open=True, _initialize_schema=False)
        if store.store_id != expected_store_id:
            raise ValueError("store identity changed during open")
        return store


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

    def register(self, dispatch_id: str, expires_at: str, *, loop_id: str,
                 correlation_id: str, backend: str, target_head: str,
                 generation: int) -> None:
        if not _UUID.fullmatch(dispatch_id):
            raise ValueError("dispatch_id must be a UUID")
        if not all(isinstance(x, str) and x.strip() for x in (loop_id, correlation_id)):
            raise ValueError("loop and correlation identity are required")
        if backend != "CLAUDE_BACKEND" or not re.fullmatch(r"[0-9a-f]{40}", target_head):
            raise ValueError("Claude backend and exact target head are required")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
            raise ValueError("generation must be a positive integer")
        expiry = _parse_time(expires_at)
        if expiry <= datetime.now(timezone.utc):
            raise ValueError("dispatch expiry must be in the future")
        with self._db() as db:
            try:
                db.execute("""INSERT INTO dispatches(dispatch_id,expires_at,created_at,loop_id,
                           correlation_id,backend,target_head,generation) VALUES(?,?,?,?,?,?,?,?)""",
                           (str(uuid.UUID(dispatch_id)), expiry.isoformat(), _now(), loop_id,
                            correlation_id, backend, target_head, generation))
            except sqlite3.IntegrityError as exc:
                raise ValueError("dispatch_id already exists; replay refused") from exc

    def mark_terminal(self, dispatch_id: str, receipt: dict | None = None) -> bool:
        if _UUID.fullmatch(dispatch_id or ""):
            dispatch_id = str(uuid.UUID(dispatch_id))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT loop_id,correlation_id,backend,target_head,generation,terminal FROM dispatches WHERE dispatch_id=?",
                             (dispatch_id,)).fetchone()
            if row is None or row[5] or not _receipt_matches(dispatch_id, row, receipt):
                db.execute("ROLLBACK")
                return False
            db.execute("UPDATE dispatches SET terminal=1 WHERE dispatch_id=? AND terminal=0", (dispatch_id,))
            db.execute("INSERT INTO terminal_receipts(dispatch_id,receipt_json,created_at) VALUES(?,?,?)",
                       (dispatch_id, json.dumps(receipt, sort_keys=True, separators=(",", ":")), _now()))
            db.execute("COMMIT")
            return True

    def dispatch_record(self, dispatch_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT dispatch_id,expires_at,loop_id,correlation_id,backend,target_head,generation,terminal,claimed FROM dispatches WHERE dispatch_id=?",
                             (dispatch_id,)).fetchone()
        if row is None:
            return None
        keys = ("dispatch_id", "expires_at", "loop_id", "correlation_id", "backend", "target_head", "generation", "terminal", "claimed")
        return dict(zip(keys, row))

    def find_context(self, loop_id: str, correlation_id: str, generation: int) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT dispatch_id,expires_at,loop_id,correlation_id,backend,target_head,generation,terminal,claimed FROM dispatches WHERE loop_id=? AND correlation_id=? AND generation=?",
                             (loop_id, correlation_id, generation)).fetchone()
        if row is None:
            return None
        keys = ("dispatch_id", "expires_at", "loop_id", "correlation_id", "backend", "target_head", "generation", "terminal", "claimed")
        return dict(zip(keys, row))

    def terminal_receipt(self, dispatch_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT receipt_json FROM terminal_receipts WHERE dispatch_id=?", (dispatch_id,)).fetchone()
        return json.loads(row[0]) if row else None

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
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT 1 FROM dispatches WHERE dispatch_id=?", (canonical,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                return
            ordinal = db.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM evidence WHERE dispatch_id=?",
                                 (canonical,)).fetchone()[0]
            db.execute("""INSERT INTO evidence(dispatch_id,ordinal,decision,timestamp,body_sha256,
                         body_bytes,prompt_id,session_id,request_class)
                         VALUES(?,?,?,?,?,?,?,?,?)""", (
                canonical, ordinal, "DENIED_BEFORE_UPSTREAM:" + reason, _now(), sha256(body).hexdigest(),
                len(body), _safe_header(headers, "x-claude-code-prompt-id"),
                _safe_header(headers, "x-claude-code-session-id"),
                _safe_header(headers, "x-claude-code-request-class")))
            db.execute("COMMIT")

    def evidence(self, dispatch_id: str) -> list[dict]:
        with self._db() as db:
            rows = db.execute("""SELECT ordinal,decision,timestamp,body_sha256,body_bytes,
                       prompt_id,session_id,request_class,upstream_status
                       FROM evidence WHERE dispatch_id=? ORDER BY id""", (dispatch_id,)).fetchall()
        fields = ("ordinal", "decision", "timestamp", "body_sha256", "body_bytes",
                  "prompt_id", "session_id", "request_class", "upstream_status")
        return [dict(zip(fields, row)) for row in rows]


def prepare_production_store_bootstrap(*, state_dir: str, receipt_path: str,
                                      explicit_bootstrap: bool, retry: int = 0,
                                      fallback: str = "disabled",
                                      expected_store_id: str | None = None,
                                      _test_only_temp_fixture: bool = False) -> dict:
    """Validate a one-time bootstrap plan without creating any files."""
    if (explicit_bootstrap is not True or retry != 0 or fallback != "disabled"
            or expected_store_id is not None):
        return {"status": "BLOCKED", "reason": "explicit one-time bootstrap with retry=0/fallback=disabled required"}
    try:
        root = Path(state_dir)
        receipt = Path(receipt_path)
        if not root.is_absolute() or not receipt.is_absolute():
            raise ValueError("absolute state and external receipt paths are required")
        resolved_root = root.resolve(strict=True)
        resolved_receipt_parent = receipt.parent.resolve(strict=True)
        if (not resolved_root.is_dir() or resolved_root.name != "claude-gate"
                or receipt.name != "claude-gate-bootstrap-receipt.json"):
            raise ValueError("fixed state directory and bootstrap receipt filename required")
        if resolved_receipt_parent != resolved_root.parent:
            raise ValueError("bootstrap receipt must use the fixed host-control-plane sibling path")
        if receipt.is_symlink() or receipt.exists():
            raise ValueError("bootstrap receipt already exists or is a symlink")
        if list(resolved_root.iterdir()):
            raise ValueError("state directory is not empty; refuse bootstrap")
        if os.name == "nt":
            temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
            if (not _test_only_temp_fixture or not resolved_root.is_relative_to(temp_root)
                    or not resolved_receipt_parent.is_relative_to(temp_root)):
                raise ValueError("Windows production bootstrap is BLOCKED; test fixtures must remain in the OS temp root")
        else:
            st = resolved_root.stat()
            receipt_st = resolved_receipt_parent.stat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
                raise ValueError("state directory must be host-owned and private")
            if (not stat.S_ISDIR(receipt_st.st_mode) or receipt_st.st_uid != os.getuid()
                    or stat.S_IMODE(receipt_st.st_mode) & 0o077):
                raise ValueError("external receipt directory must be host-owned and private")
        return {"status": "READY", "state_dir": str(resolved_root),
                "database_path": str(resolved_root / "dispatches.sqlite3"),
                "receipt_path": str(resolved_receipt_parent / receipt.name),
                "retry": 0, "fallback": "disabled", "bootstrap_once": True}
    except (OSError, TypeError, ValueError) as exc:
        return {"status": "BLOCKED", "reason": str(exc)}


def initialize_production_store_once(*, state_dir: str, receipt_path: str,
                                     explicit_bootstrap: bool, retry: int = 0,
                                     fallback: str = "disabled",
                                     expected_store_id: str | None = None,
                                     _test_only_temp_fixture: bool = False) -> dict:
    """Create a production store only once, with an external durable replay marker.

    Any interrupted attempt leaves its exclusive receipt marker behind and must
    be resolved manually; this function never retries or repairs partial state.
    """
    plan = prepare_production_store_bootstrap(state_dir=state_dir, receipt_path=receipt_path,
                                              explicit_bootstrap=explicit_bootstrap,
                                              retry=retry, fallback=fallback,
                                              expected_store_id=expected_store_id,
                                              _test_only_temp_fixture=_test_only_temp_fixture)
    if plan["status"] != "READY":
        raise ValueError(plan["reason"])
    marker = {"schema_version": 1, "status": "INITIALIZING", "created_at": _now(),
              "state_dir_identity_sha256": sha256(plan["state_dir"].encode("utf-8")).hexdigest(),
              "database_filename": "dispatches.sqlite3", "retry": 0,
              "fallback": "disabled", "bootstrap_once": True}
    receipt_bytes = json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        fd = os.open(plan["receipt_path"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("bootstrap receipt appeared concurrently; refuse") from exc
    try:
        os.write(fd, receipt_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(Path(plan["receipt_path"]).parent)
    try:
        db_fd = os.open(plan["database_path"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(db_fd)
        _fsync_directory(Path(plan["database_path"]).parent)
        store = DispatchStore(plan["database_path"])
        if not _UUID.fullmatch(store.store_id):
            raise ValueError("initialized store returned invalid identity")
        db_hash = sha256(Path(plan["database_path"]).read_bytes()).hexdigest()
        marker.update({"status": "COMPLETE", "store_id": store.store_id,
                       "completed_at": _now(), "database_sha256": db_hash})
        completed = json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
        receipt_fd = os.open(plan["receipt_path"], os.O_WRONLY)
        try:
            os.ftruncate(receipt_fd, 0)
            os.write(receipt_fd, completed)
            os.fsync(receipt_fd)
        finally:
            os.close(receipt_fd)
        _fsync_directory(Path(plan["receipt_path"]).parent)
        return marker
    except Exception:
        # The external INITIALIZING marker permanently burns this bootstrap attempt.
        raise


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare_transport(*, dispatch_id: str, gate_base_url: str, transport_mode: str = HOST_LOOPBACK, retry: int = 0,
                      fallback: str = "disabled", live_model: bool = False,
                      external_send: bool = False) -> dict:
    """Return a non-launching env contract for future host integration."""
    if retry != 0 or fallback != "disabled" or live_model or external_send:
        return {"status": "BLOCKED", "reason": "live/retry/fallback request rejected"}
    if not _UUID.fullmatch(dispatch_id):
        return {"status": "BLOCKED", "reason": "invalid dispatch ID"}
    topology_state = "NOT_APPLICABLE"
    if transport_mode == HOST_LOOPBACK:
        valid_endpoint = _is_local_gate_url(gate_base_url)
    elif transport_mode == CONTAINER_INTERNAL:
        topology = validate_container_topology(load_container_manifest())
        topology_state = topology["status"]
        valid_endpoint = (topology_state == "PASS" and
                          gate_base_url == "http://gate:8080" and
                          _is_container_gate_url(gate_base_url))
    else:
        return {"status": "BLOCKED", "reason": "transport mode must be explicit and recognized",
                "transport_mode": transport_mode, "topology_validation_state": "NOT_RUN"}
    if not valid_endpoint:
        return {"status": "BLOCKED", "reason": "gateway URL or transport topology rejected",
                "transport_mode": transport_mode, "topology_validation_state": topology_state}
    return {"status": "PREPARED", "launch": False, "retry": 0, "fallback": "disabled",
            "live_model": False, "external_send": False,
            "transport_mode": transport_mode,
            "validated_gate_endpoint": gate_base_url,
            "topology_validation_state": topology_state,
            "env": {"ANTHROPIC_BASE_URL": gate_base_url,
                    "ANTHROPIC_CUSTOM_HEADERS": f"{DISPATCH_HEADER}: {str(uuid.UUID(dispatch_id))}",
                    "CLAUDE_CODE_GATEWAY_HINT_HEADERS": "1",
                    "CLAUDE_CODE_MAX_RETRIES": "0"}}


def make_server(*, store: DispatchStore, upstream_url: str, bind_host: str = "127.0.0.1",
                connect_timeout: float = 5.0,
                test_only_upstream_factory: Callable | None = None,
                container_mode: bool = False):
    """Create a production-pinned gate or an explicitly injected loopback test gate."""
    if container_mode:
        topology = validate_container_topology(load_container_manifest())
        if topology["status"] != "PASS" or bind_host != CONTAINER_GATE_BIND_IP:
            raise ValueError("container mode requires validated internal-only bind configuration")
        if test_only_upstream_factory is not None or not store.production:
            raise ValueError("container mode requires production store and upstream policy")
    else:
        try:
            if not ipaddress.ip_address(bind_host).is_loopback:
                raise ValueError("gate must bind to a literal loopback address")
        except ValueError as exc:
            raise ValueError("gate must bind to a literal loopback address") from exc
    try:
        upstream = urlsplit(upstream_url)
        port = upstream.port
    except ValueError as exc:
        raise ValueError("malformed upstream URL") from exc
    if test_only_upstream_factory is not None:
        try:
            loopback_upstream = ipaddress.ip_address(upstream.hostname or "").is_loopback
        except ValueError:
            loopback_upstream = False
        if (container_mode or upstream.scheme != "http" or not loopback_upstream or port is None
                or upstream.username or upstream.password or upstream.path not in {"", "/"}
                or upstream.query or upstream.fragment):
            raise ValueError("test-only upstream must be explicit plain-HTTP loopback")
        conn_factory = test_only_upstream_factory
    else:
        if (upstream.scheme != "https" or upstream.hostname != PRODUCTION_UPSTREAM_HOST
                or port not in {None, 443} or upstream.username or upstream.password
                or upstream.path not in {"", "/"} or upstream.query or upstream.fragment):
            raise ValueError("production upstream must be exactly https://api.anthropic.com:443")
        if not store.production:
            raise ValueError("production upstream requires an identity-checked production store")
        conn_factory = HTTPSConnection
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

    return ThreadingHTTPServer((bind_host, 8080 if container_mode else 0), Handler)


def _is_local_gate_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        ip = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (parsed.scheme == "http" and ip.is_loopback and port is not None and port > 0
            and parsed.username is None and parsed.password is None
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)


def _is_container_gate_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (parsed.scheme == "http" and parsed.hostname == CONTAINER_GATE_SERVICE
            and port == CONTAINER_GATE_PORT and parsed.username is None and parsed.password is None
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)


def validate_production_store_path(path: str, *, state_dir: str) -> dict:
    """Check a fixed existing host store; do not silently create/reset production state."""
    if os.name == "nt":
        raise ValueError("production ACL verification is UNKNOWN on Windows")
    try:
        root = Path(state_dir).resolve(strict=True)
        candidate = Path(path)
        if not candidate.is_absolute() or candidate.is_symlink():
            raise ValueError("production DB path must be absolute and not a symlink")
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError("production state path must already exist") from exc
    if resolved.parent != root or resolved.name != "dispatches.sqlite3":
        raise ValueError("production DB must be dispatches.sqlite3 directly under state_dir")
    file_stat, dir_stat = resolved.stat(), root.stat()
    if (not stat.S_ISREG(file_stat.st_mode) or file_stat.st_uid != os.getuid()
            or dir_stat.st_uid != os.getuid()):
        raise ValueError("production state must be regular and owned by the current host user")
    if stat.S_IMODE(file_stat.st_mode) & 0o077 or stat.S_IMODE(dir_stat.st_mode) & 0o077:
        raise ValueError("production DB and state directory must deny group/other access")
    return {"status": "PASS", "path": str(resolved), "permissions_checked": True}


def load_container_manifest() -> dict:
    return json.loads(COMPOSE_MANIFEST.read_text(encoding="utf-8"))


def validate_container_topology(manifest: dict) -> dict:
    """Fail-closed static Compose topology and isolated auth-volume contract."""
    try:
        services, networks = manifest["services"], manifest["networks"]
        claude, gate = services["claude"], services["gate"]
        auth_proxy = services["auth-control-proxy"]
        gate_bootstrap = services["gate-bootstrap"]
        auth = services["auth-bootstrap"]
        internal, egress = networks["internal"], networks["egress"]
        internal_subnet = internal["ipam"]["config"][0]["subnet"]
        gate_bind = gate["environment"]["PHASE0_GATE_BIND"]
        gate_port = gate["environment"]["PHASE0_GATE_PORT"]
        expected_store_id = gate["environment"]["PHASE0_GATE_EXPECTED_STORE_ID"]
        state_dir = gate["environment"]["PHASE0_GATE_STATE_DIR"]
        upstream_url = gate["environment"]["PHASE0_GATE_UPSTREAM_URL"]
        claude_gateway = claude["environment"]["ANTHROPIC_BASE_URL"]
        gate_ip = gate["networks"]["internal"]["ipv4_address"]
        auth_proxy_ip = auth_proxy["networks"]["internal"]["ipv4_address"]
        internal_network = ipaddress.ip_network(internal_subnet, strict=True)
        gate_ip_obj = ipaddress.ip_address(gate_ip)
        auth_proxy_ip_obj = ipaddress.ip_address(auth_proxy_ip)
    except (KeyError, TypeError, IndexError, ValueError):
        return {"status": "BLOCKED", "reason": "missing or malformed topology fields"}
    claude_networks = set(claude.get("networks", []))
    auth_proxy_networks = set(auth_proxy.get("networks", {}))
    auth_networks = set(auth.get("networks", []))
    gate_networks = set(gate.get("networks", {}))
    claude_env = claude.get("environment", {})
    auth_env = auth.get("environment", {})
    auth_proxy_env = auth_proxy.get("environment", {})
    gate_bootstrap_env = gate_bootstrap.get("environment", {})
    forbidden_env_names = {
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "ANTHROPIC_AWS_API_KEY",
        "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
        "ANTHROPIC_CUSTOM_HEADERS", "AWS_BEARER_TOKEN_BEDROCK",
        "HTTP_PROXY", "ALL_PROXY",
    }
    env_maps = [service.get("environment", {}) for service in services.values()]
    env_keys = {str(key).upper() for env in env_maps if isinstance(env, dict) for key in env}
    runtime_contract = manifest.get("x-phase0-runtime-contract", {})
    auth_volume = "claude-auth:/home/node/.claude"
    runtime_vars = {
        "CLAUDE_CODE_PROXY_RESOLVES_HOSTS": "1",
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
    checks = {
        "exact_services": set(services) == {"claude", "auth-control-proxy", "gate", "auth-bootstrap", "gate-bootstrap"},
        "claude_internal_only": claude_networks == {"internal"},
        "auth_proxy_internal_and_egress_only": auth_proxy_networks == {"internal", "egress"},
        "auth_bootstrap_egress_only": auth_networks == {"egress"},
        "gate_internal_and_egress": gate_networks == {"internal", "egress"},
        "internal_true": internal.get("internal") is True,
        "internal_bridge": internal.get("driver") == "bridge",
        "egress_is_external_bridge": egress.get("driver") == "bridge" and egress.get("internal") is not True,
        "claude_no_ports": not claude.get("ports"),
        "auth_bootstrap_no_ports": not auth.get("ports"),
        "auth_proxy_no_published_ports": not auth_proxy.get("ports"),
        "gate_no_published_ports": not gate.get("ports"),
        "no_host_network_mode": all("network_mode" not in service for service in (claude, gate, auth, auth_proxy)),
        "not_privileged": all(service.get("privileged") is False for service in (claude, gate, auth, auth_proxy, gate_bootstrap)),
        "runtime_seccomp_profile_exact": claude.get("security_opt") == [f"seccomp={RUNTIME_SECCOMP_RELATIVE_PATH}"],
        "seccomp_only_on_runtime": all("security_opt" not in service for service in (gate, auth, gate_bootstrap)),
        "no_added_capabilities": all("cap_add" not in service for service in services.values()),
        "no_claude_host_route_overrides": not any(k in claude for k in ("extra_hosts", "links")),
        "no_auth_host_route_overrides": not any(k in auth for k in ("extra_hosts", "links")),
        "gate_binds_internal_address": gate_ip == gate_bind == CONTAINER_GATE_BIND_IP and gate_ip_obj in internal_network,
        "auth_proxy_binds_internal_address": auth_proxy_ip == CONTAINER_AUTH_PROXY_BIND_IP and auth_proxy_ip_obj in internal_network and auth_proxy_ip_obj != gate_ip_obj,
        "claude_gateway_exact": claude_gateway == "http://gate:8080",
        "model_traffic_remains_on_gate": claude_gateway == "http://gate:8080" and upstream_url == "https://api.anthropic.com",
        "runtime_has_only_fixed_https_proxy": claude_env.get("HTTPS_PROXY") == "http://auth-control-proxy:3128" and claude_env.get("NO_PROXY") == "gate" and not (set(claude_env) & {"HTTP_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"}),
        "other_services_have_no_proxy_environment": all(
            not (set(service.get("environment", {})) & {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"})
            for service_name, service in services.items() if service_name != "claude"
        ),
        "auth_proxy_service_is_exact_nonroot_internal_egress": auth_proxy.get("image") == "phase0-claude-auth-control-proxy:1" and auth_proxy.get("build") == {"context": ".", "dockerfile": "docker/auth-control-plane/Dockerfile"} and auth_proxy.get("profiles") == ["human-approval-required"] and auth_proxy.get("entrypoint") == ["node", "/opt/phase0/auth_control_plane_proxy.mjs"] and auth_proxy.get("user") == "1000:1000" and auth_proxy.get("ports") == [] and auth_proxy_networks == {"internal", "egress"} and auth_proxy.get("cap_drop") == ["ALL"] and auth_proxy.get("security_opt") == ["no-new-privileges:true"],
        "auth_proxy_has_no_environment_or_mounts": auth_proxy_env == {} and "env_file" not in auth_proxy and not auth_proxy.get("volumes"),
        "gate_port_exact": gate_port == str(CONTAINER_GATE_PORT),
        "production_upstream_exact": upstream_url == "https://api.anthropic.com",
        "fixed_state_directory": state_dir == "/var/lib/phase0/claude-gate",
        "store_id_externally_supplied": expected_store_id == "${PHASE0_GATE_EXPECTED_STORE_ID:?must be externally provisioned}",
        "named_volume_mounted_at_fixed_state": gate.get("volumes") == ["gate-state:/var/lib/phase0/claude-gate"],
        "auth_volume_declared_separately": manifest.get("volumes") == {"gate-state": {}, "claude-auth": {}},
        "auth_and_runtime_share_only_fixed_auth_volume": claude.get("volumes") == [auth_volume] and auth.get("volumes") == [auth_volume],
        "all_services_are_profile_gated": all(service.get("profiles") for service in services.values()),
        "claude_image_has_local_build_target": claude.get("build") == {"context": ".", "dockerfile": "docker/claude-runtime/Dockerfile"},
        "gate_image_has_local_build_target": gate.get("build") == {"context": ".", "dockerfile": "docker/admission-gate/Dockerfile"},
        "auth_image_reuses_claude_build_target": auth.get("build") == claude.get("build"),
        "auth_bootstrap_is_human_gated_login_only": auth.get("profiles") == ["human-auth-bootstrap"] and auth.get("entrypoint") == ["claude"] and auth.get("command") == ["auth", "login"],
        "runtime_is_human_gated": claude.get("profiles") == ["human-approval-required"],
        "runtime_launcher_is_explicit_and_default_fail_closed": claude.get("profiles") == ["human-approval-required"] and claude.get("entrypoint") == ["node", "/opt/phase0/claude_runtime_launcher.mjs"] and "command" not in claude and "PHASE0_LIVE_EXECUTION" not in claude_env and "PHASE0_DISPATCH_ID" not in claude_env,
        "gate_entrypoint_is_existing_store_serve_only": gate.get("profiles") == ["human-approval-required"] and gate.get("entrypoint") == ["python3", "/opt/phase0/gate_entrypoint.py"] and gate.get("command") == ["serve"] and gate.get("environment", {}).get("PHASE0_GATE_MODE") == "OPEN_EXISTING_ONLY",
        "gate_bootstrap_profile_exact_and_not_default": gate_bootstrap.get("profiles") == ["human-gate-bootstrap"],
        "gate_bootstrap_service_fields_exact": set(gate_bootstrap) == {"image", "build", "profiles", "entrypoint", "privileged", "ports", "network_mode", "user", "volumes"},
        "gate_bootstrap_network_fully_disabled": gate_bootstrap.get("network_mode") == "none" and "networks" not in gate_bootstrap,
        "gate_bootstrap_has_no_published_ports": not gate_bootstrap.get("ports"),
        "gate_bootstrap_nonroot_identity": gate_bootstrap.get("user") == "1000:1000",
        "gate_bootstrap_uses_gate_only_image": gate_bootstrap.get("image") == gate.get("image") == "phase0-claude-gate:1" and gate_bootstrap.get("build") == gate.get("build") == {"context": ".", "dockerfile": "docker/admission-gate/Dockerfile"},
        "gate_bootstrap_entrypoint_exact_and_no_default_command": gate_bootstrap.get("entrypoint") == ["python3", "/opt/phase0/gate_bootstrap_entrypoint.py"] and "command" not in gate_bootstrap,
        "gate_bootstrap_control_mount_exact": gate_bootstrap.get("volumes", [None])[0] == "${PHASE0_GATE_CONTROL_DIR:?must be externally provisioned}:/var/lib/phase0",
        "gate_bootstrap_mounts_only_control_and_gate_state": gate_bootstrap.get("volumes") == ["${PHASE0_GATE_CONTROL_DIR:?must be externally provisioned}:/var/lib/phase0", "gate-state:/var/lib/phase0/claude-gate"],
        "gate_bootstrap_does_not_mount_auth_or_workspace": not any("claude-auth" in str(v) or "/workspace" in str(v) or str(v).startswith(("./", "../")) for v in gate_bootstrap.get("volumes", [])),
        "gate_bootstrap_environment_empty_and_no_env_file": gate_bootstrap_env == {} and "env_file" not in gate_bootstrap,
        "gate_bootstrap_cannot_generate_or_receive_expected_store_id": "PHASE0_GATE_EXPECTED_STORE_ID" not in gate_bootstrap_env and "PHASE0_GATE_EXPECTED_STORE_ID" not in str(gate_bootstrap),
        "bootstrap_and_runtime_gate_are_separate_profiles_and_paths": gate_bootstrap.get("profiles") != gate.get("profiles") and gate.get("entrypoint") == ["python3", "/opt/phase0/gate_entrypoint.py"] and gate.get("command") == ["serve"] and gate.get("volumes") == ["gate-state:/var/lib/phase0/claude-gate"] and gate.get("environment", {}).get("PHASE0_GATE_MODE") == "OPEN_EXISTING_ONLY",
        "runtime_and_gate_images_are_not_latest": claude.get("image") == auth.get("image") == "phase0-claude-runtime:2.1.283" and gate.get("image") == "phase0-claude-gate:1" and all("latest" not in str(service.get("image", "")) and "UNBUILT" not in str(service.get("image", "")) for service in services.values()),
        "fixed_nonroot_identity": claude.get("user") == auth.get("user") == "1000:1000",
        "gate_nonroot_identity": gate.get("user") == "1000:1000",
        "auth_config_dir_same_as_volume": claude_env.get("CLAUDE_CONFIG_DIR") == auth_env.get("CLAUDE_CONFIG_DIR") == "/home/node/.claude",
        "bootstrap_environment_allowlist_exact": auth_env == {
            "CLAUDE_CONFIG_DIR": "/home/node/.claude",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_UPDATES": "1",
        },
        "runtime_environment_allowlist_exact": claude_env == {"ANTHROPIC_BASE_URL": "http://gate:8080", "HTTPS_PROXY": "http://auth-control-proxy:3128", "NO_PROXY": "gate", "PHASE0_TRANSPORT_MODE": "CONTAINER_INTERNAL", **runtime_vars},
        "no_direct_credential_or_workspace_mount": not (env_keys & forbidden_env_names) and not any(str(v).startswith(("./", "../")) or "/workspace" in str(v) for service in (claude, auth, gate_bootstrap) for v in service.get("volumes", [])),
        "bootstrap_has_no_workspace_or_gate_state": auth.get("volumes") == [auth_volume],
        "gate_cannot_read_auth_volume": auth_volume not in gate.get("volumes", []),
        "runtime_retry_and_resume_contract": all(claude_env.get(k) == v for k, v in runtime_vars.items()),
        "bootstrap_has_no_injected_credentials": not (set(auth_env) & forbidden_env_names),
        "runtime_cli_contract_explicit": runtime_contract == {
            "mode": "runnable-packaging-static-unexecuted",
            "argv": ["-p", "--safe-mode", "--no-session-persistence", "--max-turns", "1", "--tools", "", "--mcp-config", "{\"mcpServers\":{}}", "--strict-mcp-config", "--permission-prompts", "none"],
            "automatic_model_fallback": "not_proven_disabled; the Admission Gate is the one-upstream-request boundary",
            "tool_scope": "all_builtin_tools_disabled; MCP denied by separate config requirement",
            "live_execution_gate": "PHASE0_LIVE_EXECUTION=1 plus dispatch metadata; absent from Compose environment",
            "default_launcher_result": "BLOCKED",
        },
        "no_extra_networks": set(networks) == {"internal", "egress"},
    }
    failed = [key for key, passed in checks.items() if not passed]
    return {"status": "PASS" if not failed else "BLOCKED", "checks": checks,
            "failed": failed,
            "claude_egress": "DENIED_BY_NETWORK_MEMBERSHIP" if not failed else "UNKNOWN"}


def validate_container_artifacts() -> dict:
    """Static, no-Docker verification of the narrowly scoped image build inputs."""
    paths = {
        "claude_dockerfile": CONTAINER_ARTIFACT_ROOT / "claude-runtime" / "Dockerfile",
        "claude_ignore": CONTAINER_ARTIFACT_ROOT / "claude-runtime" / "Dockerfile.dockerignore",
        "claude_launcher": CONTAINER_ARTIFACT_ROOT / "claude-runtime" / "claude_runtime_launcher.mjs",
        "claude_seccomp": RUNTIME_SECCOMP_PROFILE,
        "gate_dockerfile": CONTAINER_ARTIFACT_ROOT / "admission-gate" / "Dockerfile",
        "gate_ignore": CONTAINER_ARTIFACT_ROOT / "admission-gate" / "Dockerfile.dockerignore",
        "gate_entrypoint": CONTAINER_ARTIFACT_ROOT / "admission-gate" / "gate_entrypoint.py",
        "gate_bootstrap_entrypoint": CONTAINER_ARTIFACT_ROOT / "admission-gate" / "gate_bootstrap_entrypoint.py",
        "auth_proxy_dockerfile": CONTAINER_ARTIFACT_ROOT / "auth-control-plane" / "Dockerfile",
        "auth_proxy_ignore": CONTAINER_ARTIFACT_ROOT / "auth-control-plane" / "Dockerfile.dockerignore",
        "auth_proxy_source": CONTAINER_ARTIFACT_ROOT / "auth-control-plane" / "auth_control_plane_proxy.mjs",
    }
    try:
        files = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
        manifest = load_container_manifest()
        seccomp_profile = json.loads(files["claude_seccomp"])
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"status": "BLOCKED", "reason": "container artifact missing or unreadable"}

    claude_dockerfile = files["claude_dockerfile"]
    gate_dockerfile = files["gate_dockerfile"]
    launcher = files["claude_launcher"]
    gate_entrypoint = files["gate_entrypoint"]
    gate_bootstrap_entrypoint = files["gate_bootstrap_entrypoint"]
    auth_proxy_dockerfile = files["auth_proxy_dockerfile"]
    auth_proxy_source = files["auth_proxy_source"]
    launcher_args = launcher.split("args: [", 1)[1].split("],\n    env:", 1)[0] if "args: [" in launcher else ""
    claude_ignore_expected = "\n".join((
        "**", "!docker/", "!docker/claude-runtime/", "!docker/claude-runtime/Dockerfile",
        "!docker/claude-runtime/Dockerfile.dockerignore",
        "!docker/claude-runtime/claude_runtime_launcher.mjs", "",
    ))
    gate_ignore_expected = "\n".join((
        "**", "!claude_admission_gate.py", "!claude_gate_compose.yaml", "!docker/",
        "!docker/admission-gate/", "!docker/admission-gate/Dockerfile",
        "!docker/admission-gate/Dockerfile.dockerignore",
        "!docker/admission-gate/gate_entrypoint.py",
        "!docker/admission-gate/gate_bootstrap_entrypoint.py", "",
    ))
    auth_proxy_ignore_expected = "\n".join((
        "**", "!docker/", "!docker/auth-control-plane/", "!docker/auth-control-plane/Dockerfile",
        "!docker/auth-control-plane/Dockerfile.dockerignore",
        "!docker/auth-control-plane/auth_control_plane_proxy.mjs", "",
    ))
    gate_copy_lines = [line for line in gate_dockerfile.splitlines() if line.startswith("COPY ")]
    checks = {
        "all_required_artifacts_exist": all(path.is_file() for path in paths.values()),
        "claude_seccomp_profile_pinned": sha256(files["claude_seccomp"].encode("utf-8")).hexdigest() == RUNTIME_SECCOMP_SHA256,
        "claude_seccomp_default_denies": isinstance(seccomp_profile, dict) and seccomp_profile.get("defaultAction") == "SCMP_ACT_ERRNO",
        "claude_base_image_digest_pinned": "FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c" in claude_dockerfile,
        "claude_code_exact_version_pinned": "npm install --global @anthropic-ai/claude-code@2.1.283" in claude_dockerfile and "@anthropic-ai/claude-code@latest" not in claude_dockerfile,
        "claude_runs_nonroot": "USER node" in claude_dockerfile and claude_dockerfile.rstrip().endswith('ENTRYPOINT ["node", "/opt/phase0/claude_runtime_launcher.mjs"]'),
        "gate_base_image_digest_pinned": "FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254" in gate_dockerfile,
        "gate_runs_nonroot": "USER 1000:1000" in gate_dockerfile and "USER root" in gate_dockerfile,
        "gate_copies_only_minimum_runtime_files": gate_copy_lines == [
            "COPY --chown=1000:1000 claude_admission_gate.py /opt/phase0/claude_admission_gate.py",
            "COPY --chown=1000:1000 claude_gate_compose.yaml /opt/phase0/claude_gate_compose.yaml",
            "COPY --chown=1000:1000 docker/admission-gate/gate_entrypoint.py /opt/phase0/gate_entrypoint.py",
            "COPY --chown=1000:1000 docker/admission-gate/gate_bootstrap_entrypoint.py /opt/phase0/gate_bootstrap_entrypoint.py",
        ],
        "gate_has_no_claude_node_npm_or_auth_volume": not any(term in gate_dockerfile.lower() for term in ("npm", "node:", "claude-auth", "github-cli", "git install")),
        "claude_context_is_exact_allowlist": files["claude_ignore"] == claude_ignore_expected,
        "gate_context_is_exact_allowlist": files["gate_ignore"] == gate_ignore_expected,
        "auth_proxy_context_is_exact_allowlist": files["auth_proxy_ignore"] == auth_proxy_ignore_expected,
        "auth_proxy_base_image_digest_pinned": "FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c" in auth_proxy_dockerfile,
        "auth_proxy_runs_nonroot": "USER 1000:1000" in auth_proxy_dockerfile and auth_proxy_dockerfile.rstrip().endswith('ENTRYPOINT ["node", "/opt/phase0/auth_control_plane_proxy.mjs"]'),
        "auth_proxy_has_no_package_or_system_installs": not any(fragment in auth_proxy_dockerfile.lower() for fragment in ("npm", "apt-get", "curl", "wget", "adduser", "useradd")),
        "auth_proxy_exact_host_and_port_policy": 'ALLOWED_AUTH_HOST = "platform.claude.com"' in auth_proxy_source and 'ALLOWED_AUTH_AUTHORITY = `${ALLOWED_AUTH_HOST}:443`' in auth_proxy_source and 'DENIED_MODEL_AUTHORITY = "api.anthropic.com:443"' in auth_proxy_source,
        "auth_proxy_binds_only_internal_address": 'PROXY_BIND = "172.29.247.3"' in auth_proxy_source and 'PROXY_BIND = "0.0.0.0"' not in auth_proxy_source,
        "auth_proxy_only_connect_and_no_dynamic_request_logging": 'server.on("connect"' in auth_proxy_source and "console." not in auth_proxy_source and "JSON.stringify" not in auth_proxy_source,
        "auth_proxy_one_resolution_and_one_connect_no_retry": "const addresses = await resolveHost();" in auth_proxy_source and "connectAddress(selected)" in auth_proxy_source and "retry" not in auth_proxy_source.lower(),
        "launcher_has_explicit_live_gate": 'env.PHASE0_LIVE_EXECUTION !== "1"' in launcher and "default_launcher_result" in json.dumps(manifest),
        "compose_and_launcher_both_require_oauth_compatible_safe_mode": "--safe-mode" in manifest["x-phase0-runtime-contract"]["argv"] and '"--safe-mode"' in launcher_args and "--bare" not in manifest["x-phase0-runtime-contract"]["argv"] and '"--bare"' not in launcher_args,
        "launcher_preserves_bounded_cli_flags": all(fragment in launcher_args for fragment in (
            '"--no-session-persistence"', '"--max-turns", "1"', '"--tools", ""',
            '"--mcp-config", JSON.stringify({ mcpServers: {} })', '"--strict-mcp-config"',
            '"--permission-prompts", "none"',
        )),
        "launcher_checks_dispatch_retry_tools_mcp_and_gateway": all(token in launcher for token in (
            "PHASE0_DISPATCH_ID", "CLAUDE_CODE_MAX_RETRIES", "CLAUDE_CODE_MAX_TURNS",
            "ANTHROPIC_BASE_URL", "--tools", "--mcp-config", "--strict-mcp-config",
            "--no-session-persistence", "CLAUDE_CODE_SKIP_PROMPT_HISTORY",
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            "DISABLE_UPDATES", "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK",
        )),
        "launcher_has_no_client_retry": all(fragment in launcher for fragment in (
            "spawn = spawnSync",
            "spawn(invocation.executable",
            "no retry will be attempted",
        )),
        "launcher_constructs_dispatch_header": "X-Phase0-Dispatch-ID" in launcher and "ANTHROPIC_CUSTOM_HEADERS" in launcher,
        "gate_open_existing_only_no_bootstrap_or_retry": "DispatchStore.open_production" in gate_entrypoint and "OPEN_EXISTING_ONLY" in gate_entrypoint and "initialize_production_store_once" not in gate_entrypoint and "prepare_production_store_bootstrap" not in gate_entrypoint and "no bootstrap or retry" in gate_entrypoint,
        "gate_bootstrap_fixed_paths_confirmation_and_contract": all(fragment in gate_bootstrap_entrypoint for fragment in (
            'CONTROL_DIR = "/var/lib/phase0"',
            'STATE_DIR = "/var/lib/phase0/claude-gate"',
            'RECEIPT_PATH = "/var/lib/phase0/claude-gate-bootstrap-receipt.json"',
            'CONFIRMATION_ARGUMENT = "--confirm-one-time-production-bootstrap"',
            "initialize_production_store_once(", "explicit_bootstrap=True", "retry=0",
            'fallback="disabled"', "expected_store_id=None", "no retry", "os.path.ismount(CONTROL_DIR)",
            "os.path.ismount(STATE_DIR)",
        )),
        "gate_bootstrap_never_reads_or_emits_expected_id_or_credentials": not any(token in gate_bootstrap_entrypoint for token in (
            "PHASE0_GATE_EXPECTED_STORE_ID", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN", "subprocess", "Popen", "HTTPConnection", "https://",
            "print(receipt", "print(result", "print(store_id", 'receipt["store_id"]',
        )),
        "gate_bootstrap_has_no_shell_or_provider_execution": not any(token in gate_bootstrap_entrypoint for token in (
            "os.system", "create_subprocess", "subprocess", "anthropic",
        )),
        "compose_has_no_unbuilt_or_gate_false_placeholder": all("UNBUILT" not in str(s.get("image", "")) for s in manifest["services"].values()) and manifest["services"]["gate"].get("entrypoint") != ["/bin/false"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {"status": "PASS" if not failed else "BLOCKED", "checks": checks,
            "failed": failed, "artifact_paths": [str(path) for path in paths.values()]}


@dataclass(frozen=True)
class LifecycleResult:
    status: str
    reason: str
    dispatch_id: str | None = None
    transport: dict | None = None


class ClaudeDispatchLifecycle:
    """Prepare and terminalize Phase 0 Claude dispatch records without launching."""

    def __init__(self, store: DispatchStore, *, expected_store_id: str):
        self.store = store
        self.expected_store_id = expected_store_id

    def prepare(self, *, loop_id: str, correlation_id: str, generation: int,
                expires_at: str, target_head: str, gate_base_url: str,
                transport_mode: str = HOST_LOOPBACK, terminal_receipts=()) -> LifecycleResult:
        if self.store.store_id != self.expected_store_id:
            return LifecycleResult("BLOCKED", "store identity mismatch")
        if not re.fullmatch(r"[0-9a-f]{40}", target_head or ""):
            return LifecycleResult("BLOCKED", "fresh exact target head required")
        for receipt in terminal_receipts:
            if not isinstance(receipt, dict):
                return LifecycleResult("UNKNOWN", "unverifiable terminal receipt")
            same_correlation = (receipt.get("loop_id"), receipt.get("correlation_id")) == (loop_id, correlation_id)
            if same_correlation:
                receipt_generation = receipt.get("generation", receipt.get("round"))
                if (receipt_generation != generation or receipt.get("expected_target_head") != target_head
                        or receipt.get("state") not in {"CONSUMED", "SUCCEEDED", "FAILED", "UNKNOWN", "FAILED_PREPARE"}
                        or receipt.get("terminal", receipt.get("state") == "CONSUMED") is not True):
                    return LifecycleResult("BLOCKED", "command-bus terminal receipt identity mismatch")
                return LifecycleResult("NO-OP", "command-bus terminal receipt prevents replay")
        existing = self.store.find_context(loop_id, correlation_id, generation)
        if existing is not None:
            return LifecycleResult("NO-OP" if existing["terminal"] else "BLOCKED",
                                   "dispatch context already exists; never reuse its ID",
                                   existing["dispatch_id"])
        dispatch_id = str(uuid.uuid4())
        try:
            self.store.register(dispatch_id, expires_at, loop_id=loop_id,
                                correlation_id=correlation_id, backend="CLAUDE_BACKEND",
                                target_head=target_head, generation=generation)
        except (ValueError, sqlite3.Error) as exc:
            return LifecycleResult("UNKNOWN", f"registration unconfirmed: {type(exc).__name__}")
        transport = prepare_transport(dispatch_id=dispatch_id, gate_base_url=gate_base_url,
                                      transport_mode=transport_mode)
        if transport["status"] != "PREPARED":
            receipt = _terminal_record(self.store.dispatch_record(dispatch_id), dispatch_id, "FAILED_PREPARE")
            if not self.store.mark_terminal(dispatch_id, receipt):
                return LifecycleResult("UNKNOWN", "failed-preflight dispatch burn unconfirmed", dispatch_id)
            return LifecycleResult("BLOCKED", "transport failed; dispatch permanently burned", dispatch_id)
        return LifecycleResult("PREPARED", "static only; launcher not invoked", dispatch_id, transport)

    def complete_fake(self, dispatch_id: str, outcome: str) -> dict:
        if outcome not in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
            raise ValueError("explicit fake terminal outcome required")
        record = self.store.dispatch_record(dispatch_id)
        receipt = _terminal_record(record, dispatch_id, outcome)
        if not self.store.mark_terminal(dispatch_id, receipt):
            raise ValueError("terminal state mismatch; refuse replay")
        return receipt


def _terminal_record(record: dict | None, dispatch_id: str, outcome: str) -> dict:
    if record is None:
        raise ValueError("unknown dispatch")
    return {"schema_version": 1, "dispatch_id": dispatch_id, "loop_id": record["loop_id"],
            "correlation_id": record["correlation_id"], "generation": record["generation"],
            "backend": record["backend"], "expected_target_head": record["target_head"],
            "terminal": True, "state": outcome, "retry": 0, "fallback": "disabled",
            "fake_only": True}


def _receipt_matches(dispatch_id: str, row, receipt: dict | None) -> bool:
    if not isinstance(receipt, dict) or receipt.get("dispatch_id") != dispatch_id:
        return False
    expected = {"loop_id": row[0], "correlation_id": row[1], "backend": row[2],
                "expected_target_head": row[3], "generation": row[4]}
    return (all(receipt.get(key) == value for key, value in expected.items())
            and receipt.get("terminal") is True
            and receipt.get("state") in {"SUCCEEDED", "FAILED", "UNKNOWN", "FAILED_PREPARE"}
            and receipt.get("retry") == 0 and receipt.get("fallback") == "disabled")


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
