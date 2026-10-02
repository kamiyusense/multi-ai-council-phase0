"""Gate script/launcher behavior without any adapter (runs on Linux and Windows).

Uses only the fixture backend. On Windows the launcher is exercised through
cmd.exe exactly like codex-acp does (shell mode), including a path with spaces.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RELAY = REPO / "src" / "relay"
FAKE = REPO / "fixtures" / "relay" / "fake_codex_app_server.py"


def _rpc(*messages):
    return b"".join(json.dumps(m).encode() + b"\n" for m in messages)


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
TURN = lambda i: {"jsonrpc": "2.0", "id": i, "method": "turn/start", "params": {"threadId": "t1"}}  # noqa: E731


class TestCodexTurnGate(unittest.TestCase):
    def _launch(self, directory, args="app-server", extra_env=None):
        """Start the gate the way the platform's adapter would; returns CompletedProcess builder."""
        env = dict(os.environ)
        env.update({
            "RELAY_GATE_BACKEND": str(Path(directory) / "fake_codex_app_server.py"),
            "RELAY_GATE_LOG": str(Path(directory) / "gate.log"),
            "FAKE_CODEX_LOG": str(Path(directory) / "backend.log"),
            "RELAY_GATE_PYTHON": sys.executable,
        })
        env.update(extra_env or {})
        if os.name == "nt":
            command = f'"{Path(directory) / "codex_turn_gate.cmd"}" {args}'
            return lambda data: subprocess.run(command, input=data, capture_output=True, timeout=30, env=env, shell=True)
        command = [sys.executable, str(Path(directory) / "codex_turn_gate.py")] + args.split()
        return lambda data: subprocess.run(command, input=data, capture_output=True, timeout=30, env=env)

    def _stage(self, name):
        base = Path(tempfile.mkdtemp()) / name
        base.mkdir()
        for src in (RELAY / "codex_turn_gate.py", RELAY / "codex_turn_gate.cmd", FAKE):
            shutil.copy(src, base / src.name)
        return base

    def _check_one_generation(self, directory):
        done = self._launch(directory)(_rpc(INIT, TURN(2), TURN(3)))
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
        by_id = {m["id"]: m for m in lines if "id" in m}
        self.assertIn("result", by_id[1])            # initialize passes through intact
        self.assertIn("result", by_id[2])            # first generation is allowed
        self.assertEqual(by_id[3]["error"]["code"], -32001)  # second is blocked locally
        self.assertNotIn(b"\r\r", done.stdout)       # no doubled CR from newline translation
        backend = (Path(directory) / "backend.log").read_text().split()
        self.assertEqual((backend.count("initialize"), backend.count("turn/start")), (1, 1))
        decisions = [json.loads(x)["decision"] for x in (Path(directory) / "gate.log").read_text().splitlines()]
        self.assertEqual(decisions, ["allowed", "blocked"])

    def test_first_generation_only_and_args_and_json_intact(self):
        self._check_one_generation(self._stage("relay_gate"))

    def test_path_with_spaces(self):
        self._check_one_generation(self._stage("relay gate dir with spaces"))

    def test_exit_code_is_propagated(self):
        done = self._launch(self._stage("relay_gate_rc"), args="not-app-server")(b"")
        self.assertEqual(done.returncode, 2)

    def test_missing_backend_fails_closed(self):
        directory = self._stage("relay_gate_nobackend")
        done = self._launch(directory, extra_env={"RELAY_GATE_BACKEND": ""})(_rpc(INIT, TURN(2)))
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, b"")

    def test_unparsable_client_line_is_not_forwarded(self):
        directory = self._stage("relay_gate_junk")
        done = self._launch(directory)(b"not json\n" + _rpc(INIT))
        self.assertEqual(done.returncode, 0)
        self.assertEqual((Path(directory) / "backend.log").read_text().split(), ["initialize"])
        self.assertIn("dropped_unparsable", (Path(directory) / "gate.log").read_text())


if __name__ == "__main__":
    unittest.main()
