from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Event, Lock
import time
import unittest
import uuid

from automation.command_bus.claude_admission_gate import DispatchStore, make_server, prepare_transport


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
        self.gate = make_server(store=self.store, upstream_url=self.provider.url, connect_timeout=2.5)
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
        self.store.register(dispatch or self.dispatch,
                            expires or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

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
        self.store.mark_terminal(self.dispatch)
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
            make_server(store=self.store, upstream_url=self.provider.url, bind_host="0.0.0.0")

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


if __name__ == "__main__":
    unittest.main()
