"""Claude Path B one-shot state: STATIC tests (files only; no process, no Docker, no account)."""
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

from relay import claude_live_state as st
from relay import m9_live_state as m9


class ClaudeLiveStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="claude live "))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.dispatch = str(uuid.uuid4())

    def write(self, name, value):
        (self.tmp / name).write_text(json.dumps(value), encoding="utf-8")

    def consumed_auth(self):
        approval = st.build_approval(self.dispatch)
        self.write(st.APPROVAL_FILE, approval)
        self.assertTrue(m9.write_exclusive(self.tmp / st.CONSUMED_FILE, {"approval_sha256": approval["approval_sha256"]}))
        return st.LiveAuthorization(self.tmp, approval["approval_sha256"])

    def test_consumed_approval_returns_its_dispatch_id(self):
        self.assertEqual(st.verify_claude_live_authorization(self.consumed_auth(), "anthropic"), self.dispatch)

    def test_bad_records_are_refused(self):
        good = st.build_approval(self.dispatch)["record"]
        cases = {"codex decision": {"decision": m9.DECISION}, "other scope": {"scope": m9.SCOPE},
                 "not one shot": {"one_shot": 1}, "openai": {"provider": "openai"}, "bad id": {"dispatch_id": "x"},
                 "upper id": {"dispatch_id": self.dispatch.upper()}, "two prompts": {"max_prompts": 2},
                 "two generations": {"max_generations": 2}, "retry": {"retry": 1}, "fallback": {"fallback": "on"},
                 "extra key": {"model": "any"}}
        for name, change in cases.items():
            with self.subTest(name):
                record = {**good, **change}
                with self.assertRaises(ValueError):
                    st.verify_approval_record({"record": record, "approval_sha256": m9.canonical_sha256(record)})
        with self.assertRaises(ValueError):
            st.verify_approval_record({"record": good, "approval_sha256": "0" * 64})

    def test_codex_approval_is_not_accepted_and_claude_approval_is_not_accepted_by_codex(self):
        auth = self.consumed_auth()
        with self.assertRaises(ValueError):
            m9.verify_live_authorization(auth, "anthropic")
        with self.assertRaises(ValueError):
            m9.verify_approval_record(json.loads((self.tmp / st.APPROVAL_FILE).read_text()))
        with self.assertRaises(ValueError):
            st.verify_claude_live_authorization(auth, "openai")

    def test_missing_consumed_wrong_digest_and_terminal_fail_closed(self):
        approval = st.build_approval(self.dispatch)
        self.write(st.APPROVAL_FILE, approval)
        auth = st.LiveAuthorization(self.tmp, approval["approval_sha256"])
        with self.assertRaisesRegex(ValueError, "APPROVAL_PROVENANCE_NOT_VERIFIED"):
            st.verify_claude_live_authorization(auth, "anthropic")  # not consumed yet
        self.write(st.CONSUMED_FILE, {"approval_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "not consumed for this run"):
            st.verify_claude_live_authorization(auth, "anthropic")
        self.write(st.CONSUMED_FILE, {"approval_sha256": approval["approval_sha256"]})
        with self.assertRaisesRegex(ValueError, "not consumed for this run"):
            st.verify_claude_live_authorization(st.LiveAuthorization(self.tmp, "1" * 64), "anthropic")
        self.write(st.TERMINAL_FILE, {"state": "DONE"})
        with self.assertRaisesRegex(ValueError, "terminal receipt exists"):
            st.verify_claude_live_authorization(auth, "anthropic")

    def test_not_a_live_authorization(self):
        with self.assertRaises(ValueError):
            st.verify_claude_live_authorization({"state_dir": str(self.tmp)}, "anthropic")


if __name__ == "__main__":
    unittest.main()
