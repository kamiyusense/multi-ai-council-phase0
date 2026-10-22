# 使用停止中・実行禁止（規約上の理由、2026-10）
# SUSPENDED - DO NOT RUN (Antigravity terms, 2026-10). Archived from the Relay; see archive/antigravity_launch/README.md.
"""Antigravity login-only probe: STATIC tests with a fake ACP server only (no real binary, no provider, no login)."""
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from relay import antigravity_login_probe as probe

FAKE_SERVER = r'''#!{python}
import json, sys, time
log = open({log!r}, "a", encoding="utf-8")
auth_ids = {auth_ids!r}
auth_mode = {auth_mode!r}
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method", "?")
    log.write(method + ":" + str((msg.get("params") or {{}}).get("methodId", "")) + "\n"); log.flush()
    if method == "initialize":
        sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg["id"], "result": {{
            "protocolVersion": 1, "agentInfo": {{"name": "agy_acp_server", "version": "9.9.9"}},
            "authMethods": [{{"id": i}} for i in auth_ids], "agentCapabilities": {{"loadSession": True}}}}}}) + "\n")
        sys.stdout.flush()
    elif method == "authenticate":
        if auth_mode == "hang":
            time.sleep(30)
        elif auth_mode == "error":
            sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg["id"], "error": {{"code": -32000, "message": "secret.person@example.invalid"}}}}) + "\n")
        else:
            sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg["id"], "result": {{"account": "secret.person@example.invalid"}}}}) + "\n")
        sys.stdout.flush()
    else:
        sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg.get("id"), "error": {{"code": -32601, "message": "no"}}}}) + "\n")
        sys.stdout.flush()
'''


@unittest.skipIf(os.name == "nt", "fake server is a POSIX script named like the Linux binary")
class LoginProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agy login "))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = self.tmp / "server.log"
        self.state = self.tmp / "state"
        self.lines: list[str] = []
        self.binary = self.tmp / "agy_acp_server.par"
        self.sha = self.make_binary()

    def make_binary(self, auth_ids=("oauth-personal", "gemini-api-key"), auth_mode="ok"):
        self.binary.write_text(FAKE_SERVER.format(python=sys.executable, log=str(self.log), auth_ids=list(auth_ids),
                                                  auth_mode=auth_mode), encoding="utf-8")
        self.binary.chmod(0o755)
        self.sha = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        return self.sha

    def run_probe(self, answer=None, sha=None, binary=None, auth_timeout=10):
        phrase = f"{probe.PHRASE_PREFIX} {self.sha[:7]}" if answer is None else answer
        return probe.run(binary or self.binary, sha or self.sha, self.state, confirm=lambda _p: phrase,
                         out=self.lines.append, platform_name="linux", architecture="x86_64",
                         init_timeout=10, auth_timeout=auth_timeout)

    def server_calls(self):
        return self.log.read_text(encoding="utf-8").split() if self.log.exists() else []

    def receipt(self):
        return json.loads((self.state / probe.RECEIPT_FILE).read_text(encoding="utf-8"))

    def test_success_sends_initialize_then_one_oauth_personal_authenticate_only(self):
        self.assertEqual(self.run_probe(), 0)
        self.assertEqual(self.server_calls(), ["initialize:", "authenticate:oauth-personal"])
        receipt = self.receipt()
        self.assertEqual(receipt["authenticate_state"], "AUTHENTICATE_OK")
        self.assertEqual(receipt["authenticate_count"], 1)
        for key in ("session_new_count", "prompt_count", "model_generations", "retry_count"):
            self.assertEqual(receipt[key], 0)
        self.assertEqual(receipt["fallback_state"], "disabled")
        self.assertEqual(json.dumps(receipt).count("secret.person"), 0)

    def test_method_not_offered_sends_no_authenticate(self):
        self.make_binary(auth_ids=("gemini-api-key", "agent-platform"))
        self.assertEqual(self.run_probe(), 0)
        self.assertEqual(self.server_calls(), ["initialize:"])
        receipt = self.receipt()
        self.assertEqual(receipt["authenticate_state"], "METHOD_NOT_OFFERED")
        self.assertEqual(receipt["authenticate_count"], 0)

    def test_authenticate_error_is_terminal_classified_and_not_retried(self):
        self.make_binary(auth_mode="error")
        self.assertEqual(self.run_probe(), 1)
        self.assertEqual(self.server_calls(), ["initialize:", "authenticate:oauth-personal"])
        receipt = self.receipt()
        self.assertEqual(receipt["authenticate_state"], "AUTHENTICATE_FAILED")
        self.assertEqual(receipt["retry_count"], 0)
        self.assertEqual(json.dumps(receipt).count("secret.person"), 0)

    def test_authenticate_timeout_is_terminal(self):
        self.make_binary(auth_mode="hang")
        self.assertEqual(self.run_probe(auth_timeout=1), 1)
        self.assertEqual(self.receipt()["authenticate_state"], "AUTHENTICATE_TIMEOUT")
        self.assertEqual(self.server_calls().count("authenticate:oauth-personal"), 1)

    def test_second_run_is_noop_and_does_not_start_the_binary(self):
        self.assertEqual(self.run_probe(), 0)
        self.log.unlink()
        self.assertEqual(self.run_probe(), 0)
        self.assertEqual(self.server_calls(), [])

    def test_wrong_approval_or_other_probes_phrase_starts_nothing_and_consumes_nothing(self):
        self.assertEqual(self.run_probe(answer="yes"), 5)
        self.assertEqual(self.run_probe(answer=f"APPROVE_ANTIGRAVITY_INITIALIZE_PROBE {self.sha[:7]}"), 5)
        self.assertEqual(self.server_calls(), [])
        self.assertFalse((self.state / probe.CONSUMED_FILE).exists())

    def test_hash_mismatch_and_bad_inputs_stop_before_approval_prompt(self):
        asked = []
        code = probe.run(self.binary, "0" * 64, self.state, confirm=lambda p: asked.append(p) or "", out=self.lines.append,
                         platform_name="linux", architecture="x86_64")
        self.assertEqual(code, 2)
        self.assertEqual(asked, [])
        self.assertEqual(self.run_probe(sha="ABC"), 2)
        self.assertEqual(self.server_calls(), [])

    def test_consumed_without_receipt_is_unknown_and_never_rerun(self):
        self.state.mkdir()
        (self.state / probe.CONSUMED_FILE).write_text("{}", encoding="utf-8")
        self.assertEqual(self.run_probe(), 3)
        self.assertEqual(self.server_calls(), [])


class StaticGuardTests(unittest.TestCase):
    def source_tree(self):
        path = Path(__file__).resolve().parents[2] / "src" / "relay" / "antigravity_login_probe.py"
        return ast.parse(path.read_text(encoding="utf-8"))

    def test_module_never_sends_session_or_prompt_requests(self):
        tree = self.source_tree()
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertEqual(imported & {"_acp_new_session", "_acp_prompt_text", "acp_initialize_wire", "_acp_handshake"}, set())
        self.assertFalse(names & {"_acp_new_session", "_acp_prompt_text", "_acp_handshake"})
        constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse(constants & {"session/new", "session/prompt", "gemini-api-key", "agent-platform", "oauth-business"})

    def test_authenticate_is_sent_once_and_only_with_the_admitted_method(self):
        tree = self.source_tree()
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_acp_exchange"]
        self.assertEqual(len(calls), 1)  # the single authenticate round-trip (initialize uses _acp_initialize)
        self.assertEqual(probe.ALLOWED_METHOD_ID, "oauth-personal")

    def test_allowed_method_matches_route_admission(self):
        from providers.policy import antigravity_route_admission  # noqa: F401  (import proves the admission gate exists)
        import inspect
        self.assertIn("oauth-personal", inspect.getsource(sys.modules["providers.policy"]))


if __name__ == "__main__":
    unittest.main()
