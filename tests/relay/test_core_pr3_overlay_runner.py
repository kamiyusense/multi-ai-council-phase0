import ast
import sys
import unittest
from pathlib import Path
import tempfile

from .core_pr3_overlay_runner import run_overlay

class TestCorePR3OverlayRunner(unittest.TestCase):
    def setUp(self):
        self.pinned_head = "494b7296f32dce1c173a7699e4bd2d87f70d31a9"

    def test_wrong_core_head_fails(self):
        with self.assertRaises(ValueError) as cm:
            run_overlay(Path("/tmp/core"), Path("/tmp/relay"), "wrong_head")
        self.assertIn("core_head mismatch", str(cm.exception))

    def test_missing_explicit_roots_fails(self):
        with tempfile.TemporaryDirectory() as td:
            core_root = Path(td) / "core"
            relay_root = Path(td) / "relay"
            core_root.mkdir()
            relay_root.mkdir()

            with self.assertRaises(FileNotFoundError) as cm:
                run_overlay(core_root, relay_root, self.pinned_head)
            self.assertIn("Missing required explicit file", str(cm.exception))

    def test_sys_path_and_module_restoration_on_import_error(self):
        with tempfile.TemporaryDirectory() as td:
            base_dir = Path(td)
            core_root = base_dir / "core"
            relay_root = base_dir / "relay"

            for d in [
                core_root / "src/phase0_core",
                relay_root / "src/providers",
                relay_root / "src/relay",
            ]:
                d.mkdir(parents=True)

            (core_root / "src/phase0_core/adapter.py").touch()
            with open(core_root / "src/phase0_core/runner.py", "w") as f:
                f.write("raise RuntimeError('Failing fake import')\n")

            (relay_root / "src/providers/core_boundary.py").touch()
            (relay_root / "src/providers/bundle.py").touch()
            (relay_root / "src/relay/core_adapter.py").touch()

            original_path = sys.path[:]

            with self.assertRaises(RuntimeError) as cm:
                run_overlay(core_root, relay_root, self.pinned_head)
            self.assertIn("Failing fake import", str(cm.exception))

            self.assertEqual(sys.path, original_path)
            self.assertFalse(any(m.startswith("phase0_core") for m in sys.modules))

    def test_static_ast_proof(self):
        runner_path = Path(__file__).parent / "core_pr3_overlay_runner.py"
        with open(runner_path, "r") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr == "environ" and getattr(node.value, "id", "") == "os":
                    self.fail("os.environ found in runner")
            if isinstance(node, ast.Import):
                for name in node.names:
                    if name.name in ("subprocess", "socket", "requests", "urllib"):
                        self.fail(f"Forbidden import found: {name.name}")
            if isinstance(node, ast.ImportFrom):
                if node.module in ("subprocess", "socket", "requests", "urllib"):
                    self.fail(f"Forbidden import from found: {node.module}")
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if func.attr in ("rglob", "glob") and isinstance(func.value, ast.Name) and func.value.id == "Path":
                         self.fail(f"Forbidden filesystem search method found: {func.attr}")

if __name__ == '__main__':
    unittest.main()
