import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import socket
import threading
import unittest
from urllib.request import Request, urlopen

from automation.command_bus.probes.claude_literal_retry_zero.probe import (
    FAKE_KEY,
    ProviderState,
    classify_case,
    make_base_env,
    make_handler,
    safe_headers,
)


class ClaudeRetryProbeHarnessTests(unittest.TestCase):
    def test_duplicate_provider_request_is_fail(self):
        self.assertEqual(classify_case({"fake_provider_request_count": 2}), "FAIL")

    def test_missing_or_incomplete_observation_is_unknown(self):
        self.assertEqual(classify_case({"controller_dispatch_count": 1, "fake_provider_request_count": 1}), "UNKNOWN")
        self.assertEqual(classify_case({"controller_dispatch_count": 1, "fake_provider_request_count": 0,
                                        "process_observation_complete": True}), "UNKNOWN")

    def test_one_complete_clean_request_is_pass(self):
        self.assertEqual(classify_case({
            "controller_dispatch_count": 1,
            "fake_provider_request_count": 1,
            "process_observation_complete": True,
            "retry_or_continuation_indication": False,
            "fallback_indication": False,
        }), "PASS")

    def test_auth_header_value_is_never_recorded(self):
        recorded = safe_headers({"x-api-key": FAKE_KEY, "authorization": "Bearer not-to-log", "anthropic-version": "2023-06-01"})
        self.assertTrue(recorded["x-api-key-present"])
        self.assertTrue(recorded["authorization-present"])
        self.assertEqual(recorded["anthropic-version"], "2023-06-01")
        self.assertNotIn(FAKE_KEY, json.dumps(recorded))
        self.assertNotIn("not-to-log", json.dumps(recorded))

    def test_fake_server_records_hash_and_returns_local_sse(self):
        state = ProviderState("A")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps({"model": "fake-model", "stream": True, "max_tokens": 8, "messages": [{"role": "user", "content": "safe"}]}).encode()
            request = Request(f"http://127.0.0.1:{server.server_port}/v1/messages", data=body,
                              headers={"Content-Type": "application/json", "x-api-key": FAKE_KEY})
            with urlopen(request, timeout=3) as response:
                text = response.read().decode()
            self.assertIn("event: message_start", text)
            self.assertIn("event: message_stop", text)
            self.assertEqual(len(state.requests), 1)
            self.assertTrue(state.requests[0]["body_sha256"])
            self.assertEqual(state.requests[0]["request_model"], "fake-model")
            self.assertTrue(state.requests[0]["headers"]["x-api-key-present"])
            self.assertNotIn(FAKE_KEY, json.dumps(state.requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_error_and_truncation_fixtures_are_distinct(self):
        fixtures = {
            "B": (200, b'"stop_reason":"max_tokens"'),
            "E": (500, b"fake retryable 5xx"),
            "F": (429, b"fake 429"),
            "G": (401, b"fake auth failure"),
        }
        for case_id, (expected_status, marker) in fixtures.items():
            with self.subTest(case=case_id):
                state = ProviderState(case_id)
                server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    body = json.dumps({"model": "fake-model", "stream": True, "max_tokens": 2, "messages": []}).encode()
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    connection.request("POST", "/v1/messages", body=body, headers={"Content-Type": "application/json"})
                    response = connection.getresponse()
                    payload = response.read()
                    self.assertEqual(response.status, expected_status)
                    self.assertIn(marker, payload)
                    self.assertEqual(len(state.requests), 1)
                    self.assertEqual(state.requests[0]["response_status"], expected_status)
                    if case_id == "G":
                        connection.request("POST", "/v1/messages", body=body,
                                           headers={"Content-Type": "application/json"})
                        recovered = connection.getresponse()
                        recovered.read()
                        self.assertEqual(recovered.status, 200)
                        self.assertEqual(len(state.requests), 2)
                    connection.close()
                finally:
                    state.release_waiting_response.set()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_disconnect_fixture_has_no_terminal_sse_event(self):
        state = ProviderState("D")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps({"model": "fake-model", "stream": True, "max_tokens": 8, "messages": []}).encode()
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("POST", "/v1/messages", body=body, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            payload = response.read().decode()
            self.assertEqual(response.status, 200)
            self.assertIn("event: content_block_delta", payload)
            self.assertNotIn("event: message_stop", payload)
            self.assertIn("stream_disconnected_mid_response", state.requests[0]["connection_lifecycle"])
            connection.close()
        finally:
            state.release_waiting_response.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_no_response_and_interrupt_fixtures_withhold_response(self):
        for case_id in ("C", "H"):
            with self.subTest(case=case_id):
                state = ProviderState(case_id)
                server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=0.2)
                try:
                    body = json.dumps({"model": "fake-model", "stream": True, "messages": []}).encode()
                    connection.request("POST", "/v1/messages", body=body,
                                       headers={"Content-Type": "application/json"})
                    with self.assertRaises(socket.timeout):
                        connection.getresponse()
                    self.assertEqual(len(state.requests), 1)
                    self.assertNotIn("response_status", state.requests[0])
                finally:
                    state.release_waiting_response.set()
                    connection.close()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_runtime_environment_has_literal_zero_and_local_config_paths(self):
        env = make_base_env("/tmp/home", "/tmp/config", "/tmp/tmp")
        self.assertEqual(env["CLAUDE_CODE_MAX_RETRIES"], "0")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"], "1")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], "/tmp/config")
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_workflow_is_read_only_and_network_none_scoped(self):
        root = Path(__file__).resolve().parents[3]
        workflow = (root / ".github/workflows/claude-literal-retry-zero-probe.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("--network none", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("GITHUB_TOKEN=", workflow)


if __name__ == "__main__":
    unittest.main()
