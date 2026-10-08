"""Jules Tools CLI read-only transport: allowlist, no key in the child env, bounded read retry, no guessing."""
from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace

from automation.command_bus.claude_jules_cli_transport import (
    BACKOFF_SECONDS, MAX_READ_ATTEMPTS, command_allowed, find_session, run_read, sanitized_env,
)


class Recorder:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def done(code=0, out="", err=""):
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


class AllowlistTests(unittest.TestCase):
    def test_only_exact_read_commands_are_allowed(self):
        for args in (("version",), ("remote", "list", "--session"), ("remote", "list", "--repo")):
            with self.subTest(args=args):
                self.assertTrue(command_allowed(args)[0])

    def test_session_creation_login_tui_and_pull_are_refused(self):
        for args in ((), ("remote", "new", "--session", "x"), ("remote", "new", "--parallel", "2"), ("login",),
                     ("logout",), ("remote", "pull", "--session", "1"), ("remote", "list"),
                     ("remote", "list", "--session", "--repo"), ("--theme", "light"), ("remote", "list", "--session", "x")):
            with self.subTest(args=args):
                self.assertFalse(command_allowed(args)[0])

    def test_refused_command_never_starts_a_process(self):
        runner = Recorder()
        result = run_read(("remote", "new", "--session", "write tests"), runner=runner, sleep=lambda s: None)
        self.assertEqual(result.status, "REFUSED")
        self.assertEqual(runner.calls, [])


class EnvironmentTests(unittest.TestCase):
    def test_keys_tokens_and_credentials_are_removed(self):
        env = {"PATH": "/bin", "HOME": "/h", "JULES_API_KEY": "k", "GOOGLE_API_KEY": "k", "GH_TOKEN": "t",
               "GITHUB_TOKEN": "t", "JULES_TOKEN": "t", "MY_SECRET": "s", "GOOGLE_APPLICATION_CREDENTIALS": "/c.json",
               "DB_PASSWORD": "p"}
        self.assertEqual(sanitized_env(env), {"PATH": "/bin", "HOME": "/h"})

    def test_child_process_gets_the_sanitized_environment(self):
        runner = Recorder(done(0, "jules v1"))
        run_read(("version",), runner=runner, sleep=lambda s: None, env={"PATH": "/bin", "JULES_API_KEY": "k"})
        self.assertEqual(runner.calls[0][1]["env"], {"PATH": "/bin"})
        self.assertEqual(runner.calls[0][0], ["jules", "version"])


class ReadRetryTests(unittest.TestCase):
    def test_transient_failures_are_retried_with_bounded_backoff(self):
        sleeps = []
        runner = Recorder(done(1, err="network"), subprocess.TimeoutExpired("jules", 1), done(0, "ok"))
        result = run_read(("remote", "list", "--session"), runner=runner, sleep=sleeps.append)
        self.assertEqual((result.status, result.attempts), ("OK", 3))
        self.assertEqual(sleeps, list(BACKOFF_SECONDS[1:3]))
        self.assertEqual([e["result"] for e in result.attempt_log], ["exit 1", "timeout", "exit 0"])

    def test_retries_stop_at_the_cap(self):
        runner = Recorder(*[done(1)] * MAX_READ_ATTEMPTS)
        result = run_read(("remote", "list", "--session"), runner=runner, sleep=lambda s: None)
        self.assertEqual((result.status, result.attempts), ("FAILED", MAX_READ_ATTEMPTS))
        self.assertEqual(len(runner.calls), MAX_READ_ATTEMPTS)
        with self.assertRaises(ValueError):
            run_read(("version",), runner=Recorder(), sleep=lambda s: None, max_attempts=MAX_READ_ATTEMPTS + 1)

    def test_missing_cli_is_unavailable_without_retry(self):
        runner = Recorder(FileNotFoundError("jules"))
        result = run_read(("version",), runner=runner, sleep=lambda s: None)
        self.assertEqual((result.status, result.attempts), ("UNAVAILABLE", 1))


class FindSessionTests(unittest.TestCase):
    SID = "12043323850985900453"

    def test_exact_single_hit_is_found_but_state_stays_unknown(self):
        listing = f"ID  REPO  STATUS\n{self.SID}  kamiyusense/multi-ai-council-phase0  Completed\n"
        result = find_session(listing, self.SID)
        self.assertEqual((result["presence"], result["state"], result["pr_url"]), ("FOUND", "UNKNOWN", "UNKNOWN"))

    def test_prefix_or_longer_number_is_not_a_hit(self):
        listing = f"{self.SID}9  x\n1{self.SID}  y\n"
        self.assertEqual(find_session(listing, self.SID)["presence"], "NOT_FOUND")

    def test_two_lines_are_ambiguous(self):
        listing = f"{self.SID} a\nparent {self.SID} b\n"
        self.assertEqual(find_session(listing, self.SID)["presence"], "AMBIGUOUS")

    def test_non_numeric_session_id_is_refused(self):
        with self.assertRaises(ValueError):
            find_session("x", "abc")


if __name__ == "__main__":
    unittest.main()
