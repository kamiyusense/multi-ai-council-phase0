import base64
import copy
import hashlib
import json
import unittest

from automation.command_bus.cloud_work_snapshot import collect_lane_snapshot, discover_carrier
from automation.command_bus.cloud_work_lanes import LANES, lane_identity
from automation.command_bus.github_readonly import ROOT, ReadResponse
from .closed_loop_fixtures import snapshot


class SnapshotReader:
    def __init__(self, lane="blue"):
        x = snapshot(lane, with_review=False)["wake"]
        self.carrier, self.result = x["carrier_pr"], x["result_pr"]
        self.carrier["id"] = self.carrier["number"]
        self.carrier["merged_at"] = None
        metadata = lane_identity(lane)
        number, branch = self.carrier["number"], self.carrier["head"]["ref"]
        path = f"automation/cloud_work_lanes/carriers/{lane}_v1.md"
        state_path = f"automation/cloud_work_lanes/carriers/{lane}_worker_state_v1.json"
        values = {"lane": lane, "carrier PR": f"#{number}", "carrier branch": branch,
                  "required label": metadata["label"], "command review prefix": metadata["command_prefix"],
                  "receipt comment prefix": metadata["receipt_prefix"], "protocol file": path, "protocol version": "1"}
        self.carrier["body"] = "\n".join(f"- {k}: `{v}`" for k, v in values.items())
        values["repository"] = "kamiyusense/multi-ai-council-phase0"
        values["required PR label"] = values.pop("required label")
        values["worker state"] = state_path
        protocol = "\n".join(f"- {k}: `{v}`" for k, v in values.items())
        self.pages = {ROOT + "/pulls?state=open&per_page=100": ReadResponse([self.carrier], {}),
                      ROOT + f"/pulls/{number}": ReadResponse(self.carrier, {}),
                      ROOT + "/pulls/42": ReadResponse(self.result, {}),
                      ROOT + f"/pulls/{number}/reviews?per_page=100": ReadResponse([], {}),
                      ROOT + f"/issues/{number}/comments?per_page=100": ReadResponse([], {})}
        self.put_content(path, protocol)
        self.put_content(state_path, json.dumps(x["worker_state"]))
        self.calls = []
        self.mutate = None

    def put_content(self, path, content):
        raw = content.encode()
        blob = {"type": "file", "encoding": "base64", "content": base64.b64encode(raw).decode(),
                "sha": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
        self.pages[ROOT + "/contents/" + path + "?ref=" + self.carrier["head"]["sha"]] = ReadResponse(blob, {})

    def get(self, url):
        self.calls.append(url)
        if self.mutate:
            self.mutate(self, url)
        return copy.deepcopy(self.pages[url])


class CarrierSnapshotTests(unittest.TestCase):
    def test_all_four_complete_snapshots(self):
        for lane in LANES:
            reader = SnapshotReader(lane)
            result = collect_lane_snapshot(reader, lane=lane, result_number=42)
            self.assertEqual(result.lane, lane)
            self.assertEqual(result.worker_state["active_generation"], 1)
            self.assertEqual(result.protocol.command_prefix, lane_identity(lane)["command_prefix"])
            self.assertEqual(result.result_pr["number"], 42)

    def test_duplicate_carrier_on_second_page_is_not_hidden(self):
        reader = SnapshotReader()
        url = ROOT + "/pulls?state=open&per_page=100"
        second = url + "&page=2"
        duplicate = copy.deepcopy(reader.carrier)
        duplicate.update(number=999, id=999)
        reader.pages[url] = ReadResponse([reader.carrier], {"link": f'<{second}>; rel="next"'})
        reader.pages[second] = ReadResponse([duplicate], {})
        with self.assertRaises(ValueError):
            collect_lane_snapshot(reader, lane="blue", result_number=42)

    def test_zero_conflicting_or_unreadable_carriers_unknown(self):
        reader = SnapshotReader()
        for prs in ([], [dict(reader.carrier, labels=[])], [dict(reader.carrier, labels=None)],
                    [dict(reader.carrier, merged_at="2026-10-01")]):
            with self.assertRaises(ValueError):
                discover_carrier(prs, "blue")

    def test_body_and_protocol_identity_mismatch_unknown(self):
        for kind in ("body", "protocol"):
            reader = SnapshotReader()
            if kind == "body":
                reader.carrier["body"] = reader.carrier["body"].replace("[CW_BLUE_V1]", "[CW_RED_V1]")
            else:
                path = "automation/cloud_work_lanes/carriers/blue_v1.md"
                reader.put_content(path, "- protocol version: `1`\n")
            with self.assertRaises(ValueError):
                collect_lane_snapshot(reader, lane="blue", result_number=42)

    def test_state_generation_and_branch_mismatch_unknown(self):
        for changes in ({"active_generation": True}, {"lane": "red"}, {"carrier_branch": "other"}, {"carrier_pr": 166}):
            reader = SnapshotReader()
            state = snapshot(with_review=False)["wake"]["worker_state"]
            state.update(changes)
            reader.put_content("automation/cloud_work_lanes/carriers/blue_worker_state_v1.json", json.dumps(state))
            with self.assertRaises(ValueError):
                collect_lane_snapshot(reader, lane="blue", result_number=42)

    def test_result_changed_during_readback_fails_without_retry(self):
        reader = SnapshotReader()
        url = ROOT + "/pulls/42"
        def mutate(r, u):
            if u == url and r.calls.count(u) == 2:
                r.result["head"]["sha"] = "b" * 40
        reader.mutate = mutate
        with self.assertRaises(ValueError):
            collect_lane_snapshot(reader, lane="blue", result_number=42)
        self.assertEqual(reader.calls.count(url), 2)

    def test_records_changed_during_collection_unknown(self):
        reader = SnapshotReader()
        url = ROOT + "/pulls/167/reviews?per_page=100"
        def mutate(r, u):
            if u == url and r.calls.count(u) == 2:
                r.pages[url].data.append({"id": 99, "body": "new unrelated review"})
        reader.mutate = mutate
        with self.assertRaises(ValueError):
            collect_lane_snapshot(reader, lane="blue", result_number=42)

    def test_carrier_and_target_are_separate(self):
        reader = SnapshotReader()
        with self.assertRaises(ValueError):
            collect_lane_snapshot(reader, lane="blue", result_number=167)


if __name__ == "__main__":
    unittest.main()
