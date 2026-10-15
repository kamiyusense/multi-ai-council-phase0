"""Antigravity initialize-only probe: STATIC tests with a fake ACP server only (no real binary, no provider)."""
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from relay import antigravity_initialize_probe as probe

FAKE_SERVER = r'''#!{python}
import json, sys
log = open({log!r}, "a", encoding="utf-8")
for line in sys.stdin:
    msg = json.loads(line)
    log.write(msg.get("method", "?") + "\n"); log.flush()
    if msg.get("method") == "initialize":
        sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg["id"], "result": {{
            "protocolVersion": 1, "agentInfo": {{"name": "agy_acp_server", "version": "9.9.9"}},
            "authMethods": [{{"id": "oauth-personal"}}, {{"id": "gemini-api-key"}}, {{"id": "secret.person@example.invalid"[:0] + "agent-platform"}}],
            "agentCapabilities": {{"loadSession": True, "promptCapabilities": {{"image": True}}}}}}}}) + "\n")
        sys.stdout.flush()
    else:
        sys.stdout.write(json.dumps({{"jsonrpc": "2.0", "id": msg.get("id"), "error": {{"code": -32601, "message": "no"}}}}) + "\n")
        sys.stdout.flush()
'''


@unittest.skipIf(os.name == "nt", "fake server is a POSIX script named like the Linux binary")
class InitializeProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agy probe "))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = self.tmp / "server.log"
        self.binary = self.tmp / "agy_acp_server.par"
        self.binary.write_text(FAKE_SERVER.format(python=sys.executable, log=str(self.log)), encoding="utf-8")
        self.binary.chmod(0o755)
        self.sha = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.state = self.tmp / "state"
        self.lines: list[str] = []

    def run_probe(self, answer=None, sha=None, binary=None):
        phrase = f"{probe.PHRASE_PREFIX} {self.sha[:7]}" if answer is None else answer
        return probe.run(binary or self.binary, sha or self.sha, self.state, confirm=lambda _p: phrase,
                         out=self.lines.append, platform_name="linux", architecture="x86_64", timeout=10)

    def server_methods(self):
        return self.log.read_text(encoding="utf-8").split() if self.log.exists() else []

    def test_success_sends_initialize_only_and_writes_one_receipt(self):
        self.assertEqual(self.run_probe(), 0)
        self.assertEqual(self.server_methods(), ["initialize"])
        receipt = json.loads((self.state / probe.RECEIPT_FILE).read_text(encoding="utf-8"))
        self.assertEqual(receipt["terminal_state"], "INITIALIZE_OK")
        self.assertEqual(receipt["auth_method_ids"], ["agent-platform", "gemini-api-key", "oauth-personal"])
        self.assertEqual(receipt["agent_version"], "9.9.9")
        self.assertEqual(receipt["capability_flags"], {"loadSession": True})
        for key in ("authenticate_count", "session_new_count", "prompt_count", "model_generations", "retry_count"):
            self.assertEqual(receipt[key], 0)
        self.assertEqual(receipt["fallback_state"], "disabled")
        self.assertEqual(receipt["binary_sha256"], self.sha)

    def test_second_run_is_noop_and_does_not_start_the_binary(self):
        self.assertEqual(self.run_probe(), 0)
        self.log.unlink()
        self.assertEqual(self.run_probe(), 0)
        self.assertEqual(self.server_methods(), [])

    def test_wrong_approval_starts_nothing_and_consumes_nothing(self):
        self.assertEqual(self.run_probe(answer="yes"), 5)
        self.assertEqual(self.server_methods(), [])
        self.assertFalse((self.state / probe.CONSUMED_FILE).exists())

    def test_hash_mismatch_stops_before_approval_prompt(self):
        asked = []
        code = probe.run(self.binary, "0" * 64, self.state, confirm=lambda p: asked.append(p) or "", out=self.lines.append,
                         platform_name="linux", architecture="x86_64")
        self.assertEqual(code, 2)
        self.assertEqual(asked, [])
        self.assertEqual(self.server_methods(), [])

    def test_bad_expected_sha_and_wrong_binary_name_stop(self):
        self.assertEqual(self.run_probe(sha="ABC"), 2)
        other = self.tmp / "something_else.par"
        shutil.copy(self.binary, other)
        self.assertEqual(self.run_probe(binary=other), 2)
        self.assertEqual(self.server_methods(), [])

    def test_consumed_without_receipt_is_unknown_and_never_rerun(self):
        self.state.mkdir()
        (self.state / probe.CONSUMED_FILE).write_text("{}", encoding="utf-8")
        self.assertEqual(self.run_probe(), 3)
        self.assertEqual(self.server_methods(), [])

    def test_failed_initialize_is_terminal_and_not_retried(self):
        broken = self.tmp / "agy_acp_server.par"
        broken.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(3)\n", encoding="utf-8")
        sha = hashlib.sha256(broken.read_bytes()).hexdigest()
        code = probe.run(broken, sha, self.state, confirm=lambda _p: f"{probe.PHRASE_PREFIX} {sha[:7]}", out=self.lines.append,
                         platform_name="linux", architecture="x86_64", timeout=5)
        self.assertEqual(code, 1)
        receipt = json.loads((self.state / probe.RECEIPT_FILE).read_text(encoding="utf-8"))
        self.assertIn(receipt["terminal_state"], {"UNKNOWN_ERROR", "TIMEOUT"})
        self.assertEqual(receipt["retry_count"], 0)

    def test_summary_keeps_classifications_only(self):
        summary = probe.summarize_initialize({
            "protocolVersion": 1, "agentInfo": {"name": "x", "version": "1", "email": "secret.person@example.invalid"},
            "authMethods": [{"id": "oauth-personal", "name": "secret"}, "junk"],
            "agentCapabilities": {"a": True, "b": {"c": 1}, "d": "text"}})
        self.assertEqual(json.dumps(summary).count("secret"), 0)
        self.assertEqual(summary["capability_flags"], {"a": True})


class StaticGuardTests(unittest.TestCase):
    def test_module_never_sends_session_or_prompt_requests(self):
        tree = ast.parse((Path(__file__).resolve().parents[2] / "src" / "relay" / "antigravity_initialize_probe.py").read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertEqual(imported & {"_acp_new_session", "_acp_prompt_text", "_acp_exchange", "acp_initialize_wire"}, set())
        self.assertFalse(names & {"_acp_new_session", "_acp_prompt_text", "_acp_exchange"})
        constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse(constants & {"session/new", "session/prompt", "authenticate"})
        self.assertIn("_acp_initialize", imported)

    def test_forbidden_env_is_not_in_default_environment(self):
        os.environ["GEMINI_API_KEY"] = "x"
        try:
            from relay.acp_stdio_transport import default_environment
            self.assertFalse(probe.FORBIDDEN_ENV & set(default_environment()))
        finally:
            os.environ.pop("GEMINI_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
