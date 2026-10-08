"""Jules Tools CLI read-only transport: allowlist, no key in the child env, bounded read retry, no guessing."""
from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace

from pathlib import Path

from automation.command_bus.claude_jules_cli_transport import (
    BACKOFF_SECONDS, MAX_READ_ATTEMPTS, build_cli_settlement_observation, classify_status, cli_settlement_path,
    CliSettlementStore, command_allowed, find_session, parse_session_listing, run_read, sanitized_env,
    validate_cli_settlement_observation,
)

SAMPLE = (Path(__file__).parent / "fixtures" / "jules_cli" / "remote-list-session-v0.1.42.txt").read_text(encoding="utf-8")
LOOP_139 = "12043323850985900453"
CORRELATION = {"dispatch_session_id": LOOP_139, "pr_task_id": LOOP_139, "pr_number": 322,
               "workflow_run_id": "37417380878", "job_id": "112118884171"}


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


class ListingParserTests(unittest.TestCase):
    """Fixed against the real v0.1.42 output; anything else is refused or UNKNOWN."""

    def test_recorded_sample_parses_every_row(self):
        parsed = parse_session_listing(SAMPLE)
        self.assertEqual(parsed["unparseable_rows"], 0)
        states = {r["session_id"]: (r["provider_state"], r["settlement"]) for r in parsed["rows"]}
        self.assertEqual(states[LOOP_139], ("COMPLETED", "SETTLED"))
        self.assertEqual(states["6434310586203890908"], ("FAILED", "SETTLED"))
        self.assertEqual(states["3439047194842417107"], ("IN_PROGRESS", "RUNNING"))
        self.assertEqual(states["16889081422233772529"], ("AWAITING_USER_FEEDBACK", "RUNNING"))

    def test_trailing_padding_as_printed_by_the_cli_is_accepted(self):
        padded = "\n".join(line.ljust(158) for line in SAMPLE.splitlines()) + "\n" + " " * 150 + "\n"
        rows = parse_session_listing(padded)["rows"]
        self.assertEqual(len(rows), len(parse_session_listing(SAMPLE)["rows"]))

    def test_other_header_is_refused(self):
        for header in ("ID  Description  Repo  Status", "ID  Description  Repo  Last active  State",
                       '{"sessions": []}', ""):
            with self.subTest(header=header):
                with self.assertRaises(ValueError):
                    parse_session_listing(header + "\n" + "\n".join(SAMPLE.splitlines()[1:]))

    def test_unknown_or_unexpected_status_is_never_settled(self):
        for text in ("Done", "completed", "Complete", "Paused", "Awaiting Plan Approval", "Failed!", ""):
            with self.subTest(text=text):
                self.assertEqual(classify_status(text), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual(classify_status("Awaiting User Feedback"), ("AWAITING_USER_FEEDBACK", "RUNNING"))

    def test_row_with_merged_columns_is_unparseable_not_guessed(self):
        broken = SAMPLE.splitlines()[0] + "\n" + f" {LOOP_139} Multi-AI Council kamiyusense 2 days ago Completed\n"
        parsed = parse_session_listing(broken)
        self.assertEqual((parsed["rows"], parsed["unparseable_rows"]), ([], 1))


class CliSettlementObservationTests(unittest.TestCase):
    def build(self, **overrides):
        args = dict(command_id="relay-dev-loop-139-live-proof-3-note", session_id=LOOP_139, listing=SAMPLE,
                    cli_version="v0.1.42", cli_commit="4bd6b25084aa1af52d6d3979cda31f3a3d99fc04",
                    expected_repo="kamiyusense/multi-ai-council-phase0", correlation=CORRELATION,
                    observed_at="2026-10-08T00:20:00+00:00")
        args.update(overrides)
        return build_cli_settlement_observation(**args)

    def test_loop_139_settles_from_the_recorded_listing(self):
        record = self.build()
        self.assertEqual((record["provider_state"], record["settlement"], record["row_status"]),
                         ("COMPLETED", "SETTLED", "Completed"))
        self.assertIs(validate_cli_settlement_observation(record), record)
        self.assertEqual(cli_settlement_path(record["command_id"]),
                         "automation/command_bus/evidence/claude-auto-cli-settlements/"
                         "relay-dev-loop-139-live-proof-3-note.json")

    def test_correlation_must_name_the_same_session(self):
        for key in ("pr_task_id", "dispatch_session_id"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.build(correlation=dict(CORRELATION, **{key: "999"}))

    def test_missing_or_duplicated_session_is_refused(self):
        with self.assertRaises(ValueError):
            self.build(session_id="111", correlation=dict(CORRELATION, pr_task_id="111", dispatch_session_id="111"))
        lines = SAMPLE.splitlines()
        doubled = "\n".join(lines + [l for l in lines if l.strip().startswith(LOOP_139)]) + "\n"
        with self.assertRaises(ValueError):
            self.build(listing=doubled)

    def test_repository_prefix_must_match(self):
        with self.assertRaises(ValueError):
            self.build(expected_repo="someone/else")

    def test_tampered_record_is_refused(self):
        for change in ({"settlement": "RUNNING"}, {"row_status": "Failed"}, {"session_id": "1"},
                       {"provider_state": "FAILED"}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_cli_settlement_observation(dict(self.build(), **change))


class FakeContents:
    def __init__(self, *, fail_create=None):
        self.files, self.fail_create, self.creates = {}, fail_create, 0

    def get(self, path, branch):
        text = self.files.get((path, branch))
        return None if text is None else SimpleNamespace(path=path, text=text)

    def create(self, path, text, message, branch):
        self.creates += 1
        if self.fail_create == "before":
            raise RuntimeError("network down before write")
        self.files[(path, branch)] = text
        if self.fail_create == "after":
            raise RuntimeError("timeout after write")


class CliSettlementStoreTests(unittest.TestCase):
    def record(self, observed_at="2026-10-08T00:20:00+00:00", listing=SAMPLE):
        return build_cli_settlement_observation(
            command_id="relay-dev-loop-139-live-proof-3-note", session_id=LOOP_139, listing=listing,
            cli_version="v0.1.42", cli_commit="c", expected_repo="kamiyusense/multi-ai-council-phase0",
            correlation=CORRELATION, observed_at=observed_at)

    def test_create_then_restart_replay_is_recovered_and_later_reread_is_no_op(self):
        store = CliSettlementStore(FakeContents(), data_branch="d")
        self.assertEqual(store.persist(self.record()), "CREATED")
        self.assertEqual(store.persist(self.record()), "RECOVERED")          # same record after a restart
        self.assertEqual(store.persist(self.record("2026-10-08T05:00:00+00:00")), "NO_OP")  # later re-read
        self.assertEqual(store.client.creates, 1)

    def test_ambiguous_write_is_read_back_not_resent(self):
        after = CliSettlementStore(FakeContents(fail_create="after"), data_branch="d")
        self.assertEqual(after.persist(self.record()), "CREATED")
        before = CliSettlementStore(FakeContents(fail_create="before"), data_branch="d")
        self.assertEqual(before.persist(self.record()), "UNKNOWN")
        self.assertEqual((after.client.creates, before.client.creates), (1, 1))

    def test_running_observation_is_not_stored_as_terminal(self):
        running = SAMPLE.replace("2 days ago              Completed", "2 days ago              In Progress")
        store = CliSettlementStore(FakeContents(), data_branch="d")
        self.assertEqual(store.persist(self.record(listing=running)), "BLOCKED")
        self.assertEqual(store.client.creates, 0)

    def test_conflicting_existing_record_blocks(self):
        client = FakeContents()
        client.files[("automation/command_bus/evidence/claude-auto-cli-settlements/"
                      "relay-dev-loop-139-live-proof-3-note.json", "d")] = '{"tampered": true}'
        self.assertEqual(CliSettlementStore(client, data_branch="d").persist(self.record()), "BLOCKED")
        self.assertEqual(client.creates, 0)


if __name__ == "__main__":
    unittest.main()
