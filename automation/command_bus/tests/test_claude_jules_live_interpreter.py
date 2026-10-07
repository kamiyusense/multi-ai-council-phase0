"""Claude's own candidate test run uses the interpreter that runs the controller (Windows has no ``python3``)."""
from __future__ import annotations

import sys
import unittest

from automation.command_bus.claude_jules_live import DEFAULT_TEST_COMMAND


class InterpreterTests(unittest.TestCase):
    def test_default_test_command_uses_the_current_interpreter(self):
        self.assertEqual(DEFAULT_TEST_COMMAND[0], sys.executable or "python3")
        self.assertEqual(DEFAULT_TEST_COMMAND[1:], ["-m", "unittest", "discover", "-s", "automation/command_bus/tests",
                                                    "-t", "."])


if __name__ == "__main__":
    unittest.main()
