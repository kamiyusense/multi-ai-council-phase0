"""Path B (STATIC): the pure argv filter for the gated Claude container. Nothing is started."""

import json
import unittest

from relay.claude_container_argv import AUTH_PROBE_ARGV, prepare_container_claude_argv

# Recorded from the official claude-agent-acp 0.85.1 with a tripwire CLI (see test_claude_acp_static_boundary).
OBSERVED = [
    "--output-format", "stream-json", "--verbose", "--input-format", "stream-json",
    "--permission-prompt-tool", "stdio", "--disallowedTools", "AskUserQuestion", "--tools", "default",
    "--setting-sources=user,project,local", "--permission-mode", "default", "--include-partial-messages",
    "--session-id=3d01e114-c91d-423f-b792-13e2c2242c3f", "--replay-user-messages", "",
]


class TestPrepareContainerClaudeArgv(unittest.TestCase):
    def test_observed_argv_is_accepted_and_hardened(self):
        out = prepare_container_claude_argv(OBSERVED)
        self.assertEqual(out[out.index("--tools") + 1], "")
        self.assertNotIn("default", out[out.index("--tools"):])
        self.assertEqual(out[out.index("--max-turns") + 1], "1")
        self.assertIn("--safe-mode", out)
        self.assertIn("--strict-mcp-config", out)
        self.assertEqual(json.loads(out[out.index("--mcp-config") + 1]), {"mcpServers": {}})
        self.assertEqual(out[out.index("--permission-mode") + 1], "default")
        self.assertEqual(out.count("--tools"), 1)
        self.assertFalse([a for a in out if "dangerously" in a.lower()])

    def test_auth_probe_passes_unchanged(self):
        self.assertEqual(prepare_container_claude_argv(list(AUTH_PROBE_ARGV)), ["auth", "status", "--json"])

    def test_bypass_and_unknown_flags_are_refused(self):
        for extra in (["--allow-dangerously-skip-permissions"], ["--dangerously-skip-permissions"],
                      ["--model", "x"], ["--mcp-config", "{}"], ["-p"], ["--max-turns", "9"]):
            argv = OBSERVED[:-1] + extra + [""]
            with self.assertRaises(ValueError, msg=extra):
                prepare_container_claude_argv(argv)

    def test_changed_values_are_refused(self):
        for key, bad in (("--permission-mode", "bypassPermissions"), ("--permission-prompt-tool", "none"),
                         ("--output-format", "text"), ("--tools", "Bash")):
            argv = list(OBSERVED)
            argv[argv.index(key) + 1] = bad
            with self.assertRaises(ValueError, msg=key):
                prepare_container_claude_argv(argv)

    def test_bad_shape_is_refused(self):
        with self.assertRaises(ValueError):
            prepare_container_claude_argv(OBSERVED[:-1])  # no trailing empty argument
        with self.assertRaises(ValueError):
            prepare_container_claude_argv(OBSERVED[:-1] + ["a prompt"])
        with self.assertRaises(ValueError):
            prepare_container_claude_argv([a.replace("3d01e114-c91d-423f-b792-13e2c2242c3f", "not-a-uuid") for a in OBSERVED])
        with self.assertRaises(ValueError):
            prepare_container_claude_argv(OBSERVED[:-1] + ["--verbose", ""])  # duplicate
        with self.assertRaises(ValueError):
            prepare_container_claude_argv(["auth", "status"])
        with self.assertRaises(ValueError):
            prepare_container_claude_argv("auth status --json")


if __name__ == "__main__":
    unittest.main()
