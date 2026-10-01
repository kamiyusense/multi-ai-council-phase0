import copy
import unittest
from urllib.parse import urlencode

from automation.command_bus.github_jules_source import collect_global_jules_snapshot, read_result_source
from automation.command_bus.github_readonly import ROOT, ReadResponse
from .test_cloud_work_snapshot import SnapshotReader
from .closed_loop_fixtures import snapshot


class JulesSourceReader(SnapshotReader):
    def __init__(self):
        super().__init__()
        self.source = snapshot()["source"]
        self.pages[ROOT + "/git/ref/heads/main"] = ReadResponse({"object": {"sha": self.carrier["head"]["sha"]}}, {})
        self.put_content(".github/workflows/jules-chat-semiauto.yml", "on:\n  push:\n    branches:\n      - feature/chat-work-command-bus\n    paths:\n      - automation/command_bus/jules_api_requests/*.json\n")
        self.pages[ROOT + "/git/ref/heads/feature/chat-work-command-bus"] = ReadResponse({"object": {"sha": self.carrier["head"]["sha"]}}, {})
        tree = [{"path": "automation/command_bus/loop_id_claims/900.json", "type": "blob"},
                {"path": "automation/command_bus/jules_api_requests/relay-dev-loop-900-mock-source.json", "type": "blob"}]
        self.pages[ROOT + "/git/trees/" + self.carrier["head"]["sha"] + "?recursive=1"] = ReadResponse({"truncated": False, "tree": tree}, {})
        self.pages[ROOT + "/branches?per_page=100"] = ReadResponse([{"name": "jules-work/relay-dev-loop-900-mock-source", "commit": {"sha": "a" * 40}}], {})
        import json
        self.path = "automation/command_bus/jules_api_requests/relay-dev-loop-900-mock-source.json"
        self.put_content(self.path, json.dumps(self.source["request"]))
        self.put_content("automation/command_bus/loop_id_claims/900.json", json.dumps(self.source["claim"]))
        self.history_url = ROOT + "/commits?" + urlencode({"sha": self.carrier["head"]["sha"], "path": self.path, "per_page": 100})
        self.pages[self.history_url] = ReadResponse([{"sha": "f" * 40}], {})
        self.pages[ROOT + "/commits/" + "f" * 40] = ReadResponse(self.source["command_commit"], {})
        self.runs_url = ROOT + "/actions/runs?" + urlencode({"head_sha": "f" * 40, "per_page": 100})
        self.pages[self.runs_url] = ReadResponse({"total_count": 1, "workflow_runs": [self.source["dispatch_run"]]}, {})


class JulesSourceTests(unittest.TestCase):
    def test_discovered_carrier_complete_global_tree_branches_and_source(self):
        reader = JulesSourceReader()
        global_snapshot = collect_global_jules_snapshot(reader)
        self.assertEqual(global_snapshot.carrier_branch, "feature/chat-work-command-bus")
        source = read_result_source(reader, global_snapshot, self_branch())
        self.assertEqual(source["request"]["command_id"], "relay-dev-loop-900-mock-source")
        self.assertEqual(source["claim"]["schema_version"], 3)
        self.assertEqual(source["jules_direct_session_readback"], "NOT_WIRED")

    def test_additional_branch_pages_prevent_lane_local_loop_choice(self):
        reader = JulesSourceReader()
        url = ROOT + "/branches?per_page=100"
        reader.pages[url].headers["link"] = f'<{url}&page=2>; rel="next"'
        reader.pages[url + "&page=2"] = ReadResponse([{"name": "jules-work/relay-dev-loop-999-red-source", "commit": {"sha": "b" * 40}}], {})
        result = collect_global_jules_snapshot(reader)
        self.assertEqual(len(result.branch_refs), 2)

    def test_workflow_route_change_is_unknown_not_remembered_fallback(self):
        reader = JulesSourceReader()
        reader.put_content(".github/workflows/jules-chat-semiauto.yml", "on: push\n")
        with self.assertRaises(ValueError):
            collect_global_jules_snapshot(reader)

    def test_truncated_global_tree_unknown(self):
        reader = JulesSourceReader()
        url = ROOT + "/git/trees/" + reader.carrier["head"]["sha"] + "?recursive=1"
        reader.pages[url].data["truncated"] = True
        with self.assertRaises(ValueError):
            collect_global_jules_snapshot(reader)

    def test_missing_or_edited_command_history_blocks(self):
        for rows in ([], [{"sha": "f" * 40}, {"sha": "b" * 40}]):
            reader = JulesSourceReader()
            global_snapshot = collect_global_jules_snapshot(reader)
            reader.pages[reader.history_url] = ReadResponse(rows, {})
            with self.assertRaises(ValueError):
                read_result_source(reader, global_snapshot, self_branch())

    def test_ambiguous_multiple_dispatch_or_rerun_unknown(self):
        for rerun in (False, True):
            reader = JulesSourceReader()
            global_snapshot = collect_global_jules_snapshot(reader)
            if rerun:
                reader.pages[reader.runs_url].data["workflow_runs"][0]["run_attempt"] = 2
            else:
                other = copy.deepcopy(reader.source["dispatch_run"])
                other["id"] = 999
                reader.pages[reader.runs_url].data.update(total_count=2, workflow_runs=[reader.source["dispatch_run"], other])
            with self.assertRaises(ValueError):
                read_result_source(reader, global_snapshot, self_branch())

    def test_unnumbered_fake_branch_cannot_establish_lineage(self):
        reader = JulesSourceReader()
        global_snapshot = collect_global_jules_snapshot(reader)
        for branch in ("jules-work/fake", "human/relay-dev-loop-900-mock-source", None):
            with self.assertRaises(ValueError):
                read_result_source(reader, global_snapshot, branch)


def self_branch():
    return "jules-work/relay-dev-loop-900-mock-source"


if __name__ == "__main__":
    unittest.main()
