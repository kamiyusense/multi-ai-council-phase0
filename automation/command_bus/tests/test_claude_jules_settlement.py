"""STATIC tests for the provider-settlement source (no network, no Jules call, no LIVE)."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from automation.command_bus import claude_jules_settlement as s
from automation.command_bus.claude_jules_dispatch import sha256_of
from automation.command_bus.claude_jules_live import LiveResultFacts

CMD = "relay-dev-loop-201-settle-note"
SESSION = "12043323850985900453"
REQ_PATH = f"{s.STATUS_REQUEST_DIR}/status-{CMD}.json"
REQ_COMMIT = "a" * 40
DISPATCHED = "2026-10-07T00:00:00+00:00"


JOB_STARTED = "2026-10-07T06:59:00Z"
JOB_DONE = "2026-10-07T06:59:30Z"


def line(state: str, session: str = SESSION) -> str:
    return f"Jules session readback: name=sessions/{session} state={state} accepted_at_jst=2026-10-07T09:00:00+09:00 pr_url=NONE"


def job_log(*lines: str) -> str:
    """A job log as GitHub serves it: timestamped lines, the script echo and the agent-message line included."""
    body = ["2026-10-07T06:59:01.0000000Z ##[group]Run set -euo pipefail",
            '2026-10-07T06:59:01.0000000Z echo "Jules session readback: name=${name} state=${state} pr_url=${pr_url:-NONE}"',
            "2026-10-07T06:59:01.0000000Z ##[endgroup]"]
    body += [f"2026-10-07T06:59:20.0000000Z {x}" for x in lines]
    return "\n".join(body) + "\n"


def record(state: str = "COMPLETED", *, run: str = "100", job: str = "200", at: str = "2026-10-07T07:00:00+00:00",
           session: str = SESSION, command: str = CMD) -> dict:
    return s.build_settlement_observation(
        command_id=command, status_request_path=REQ_PATH, status_request_commit=REQ_COMMIT,
        workflow_run_id=run, job_id=job, log_line=line(state, session), observed_at=at)


def facts(r, *, started=JOB_STARTED, done=JOB_DONE):
    return {"session_id": r["session_id"], "provider_state": r["provider_state"], "workflow_run_id": r["workflow_run_id"],
            "job_id": r["job_id"], "job_started_at": started, "job_completed_at": done}


def status(records, verify=facts, session=SESSION):
    return s.settlement_status(records, command_id=CMD, accepted_session_id=session, dispatched_at=DISPATCHED,
                               verify=verify)


class StateMappingTests(unittest.TestCase):
    def test_only_completed_and_failed_are_settled(self):
        self.assertEqual({x: s.classify_provider_state(x) for x in s.SETTLED_STATES}, {"COMPLETED": "SETTLED", "FAILED": "SETTLED"})
        for state in ("QUEUED", "PLANNING", "IN_PROGRESS", "AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK", "PAUSED"):
            self.assertEqual(s.classify_provider_state(state), "RUNNING", state)
        for state in ("CANCELLED", "STATE_UNSPECIFIED", "", None, "completed"):
            self.assertEqual(s.classify_provider_state(state), "UNKNOWN", state)


class RecordTests(unittest.TestCase):
    def test_round_trip_and_digest(self):
        r = record()
        self.assertEqual((r["session_id"], r["provider_state"]), (SESSION, "COMPLETED"))
        self.assertEqual(s.validate_settlement_observation(json.loads(json.dumps(r))), r)
        self.assertTrue(s.settlement_path(CMD, "100").endswith(f"claude-auto-settlement-observations/{CMD}/100.json"))

    def test_tampering_is_rejected(self):
        for key, value in {"provider_state": "FAILED", "session_id": "1", "job_id": "x", "status_request_path": "x.json",
                           "status_request_commit": "abc", "observed_at": "2026-10-07T07:00:00"}.items():
            bad = dict(record(), **{key: value})
            bad["observation_sha256"] = sha256_of({k: v for k, v in bad.items() if k != "observation_sha256"})
            with self.assertRaises(ValueError, msg=key):
                s.validate_settlement_observation(bad)
        forged = dict(record(), provider_state="FAILED")  # digest not refreshed
        with self.assertRaises(ValueError):
            s.validate_settlement_observation(forged)

    def test_log_line_must_hold_exactly_one_readback(self):
        for bad in ("", "Jules session accepted: sessions/1", line("COMPLETED") + " " + line("RUNNING")):
            with self.assertRaises(ValueError):
                s.build_settlement_observation(command_id=CMD, status_request_path=REQ_PATH,
                                               status_request_commit=REQ_COMMIT, workflow_run_id="1", job_id="2",
                                               log_line=bad, observed_at="2026-10-07T07:00:00+00:00")


class StatusTests(unittest.TestCase):
    def test_no_records_or_unknown_session_is_unknown(self):
        self.assertEqual(status([])[0], "UNKNOWN")
        self.assertEqual(status([record()], session=None)[0], "UNKNOWN")

    def test_settled_and_running(self):
        self.assertEqual(status([record("COMPLETED")])[0], "SETTLED")
        self.assertEqual(status([record("FAILED")])[0], "SETTLED")
        self.assertEqual(status([record("IN_PROGRESS")])[0], "RUNNING")
        self.assertEqual(status([record("CANCELLED")])[0], "UNKNOWN")

    def test_latest_verified_job_decides_progress(self):
        older = record("IN_PROGRESS", run="100", at="2026-10-07T08:00:00+00:00")
        newer = record("COMPLETED", run="101", at="2026-10-07T08:00:00+00:00")
        times = {"100": ("2026-10-07T06:00:00Z", "2026-10-07T06:00:30Z"),
                 "101": ("2026-10-07T07:00:00Z", "2026-10-07T07:00:30Z")}
        verify = lambda r: facts(r, started=times[r["workflow_run_id"]][0], done=times[r["workflow_run_id"]][1])
        result, ref = status([newer, older], verify=verify)
        self.assertEqual(result, "SETTLED")
        self.assertIn("run 101", ref)

    def test_order_comes_from_job_times_not_from_observed_at(self):
        # An old COMPLETED job transcribed late (newer observed_at) must not outrank a newer IN_PROGRESS job.
        old_job = record("COMPLETED", run="100", at="2026-10-07T09:00:00+00:00")
        new_job = record("IN_PROGRESS", run="101", at="2026-10-07T08:00:00+00:00")
        times = {"100": ("2026-10-07T06:00:00Z", "2026-10-07T06:00:30Z"),
                 "101": ("2026-10-07T07:00:00Z", "2026-10-07T07:00:30Z")}
        verify = lambda r: facts(r, started=times[r["workflow_run_id"]][0], done=times[r["workflow_run_id"]][1])
        self.assertEqual(status([old_job, new_job], verify=verify)[0], "UNKNOWN")  # unsettled after settled

    def test_unsettled_after_settled_is_a_contradiction(self):
        settled = record("COMPLETED", run="100")
        later = record("IN_PROGRESS", run="101")
        times = {"100": "2026-10-07T06:00:00Z", "101": "2026-10-07T06:30:00Z"}
        verify = lambda r: facts(r, started=times[r["workflow_run_id"]], done=times[r["workflow_run_id"]])
        self.assertEqual(status([settled, later], verify=verify)[0], "UNKNOWN")

    def test_old_job_with_a_fresh_transcription_time_proves_nothing(self):
        stale = record("COMPLETED", at="2026-10-07T09:00:00+00:00")
        verify = lambda r: facts(r, started="2026-10-06T23:00:00Z", done="2026-10-06T23:00:30Z")
        self.assertEqual(status([stale], verify=verify), ("UNKNOWN", "no verified provider readback after the dispatch"))

    def test_record_written_before_its_job_finished_is_a_contradiction(self):
        early = record("COMPLETED", at="2026-10-07T06:59:10+00:00")
        result, reason = status([early])
        self.assertEqual(result, "UNKNOWN")
        self.assertIn("contradiction", reason)

    def test_other_session_or_failed_verification_is_unknown(self):
        self.assertEqual(status([record(session="99")])[0], "UNKNOWN")

        def mismatch(r):
            raise s.ReadbackMismatch("recorded state differs from the job log")

        def unavailable(r):
            raise s.ReadbackUnavailable("job log read failed: HTTPError")

        def boom(r):
            raise RuntimeError("403")
        self.assertIn("contradiction", status([record()], verify=mismatch)[1])
        self.assertIn("unavailable", status([record()], verify=unavailable)[1])
        self.assertEqual(status([record()], verify=boom)[0], "UNKNOWN")
        self.assertEqual(status([record()], verify=lambda r: dict(facts(r), session_id="5"))[0], "UNKNOWN")

    def test_readback_of_other_command_is_ignored(self):
        other = record("COMPLETED", command="relay-dev-loop-202-other")
        self.assertEqual(status([other])[0], "UNKNOWN")

    def test_invalid_record_is_unknown_not_skipped(self):
        bad = dict(record(), provider_state="FAILED")
        self.assertEqual(status([bad, record()])[0], "UNKNOWN")

    def test_unknown_classification_of_settlement_reasons(self):
        from automation.command_bus.claude_jules_campaign import classify_boundary
        unavailable = classify_boundary("UNKNOWN", "provider readback unavailable: job log read failed")
        contradiction = classify_boundary("UNKNOWN", "provider readback contradiction: recorded state differs")
        self.assertTrue(unavailable.retry_safe)  # bounded re-read of GitHub only
        self.assertFalse(contradiction.retry_safe)


class FakeGit:
    def __init__(self, files=None, added=None, shown=None):
        self.files, self.added, self.shown = files or {}, added or {}, shown or {}

    def added_by(self, branch, path):
        return self.added.get((branch, path), [])

    def show(self, sha, path):
        return self.shown.get((sha, path))

    def list(self, prefix, ref):
        return [SimpleNamespace(path=p, text=t) for p, t in sorted(self.files.items()) if p.startswith(prefix)]


class FakeRest:
    def __init__(self, runs=None, jobs=None, logs=None):
        self.runs, self.jobs, self.logs = runs or {}, jobs or {}, logs or {}
        self.log_reads = 0

    def workflow_runs_for_commit(self, workflow, sha):
        return self.runs.get((workflow, sha), [])

    def run_jobs(self, run_id):
        return self.jobs.get(run_id, [])

    def job_log(self, job_id):
        self.log_reads += 1
        value = self.logs.get(job_id)
        if isinstance(value, Exception):
            raise value
        return value


def verified_world(*, provider_state="COMPLETED", log=None, run_conclusion="success", request=None, run=None, job=None):
    git = FakeGit(added={("carrier", REQ_PATH): [REQ_COMMIT]},
                  shown={(REQ_COMMIT, REQ_PATH): json.dumps(request or {"session_id": SESSION})})
    run_row = dict({"id": 100, "event": "push", "status": "completed", "conclusion": run_conclusion,
                    "head_sha": REQ_COMMIT, "run_attempt": 1}, **(run or {}))
    job_row = dict({"id": 200, "status": "completed", "conclusion": "success", "run_attempt": 1,
                    "started_at": JOB_STARTED, "completed_at": JOB_DONE}, **(job or {}))
    rest = FakeRest(runs={(s.READBACK_WORKFLOW, REQ_COMMIT): [run_row]}, jobs={100: [job_row]},
                    logs={200: log if log is not None else job_log(line(provider_state),
                                                                    'Jules latest agent message JSON: "done"')})
    return git, rest


def verify(r, git, rest):
    return s.verify_readback(r, git=git, rest=rest, carrier_branch="carrier")


class VerifyReadbackTests(unittest.TestCase):
    def test_verified_readback_comes_from_the_job_log(self):
        git, rest = verified_world()
        got = verify(record(), git, rest)
        self.assertEqual((got["provider_state"], got["job_completed_at"]), ("COMPLETED", JOB_DONE))
        self.assertEqual(rest.log_reads, 1)

    def test_valid_digest_but_log_says_in_progress(self):
        # The reproduced hole: digest-consistent COMPLETED record, real job log IN_PROGRESS, successful run.
        git, rest = verified_world(provider_state="IN_PROGRESS")
        forged = record("COMPLETED")
        self.assertEqual(s.validate_settlement_observation(forged), forged)  # digest alone is fine
        with self.assertRaises(s.ReadbackMismatch):
            verify(forged, git, rest)
        self.assertEqual(rest.log_reads, 1)
        result, reason = status([forged], verify=lambda r: verify(r, git, rest))
        self.assertEqual(result, "UNKNOWN")
        self.assertIn("contradiction", reason)

    def test_run_success_with_provider_in_progress_is_running_not_settled(self):
        git, rest = verified_world(provider_state="IN_PROGRESS")
        self.assertEqual(status([record("IN_PROGRESS")], verify=lambda r: verify(r, git, rest))[0], "RUNNING")

    def test_log_without_the_target_session_or_with_another_session(self):
        for log in (job_log('Jules latest agent message JSON: "nothing"'), job_log(line("COMPLETED", "77"))):
            git, rest = verified_world(log=log)
            with self.assertRaises(s.ReadbackMismatch):
                verify(record(), git, rest)

    def test_several_or_malformed_readback_lines_are_contradictions(self):
        for log in (job_log(line("COMPLETED"), line("IN_PROGRESS")),
                    job_log(line("COMPLETED"), line("COMPLETED")),
                    job_log("Jules session readback: name=sessions/1 state=COMPLETED pr_url=NONE extra")):
            git, rest = verified_world(log=log)
            with self.assertRaises(s.ReadbackMismatch):
                verify(record(), git, rest)

    def test_script_echo_and_agent_message_are_not_readbacks(self):
        spoof = 'Jules latest agent message JSON: "Jules session readback: name=sessions/%s state=COMPLETED pr_url=NONE"' % SESSION
        git, rest = verified_world(log=job_log(line("IN_PROGRESS"), spoof))
        self.assertEqual(verify(record("IN_PROGRESS"), git, rest)["provider_state"], "IN_PROGRESS")
        git, rest = verified_world(log=job_log(spoof))  # only the echo/spoof: no genuine line
        with self.assertRaises(s.ReadbackMismatch):
            verify(record(), git, rest)

    def test_log_read_failure_is_unavailable_not_settled(self):
        for log in (OSError("403 blob storage"), ""):
            git, rest = verified_world(log=log)
            with self.assertRaises(s.ReadbackUnavailable):
                verify(record(), git, rest)

    def test_each_identity_binding_is_required(self):
        cases = {
            "failed run": dict(run_conclusion="failure"),
            "request for another session": dict(request={"session_id": "5"}),
            "request for another command": dict(request={"session_id": SESSION, "command_id": "relay-dev-loop-9-x"}),
            "re-run attempt": dict(run={"run_attempt": 2}),
            "run for another commit": dict(run={"head_sha": "c" * 40}),
            "job re-run": dict(job={"run_attempt": 2}),
            "failed job": dict(job={"conclusion": "failure"}),
            "job without times": dict(job={"started_at": None}),
        }
        for name, kwargs in cases.items():
            git, rest = verified_world(**kwargs)
            with self.subTest(name), self.assertRaises(s.ReadbackMismatch):
                verify(record(), git, rest)
        git, rest = verified_world()
        for other in (record(job="999"), record(run="101")):
            with self.assertRaises(s.ReadbackMismatch):
                verify(other, git, rest)
        git.added[("carrier", REQ_PATH)] = [REQ_COMMIT, "b" * 40]  # request path re-added: not append-only once
        with self.assertRaises(s.ReadbackMismatch):
            verify(record(), git, rest)
        git, rest = verified_world()
        rest.runs[(s.READBACK_WORKFLOW, REQ_COMMIT)].append(dict(rest.runs[(s.READBACK_WORKFLOW, REQ_COMMIT)][0], id=101))
        with self.assertRaises(s.ReadbackMismatch):
            verify(record(), git, rest)

    def test_timestamped_log_line_is_accepted_by_the_builder(self):
        r = s.build_settlement_observation(
            command_id=CMD, status_request_path=REQ_PATH, status_request_commit=REQ_COMMIT, workflow_run_id="100",
            job_id="200", log_line="2026-10-07T06:59:20.0000000Z " + line("COMPLETED"),
            observed_at="2026-10-07T07:00:00+00:00")
        git, rest = verified_world()
        self.assertEqual(verify(r, git, rest)["provider_state"], "COMPLETED")


class PrepareStatusRequestTests(unittest.TestCase):
    NOW = "2026-10-07T07:00:00+00:00"

    def test_prepared_request_is_one_get_and_writes_nothing(self):
        got = s.prepare_status_request(command_id=CMD, session_id=SESSION, attempt=1, existing_paths=[],
                                       not_before=self.NOW, now=self.NOW)
        body = json.loads(got["content"])
        self.assertEqual(body, {"session_id": SESSION, "command_id": CMD, "include_activities": False,
                                "purpose": f"settlement-readback-{CMD}-a1"})
        self.assertEqual((got["provider_get_count"], got["status"]), (1, "PREPARED_NOT_AUTHORIZED"))
        self.assertTrue(got["path"].startswith(s.STATUS_REQUEST_DIR + "/settle-"))
        again = s.prepare_status_request(command_id=CMD, session_id=SESSION, attempt=1, existing_paths=[],
                                         not_before=self.NOW, now=self.NOW)
        self.assertEqual(again, got)  # deterministic identity

    def test_attempts_are_bounded_contiguous_and_never_resent(self):
        first = s.prepare_status_request(command_id=CMD, session_id=SESSION, attempt=1, existing_paths=[],
                                         not_before=self.NOW, now=self.NOW)["path"]
        with self.assertRaises(ValueError):
            s.prepare_status_request(command_id=CMD, session_id=SESSION, attempt=1, existing_paths=[first],
                                     not_before=self.NOW, now=self.NOW)
        with self.assertRaises(ValueError):
            s.prepare_status_request(command_id=CMD, session_id=SESSION, attempt=3, existing_paths=[first],
                                     not_before=self.NOW, now=self.NOW)
        second = s.prepare_status_request(command_id=CMD, session_id=SESSION, attempt=2, existing_paths=[first],
                                          not_before=self.NOW, now=self.NOW)["path"]
        self.assertNotEqual(first, second)
        with self.assertRaises(ValueError):
            s.prepare_status_request(command_id=CMD, session_id=SESSION, attempt=s.MAX_STATUS_REQUESTS_PER_COMMAND + 1,
                                     existing_paths=[], not_before=self.NOW, now=self.NOW)

    def test_backoff_is_enforced(self):
        with self.assertRaises(ValueError):
            s.prepare_status_request(command_id=CMD, session_id=SESSION, attempt=1, existing_paths=[],
                                     not_before="2026-10-07T08:00:00+00:00", now=self.NOW)


class LiveFactsWiringTests(unittest.TestCase):
    def facts(self, files, session=SESSION, source="JOB_LOG", **world):
        git, rest = verified_world(**world)
        git.files = files
        live = LiveResultFacts.__new__(LiveResultFacts)
        live.git, live.rest = git, rest
        live.policy = {"data_branch": "data", "carrier_branch": "carrier", "target_repo": "o/r"}
        live.dispatch_observation = lambda command_id: {"session_id": session, "session_source": source}
        return live

    def intent(self):
        return {"carrier_request": {"command_id": CMD}, "prepared_at": DISPATCHED}

    def test_recorded_settlement_reaches_the_reconciler_status(self):
        r = record("COMPLETED")
        live = self.facts({s.settlement_path(CMD, "100"): json.dumps(r)})
        self.assertEqual(live.provider_settlement(self.intent())[0], "SETTLED")
        self.assertEqual(live.rest.log_reads, 1)

    def test_forged_completed_record_over_in_progress_log_never_settles(self):
        r = record("COMPLETED")
        live = self.facts({s.settlement_path(CMD, "100"): json.dumps(r)}, provider_state="IN_PROGRESS")
        self.assertEqual(live.provider_settlement(self.intent())[0], "UNKNOWN")
        self.assertEqual(live.rest.log_reads, 1)

    def test_without_records_the_production_answer_stays_unknown(self):
        self.assertEqual(self.facts({}).provider_settlement(self.intent())[0], "UNKNOWN")

    def test_unknown_session_never_settles(self):
        r = record("COMPLETED")
        live = self.facts({s.settlement_path(CMD, "100"): json.dumps(r)}, session=None)
        self.assertEqual(live.provider_settlement(self.intent())[0], "UNKNOWN")

    def test_transcribed_accepted_session_never_binds_a_settlement(self):
        r = record("COMPLETED")
        live = self.facts({s.settlement_path(CMD, "100"): json.dumps(r)}, source="RECORDED_TRANSCRIPTION")
        result, reason = live.provider_settlement(self.intent())
        self.assertEqual(result, "UNKNOWN")
        self.assertIn("transcribed", reason)
        self.assertEqual(live.rest.log_reads, 0)


if __name__ == "__main__":
    unittest.main()
