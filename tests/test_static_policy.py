from __future__ import annotations

import unittest
from pathlib import Path


SRC = Path(__file__).parents[1] / "src" / "phase0_core"


class StaticPolicyTests(unittest.TestCase):
    def source_text(self) -> str:
        return "\n".join(path.read_text(encoding="utf-8") for path in sorted(SRC.glob("*.py")))

    def test_no_permission_bypass_flags(self):
        text = self.source_text().lower()
        for forbidden in ("--dangerously-", "--yolo", "skip-permissions", "bypass-approvals"):
            self.assertNotIn(forbidden, text)

    def test_no_provider_api_key_env_routes(self):
        text = self.source_text()
        for forbidden in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            self.assertNotIn(forbidden, text)

    def test_no_process_or_network_runtime_imports(self):
        text = self.source_text()
        for forbidden in ("import subprocess", "from subprocess", "import socket", "import requests", "import httpx", "urllib.request"):
            self.assertNotIn(forbidden, text)

    def test_live_mode_remains_hard_disabled(self):
        runner = (SRC / "runner.py").read_text(encoding="utf-8")
        self.assertIn('if mode is ExecutionMode.LIVE:', runner)
        self.assertIn('live provider execution is disabled in the static core', runner)
