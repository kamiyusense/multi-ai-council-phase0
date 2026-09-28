from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Event, Lock
import time
import unittest
import uuid
from unittest.mock import patch

from automation.command_bus import claude_admission_gate as gate_module
from automation.command_bus.claude_admission_gate import (
    CONTAINER_INTERNAL, HOST_LOOPBACK, ClaudeDispatchLifecycle, DispatchStore,
    initialize_production_store_once, load_container_manifest, make_server,
    prepare_production_store_bootstrap,
    prepare_transport, validate_container_artifacts, validate_container_topology,
)

_BOOTSTRAP_ENTRYPOINT_PATH = (Path(__file__).resolve().parents[1] / "docker" / "admission-gate"
                              / "gate_bootstrap_entrypoint.py")
_BOOTSTRAP_ENTRYPOINT_SPEC = importlib.util.spec_from_file_location(
    "gate_bootstrap_entrypoint", _BOOTSTRAP_ENTRYPOINT_PATH)
gate_bootstrap_entrypoint = importlib.util.module_from_spec(_BOOTSTRAP_ENTRYPOINT_SPEC)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    _BOOTSTRAP_ENTRYPOINT_SPEC.loader.exec_module(gate_bootstrap_entrypoint)
finally:
    sys.path.pop(0)


class FakeProvider:
    def __init__(self, status=200, body=b'{"ok":true}', streaming=False, delay=False):
        self.hits = 0
        self.lock = Lock()
        self.status = status
        self.body = body
        self.streaming = streaming
        self.first_chunk = Event()
        self.allow_rest = Event()
        self.received_body = None
        self.received_headers = None
        self.stall = False

        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *_):
                return

            def do_POST(self):
                with owner.lock:
                    owner.hits += 1
                    owner.received_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    owner.received_headers = {key.lower(): value for key, value in self.headers.items()}
                if owner.stall:
                    owner.allow_rest.wait(4)
                    return
                self.send_response(owner.status)
                if owner.streaming:
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b"data: chunk1\n\n")
                    self.wfile.flush()
                    owner.first_chunk.set()
                    owner.allow_rest.wait(2)
                    self.wfile.write(b"data: chunk2\n\ndata: chunk3\n\n")
                    self.wfile.flush()
                else:
                    self.send_header("Content-Length", str(len(owner.body)))
                    self.end_headers()
                    if owner.body:
                        self.wfile.write(owner.body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"


class AdmissionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "gate.sqlite3")
        self.store = DispatchStore(self.db)
        self.provider = FakeProvider()
        self.gate = make_server(store=self.store, upstream_url=self.provider.url,
                                connect_timeout=2.5, test_only_upstream_factory=HTTPConnection)
        self.gate_thread = __import__("threading").Thread(target=self.gate.serve_forever, daemon=True)
        self.provider_thread = __import__("threading").Thread(target=self.provider.server.serve_forever, daemon=True)
        self.gate_thread.start()
        self.provider_thread.start()
        self.dispatch = str(uuid.uuid4())
        self.register()

    def tearDown(self):
        self.gate.shutdown()
        self.provider.server.shutdown()
        self.gate.server_close()
        self.provider.server.server_close()
        self.temp.cleanup()

    def register(self, dispatch=None, expires=None):
        actual = dispatch or self.dispatch
        self.store.register(actual,
                            expires or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                            loop_id="test-loop", correlation_id=f"test-correlation-{actual}",
                            backend="CLAUDE_BACKEND", target_head="a" * 40, generation=1)

    def matching_receipt(self, dispatch=None):
        actual = dispatch or self.dispatch
        record = self.store.dispatch_record(actual)
        return {"dispatch_id": actual, "loop_id": record["loop_id"],
                "correlation_id": record["correlation_id"], "backend": record["backend"],
                "expected_target_head": record["target_head"], "generation": record["generation"],
                "terminal": True, "state": "FAILED", "retry": 0, "fallback": "disabled"}

    def request(self, *, path="/v1/messages", method="POST", dispatch=None, body=b'{"prompt":"fake"}', headers=None):
        conn = HTTPConnection("127.0.0.1", self.gate.server_port, timeout=4)
        h = dict(headers or {})
        h["Content-Length"] = str(len(body))
        if dispatch is not None:
            h["X-Phase0-Dispatch-ID"] = dispatch
        conn.request(method, path, body=body if method == "POST" else None, headers=h)
        response = conn.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        conn.close()
        return result

    def test_01_first_generation_is_forwarded_once(self):
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 200)
        self.assertEqual(self.provider.hits, 1)

    def test_02_second_generation_denied_before_upstream(self):
        self.request(dispatch=self.dispatch)
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 429)
        self.assertEqual(self.provider.hits, 1)

    def test_03_concurrent_same_dispatch_only_one_admitted(self):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: self.request(dispatch=self.dispatch)[0], range(10)))
        self.assertEqual(results.count(200), 1)
        self.assertEqual(results.count(429), 9)
        self.assertEqual(self.provider.hits, 1)
        self.assertEqual([item["ordinal"] for item in self.store.evidence(self.dispatch)], list(range(1, 11)))

    def test_04_missing_dispatch_denied(self):
        self.assertEqual(self.request()[0], 429)
        self.assertEqual(self.provider.hits, 0)

    def test_05_malformed_dispatch_denied(self):
        self.assertEqual(self.request(dispatch="not-a-uuid")[0], 429)
        self.assertEqual(self.provider.hits, 0)

    def test_06_unknown_dispatch_denied(self):
        self.assertEqual(self.request(dispatch=str(uuid.uuid4()))[0], 429)
        self.assertEqual(self.provider.hits, 0)

    def test_07_terminal_dispatch_denied(self):
        self.assertTrue(self.store.mark_terminal(self.dispatch, self.matching_receipt()))
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 429)
        self.assertEqual(self.provider.hits, 0)

    def test_expired_registered_dispatch_is_denied_before_upstream(self):
        with self.store._db() as db:
            db.execute("UPDATE dispatches SET expires_at=? WHERE dispatch_id=?",
                       ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), self.dispatch))
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 429)
        self.assertEqual(self.provider.hits, 0)

    def test_08_count_tokens_denied_locally_without_budget_use(self):
        self.assertEqual(self.request(path="/v1/messages/count_tokens", dispatch=self.dispatch)[0], 403)
        self.assertEqual(self.provider.hits, 0)
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 200)

    def test_09_head_health_is_local_and_free(self):
        self.assertEqual(self.request(method="HEAD", path="/api/hello")[0], 204)
        self.assertEqual(self.provider.hits, 0)
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 200)

    def test_10_unknown_path_fails_closed(self):
        self.assertEqual(self.request(path="/other", dispatch=self.dispatch)[0], 404)
        self.assertEqual(self.provider.hits, 0)

    def test_11_body_is_byte_identical(self):
        body = b'{ "message" : "FAKE-PRIVATE-BODY" }'
        self.request(dispatch=self.dispatch, body=body)
        self.assertEqual(self.provider.received_body, body)

    def test_12_anthropic_beta_preserved(self):
        self.request(dispatch=self.dispatch, headers={"anthropic-beta": "beta-a,beta-b"})
        self.assertEqual(self.provider.received_headers["anthropic-beta"], "beta-a,beta-b")

    def test_13_anthropic_version_preserved(self):
        self.request(dispatch=self.dispatch, headers={"anthropic-version": "2023-06-01"})
        self.assertEqual(self.provider.received_headers["anthropic-version"], "2023-06-01")

    def test_14_auth_header_is_not_logged(self):
        self.request(dispatch=self.dispatch, headers={"Authorization": "Bearer FAKE-SECRET"})
        serialized = json.dumps(self.store.evidence(self.dispatch))
        self.assertNotIn("FAKE-SECRET", serialized)

    def test_15_body_plaintext_is_not_logged_hash_only(self):
        self.request(dispatch=self.dispatch, body=b"PRIVATE-FAKE-TEXT")
        serialized = json.dumps(self.store.evidence(self.dispatch))
        self.assertNotIn("PRIVATE-FAKE-TEXT", serialized)
        self.assertIn("body_sha256", serialized)

    def test_16_stream_is_forwarded_incrementally_and_in_order(self):
        self.provider.streaming = True
        first_read = Event()
        client_result = {}

        def read_stream():
            conn = HTTPConnection("127.0.0.1", self.gate.server_port, timeout=4)
            conn.request("POST", "/v1/messages", body=b"{}", headers={
                "Content-Length": "2", "X-Phase0-Dispatch-ID": self.dispatch})
            response = conn.getresponse()
            client_result["status"] = response.status
            client_result["headers"] = dict(response.getheaders())
            if response.status != 200:
                client_result["error_body"] = response.read()
                first_read.set()
                conn.close()
                return
            client_result["first"] = response.read(14)
            first_read.set()
            client_result["rest"] = response.read()
            conn.close()

        worker = __import__("threading").Thread(target=read_stream, daemon=True)
        worker.start()
        self.assertTrue(self.provider.first_chunk.wait(1))
        self.assertTrue(first_read.wait(1))
        self.assertEqual(client_result["first"], b"data: chunk1\n\n", repr(client_result) + repr(self.provider.received_headers))
        self.provider.allow_rest.set()
        worker.join(3)
        self.assertEqual(client_result["status"], 200)
        self.assertEqual(client_result["first"] + client_result["rest"],
                         b"data: chunk1\n\ndata: chunk2\n\ndata: chunk3\n\n")
        self.assertEqual(self.provider.hits, 1)

    def test_17_upstream_500_is_not_retried(self):
        self.provider.status = 500
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 500)
        self.assertEqual(self.provider.hits, 1)

    def test_18_upstream_429_is_not_retried(self):
        self.provider.status = 429
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 429)
        self.assertEqual(self.provider.hits, 1)

    def test_19_upstream_disconnect_is_not_retried(self):
        self.provider.body = b""
        original = self.provider.server.RequestHandlerClass
        del original
        self.provider.status = 200
        # A refused/closed upstream after local admission still consumes the slot.
        self.provider.server.shutdown()
        status = self.request(dispatch=self.dispatch)[0]
        self.assertEqual(status, 502)
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 429)

    def test_20_denial_has_retry_suppression_metadata(self):
        self.request(dispatch=self.dispatch)
        status, headers, _ = self.request(dispatch=self.dispatch)
        self.assertEqual(status, 429)
        self.assertEqual(headers["x-should-retry"], "false")
        self.assertEqual(headers["retry-after"], "61")
        evidence = self.store.evidence(self.dispatch)
        self.assertEqual(evidence[-1]["decision"], "DENIED_BEFORE_UPSTREAM:generation_budget_exhausted")

    def test_21_prompt_id_is_optional(self):
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 200)

    def test_22_claude_metadata_does_not_authorize_dispatch(self):
        headers = {"x-claude-code-prompt-id": self.dispatch,
                   "x-claude-code-session-id": self.dispatch,
                   "x-claude-code-request-class": "main"}
        self.assertEqual(self.request(headers=headers)[0], 429)
        self.assertEqual(self.provider.hits, 0)

    def test_23_distinct_dispatches_have_independent_budgets(self):
        other = str(uuid.uuid4())
        self.register(dispatch=other)
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 200)
        self.assertEqual(self.request(dispatch=other)[0], 200)
        self.assertEqual(self.provider.hits, 2)

    def test_24_store_restart_preserves_claim_and_expiry_is_fail_closed(self):
        self.request(dispatch=self.dispatch)
        reopened = DispatchStore(self.db)
        self.store = reopened
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 429)
        stale = str(uuid.uuid4())
        with self.assertRaises(ValueError):
            self.register(dispatch=stale, expires=(datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat())

    def test_25_prepare_transport_is_static_and_explicit(self):
        prepared = prepare_transport(dispatch_id=self.dispatch, gate_base_url="http://127.0.0.1:8080",
                                    retry=0, fallback="disabled")
        self.assertEqual(prepared["status"], "PREPARED")
        self.assertFalse(prepared["launch"])
        self.assertIn("X-Phase0-Dispatch-ID", prepared["env"]["ANTHROPIC_CUSTOM_HEADERS"])
        self.assertEqual(prepare_transport(dispatch_id=self.dispatch, gate_base_url="http://127.0.0.1:1",
                                           live_model=True)["status"], "BLOCKED")

    def test_26_non_loopback_bind_is_rejected(self):
        with self.assertRaises(ValueError):
            make_server(store=self.store, upstream_url=self.provider.url, bind_host="0.0.0.0",
                        test_only_upstream_factory=HTTPConnection)

    def test_27_duplicate_registration_is_rejected(self):
        with self.assertRaises(ValueError):
            self.register()

    def test_28_admission_evidence_has_hash_and_metadata_not_secret(self):
        self.request(dispatch=self.dispatch, headers={"x-claude-code-request-class": "main",
                                                     "Authorization": "FAKE-SECRET"})
        evidence = self.store.evidence(self.dispatch)[0]
        self.assertEqual(evidence["decision"], "ADMITTED")
        self.assertEqual(evidence["request_class"], "main")
        self.assertNotIn("authorization", evidence)

    def test_29_upstream_timeout_consumes_slot_without_retry(self):
        self.provider.stall = True
        status = self.request(dispatch=self.dispatch)[0]
        self.assertEqual(status, 502)
        self.assertEqual(self.provider.hits, 1)
        self.assertEqual(self.request(dispatch=self.dispatch)[0], 429)
        self.assertEqual(self.provider.hits, 1)

    def test_gate_url_accepts_literal_loopback_only(self):
        for url in ("http://127.0.0.1:8080", "http://[::1]:8080/"):
            with self.subTest(url=url):
                result = prepare_transport(dispatch_id=self.dispatch, gate_base_url=url,
                                           transport_mode=HOST_LOOPBACK)
                self.assertEqual(result["status"], "PREPARED")
                self.assertEqual(result["transport_mode"], HOST_LOOPBACK)
                self.assertEqual(result["validated_gate_endpoint"], url)
                self.assertEqual(result["topology_validation_state"], "NOT_APPLICABLE")
        for url in ("https://example.com", "http://10.0.0.1:8080", "http://192.168.1.4:8080",
                    "http://public-host:8080", "http://localhost:8080", "http://user@127.0.0.1:8080",
                    "http://127.0.0.1:8080/path", "http://127.0.0.1:8080/?q=x",
                    "http://127.0.0.1:8080/#fragment", "http://127.0.0.1:0",
                    "http://[::1]:8080/%2e%2e"):
            with self.subTest(url=url):
                self.assertEqual(prepare_transport(dispatch_id=self.dispatch, gate_base_url=url)["status"], "BLOCKED")

    def test_container_transport_requires_exact_manifest_endpoint_and_pass(self):
        result = prepare_transport(dispatch_id=self.dispatch, gate_base_url="http://gate:8080",
                                   transport_mode=CONTAINER_INTERNAL)
        self.assertEqual(result["status"], "PREPARED")
        self.assertEqual(result["transport_mode"], CONTAINER_INTERNAL)
        self.assertEqual(result["validated_gate_endpoint"], "http://gate:8080")
        self.assertEqual(result["topology_validation_state"], "PASS")
        self.assertFalse(result["live_model"])
        self.assertFalse(result["external_send"])
        for url in ("http://gate:8081", "http://other-service:8080", "http://10.0.0.2:8080",
                    "http://192.168.1.2:8080", "http://8.8.8.8:8080", "http://user@gate:8080",
                    "http://gate:8080/path", "http://gate:8080/?q=x"):
            with self.subTest(url=url):
                self.assertEqual(prepare_transport(dispatch_id=self.dispatch, gate_base_url=url,
                                                   transport_mode=CONTAINER_INTERNAL)["status"], "BLOCKED")

    def test_transport_mode_unknown_blocks_and_default_is_host_loopback(self):
        self.assertEqual(prepare_transport(dispatch_id=self.dispatch,
                                           gate_base_url="http://127.0.0.1:8080")["transport_mode"], HOST_LOOPBACK)
        for mode in (None, "UNKNOWN", "container_internal"):
            if mode is None:
                continue  # omitted mode intentionally retains safe HOST_LOOPBACK default
            self.assertEqual(prepare_transport(dispatch_id=self.dispatch, gate_base_url="http://gate:8080",
                                               transport_mode=mode)["status"], "BLOCKED")

    def test_container_transport_fails_when_fresh_manifest_drifted(self):
        bad = load_container_manifest()
        bad["services"]["claude"]["environment"]["ANTHROPIC_BASE_URL"] = "http://other:8080"
        with patch("automation.command_bus.claude_admission_gate.load_container_manifest", return_value=bad):
            result = prepare_transport(dispatch_id=self.dispatch, gate_base_url="http://gate:8080",
                                       transport_mode=CONTAINER_INTERNAL)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["topology_validation_state"], "BLOCKED")

    def test_production_upstream_is_exact_anthropic_https_origin(self):
        for url in ("http://api.anthropic.com", "https://example.com", "https://api.anthropic.com:444",
                    "https://user@api.anthropic.com", "https://api.anthropic.com/v1",
                    "https://api.anthropic.com/?q=1", "https://api.anthropic.com/#frag"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                make_server(store=self.store, upstream_url=url)
        with self.assertRaises(ValueError):
            make_server(store=self.store, upstream_url="https://api.anthropic.com")

    def test_fake_upstream_requires_explicit_test_factory_and_loopback(self):
        server = make_server(store=self.store, upstream_url=self.provider.url,
                             test_only_upstream_factory=HTTPConnection)
        server.server_close()
        for url in ("http://10.1.2.3:8080", "http://localhost:8080", "http://127.0.0.1:8080/prefix",
                    "http://127.0.0.1:8080/?q=1", "http://user@127.0.0.1:8080"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                make_server(store=self.store, upstream_url=url,
                            test_only_upstream_factory=HTTPConnection)

    def test_docker_manifest_is_valid_and_mutations_fail_closed(self):
        manifest = load_container_manifest()
        self.assertEqual(validate_container_topology(manifest)["status"], "PASS")
        artifact_result = validate_container_artifacts()
        self.assertEqual(artifact_result["status"], "PASS", artifact_result)
        self.assertTrue(all(artifact_result["checks"].values()))
        cases = []
        bad = deepcopy(manifest)
        bad["services"]["claude"]["networks"].append("egress")
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["networks"]["internal"]["internal"] = False
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["gate"]["ports"] = ["8080:8080"]
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["gate"]["networks"].pop("internal")
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["gate"]["networks"].pop("egress")
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["auth-control-proxy"]["networks"].pop("egress")
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["auth-control-proxy"]["ports"] = ["3128:3128"]
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["auth-control-proxy"]["volumes"] = ["claude-auth:/home/node/.claude"]
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["claude"]["network_mode"] = "host"
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["claude"]["privileged"] = True
        cases.append(bad)
        for mutate in (
            lambda s: s["claude"].update(security_opt=["seccomp=unconfined"]),
            lambda s: s["claude"].update(security_opt=["seccomp=./other.json"]),
            lambda s: s["claude"]["security_opt"].append("apparmor=unconfined"),
            lambda s: s["claude"].update(cap_add=["SYS_ADMIN"]),
            lambda s: s["gate"].update(security_opt=s["claude"]["security_opt"]),
            lambda s: s["auth-bootstrap"].update(security_opt=s["claude"]["security_opt"]),
            lambda s: s["gate-bootstrap"].update(security_opt=s["claude"]["security_opt"]),
        ):
            bad = deepcopy(manifest)
            mutate(bad["services"])
            cases.append(bad)
        for path, value in (("ANTHROPIC_BASE_URL", "http://other-service:8080"),
                            ("PHASE0_GATE_BIND", "0.0.0.0"), ("PHASE0_GATE_PORT", "8081")):
            bad = deepcopy(manifest)
            service = "claude" if path == "ANTHROPIC_BASE_URL" else "gate"
            bad["services"][service]["environment"][path] = value
            cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["claude"]["environment"]["HTTPS_PROXY"] = "http://attacker.example:3128"
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["claude"]["environment"]["NO_PROXY"] = "*"
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["auth-control-proxy"]["environment"] = {"HTTPS_PROXY": "http://other:3128"}
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["gate"]["environment"]["PHASE0_GATE_EXPECTED_STORE_ID"] = "self-generated"
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["gate"]["volumes"] = ["gate-state:/other/path"]
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["gate"]["entrypoint"] = ["/bin/false"]
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["claude"]["profiles"] = []
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["claude"]["build"]["dockerfile"] = "../Dockerfile"
        cases.append(bad)
        bad = deepcopy(manifest)
        bad["services"]["gate"]["environment"]["PHASE0_GATE_MODE"] = "BOOTSTRAP"
        cases.append(bad)
        mutations = [
            lambda m: m["services"]["auth-bootstrap"].update(profiles=["default"]),
            lambda m: m["services"]["auth-bootstrap"].update(image="user-image:latest"),
            lambda m: m["services"]["auth-bootstrap"].update(entrypoint=["sh", "-c"]),
            lambda m: m["services"]["auth-bootstrap"].update(command=["-p", "do work"]),
            lambda m: m["services"]["auth-bootstrap"].update(networks=["internal", "egress"]),
            lambda m: m["services"]["auth-bootstrap"].update(volumes=["claude-auth:/home/node/.claude", ".:/workspace"]),
            lambda m: m["services"]["auth-bootstrap"]["environment"].update(CLAUDE_CODE_OAUTH_TOKEN="fake-only"),
            lambda m: m["services"]["claude"]["environment"].update(ANTHROPIC_API_KEY="fake-only"),
            lambda m: m["services"]["claude"]["environment"].update(ANTHROPIC_DEFAULT_MODEL="fallback-candidate"),
            lambda m: m["services"]["claude"]["environment"].update(CLAUDE_CONFIG_DIR="/root/.claude"),
            lambda m: m["services"]["claude"].update(volumes=["claude-auth:/home/node/.claude", "gate-state:/var/lib/phase0/claude-gate"]),
            lambda m: m["services"]["gate"].update(volumes=["gate-state:/var/lib/phase0/claude-gate", "claude-auth:/home/node/.claude"]),
            lambda m: m["volumes"].update({"claude-auth": {"external": True}}),
            lambda m: m["services"]["claude"]["environment"].update(CLAUDE_CODE_MAX_RETRIES="1"),
            lambda m: m["x-phase0-runtime-contract"].update(argv=["-p", "--resume"]),
        ]
        for mutate in mutations:
            bad = deepcopy(manifest)
            mutate(bad)
            cases.append(bad)
        for item in cases:
            with self.subTest(item=item):
                self.assertEqual(validate_container_topology(item)["status"], "BLOCKED")

    def test_seccomp_profile_content_is_pinned(self):
        original = gate_module.RUNTIME_SECCOMP_PROFILE.read_text(encoding="utf-8")
        self.assertEqual(validate_container_artifacts()["status"], "PASS")
        with tempfile.TemporaryDirectory() as root:
            changed = Path(root) / "seccomp.json"
            changed.write_text(original.replace('"value": 268566545', '"value": 268566546', 1), encoding="utf-8")
            self.assertNotEqual(changed.read_text(encoding="utf-8"), original)
            with patch.object(gate_module, "RUNTIME_SECCOMP_PROFILE", changed):
                result = validate_container_artifacts()
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("claude_seccomp_profile_pinned", result["failed"])

    def test_gate_bootstrap_topology_mutations_fail_closed(self):
        manifest = load_container_manifest()
        cases = []
        for mutate in (
            lambda m: m["services"]["gate-bootstrap"].update(profiles=["human-approval-required"]),
            lambda m: m["services"]["gate-bootstrap"].update(network_mode="bridge"),
            lambda m: m["services"]["gate-bootstrap"].update(networks={"egress": {}}),
            lambda m: m["services"]["gate-bootstrap"].update(ports=["8080:8080"]),
            lambda m: m["services"]["gate-bootstrap"].update(privileged=True),
            lambda m: m["services"]["gate-bootstrap"].update(user="0:0"),
            lambda m: m["services"]["gate-bootstrap"].update(entrypoint=["sh", "-c"]),
            lambda m: m["services"]["gate-bootstrap"].update(command=["serve"]),
            lambda m: m["services"]["gate-bootstrap"].update(
                volumes=["${PHASE0_GATE_CONTROL_DIR:?must be externally provisioned}:/var/lib/phase0",
                         "claude-auth:/home/node/.claude"]),
            lambda m: m["services"]["gate-bootstrap"].update(
                volumes=["./:/var/lib/phase0", "gate-state:/var/lib/phase0/claude-gate"]),
            lambda m: m["services"]["gate-bootstrap"].update(
                volumes=["${PHASE0_GATE_CONTROL_DIR:?must be externally provisioned}:/var/lib/phase0",
                         "gate-state:/other/path"]),
            lambda m: m["services"]["gate-bootstrap"].update(environment={"ANTHROPIC_API_KEY": "FAKE_ONLY"}),
            lambda m: m["services"]["gate-bootstrap"].update(environment={"PHASE0_GATE_EXPECTED_STORE_ID": "self-generated"}),
            lambda m: m["services"]["gate-bootstrap"].update(env_file=["runtime.env"]),
            lambda m: m["services"]["gate-bootstrap"].update(secrets=["unexpected-secret"]),
            lambda m: m["services"]["gate-bootstrap"].update(image="phase0-claude-runtime:2.1.283"),
            lambda m: m["services"]["gate"].update(profiles=["human-gate-bootstrap"]),
            lambda m: m["services"]["gate"].update(volumes=["other-state:/var/lib/phase0/claude-gate"]),
            lambda m: m["services"]["gate"]["environment"].update(PHASE0_GATE_MODE="BOOTSTRAP"),
        ):
            bad = deepcopy(manifest)
            mutate(bad)
            cases.append(bad)
        for item in cases:
            with self.subTest(item=item):
                self.assertEqual(validate_container_topology(item)["status"], "BLOCKED")

    def test_gate_bootstrap_entrypoint_requires_explicit_confirmation_and_calls_once(self):
        with patch.object(gate_bootstrap_entrypoint, "initialize_production_store_once") as initialize:
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(gate_bootstrap_entrypoint.main([]), 64)
            initialize.assert_not_called()
            self.assertIn("no bootstrap attempted", stderr.getvalue())

        fake_store_id = "123e4567-e89b-12d3-a456-426614174000"
        with patch.object(gate_bootstrap_entrypoint, "initialize_production_store_once",
                          return_value={"status": "COMPLETE", "retry": 0,
                                        "fallback": "disabled", "bootstrap_once": True,
                                        "store_id": fake_store_id}) as initialize:
            with patch.object(gate_bootstrap_entrypoint.os.path, "ismount", return_value=True) as ismount:
                stdout = StringIO()
                with redirect_stdout(stdout):
                    self.assertEqual(gate_bootstrap_entrypoint.main([
                        gate_bootstrap_entrypoint.CONFIRMATION_ARGUMENT]), 0)
                ismount.assert_any_call("/var/lib/phase0")
                ismount.assert_any_call("/var/lib/phase0/claude-gate")
                initialize.assert_called_once_with(
                    state_dir="/var/lib/phase0/claude-gate",
                    receipt_path="/var/lib/phase0/claude-gate-bootstrap-receipt.json",
                    explicit_bootstrap=True,
                    retry=0,
                    fallback="disabled",
                    expected_store_id=None,
                )
                self.assertNotIn(fake_store_id, stdout.getvalue())

    def test_gate_bootstrap_blocks_without_both_mountpoints(self):
        with patch.object(gate_bootstrap_entrypoint, "initialize_production_store_once") as initialize:
            with patch.object(gate_bootstrap_entrypoint.os.path, "ismount",
                              side_effect=lambda path: path == "/var/lib/phase0"):
                stderr = StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(gate_bootstrap_entrypoint.main([
                        gate_bootstrap_entrypoint.CONFIRMATION_ARGUMENT]), 78)
            initialize.assert_not_called()
            self.assertIn("no retry", stderr.getvalue())

    def test_compose_and_actual_launcher_share_bounded_cli_flags(self):
        manifest = load_container_manifest()
        declared = manifest["x-phase0-runtime-contract"]["argv"]
        launcher_path = Path(__file__).resolve().parents[1] / "docker" / "claude-runtime" / "claude_runtime_launcher.mjs"
        launcher = launcher_path.read_text(encoding="utf-8")
        self.assertIn("--safe-mode", declared)
        self.assertNotIn("--bare", declared)
        self.assertIn('env.PHASE0_LIVE_EXECUTION !== "1"', launcher)
        launcher_args = launcher.split("args: [", 1)[1].split("],\n    env:", 1)[0]
        self.assertIn('"--safe-mode"', launcher_args)
        self.assertNotIn('"--bare"', launcher_args)
        for fragment in (
            '"--tools", ""',
            '"--mcp-config", JSON.stringify({ mcpServers: {} })',
            '"--strict-mcp-config"',
            '"--permission-prompts", "none"',
            '"--no-session-persistence"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, launcher)
        artifact_checks = validate_container_artifacts()["checks"]
        self.assertTrue(artifact_checks["compose_and_launcher_both_require_oauth_compatible_safe_mode"])
        self.assertTrue(artifact_checks["launcher_preserves_bounded_cli_flags"])

    def test_lifecycle_prepares_then_fake_terminal_receipt_blocks_replay(self):
        lifecycle = ClaudeDispatchLifecycle(self.store, expected_store_id=self.store.store_id)
        prepared = lifecycle.prepare(loop_id="loop-a", correlation_id="corr-a", generation=4,
                                     expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                     target_head="c" * 40, gate_base_url="http://127.0.0.1:8080")
        self.assertEqual(prepared.status, "PREPARED")
        self.assertFalse(prepared.transport["launch"])
        record = self.store.dispatch_record(prepared.dispatch_id)
        self.assertEqual((record["loop_id"], record["correlation_id"], record["generation"], record["target_head"]),
                         ("loop-a", "corr-a", 4, "c" * 40))
        receipt = lifecycle.complete_fake(prepared.dispatch_id, "FAILED")
        self.assertEqual(self.store.terminal_receipt(prepared.dispatch_id), receipt)
        self.assertEqual(self.store.claim(prepared.dispatch_id, b"{}", {}).decision, "DENIED_BEFORE_UPSTREAM")
        local_duplicate = lifecycle.prepare(loop_id="loop-a", correlation_id="corr-a", generation=4,
                                            expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                            target_head="c" * 40, gate_base_url="http://127.0.0.1:8080")
        self.assertEqual(local_duplicate.status, "NO-OP")
        replay = lifecycle.prepare(loop_id="loop-a", correlation_id="corr-a", generation=4,
                                   expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                   target_head="c" * 40, gate_base_url="http://127.0.0.1:8080",
                                   terminal_receipts=[receipt])
        self.assertEqual(replay.status, "NO-OP")

    def test_lifecycle_transport_mode_change_cannot_create_replay_escape(self):
        lifecycle = ClaudeDispatchLifecycle(self.store, expected_store_id=self.store.store_id)
        kwargs = dict(loop_id="mode-loop", correlation_id="mode-corr", generation=1,
                      expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                      target_head="a" * 40)
        first = lifecycle.prepare(**kwargs, gate_base_url="http://127.0.0.1:8080",
                                  transport_mode=HOST_LOOPBACK)
        self.assertEqual(first.status, "PREPARED")
        replay = lifecycle.prepare(**kwargs, gate_base_url="http://gate:8080",
                                   transport_mode=CONTAINER_INTERNAL)
        self.assertEqual(replay.status, "BLOCKED")
        self.assertEqual(replay.dispatch_id, first.dispatch_id)

    def test_lifecycle_container_mode_uses_same_static_gate_contract(self):
        lifecycle = ClaudeDispatchLifecycle(self.store, expected_store_id=self.store.store_id)
        result = lifecycle.prepare(loop_id="container-loop", correlation_id="container-corr", generation=1,
                                   expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                   target_head="b" * 40, gate_base_url="http://gate:8080",
                                   transport_mode=CONTAINER_INTERNAL)
        self.assertEqual(result.status, "PREPARED")
        self.assertEqual(result.transport["topology_validation_state"], "PASS")
        self.assertEqual(result.transport["env"]["ANTHROPIC_BASE_URL"], "http://gate:8080")

    def test_lifecycle_consumes_existing_executor_terminal_receipt_shape(self):
        lifecycle = ClaudeDispatchLifecycle(self.store, expected_store_id=self.store.store_id)
        existing_receipt = {"schema_version": 1, "receipt_id": "executor-result-9",
                            "execution_receipt_id": "executor-result-9", "result_id": "result-9",
                            "execution_result_id": "result-9", "request_id": "request-9",
                            "execution_request_id": "request-9", "state": "CONSUMED",
                            "loop_id": "loop-existing", "round": 3,
                            "correlation_id": "corr-existing", "expected_target_head": "f" * 40}
        result = lifecycle.prepare(loop_id="loop-existing", correlation_id="corr-existing", generation=3,
                                   expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                   target_head="f" * 40, gate_base_url="http://127.0.0.1:8080",
                                   terminal_receipts=[existing_receipt])
        self.assertEqual(result.status, "NO-OP")

    def test_lifecycle_failed_preflight_burns_dispatch_and_bad_receipt_blocks(self):
        lifecycle = ClaudeDispatchLifecycle(self.store, expected_store_id=self.store.store_id)
        result = lifecycle.prepare(loop_id="loop-b", correlation_id="corr-b", generation=1,
                                   expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                   target_head="d" * 40, gate_base_url="https://remote.invalid")
        self.assertEqual(result.status, "BLOCKED")
        record = self.store.dispatch_record(result.dispatch_id)
        self.assertTrue(record["terminal"])
        self.assertIsNotNone(self.store.terminal_receipt(result.dispatch_id))
        self.assertEqual(lifecycle.prepare(loop_id="loop-b", correlation_id="corr-b", generation=1,
                                           expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                           target_head="d" * 40, gate_base_url="http://127.0.0.1:8080",
                                           terminal_receipts=[{"loop_id": "loop-b", "correlation_id": "corr-b",
                                                               "generation": 1, "expected_target_head": "x" * 40,
                                                               "terminal": True}]).status, "BLOCKED")
        self.assertFalse(self.store.mark_terminal(result.dispatch_id, {"state": "SUCCEEDED"}))

    def test_lifecycle_store_identity_mismatch_blocks(self):
        lifecycle = ClaudeDispatchLifecycle(self.store, expected_store_id=str(uuid.uuid4()))
        result = lifecycle.prepare(loop_id="loop-c", correlation_id="corr-c", generation=1,
                                   expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                                   target_head="e" * 40, gate_base_url="http://127.0.0.1:8080")
        self.assertEqual(result.status, "BLOCKED")

    def test_production_database_refuses_missing_or_temporary_path(self):
        missing = str(Path(self.temp.name) / "dispatches.sqlite3")
        with self.assertRaises(ValueError):
            DispatchStore.open_production(missing, state_dir=self.temp.name,
                                          expected_store_id=self.store.store_id)
        self.assertFalse(Path(missing).exists())
        with self.assertRaises(ValueError):
            DispatchStore.open_production(self.db, state_dir=self.temp.name,
                                          expected_store_id=self.store.store_id)
        with self.assertRaises(ValueError):
            DispatchStore.open_production(self.db, state_dir=self.temp.name,
                                          expected_store_id=str(uuid.uuid4()))


class ProductionStoreBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / "claude-gate"
        self.state.mkdir()
        os.chmod(self.state, 0o700)
        self.receipt = self.root / "claude-gate-bootstrap-receipt.json"

    def tearDown(self):
        self.temp.cleanup()

    def initialize(self):
        return initialize_production_store_once(state_dir=str(self.state), receipt_path=str(self.receipt),
                                                explicit_bootstrap=True, retry=0, fallback="disabled",
                                                _test_only_temp_fixture=os.name == "nt")

    def test_empty_state_bootstraps_once_with_external_receipt_and_uuid(self):
        plan = prepare_production_store_bootstrap(state_dir=str(self.state), receipt_path=str(self.receipt),
                                                  explicit_bootstrap=True,
                                                  _test_only_temp_fixture=os.name == "nt")
        self.assertEqual(plan["status"], "READY")
        result = self.initialize()
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["retry"], 0)
        self.assertEqual(result["fallback"], "disabled")
        self.assertTrue(result["bootstrap_once"])
        self.assertEqual(str(uuid.UUID(result["store_id"])), result["store_id"])
        self.assertEqual(len(result["database_sha256"]), 64)
        stored_receipt = json.loads(self.receipt.read_text(encoding="utf-8"))
        self.assertEqual(stored_receipt, result)
        with closing(sqlite3.connect(self.state / "dispatches.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT value FROM store_meta WHERE key='store_id'").fetchone()[0],
                             result["store_id"])

    def test_open_existing_only_accepts_expected_id_or_blocks_on_windows_acl(self):
        result = self.initialize()
        path = str(self.state / "dispatches.sqlite3")
        if os.name == "nt":
            with self.assertRaisesRegex(ValueError, "ACL verification"):
                DispatchStore.open_production(path, state_dir=str(self.state), expected_store_id=result["store_id"])
        else:
            opened = DispatchStore.open_production(path, state_dir=str(self.state), expected_store_id=result["store_id"])
            self.assertEqual(opened.store_id, result["store_id"])
        with self.assertRaises(ValueError):
            DispatchStore.open_production(path, state_dir=str(self.state), expected_store_id=str(uuid.uuid4()))

    def test_second_bootstrap_and_db_deletion_after_receipt_are_refused(self):
        self.initialize()
        with self.assertRaises(ValueError):
            self.initialize()
        (self.state / "dispatches.sqlite3").unlink()
        with self.assertRaises(ValueError):
            self.initialize()
        self.assertFalse((self.state / "dispatches.sqlite3").exists())

    def test_existing_db_or_unknown_state_content_is_refused(self):
        (self.state / "unrecognized.bin").write_bytes(b"existing")
        self.assertEqual(prepare_production_store_bootstrap(state_dir=str(self.state),
                                                            receipt_path=str(self.receipt),
                                                            explicit_bootstrap=True)["status"], "BLOCKED")
        self.assertFalse(self.receipt.exists())
        (self.state / "unrecognized.bin").unlink()
        DispatchStore(str(self.state / "dispatches.sqlite3"))
        with self.assertRaises(ValueError):
            self.initialize()

    def test_missing_db_with_existing_receipt_and_normal_open_never_bootstrap(self):
        self.receipt.write_text('{"status":"INITIALIZING"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.initialize()
        missing = self.state / "dispatches.sqlite3"
        with self.assertRaises(ValueError):
            DispatchStore.open_production(str(missing), state_dir=str(self.state),
                                          expected_store_id=str(uuid.uuid4()))
        self.assertFalse(missing.exists())

    @unittest.skipUnless(os.name != "nt", "POSIX-only read-only production schema check")
    def test_normal_production_open_refuses_incomplete_schema_without_migration(self):
        path = self.state / "dispatches.sqlite3"
        store_id = str(uuid.uuid4())
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE store_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO store_meta VALUES('store_id',?)", (store_id,))
            db.commit()
        os.chmod(path, 0o600)
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            DispatchStore.open_production(str(path), state_dir=str(self.state), expected_store_id=store_id)
        self.assertEqual(path.read_bytes(), before)

    def test_intent_retry_and_fallback_guards_refuse_without_side_effects(self):
        for kwargs in ({"explicit_bootstrap": False}, {"explicit_bootstrap": True, "retry": 1},
                       {"explicit_bootstrap": True, "fallback": "enabled"},
                       {"explicit_bootstrap": True, "expected_store_id": str(uuid.uuid4())}):
            result = prepare_production_store_bootstrap(state_dir=str(self.state), receipt_path=str(self.receipt),
                                                        **kwargs)
            self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(list(self.state.iterdir()), [])
        self.assertFalse(self.receipt.exists())

    def test_interrupted_bootstrap_marker_burns_attempt_without_retry(self):
        with patch("automation.command_bus.claude_admission_gate.DispatchStore",
                   side_effect=RuntimeError("simulated init failure")):
            with self.assertRaises(RuntimeError):
                self.initialize()
        self.assertTrue(self.receipt.exists())
        self.assertEqual(json.loads(self.receipt.read_text(encoding="utf-8"))["status"], "INITIALIZING")
        with self.assertRaises(ValueError):
            self.initialize()

    @unittest.skipUnless(os.name == "nt", "Windows-only production bootstrap ACL boundary")
    def test_windows_production_path_bootstrap_is_blocked(self):
        result = prepare_production_store_bootstrap(state_dir=str(self.state), receipt_path=str(self.receipt),
                                                    explicit_bootstrap=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(self.receipt.exists())
        self.assertEqual(list(self.state.iterdir()), [])

    def test_bootstrap_receipt_path_is_fixed_sibling_not_caller_selectable(self):
        alternate = self.root / "other-control" / "claude-gate-bootstrap-receipt.json"
        alternate.parent.mkdir()
        result = prepare_production_store_bootstrap(state_dir=str(self.state), receipt_path=str(alternate),
                                                    explicit_bootstrap=True,
                                                    _test_only_temp_fixture=os.name == "nt")
        self.assertEqual(result["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
