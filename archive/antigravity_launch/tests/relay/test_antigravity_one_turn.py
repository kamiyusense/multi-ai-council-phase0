# 使用停止中・実行禁止（規約上の理由、2026-10）
# SUSPENDED - DO NOT RUN (Antigravity terms, 2026-10). Archived from the Relay; see archive/antigravity_launch/README.md.
"""Antigravity one-turn runner: STATIC tests with a fake ACP server only (no real binary, no provider, no login)."""
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from relay import antigravity_one_turn as turn

FAKE_SERVER = r'''#!{python}
import json, sys
log = open({log!r}, "a", encoding="utf-8")
auth_ids = {auth_ids!r}
mode = {mode!r}
def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method", "?")
    params = msg.get("params") or {{}}
    log.write(method + ":" + str(params.get("methodId", "")) + ("|" + params["prompt"][0]["text"] if method == "session/prompt" else "") + "\n"); log.flush()
    if method == "initialize":
        send({{"jsonrpc": "2.0", "id": msg["id"], "result": {{"protocolVersion": 1, "agentInfo": {{"name": "agy_acp_server", "version": "9.9.9"}},
              "authMethods": [{{"id": i}} for i in auth_ids], "agentCapabilities": {{"loadSession": True}}}}}})
    elif method == "authenticate":
        if mode == "auth_error":
            send({{"jsonrpc": "2.0", "id": msg["id"], "error": {{"code": -32000, "message": "secret.person@example.invalid"}}}})
        else:
            send({{"jsonrpc": "2.0", "id": msg["id"], "result": {{}}}})
    elif method == "session/new":
        send({{"jsonrpc": "2.0", "id": msg["id"], "result": {{"sessionId": "s-1"}}}})
    elif method == "session/prompt":
        if mode == "permission_request":
            send({{"jsonrpc": "2.0", "id": 77, "method": "session/request_permission", "params": {{}}}})
        else:
            text = "AGY_OK" if mode != "wrong_text" else "something else secret.person@example.invalid"
            send({{"jsonrpc": "2.0", "method": "session/update", "params": {{"sessionId": "s-1",
                  "update": {{"sessionUpdate": "agent_message_chunk", "content": {{"type": "text", "text": text}}}}}}}})
            send({{"jsonrpc": "2.0", "id": msg["id"], "result": {{"stopReason": "end_turn"}}}})
    else:
        send({{"jsonrpc": "2.0", "id": msg.get("id"), "error": {{"code": -32601, "message": "no"}}}})
'''


@unittest.skipIf(os.name == "nt", "fake server is a POSIX script named like the Linux binary")
class OneTurnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agy turn "))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log, self.state, self.decl = self.tmp / "server.log", self.tmp / "state", self.tmp / "decl.json"
        self.binary = self.tmp / "agy_acp_server.par"
        self.lines: list[str] = []
        self.make_binary()

    def make_binary(self, auth_ids=("oauth-personal", "gemini-api-key"), mode="ok"):
        self.binary.write_text(FAKE_SERVER.format(python=sys.executable, log=str(self.log), auth_ids=list(auth_ids),
                                                  mode=mode), encoding="utf-8")
        self.binary.chmod(0o755)
        self.sha = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.write_declaration()

    def write_declaration(self, **changes):
        record = turn.build_declaration(self.sha, "test note", datetime.now(timezone.utc) - timedelta(minutes=1), 2)
        body = {k: v for k, v in record.items() if k != "declaration_sha256"}
        body.update(changes)
        body["declaration_sha256"] = record["declaration_sha256"] if not changes else turn.canonical_sha256(body)
        self.decl.write_text(json.dumps(body), encoding="utf-8")

    def run_turn(self, answer=None):
        phrase = f"{turn.RUN_PHRASE_PREFIX} {self.sha[:7]}" if answer is None else answer
        return turn.run(self.binary, self.sha, self.decl, self.state, confirm=lambda _p: phrase, out=self.lines.append,
                        platform_name="linux", architecture="x86_64")

    def calls(self):
        return self.log.read_text(encoding="utf-8").split("\n")[:-1] if self.log.exists() else []

    def receipt(self):
        return json.loads((self.state / turn.RECEIPT_FILE).read_text(encoding="utf-8"))

    def test_success_sends_each_step_once_and_stores_no_answer_text(self):
        self.assertEqual(self.run_turn(), 0)
        self.assertEqual(self.calls(), ["initialize:", "authenticate:oauth-personal", "session/new:", "session/prompt:|" + turn.PROMPT_TEXT])
        receipt = self.receipt()
        self.assertEqual((receipt["terminal_state"], receipt["stage_reached"], receipt["response_was_expected"]), ("ONE_TURN_DONE", "DONE", True))
        self.assertEqual((receipt["authenticate_count"], receipt["session_new_count"], receipt["prompt_count"], receipt["retry_count"]), (1, 1, 1, 0))
        self.assertEqual(receipt["fallback_state"], "disabled")
        self.assertNotIn("AGY_OK\"", json.dumps(receipt))

    def test_wrong_answer_is_recorded_as_a_mismatch_without_the_text(self):
        self.make_binary(mode="wrong_text")
        self.assertEqual(self.run_turn(), 0)
        receipt = self.receipt()
        self.assertFalse(receipt["response_was_expected"])
        self.assertEqual(json.dumps(receipt).count("secret.person"), 0)

    def test_authenticate_error_stops_before_session_and_prompt(self):
        self.make_binary(mode="auth_error")
        self.assertEqual(self.run_turn(), 1)
        self.assertEqual(self.calls(), ["initialize:", "authenticate:oauth-personal"])
        receipt = self.receipt()
        self.assertEqual((receipt["stage_reached"], receipt["prompt_count"]), ("AUTHENTICATE", 0))
        self.assertEqual(json.dumps(receipt).count("secret.person"), 0)

    def test_method_not_offered_sends_nothing_further(self):
        self.make_binary(auth_ids=("gemini-api-key", "agent-platform"))
        self.assertEqual(self.run_turn(), 0)
        self.assertEqual(self.calls(), ["initialize:"])
        self.assertEqual(self.receipt()["stage_reached"], "METHOD_NOT_OFFERED")

    def test_tool_permission_request_is_never_answered_and_ends_the_run(self):
        self.make_binary(mode="permission_request")
        self.assertEqual(self.run_turn(), 1)
        self.assertEqual(self.calls().count("session/prompt:|" + turn.PROMPT_TEXT), 1)
        self.assertEqual(self.receipt()["terminal_state"], "UNKNOWN_ERROR")

    def test_declaration_problems_stop_before_the_approval_prompt_and_any_process(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        past_end = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        long_end = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        cases = {"expired": dict(declared_at=past, expires_at=past_end), "too long": dict(expires_at=long_end),
                 "billing unknown": dict(billing_route="unknown"), "api key": dict(auth_method="api_key"),
                 "not owner": dict(declared_by="claude"), "other binary": dict(binary_sha256="0" * 64)}
        for name, changes in cases.items():
            with self.subTest(name):
                self.write_declaration(**changes)
                asked = []
                code = turn.run(self.binary, self.sha, self.decl, self.state, confirm=lambda p: asked.append(p) or "",
                                out=self.lines.append, platform_name="linux", architecture="x86_64")
                self.assertEqual((code, asked, self.calls()), (2, [], []))
        self.decl.write_text(json.dumps({**json.loads(self.decl.read_text()), "billing_route": "subscription"}), encoding="utf-8")
        self.assertEqual(self.run_turn(), 2)  # tampered digest
        self.decl.unlink()
        self.assertEqual(self.run_turn(), 2)  # missing file

    def test_second_run_is_noop_and_consumed_without_receipt_is_unknown(self):
        self.assertEqual(self.run_turn(), 0)
        self.log.unlink()
        self.assertEqual(self.run_turn(), 0)
        self.assertEqual(self.calls(), [])
        (self.state / turn.RECEIPT_FILE).unlink()
        self.assertEqual(self.run_turn(), 3)
        self.assertEqual(self.calls(), [])

    def test_wrong_phrases_start_nothing_and_consume_nothing(self):
        for answer in ("yes", f"APPROVE_ANTIGRAVITY_LOGIN_ONLY {self.sha[:7]}", f"APPROVE_ANTIGRAVITY_INITIALIZE_PROBE {self.sha[:7]}"):
            self.assertEqual(self.run_turn(answer=answer), 5)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.state / turn.CONSUMED_FILE).exists())

    def test_declare_writes_a_valid_short_lived_declaration_once(self):
        fresh = self.tmp / "new_decl.json"
        phrase = f"{turn.DECLARE_PHRASE_PREFIX} {self.sha[:7]}"
        kwargs = dict(out=self.lines.append, platform_name="linux", architecture="x86_64")
        self.assertEqual(turn.declare(self.binary, self.sha, fresh, "note", 1, confirm=lambda _p: "yes", **kwargs), 5)
        self.assertFalse(fresh.exists())
        self.assertEqual(turn.declare(self.binary, self.sha, fresh, "note", 5, confirm=lambda _p: phrase, **kwargs), 2)  # > 4 h
        self.assertEqual(turn.declare(self.binary, self.sha, fresh, "note", 1, confirm=lambda _p: phrase, **kwargs), 0)
        turn.check_declaration(json.loads(fresh.read_text()), self.sha, datetime.now(timezone.utc))
        self.assertEqual(turn.declare(self.binary, self.sha, fresh, "note", 1, confirm=lambda _p: phrase, **kwargs), 2)  # no overwrite


class StaticGuardTests(unittest.TestCase):
    def test_each_protocol_step_has_exactly_one_call_site(self):
        path = Path(__file__).resolve().parents[2] / "src" / "relay" / "antigravity_one_turn.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)]
        for name in ("_acp_initialize", "_acp_exchange", "_acp_new_session", "_acp_prompt_text", "spawn_stdio_transport"):
            self.assertEqual(calls.count(name), 1, name)
        constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse(constants & {"gemini-api-key", "agent-platform", "oauth-business"})
        self.assertEqual(turn.ALLOWED_METHOD_ID, "oauth-personal")


if __name__ == "__main__":
    unittest.main()
