"""Fresh complete GitHub readback for one lane, without command submission."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .blue_jules_result_event import EXPECTED_REPOSITORY
from .blue_work_reconcile_prepare import _pairs, _positive, _sha, _carrier
from .blue_work_wake_prepare import CarrierSnapshot
from .cloud_work_lanes import lane_identity
from .github_readonly import ROOT, Reader, content_at, read_all


def _field(text: str, field: str, expected: str) -> None:
    pattern = rf"^- {re.escape(field)}: ?`?{re.escape(expected)}`?\s*$"
    if len(re.findall(pattern, text, re.MULTILINE)) != 1:
        raise ValueError("carrier identity field mismatch: " + field)


def discover_carrier(prs: list[dict], lane: str) -> dict:
    label = lane_identity(lane)["label"]
    if not isinstance(prs, list) or any(not isinstance(p, dict) for p in prs):
        raise ValueError("open PR collection unavailable")
    candidates = []
    for pr in prs:
        labels = pr.get("labels")
        if not isinstance(labels, list) or any(not isinstance(x, dict) or not isinstance(x.get("name"), str) for x in labels):
            raise ValueError("PR labels unavailable")
        if label in {x["name"] for x in labels}:
            if pr.get("state") != "open" or pr.get("merged_at") is not None:
                raise ValueError("carrier open/unmerged identity mismatch")
            candidates.append(pr)
    if len(candidates) != 1:
        raise ValueError("exactly one current carrier required")
    return candidates[0]


@dataclass(frozen=True)
class LaneSnapshot:
    lane: str
    carrier_pr: dict
    worker_state: dict
    protocol: CarrierSnapshot
    reviews: list[dict]
    comments: list[dict]
    result_pr: dict


def collect_lane_snapshot(reader: Reader, *, lane: str, result_number: int) -> LaneSnapshot:
    identity = lane_identity(lane)
    if not _positive(result_number):
        raise ValueError("result PR number invalid")
    open_url = ROOT + "/pulls?state=open&per_page=100"
    found = discover_carrier(read_all(reader, open_url), lane)
    number = found.get("number")
    if not _positive(number) or result_number == number:
        raise ValueError("carrier/target must be separate")
    carrier_url = ROOT + f"/pulls/{number}"
    pr = reader.get(carrier_url).data
    if not isinstance(pr, dict) or not _sha(pr.get("head", {}).get("sha")):
        raise ValueError("carrier detail unavailable")
    head = pr["head"]["sha"]
    branch = pr["head"].get("ref")
    protocol_path = f"automation/cloud_work_lanes/carriers/{lane}_v1.md"
    state_path = f"automation/cloud_work_lanes/carriers/{lane}_worker_state_v1.json"
    text = content_at(reader, protocol_path, head)
    state = json.loads(content_at(reader, state_path, head), object_pairs_hook=_pairs)
    body = pr.get("body")
    if not isinstance(body, str) or not isinstance(branch, str):
        raise ValueError("carrier body/branch unavailable")
    for field, expected in (("lane", lane), ("carrier PR", f"#{number}"), ("carrier branch", branch),
                            ("required label", identity["label"]),
                            ("command review prefix", identity["command_prefix"]),
                            ("receipt comment prefix", identity["receipt_prefix"]),
                            ("protocol file", protocol_path), ("protocol version", "1")):
        _field(body, field, expected)
    for field, expected in (("repository", EXPECTED_REPOSITORY), ("carrier branch", branch),
                            ("carrier PR", f"#{number}"), ("required PR label", identity["label"]),
                            ("command review prefix", identity["command_prefix"]),
                            ("receipt comment prefix", identity["receipt_prefix"]),
                            ("protocol version", "1"), ("worker state", state_path)):
        _field(text, field, expected)
    protocol = CarrierSnapshot(1, lane, identity["command_prefix"], state.get("active_generation"))
    _carrier(pr, state, protocol, lane)
    review_url, comment_url = ROOT + f"/pulls/{number}/reviews?per_page=100", ROOT + f"/issues/{number}/comments?per_page=100"
    reviews, comments = read_all(reader, review_url), read_all(reader, comment_url)
    target_url = ROOT + f"/pulls/{result_number}"
    result = reader.get(target_url).data
    # A changed readback is uncertainty, never a retry. Collect no partial plan.
    if reviews != read_all(reader, review_url) or comments != read_all(reader, comment_url):
        raise ValueError("carrier records changed during collection")
    if pr != reader.get(carrier_url).data or result != reader.get(target_url).data:
        raise ValueError("carrier/result changed during collection")
    current = discover_carrier(read_all(reader, open_url), lane)
    if current.get("number") != number or current.get("head", {}).get("sha") != head:
        raise ValueError("carrier discovery changed during collection")
    return LaneSnapshot(lane, pr, state, protocol, reviews, comments, result)
