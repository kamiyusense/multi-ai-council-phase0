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
CONTAINER_GATE_SERVICE = "gate"
CONTAINER_GATE_PORT = 8080
HOST_LOOPBACK = "HOST_LOOPBACK"
CONTAINER_INTERNAL = "CONTAINER_INTERNAL"
COMPOSE_MANIFEST = Path(__file__).with_name("claude_gate_compose.yaml")
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

    def __init__(self, path: str, *, _production_open: bool = False):
        self.path = path
        self.production = _production_open
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
        store = cls(path, _production_open=True)
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
    """Fail-closed validator for Claude-isolated/Gate-egress Compose topology."""
    try:
        services, networks = manifest["services"], manifest["networks"]
        claude, gate = services["claude"], services["gate"]
        internal, egress = networks["internal"], networks["egress"]
        internal_subnet = internal["ipam"]["config"][0]["subnet"]
        gate_bind = gate["environment"]["PHASE0_GATE_BIND"]
        gate_port = gate["environment"]["PHASE0_GATE_PORT"]
        expected_store_id = gate["environment"]["PHASE0_GATE_EXPECTED_STORE_ID"]
        state_dir = gate["environment"]["PHASE0_GATE_STATE_DIR"]
        upstream_url = gate["environment"]["PHASE0_GATE_UPSTREAM_URL"]
        claude_gateway = claude["environment"]["ANTHROPIC_BASE_URL"]
        gate_ip = gate["networks"]["internal"]["ipv4_address"]
        internal_network = ipaddress.ip_network(internal_subnet, strict=True)
        gate_ip_obj = ipaddress.ip_address(gate_ip)
    except (KeyError, TypeError, IndexError, ValueError):
        return {"status": "BLOCKED", "reason": "missing or malformed topology fields"}
    claude_networks = set(claude.get("networks", []))
    gate_networks = set(gate.get("networks", {}))
    checks = {
        "exact_services": set(services) == {"claude", "gate"},
        "claude_internal_only": claude_networks == {"internal"},
        "gate_internal_and_egress": gate_networks == {"internal", "egress"},
        "internal_true": internal.get("internal") is True,
        "internal_bridge": internal.get("driver") == "bridge",
        "egress_is_external_bridge": egress.get("driver") == "bridge" and egress.get("internal") is not True,
        "claude_no_ports": not claude.get("ports"),
        "gate_no_published_ports": not gate.get("ports"),
        "no_host_network_mode": all("network_mode" not in service for service in (claude, gate)),
        "not_privileged": all(service.get("privileged") is False for service in (claude, gate)),
        "no_claude_host_route_overrides": not any(k in claude for k in ("extra_hosts", "links")),
        "gate_binds_internal_address": gate_ip == gate_bind == CONTAINER_GATE_BIND_IP and gate_ip_obj in internal_network,
        "claude_gateway_exact": claude_gateway == "http://gate:8080",
        "gate_port_exact": gate_port == str(CONTAINER_GATE_PORT),
        "production_upstream_exact": upstream_url == "https://api.anthropic.com",
        "fixed_state_directory": state_dir == "/var/lib/phase0/claude-gate",
        "store_id_externally_supplied": expected_store_id == "${PHASE0_GATE_EXPECTED_STORE_ID:?must be externally provisioned}",
        "named_volume_mounted_at_fixed_state": gate.get("volumes") == ["gate-state:/var/lib/phase0/claude-gate"],
        "no_extra_networks": set(networks) == {"internal", "egress"},
    }
    failed = [key for key, passed in checks.items() if not passed]
    return {"status": "PASS" if not failed else "BLOCKED", "checks": checks,
            "failed": failed,
            "claude_egress": "DENIED_BY_NETWORK_MEMBERSHIP" if not failed else "UNKNOWN"}


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
