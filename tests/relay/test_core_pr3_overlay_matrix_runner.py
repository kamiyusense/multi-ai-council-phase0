import ast
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from . import core_pr3_overlay_matrix_runner as matrix_runner

class TestCorePR3OverlayMatrixRunner(unittest.TestCase):
    def setUp(self):
        self.pinned_head = matrix_runner.PINNED_CORE_HEAD

    def _make_required_fake_roots(self, base: Path) -> tuple[Path, Path]:
        core_root = base / "core"
        relay_root = base / "relay"
        for path in matrix_runner._required_paths(core_root, relay_root):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        return core_root, relay_root

    def test_import_is_safe_without_phase0_core_installed(self):
        self.assertNotIn("phase0_core", matrix_runner.__dict__)
        self.assertTrue(callable(matrix_runner.run_matrix))

    def test_wrong_core_head_fails_before_path_validation_or_import(self):
        with self.assertRaisesRegex(ValueError, "core_head mismatch"):
            matrix_runner.run_matrix(
                Path("/definitely/missing/core"),
                Path("/definitely/missing/relay"),
                "wrong-head",
            )

    def test_missing_explicit_required_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            core_root, relay_root = self._make_required_fake_roots(base)
            missing = core_root / "src/phase0_core/runner.py"
            missing.unlink()

            with self.assertRaisesRegex(FileNotFoundError, "Missing required explicit file"):
                matrix_runner.run_matrix(core_root, relay_root, self.pinned_head)

    def test_sys_path_and_module_namespace_restored_on_fake_core_import_failure(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            core_root, relay_root = self._make_required_fake_roots(base)

            (core_root / "src/phase0_core/__init__.py").write_text("", encoding="utf-8")
            (core_root / "src/phase0_core/fanout.py").write_text(
                "raise RuntimeError('fake fanout import failure')\n",
                encoding="utf-8",
            )

            original_path = list(sys.path)
            sentinel = ModuleType("phase0_core.sentinel")
            src_sentinel = ModuleType("src.sentinel")
            previous = sys.modules.get("phase0_core.sentinel")
            previous_src = sys.modules.get("src.sentinel")
            sys.modules["phase0_core.sentinel"] = sentinel
            sys.modules["src.sentinel"] = src_sentinel

            try:
                with self.assertRaisesRegex(RuntimeError, "fake fanout import failure"):
                    matrix_runner.run_matrix(core_root, relay_root, self.pinned_head)
                self.assertEqual(sys.path, original_path)
                self.assertIs(sys.modules.get("phase0_core.sentinel"), sentinel)
                self.assertIs(sys.modules.get("src.sentinel"), src_sentinel)
            finally:
                if previous is None:
                    sys.modules.pop("phase0_core.sentinel", None)
                else:
                    sys.modules["phase0_core.sentinel"] = previous
                if previous_src is None:
                    sys.modules.pop("src.sentinel", None)
                else:
                    sys.modules["src.sentinel"] = previous_src

    def test_static_ast_proof_no_ambient_discovery_or_external_execution(self):
        runner_path = Path(__file__).parent / "core_pr3_overlay_matrix_runner.py"
        tree = ast.parse(runner_path.read_text(encoding="utf-8"))

        forbidden_import_roots = {
            "os",
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "http",
        }
        forbidden_calls = {
            "glob",
            "rglob",
            "walk",
            "system",
            "popen",
            "run",
            "check_call",
            "check_output",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name.split(".")[0],
                        forbidden_import_roots,
                    )
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    (node.module or "").split(".")[0],
                    forbidden_import_roots,
                )
            elif isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "environ")
                self.assertNotIn(node.attr, forbidden_calls)

if __name__ == "__main__":
    unittest.main()
