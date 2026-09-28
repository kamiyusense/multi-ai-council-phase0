import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import tests.relay.core_pr3_overlay_policy_matrix_runner as runner_module

class TestCorePR3OverlayPolicyMatrixRunner(unittest.TestCase):
    def test_namespace_matches(self):
        self.assertTrue(runner_module._namespace_matches("phase0_core"))
        self.assertTrue(runner_module._namespace_matches("phase0_core.runner"))
        self.assertTrue(runner_module._namespace_matches("providers.adapter"))
        self.assertTrue(runner_module._namespace_matches("relay.bridge"))
        self.assertTrue(runner_module._namespace_matches("src.utils"))
        self.assertFalse(runner_module._namespace_matches("json"))
        self.assertFalse(runner_module._namespace_matches("os"))

    def test_remove_and_restore_modules(self):
        sys.modules["phase0_core.fake"] = MagicMock()
        sys.modules["relay.fake"] = MagicMock()

        saved = runner_module._remove_overlay_modules()

        self.assertNotIn("phase0_core.fake", sys.modules)
        self.assertNotIn("relay.fake", sys.modules)
        self.assertIn("phase0_core.fake", saved)
        self.assertIn("relay.fake", saved)

        runner_module._restore_overlay_modules(saved)

        self.assertIn("phase0_core.fake", sys.modules)
        self.assertIn("relay.fake", sys.modules)

        sys.modules.pop("phase0_core.fake", None)
        sys.modules.pop("relay.fake", None)

    @patch("tests.relay.core_pr3_overlay_policy_matrix_runner.Path.is_file")
    def test_validate_inputs_success(self, mock_is_file):
        mock_is_file.return_value = True
        core_root = Path("/fake/core")
        relay_root = Path("/fake/relay")
        runner_module._validate_inputs(core_root, relay_root, runner_module.PINNED_CORE_HEAD)

    def test_validate_inputs_wrong_head(self):
        core_root = Path("/fake/core")
        relay_root = Path("/fake/relay")
        with self.assertRaises(ValueError) as ctx:
            runner_module._validate_inputs(core_root, relay_root, "wrong")
        self.assertIn(runner_module.PINNED_CORE_HEAD, str(ctx.exception))

    @patch("tests.relay.core_pr3_overlay_policy_matrix_runner.Path.is_file")
    def test_validate_inputs_missing_file(self, mock_is_file):
        mock_is_file.return_value = False
        core_root = Path("/fake/core")
        relay_root = Path("/fake/relay")
        with self.assertRaises(FileNotFoundError):
            runner_module._validate_inputs(core_root, relay_root, runner_module.PINNED_CORE_HEAD)

    def test_provider_states_from_checkpoint(self):
        checkpoint = {
            "FAIL": ["openai:TIMEOUT"],
            "UNKNOWN": ["anthropic:ERROR_UNKNOWN"]
        }
        states = runner_module._provider_states_from_checkpoint(checkpoint)
        self.assertEqual(states, {
            "openai": "TIMEOUT",
            "anthropic": "ERROR_UNKNOWN",
            "google": "COMPLETE"
        })

    def test_provider_states_malformed(self):
        with self.assertRaises(ValueError):
            runner_module._provider_states_from_checkpoint({"FAIL": ["invalid"]})

if __name__ == "__main__":
    unittest.main()
