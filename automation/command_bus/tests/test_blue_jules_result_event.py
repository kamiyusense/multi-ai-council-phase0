import unittest

from automation.command_bus.blue_jules_result_event import (
    EventDecision,
    EventLineage,
    classify_blue_jules_result_event,
)

HEAD = "a" * 40
BASE_SHA = "c" * 40
REPO = "kamiyusense/multi-ai-council-phase0"
WORK_BRANCH = "jules-work/test-branch"
CMD_ID = "cmd-123"


def valid_lineage(**changes):
    values = {
        "source_command_id": CMD_ID,
        "work_branch": WORK_BRANCH,
        "expected_target_head": BASE_SHA,
        "expected_repository": REPO,
    }
    values.update(changes)
    return EventLineage(**values)


def valid_event(**changes):
    event = {
        "action": "opened",
        "repository": {"full_name": REPO},
        "pull_request": {
            "number": 42,
            "head": {"sha": HEAD},
            "base": {"ref": WORK_BRANCH, "sha": BASE_SHA},
        },
    }
    event.update(changes)
    return event


class BlueJulesResultEventTests(unittest.TestCase):
    def classify(self, event=None, lineage=None, seen=()):
        return classify_blue_jules_result_event(
            valid_event() if event is None else event,
            valid_lineage() if lineage is None else lineage,
            seen,
        )

    def test_opened_and_synchronize_wake_with_exact_identity(self):
        for action in ("opened", "synchronize"):
            with self.subTest(action=action):
                result = self.classify(valid_event(action=action))
                self.assertEqual(result.decision, EventDecision.WAKE)
                self.assertEqual(
                    result.command_id,
                    f"blue-jules-result-pr42-{HEAD}",
                )
                self.assertEqual(result.reason, "eligible for wake")

    def test_same_pr_same_head_is_deterministic_and_duplicate_is_ignore(self):
        first = self.classify()
        second = self.classify()
        self.assertEqual(first.command_id, second.command_id)
        duplicate = self.classify(seen={first.command_id})
        self.assertEqual(duplicate.decision, EventDecision.IGNORE)
        self.assertEqual(duplicate.command_id, first.command_id)
        self.assertEqual(duplicate.reason, "duplicate command identity")

    def test_new_head_same_pr_gets_new_identity_and_wakes(self):
        old = self.classify()
        event = valid_event()
        event["pull_request"]["head"]["sha"] = "d" * 40
        result = self.classify(event, seen={old.command_id})
        self.assertEqual(result.decision, EventDecision.WAKE)
        self.assertEqual(result.command_id, f"blue-jules-result-pr42-{'d' * 40}")
        self.assertNotEqual(result.command_id, old.command_id)

    def test_unsupported_action_prefilters_without_pr_or_lineage_details(self):
        event = {
            "action": "closed",
            "repository": {"full_name": REPO},
        }
        result = classify_blue_jules_result_event(event, None, None)
        self.assertEqual(result.decision, EventDecision.IGNORE)
        self.assertEqual(result.reason, "unsupported action")

    def test_wrong_repository_prefilters_without_pr_or_lineage_details(self):
        event = {
            "action": "opened",
            "repository": {"full_name": "other/repo"},
        }
        result = classify_blue_jules_result_event(event, None, None)
        self.assertEqual(result.decision, EventDecision.IGNORE)
        self.assertEqual(result.reason, "wrong repository")

    def test_unrelated_base_prefilters_without_head_number_or_base_sha(self):
        event = {
            "action": "opened",
            "repository": {"full_name": REPO},
            "pull_request": {"base": {"ref": "main"}},
        }
        result = self.classify(event)
        self.assertEqual(result.decision, EventDecision.IGNORE)
        self.assertEqual(result.reason, "unrelated base branch")

    def test_matching_work_branch_with_base_sha_mismatch_is_unknown(self):
        event = valid_event()
        event["pull_request"]["base"]["sha"] = "f" * 40
        result = self.classify(event)
        self.assertEqual(result.decision, EventDecision.UNKNOWN)
        self.assertEqual(result.reason, "base SHA lineage mismatch")

    def test_missing_candidate_identity_fields_are_unknown(self):
        cases = []

        missing_base_ref = valid_event()
        del missing_base_ref["pull_request"]["base"]["ref"]
        cases.append(missing_base_ref)

        missing_base_sha = valid_event()
        del missing_base_sha["pull_request"]["base"]["sha"]
        cases.append(missing_base_sha)

        missing_number = valid_event()
        del missing_number["pull_request"]["number"]
        cases.append(missing_number)

        missing_head = valid_event()
        del missing_head["pull_request"]["head"]["sha"]
        cases.append(missing_head)

        for event in cases:
            with self.subTest(event=event):
                self.assertEqual(self.classify(event).decision, EventDecision.UNKNOWN)

    def test_malformed_head_is_unknown(self):
        for bad_head in (HEAD.upper(), "a" * 39, "z" * 40, 123):
            event = valid_event()
            event["pull_request"]["head"]["sha"] = bad_head
            with self.subTest(bad_head=bad_head):
                self.assertEqual(self.classify(event).decision, EventDecision.UNKNOWN)

    def test_malformed_pr_number_is_unknown_including_bool(self):
        for bad_number in (0, -1, "42", [], True):
            event = valid_event()
            event["pull_request"]["number"] = bad_number
            with self.subTest(bad_number=bad_number):
                self.assertEqual(self.classify(event).decision, EventDecision.UNKNOWN)

    def test_malformed_lineage_objects_fail_closed_without_throwing(self):
        for lineage in (
            None,
            {},
            valid_lineage(source_command_id=""),
            valid_lineage(work_branch=""),
            valid_lineage(expected_target_head="short"),
            valid_lineage(expected_repository="other/repo"),
        ):
            with self.subTest(lineage=lineage):
                result = classify_blue_jules_result_event(valid_event(), lineage, ())
                self.assertEqual(result.decision, EventDecision.UNKNOWN)

    def test_expected_repository_is_fixed_to_phase0_repo(self):
        event = valid_event(repository={"full_name": "other/repo"})
        lineage = valid_lineage(expected_repository="other/repo")
        result = classify_blue_jules_result_event(event, lineage, ())
        self.assertEqual(result.decision, EventDecision.IGNORE)

        result2 = self.classify(lineage=valid_lineage(expected_repository="other/repo"))
        self.assertEqual(result2.decision, EventDecision.UNKNOWN)
        self.assertEqual(result2.reason, "lineage repository mismatch")

    def test_malformed_seen_identity_input_is_unknown(self):
        for seen in (None, "one-id", [123]):
            with self.subTest(seen=seen):
                result = classify_blue_jules_result_event(valid_event(), valid_lineage(), seen)
                self.assertEqual(result.decision, EventDecision.UNKNOWN)

    def test_actor_title_and_color_are_not_correctness_inputs(self):
        event = valid_event(
            sender={"login": "google-labs-jules[bot]"},
            pull_request={
                "number": 99,
                "title": "💙 looks like Jules",
                "head": {"sha": "e" * 40},
                "base": {"ref": "main"},
            },
        )
        result = self.classify(event)
        self.assertEqual(result.decision, EventDecision.IGNORE)
        self.assertEqual(result.reason, "unrelated base branch")

    def test_malformed_top_level_payload_is_unknown(self):
        for payload in (None, [], "event"):
            with self.subTest(payload=payload):
                result = classify_blue_jules_result_event(payload, valid_lineage(), ())
                self.assertEqual(result.decision, EventDecision.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
