"""M3 Claude: what the official ``claude-agent-acp`` can and cannot do without a provider.

Skipped unless RELAY_CLAUDE_ACP_DIR points at ``node_modules/@agentclientprotocol/claude-agent-acp``
(``npm install --ignore-scripts --omit=optional @agentclientprotocol/claude-agent-acp@<pin>``).

The adapter runs the Claude Code CLI itself (``auth status --json`` at ``initialize``, the SDK
stream-json process at ``session/new``). ``CLAUDE_CODE_EXECUTABLE`` is therefore pointed at a
tripwire that only records argv and exits, so no real CLI, account or model is ever reached.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from relay.acp_client import _acp_initialize, _acp_new_session
from relay.acp_stdio_transport import spawn_stdio_transport

REPO = Path(__file__).resolve().parents[2]
TRIPWIRE = REPO / "fixtures" / "relay" / "claude_cli_tripwire.py"


class TestTripwire(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "tripwire is exec'd directly (POSIX shebang)")
    def test_records_argv_and_exits_nonzero_without_output(self):
        log = os.path.join(tempfile.mkdtemp(), "tw.log")
        done = subprocess.run([str(TRIPWIRE), "auth", "status", "--json"], capture_output=True,
                              env={"RELAY_TRIPWIRE_LOG": log, "PATH": os.environ.get("PATH", "")})
        self.assertEqual((done.returncode, done.stdout, done.stderr), (2, b"", b""))
        with open(log, encoding="utf-8") as fh:
            self.assertEqual([json.loads(line) for line in fh], [["auth", "status", "--json"]])


@unittest.skipUnless(os.environ.get("RELAY_CLAUDE_ACP_DIR") and shutil.which("node") and os.name != "nt",
                     "RELAY_CLAUDE_ACP_DIR / node / POSIX not available (TEST_ENVIRONMENT_NOT_PREPARED)")
class TestOfficialClaudeAdapterWithTripwireCli(unittest.TestCase):
    def setUp(self):
        self.dir = os.environ["RELAY_CLAUDE_ACP_DIR"]
        self.home = tempfile.mkdtemp()
        self.log = os.path.join(self.home, "tripwire.log")

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def wait_for_calls(self, count, seconds=10.0):
        deadline = time.monotonic() + seconds
        while len(self.calls()) < count and time.monotonic() < deadline:
            time.sleep(0.1)
        return self.calls()

    def run_adapter(self, with_session):
        env = {"HOME": self.home, "CLAUDE_CODE_EXECUTABLE": str(TRIPWIRE), "RELAY_TRIPWIRE_LOG": self.log}
        out = {}

        async def go():
            cm = spawn_stdio_transport("node", os.path.join(self.dir, "dist", "index.js"), env=env,
                                       cwd=self.home, shutdown_timeout=3)
            stdout, stdin, _proc = await cm.__aenter__()
            try:
                out["init"] = await _acp_initialize(stdout, stdin, 30)
                out["after_init"] = await asyncio.get_running_loop().run_in_executor(None, self.wait_for_calls, 1)
                if with_session:
                    try:
                        out["session"] = await _acp_new_session(stdout, stdin, self.home, 30)
                    except RuntimeError as exc:
                        out["session_error"] = str(exc)
                    out["after_session"] = await asyncio.get_running_loop().run_in_executor(None, self.wait_for_calls, 2)
            finally:
                await cm.__aexit__(None, None, None)

        asyncio.run(go())
        return out

    def test_initialize_handshake_works_without_any_provider(self):
        out = self.run_adapter(with_session=False)
        init = out["init"]
        self.assertEqual(init["protocolVersion"], 1)
        self.assertEqual(init["agentInfo"]["name"], "@agentclientprotocol/claude-agent-acp")
        self.assertEqual(init["authMethods"], [])  # nothing offered to a client without auth capabilities
        self.assertIn("close", init["agentCapabilities"]["sessionCapabilities"])

    def test_initialize_alone_makes_the_adapter_run_the_cli_auth_probe(self):
        """Canary: with a real CLI this would be a read of the real Claude login state."""
        out = self.run_adapter(with_session=False)
        self.assertEqual(out["after_init"], [["auth", "status", "--json"]])

    def test_session_new_needs_the_cli_so_the_lifecycle_stops_at_the_live_boundary(self):
        out = self.run_adapter(with_session=True)
        self.assertNotIn("session", out)
        self.assertIn("session/new returned error", out["session_error"])
        probe, cli = out["after_session"][0], out["after_session"][1]
        self.assertEqual(probe, ["auth", "status", "--json"])
        self.assertIn("stream-json", cli)  # the SDK's CLI process, not a model call: the tripwire exited
        # permission primitive stays the official one; no bypass flag is passed to the CLI
        self.assertEqual(cli[cli.index("--permission-mode") + 1], "default")
        self.assertEqual(cli[cli.index("--permission-prompt-tool") + 1], "stdio")
        self.assertFalse([a for a in cli if "dangerously" in a.lower()])
        self.assertEqual(len(self.calls()), 2)  # nothing else was executed


if __name__ == "__main__":
    unittest.main()
