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


def line(state: str, session: str = SESSION) -> str:
    return f"Jules session readback: name=sessions/{session} state={state} pr_url=NONE"


def record(state: str = "COMPLETED", *, run: str = "100", job: str = "200", at: str = "2026-10-07T07:00:00+00:00",
           session: str = SESSION, command: str = CMD) -> dict:
    return s.build_settlement_observation(
        command_id=command, status_request_path=REQ_PATH, status_request_commit=REQ_COMMIT,
        workflow_run_id=run, job_id=job, log_line=line(state, session), observed_at=at)


def status(records, verified=lambda r: True, session=SESSION):
    return s.settlement_status(records, command_id=CMD, accepted_session_id=session, dispatched_at=DISPATCHED,
                               run_verified=verified)


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

    def test_latest_verified_readback_decides_progress(self):
        older = record("IN_PROGRESS", run="100", at="2026-10-07T06:00:00+00:00")
        newer = record("COMPLETED", run="101", at="2026-10-07T07:00:00+00:00")
        result, ref = status([newer, older])
        self.assertEqual(result, "SETTLED")
        self.assertIn("run 101", ref)

    def test_unsettled_after_settled_is_a_contradiction(self):
        settled = record("COMPLETED", run="100", at="2026-10-07T06:00:00+00:00")
        later = record("IN_PROGRESS", run="101", at="2026-10-07T07:00:00+00:00")
        self.assertEqual(status([settled, later])[0], "UNKNOWN")

    def test_other_session_or_unverified_run_is_unknown(self):
        self.assertEqual(status([record(session="99")])[0], "UNKNOWN")
        self.assertEqual(status([record()], verified=lambda r: False)[0], "UNKNOWN")

        def boom(r):
            raise RuntimeError("403")
        self.assertEqual(status([record()], verified=boom)[0], "UNKNOWN")

    def test_readback_before_dispatch_or_other_command_is_ignored(self):
        stale = record("COMPLETED", at="2026-10-06T23:00:00+00:00")
        other = record("COMPLETED", command="relay-dev-loop-202-other")
        self.assertEqual(status([stale, other])[0], "UNKNOWN")

    def test_invalid_record_is_unknown_not_skipped(self):
        bad = dict(record(), provider_state="FAILED")
        self.assertEqual(status([bad, record()])[0], "UNKNOWN")


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
    def __init__(self, runs=None, jobs=None):
        self.runs, self.jobs = runs or {}, jobs or {}

    def workflow_runs_for_commit(self, workflow, sha):
        return self.runs.get((workflow, sha), [])

    def run_jobs(self, run_id):
        return self.jobs.get(run_id, [])


def verified_world(run_conclusion="success", request_session=SESSION):
    git = FakeGit(added={("carrier", REQ_PATH): [REQ_COMMIT]},
                  shown={(REQ_COMMIT, REQ_PATH): json.dumps({"session_id": request_session})})
    rest = FakeRest(runs={(s.READBACK_WORKFLOW, REQ_COMMIT): [
        {"id": 100, "event": "push", "status": "completed", "conclusion": run_conclusion}]},
        jobs={100: [{"id": 200}]})
    return git, rest


class VerifyRunTests(unittest.TestCase):
    def test_verified_readback_run(self):
        git, rest = verified_world()
        self.assertTrue(s.verify_readback_run(record(), git=git, rest=rest, carrier_branch="carrier"))

    def test_each_binding_is_required(self):
        cases = {
            "failed run": verified_world(run_conclusion="failure"),
            "request for another session": verified_world(request_session="5"),
        }
        for name, (git, rest) in cases.items():
            self.assertFalse(s.verify_readback_run(record(), git=git, rest=rest, carrier_branch="carrier"), name)
        git, rest = verified_world()
        self.assertFalse(s.verify_readback_run(record(job="999"), git=git, rest=rest, carrier_branch="carrier"))
        self.assertFalse(s.verify_readback_run(record(run="101"), git=git, rest=rest, carrier_branch="carrier"))
        git.added[("carrier", REQ_PATH)] = [REQ_COMMIT, "b" * 40]  # request path re-added: not append-only once
        self.assertFalse(s.verify_readback_run(record(), git=git, rest=rest, carrier_branch="carrier"))


class LiveFactsWiringTests(unittest.TestCase):
    def facts(self, files, session=SESSION):
        git, rest = verified_world()
        git.files = files
        facts = LiveResultFacts.__new__(LiveResultFacts)
        facts.git, facts.rest = git, rest
        facts.policy = {"data_branch": "data", "carrier_branch": "carrier", "target_repo": "o/r"}
        facts.dispatch_observation = lambda command_id: {"session_id": session}
        return facts

    def intent(self):
        return {"carrier_request": {"command_id": CMD}, "prepared_at": DISPATCHED}

    def test_recorded_settlement_reaches_the_reconciler_status(self):
        r = record("COMPLETED")
        facts = self.facts({s.settlement_path(CMD, "100"): json.dumps(r)})
        self.assertEqual(facts.provider_settlement(self.intent())[0], "SETTLED")

    def test_without_records_the_production_answer_stays_unknown(self):
        self.assertEqual(self.facts({}).provider_settlement(self.intent())[0], "UNKNOWN")

    def test_unknown_session_never_settles(self):
        r = record("COMPLETED")
        facts = self.facts({s.settlement_path(CMD, "100"): json.dumps(r)}, session=None)
        self.assertEqual(facts.provider_settlement(self.intent())[0], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
