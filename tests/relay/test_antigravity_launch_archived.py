import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "archive" / "antigravity_launch"
HEADER = "# 使用停止中・実行禁止（規約上の理由、2026-10）"
MODULES = ("antigravity_dispatch", "antigravity_initialize_probe", "antigravity_login_probe", "antigravity_one_turn")
TESTS = ("test_antigravity_dispatch_static", "test_antigravity_initialize_probe", "test_antigravity_login_probe",
         "test_antigravity_one_turn")


class TestAntigravityLaunchArchived(unittest.TestCase):
    """The Antigravity launch code stays out of the Relay (terms, 2026-10) and stays marked as suspended."""

    def test_launch_modules_are_not_in_the_relay(self):
        for name in MODULES:
            self.assertFalse((ROOT / "src" / "relay" / f"{name}.py").exists(), name)
        for name in TESTS:
            self.assertFalse((ROOT / "tests" / "relay" / f"{name}.py").exists(), name)

    def test_archived_files_keep_the_suspension_header(self):
        files = [ARCHIVE / "src" / "relay" / f"{n}.py" for n in MODULES]
        files += [ARCHIVE / "tests" / "relay" / f"{n}.py" for n in TESTS]
        files.append(ARCHIVE / "README.md")
        for path in files:
            with self.subTest(path=path.name):
                self.assertTrue(path.read_text(encoding="utf-8").startswith(HEADER))

    def test_launch_deny_list_still_refuses_antigravity(self):
        source = (ROOT / "src" / "relay" / "acp_stdio_relay_transport.py").read_text(encoding="utf-8")
        self.assertIn('"agy_acp_server"', source)
        self.assertIn('"antigravity-acp"', source)
        self.assertIn('_VERIFIED_BACKEND_SEAMS = {"openai": "CODEX_PATH"}', source)


if __name__ == "__main__":
    unittest.main()
