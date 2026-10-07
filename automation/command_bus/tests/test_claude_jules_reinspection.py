from __future__ import annotations

import copy
import unittest

from automation.command_bus.claude_jules_inspection import INSPECTION_PROFILE
from automation.command_bus.claude_jules_reinspection import ReinspectionStore
from automation.command_bus.claude_jules_dispatch import sha256_of
from automation.command_bus.claude_jules_dispatch import canonical_json
from automation.command_bus.claude_jules_reinspection import reinspection_path, validate_reinspection_record
from dataclasses import replace
from automation.command_bus.tests.claude_jules_autoloop_fakes import DATA, FakeGitHub


def inspection(*, verdict="UNKNOWN", decision="INVESTIGATE", reason="evidence missing", inspected_at="2026-10-07T00:00:00+00:00"):
    record = {
        "schema_version": 1,
        "profile": INSPECTION_PROFILE,
        "command_id": "relay-dev-loop-900-alpha",
        "task_id": "alpha-helper",
        "intent_sha256": "1" * 64,
        "candidate_head": "a" * 40,
        "candidate_tree": "b" * 40 if verdict == "PASS" else None,
        "repair_of": None,
        "changed_paths": [],
        "checks": ([{"check": "all", "state": "PASS", "detail": "ok"}] if verdict == "PASS"
                   else [{"check": "tests", "state": "UNKNOWN", "detail": "unavailable"}]),
        "findings": [],
        "verdict": verdict,
        "decision": decision,
        "reason": reason,
        "inspected_at": inspected_at,
        "self_report_used": False,
    }
    record["inspection_sha256"] = sha256_of(record)
    return record


class ReinspectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.store = ReinspectionStore(self.github, data_branch=DATA)
        self.base = inspection()

    def test_same_head_unknown_can_append_pass_without_overwriting_base(self):
        passed = inspection(
            verdict="PASS", decision="ADOPT_CANDIDATE", reason="all independent checks passed",
            inspected_at="2026-10-07T00:10:00+00:00",
        )
        self.assertEqual(self.store.persist(base=self.base, inspection=passed), "CREATED")
        self.assertEqual(self.store.effective(self.base)["verdict"], "PASS")
        self.assertEqual([r["verdict"] for r in self.store.all_versions(self.base)], ["UNKNOWN", "PASS"])

    def test_terminal_effective_inspection_cannot_be_reinspected(self):
        passed = inspection(
            verdict="PASS", decision="ADOPT_CANDIDATE", reason="all independent checks passed",
            inspected_at="2026-10-07T00:10:00+00:00",
        )
        self.assertEqual(self.store.persist(base=self.base, inspection=passed), "CREATED")
        another = copy.deepcopy(passed)
        another["inspected_at"] = "2026-10-07T00:20:00+00:00"
        another["inspection_sha256"] = sha256_of({k: v for k, v in another.items() if k != "inspection_sha256"})
        self.assertEqual(self.store.persist(base=self.base, inspection=another), "BLOCKED")

    def test_multiple_unknown_reinspections_form_append_only_chain(self):
        second = inspection(inspected_at="2026-10-07T00:10:00+00:00")
        third = inspection(
            verdict="PASS", decision="ADOPT_CANDIDATE", reason="all independent checks passed",
            inspected_at="2026-10-07T00:20:00+00:00",
        )
        self.assertEqual(self.store.persist(base=self.base, inspection=second), "CREATED")
        self.assertEqual(self.store.persist(base=self.base, inspection=third), "CREATED")
        self.assertEqual([r["verdict"] for r in self.store.all_versions(self.base)], ["UNKNOWN", "UNKNOWN", "PASS"])

    def test_ambiguous_create_after_write_is_read_back_not_replayed(self):
        passed = inspection(
            verdict="PASS", decision="ADOPT_CANDIDATE", reason="all independent checks passed",
            inspected_at="2026-10-07T00:10:00+00:00",
        )
        self.github.create_hook = lambda path, branch: "raise-after-write"
        self.assertEqual(self.store.persist(base=self.base, inspection=passed), "CREATED")

    def test_identity_change_is_blocked(self):
        passed = inspection(
            verdict="PASS", decision="ADOPT_CANDIDATE", reason="all independent checks passed",
            inspected_at="2026-10-07T00:10:00+00:00",
        )
        passed["intent_sha256"] = "2" * 64
        passed["inspection_sha256"] = sha256_of({k: v for k, v in passed.items() if k != "inspection_sha256"})
        self.assertEqual(self.store.persist(base=self.base, inspection=passed), "BLOCKED")

    def test_valid_digest_does_not_allow_changed_task_or_known_tree(self):
        known = inspection()
        known["candidate_tree"] = "b" * 40
        known["inspection_sha256"] = sha256_of({k: v for k, v in known.items() if k != "inspection_sha256"})
        for key, bad in (("task_id", "other-task"), ("repair_of", "c" * 40), ("candidate_tree", "c" * 40)):
            passed = inspection(verdict="PASS", decision="ADOPT_CANDIDATE", reason="checked")
            passed[key] = bad
            passed["inspection_sha256"] = sha256_of({k: v for k, v in passed.items() if k != "inspection_sha256"})
            with self.subTest(key=key):
                self.assertEqual(self.store.persist(base=known, inspection=passed), "BLOCKED")

    def test_rehashed_remote_identity_tampering_is_rejected_on_read(self):
        passed = inspection(verdict="PASS", decision="ADOPT_CANDIDATE", reason="checked")
        self.assertEqual(self.store.persist(base=self.base, inspection=passed), "CREATED")
        path = reinspection_path(self.base["command_id"], self.base["candidate_head"], 1)
        original = self.github.get(path, DATA)
        import json
        wrapper = json.loads(original.text)
        wrapper["inspection"]["task_id"] = "other-task"
        wrapper["inspection"]["inspection_sha256"] = sha256_of({k: v for k, v in wrapper["inspection"].items() if k != "inspection_sha256"})
        wrapper["reinspection_sha256"] = sha256_of({k: v for k, v in wrapper.items() if k != "reinspection_sha256"})
        validate_reinspection_record(wrapper)  # individual schema/digest alone is insufficient
        self.github.files[(DATA, path)] = replace(original, text=canonical_json(wrapper))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.store.effective(self.base)

    def test_rehashed_remote_record_cannot_continue_after_pass(self):
        import json
        passed = inspection(verdict="PASS", decision="ADOPT_CANDIDATE", reason="checked")
        self.assertEqual(self.store.persist(base=self.base, inspection=passed), "CREATED")
        first = json.loads(self.github.get(reinspection_path(self.base["command_id"], self.base["candidate_head"], 1), DATA).text)
        forged = copy.deepcopy(first)
        forged["attempt"] = 2
        forged["previous_inspection_sha256"] = passed["inspection_sha256"]
        forged["reinspection_sha256"] = sha256_of({k: v for k, v in forged.items() if k != "reinspection_sha256"})
        self.github.create(reinspection_path(self.base["command_id"], self.base["candidate_head"], 2), canonical_json(forged), "tamper fixture", DATA)
        with self.assertRaisesRegex(ValueError, "terminal verdict"):
            self.store.all_versions(self.base)


if __name__ == "__main__":
    unittest.main()
