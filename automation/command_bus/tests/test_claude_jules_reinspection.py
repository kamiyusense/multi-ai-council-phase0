from __future__ import annotations

import copy
import unittest

from automation.command_bus.claude_jules_inspection import INSPECTION_PROFILE
from automation.command_bus.claude_jules_reinspection import ReinspectionStore
from automation.command_bus.claude_jules_dispatch import sha256_of
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


if __name__ == "__main__":
    unittest.main()
