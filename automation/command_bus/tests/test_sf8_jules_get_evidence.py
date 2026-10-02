import json
import unittest

from automation.command_bus.sf8_jules_get_evidence import build_evidence, run

SECRET = "SECRET-API-KEY-VALUE"
SID = "14533806911319619381"
REPO = "kamiyusense/multi-ai-council-phase0"
BRANCH = "jules-work/relay-dev-loop-120-signal-observed-static-e2e"
CREATE = "2026-10-01T22:13:44+09:00"
SHA = "a" * 40


def session(**over):
    value = {
        "name": f"sessions/{SID}", "createTime": "2026-10-01T13:13:44.123456Z",
        "updateTime": "2026-10-01T13:30:00Z", "state": "COMPLETED",
        "sourceContext": {"source": f"sources/github/{REPO}",
                          "githubRepoContext": {"startingBranch": BRANCH}},
    }
    value.update(over)
    return value


def env(**over):
    value = {
        "SF8_SESSION_ID": SID, "SF8_EXPECTED_BRANCH": BRANCH, "SF8_EXPECTED_CREATE_TIME": CREATE,
        "GITHUB_RUN_ID": "99", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": SHA,
        "GITHUB_REPOSITORY": REPO, "JULES_API_KEY": SECRET,
    }
    value.update(over)
    return value


class FakeReader:
    def __init__(self, result, provider):
        self.result, self.calls = result, []
        self.provider = provider

    def read_session(self, session_id):
        self.calls.append(session_id)
        assert self.provider() == SECRET  # key reaches reader only via provider
        return self.result


def evidence_for(result, **env_over):
    holder = {}

    def factory(provider):
        holder["reader"] = FakeReader(result, provider)
        return holder["reader"]

    ev, code = run(env(**env_over), reader_factory=factory, now=lambda: "2026-10-02T04:00:00Z")
    return ev, code, holder["reader"]


class JulesGetEvidenceTests(unittest.TestCase):
    def test_exact_binding_passes_with_raw_completed_state_and_one_get(self):
        ev, code, reader = evidence_for(session())
        self.assertEqual((ev["status"], code), ("PASS", 0))
        self.assertEqual(ev["raw_state"], "COMPLETED")  # raw state, not RUNNING
        self.assertEqual(ev["retry_count"], 0)
        self.assertEqual(ev["http_method"], "GET")
        self.assertEqual(reader.calls, [SID])
        self.assertNotIn(SECRET, json.dumps(ev))

    def test_failures_are_unknown_not_pass(self):
        for label, result, category in (
            ("read_failed", None, "READ_FAILED"),
            ("other_branch", session(sourceContext={"source": f"sources/github/{REPO}", "githubRepoContext": {"startingBranch": "x"}}), "BINDING_MISMATCH"),
            ("other_repo", session(sourceContext={"source": "sources/github/o/r", "githubRepoContext": {"startingBranch": BRANCH}}), "BINDING_MISMATCH"),
            ("other_time", session(createTime="2026-10-01T13:13:45Z"), "BINDING_MISMATCH"),
            ("other_name", session(name="sessions/1"), "BINDING_MISMATCH"),
            ("naive_time", session(createTime="2026-10-01T13:13:44"), "BINDING_MISMATCH"),
        ):
            with self.subTest(label):
                ev, code, _ = evidence_for(result)
                self.assertEqual((ev["status"], ev["error_category"], code), ("UNKNOWN", category, 1))

    def test_bad_runner_context_or_session_id_is_rejected_before_any_get(self):
        for bad in (env(SF8_SESSION_ID="abc"), env(GITHUB_RUN_ATTEMPT="2"), env(GITHUB_SHA="x"), env(GITHUB_RUN_ID="")):
            with self.subTest(bad=bad):
                reads = []
                with self.assertRaises(ValueError):
                    run(bad, reader_factory=lambda p: reads.append(1) or FakeReader(None, p))
                self.assertEqual(reads, [])

    def test_unexpected_state_text_is_not_echoed(self):
        ev, _, _ = evidence_for(session(state="<script>alert(1)</script>"))
        self.assertEqual(ev["raw_state"], "UNKNOWN")

    def test_digest_covers_body(self):
        import hashlib
        ev, _, _ = evidence_for(session())
        body = {k: v for k, v in ev.items() if k != "evidence_sha256"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), ev["evidence_sha256"])


if __name__ == "__main__":
    unittest.main()
