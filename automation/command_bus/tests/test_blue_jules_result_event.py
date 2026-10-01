import unittest

from automation.command_bus.blue_jules_result_event import (
    EventClassificationResult,
    EventDecision,
    EventLineage,
    classify_blue_jules_result_event,
)

HEAD = "a" * 40
TREE = "b" * 40
BASE_SHA = "c" * 40
REPO = "kamiyusense/multi-ai-council-phase0"
WORK_BRANCH = "jules-work/test-branch"
CMD_ID = "cmd-123"

def valid_lineage(**changes) -> EventLineage:
    values = dict(
        source_command_id=CMD_ID,
        work_branch=WORK_BRANCH,
        expected_target_head=BASE_SHA,
        expected_repository=REPO,
    )
    values.update(changes)
    return EventLineage(**values)

def valid_event(**changes):
    values = {
        "action": "opened",
        "repository": {"full_name": REPO},
        "pull_request": {
            "number": 42,
            "head": {"sha": HEAD},
            "base": {"ref": WORK_BRANCH, "sha": BASE_SHA}
        }
    }
    # Deep update for simpler test setup
    for k, v in changes.items():
        if isinstance(v, dict) and k in values and isinstance(values[k], dict):
            values[k].update(v)
            # Ensure base has both ref and sha if only one is updated
            if k == "pull_request" and "base" in v:
                if "ref" in v["base"] and "sha" not in v["base"]:
                    values["pull_request"]["base"]["sha"] = BASE_SHA
                if "sha" in v["base"] and "ref" not in v["base"]:
                    values["pull_request"]["base"]["ref"] = WORK_BRANCH
        else:
            values[k] = v
    return values


class BlueJulesResultEventTests(unittest.TestCase):
    def test_matching_jules_result_pr_opened_wakes(self):
        result = classify_blue_jules_result_event(valid_event(action="opened"), valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.WAKE)
        self.assertEqual(result.command_id, f"blue-jules-result-pr42-{HEAD}")

    def test_matching_jules_result_pr_synchronize_wakes(self):
        result = classify_blue_jules_result_event(valid_event(action="synchronize"), valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.WAKE)
        self.assertEqual(result.command_id, f"blue-jules-result-pr42-{HEAD}")

    def test_duplicate_command_id_in_seen_ignores(self):
        event = valid_event()
        expected_id = f"blue-jules-result-pr42-{HEAD}"
        result = classify_blue_jules_result_event(event, valid_lineage(), [expected_id])
        self.assertEqual(result.decision, EventDecision.IGNORE)
        self.assertEqual(result.command_id, expected_id)

    def test_new_valid_head_for_same_pr_wakes_and_creates_distinct_id(self):
        new_head = "d" * 40
        event = valid_event(pull_request={"head": {"sha": new_head}})
        expected_id = f"blue-jules-result-pr42-{new_head}"
        result = classify_blue_jules_result_event(event, valid_lineage(), [f"blue-jules-result-pr42-{HEAD}"])
        self.assertEqual(result.decision, EventDecision.WAKE)
        self.assertEqual(result.command_id, expected_id)

    def test_unrelated_human_pr_ignores(self):
        event = valid_event(pull_request={"base": {"ref": "main"}})
        result = classify_blue_jules_result_event(event, valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.IGNORE)

    def test_wrong_repository_ignores(self):
        event = valid_event(repository={"full_name": "other/repo"})
        result = classify_blue_jules_result_event(event, valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.IGNORE)

    def test_unsupported_action_ignores(self):
        event = valid_event(action="closed")
        result = classify_blue_jules_result_event(event, valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.IGNORE)

    def test_missing_head_unknown(self):
        event = valid_event()
        del event["pull_request"]["head"]["sha"]
        result = classify_blue_jules_result_event(event, valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.UNKNOWN)

    def test_malformed_head_unknown(self):
        cases = [
            HEAD.upper(), # uppercase
            "a" * 39,     # short
            "z" * 40,     # non-hex
            123,          # invalid type
        ]
        for bad_head in cases:
            with self.subTest(bad_head=bad_head):
                event = valid_event(pull_request={"head": {"sha": bad_head}})
                result = classify_blue_jules_result_event(event, valid_lineage(), [])
                self.assertEqual(result.decision, EventDecision.UNKNOWN)

    def test_missing_malformed_pr_number_unknown(self):
        cases = [None, -1, 0, "42", []]
        for bad_pr in cases:
            with self.subTest(bad_pr=bad_pr):
                event = valid_event(pull_request={"number": bad_pr})
                if bad_pr is None:
                    del event["pull_request"]["number"]
                result = classify_blue_jules_result_event(event, valid_lineage(), [])
                self.assertEqual(result.decision, EventDecision.UNKNOWN)

    def test_missing_malformed_lineage_unknown(self):
        cases = [
            valid_lineage(source_command_id=None),
            valid_lineage(work_branch=""),
            valid_lineage(expected_target_head="short"),
            valid_lineage(expected_repository=None),
        ]
        for bad_lineage in cases:
            with self.subTest(bad_lineage=bad_lineage):
                result = classify_blue_jules_result_event(valid_event(), bad_lineage, [])
                self.assertEqual(result.decision, EventDecision.UNKNOWN)

    def test_work_branch_match_but_base_sha_mismatch_unknown(self):
        event = valid_event(pull_request={"base": {"sha": "f" * 40}}) # Different base sha
        result = classify_blue_jules_result_event(event, valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.UNKNOWN)

    def test_missing_base_ref_or_sha_unknown(self):
        event = valid_event()
        del event["pull_request"]["base"]["ref"]
        result = classify_blue_jules_result_event(event, valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.UNKNOWN)

        event2 = valid_event()
        del event2["pull_request"]["base"]["sha"]
        result = classify_blue_jules_result_event(event2, valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.UNKNOWN)

    def test_malformed_top_level_payload_unknown(self):
        result = classify_blue_jules_result_event([], valid_lineage(), [])
        self.assertEqual(result.decision, EventDecision.UNKNOWN)
