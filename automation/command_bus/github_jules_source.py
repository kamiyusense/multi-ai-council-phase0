"""Discover the current formal Jules carrier and read its complete global ledger.

This uses GitHub GET only. It never reads credentials for Jules, calls Jules,
reserves a claim or creates a work branch. A direct session reader is NOT_WIRED.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.parse import urlencode

from .blue_work_reconcile_prepare import _pairs, _sha
from .github_readonly import ROOT, Reader, content_at, read_all, recursive_tree
from .loop_id_claim import claim_filename, extract_numbered_loop
from .next_jules_prepare import used_loop_numbers


@dataclass(frozen=True)
class GlobalJulesSnapshot:
    carrier_branch: str
    carrier_head: str
    tree_entries: list[dict]
    branch_refs: list[dict]


def discover_jules_carrier(reader: Reader) -> tuple[str, str]:
    main = reader.get(ROOT + "/git/ref/heads/main").data
    if not isinstance(main, dict) or not _sha(main.get("object", {}).get("sha")):
        raise ValueError("current main workflow ref unavailable")
    workflow = content_at(reader, ".github/workflows/jules-chat-semiauto.yml", main["object"]["sha"])
    # The current accepted workflow has exactly this narrow push route. A new
    # syntax/filter is UNKNOWN until reviewed, never inferred from old memory.
    routes = re.findall(r"(?m)^on:\n  push:\n    branches:\n      - ([A-Za-z0-9._/-]+)\n    paths:\n      - automation/command_bus/jules_api_requests/\*\.json\s*$", workflow)
    if len(routes) != 1 or routes[0] in {"main", "master"} or ".." in routes[0]:
        raise ValueError("current Jules workflow route unrecognized")
    branch = routes[0]
    ref = reader.get(ROOT + "/git/ref/heads/" + branch).data
    head = ref.get("object", {}).get("sha") if isinstance(ref, dict) else None
    if not _sha(head):
        raise ValueError("Jules carrier HEAD unavailable")
    return branch, head


def collect_global_jules_snapshot(reader: Reader) -> GlobalJulesSnapshot:
    branch, head = discover_jules_carrier(reader)
    tree = recursive_tree(reader, head)
    branches_url = ROOT + "/branches?per_page=100"
    branches = read_all(reader, branches_url, identity_key="name")
    refs = []
    for row in branches:
        if not isinstance(row.get("name"), str) or not _sha(row.get("commit", {}).get("sha")):
            raise ValueError("global branch identity unavailable")
        refs.append({"ref": "refs/heads/" + row["name"], "sha": row["commit"]["sha"]})
    used_loop_numbers(tree_entries=tree["tree"], branch_refs=refs, complete=True)
    if branches != read_all(reader, branches_url, identity_key="name") or (branch, head) != discover_jules_carrier(reader):
        raise ValueError("global ledger/branches advanced during readback")
    return GlobalJulesSnapshot(branch, head, tree["tree"], refs)


def read_result_source(reader: Reader, snapshot: GlobalJulesSnapshot, work_branch: str) -> dict:
    if not isinstance(work_branch, str) or not work_branch.startswith("jules-work/"):
        raise ValueError("result is not on a Jules work branch")
    command_id = work_branch.removeprefix("jules-work/")
    parsed = extract_numbered_loop(command_id)
    if parsed is None:
        raise ValueError("numbered formal Jules source required")
    path = f"automation/command_bus/jules_api_requests/{command_id}.json"
    claim_path = "automation/command_bus/loop_id_claims/" + claim_filename(parsed[0])
    command = json.loads(content_at(reader, path, snapshot.carrier_head), object_pairs_hook=_pairs)
    claim = json.loads(content_at(reader, claim_path, snapshot.carrier_head), object_pairs_hook=_pairs)
    history = read_all(reader, ROOT + "/commits?" + urlencode({"sha": snapshot.carrier_head, "path": path, "per_page": 100}), identity_key="sha")
    if len(history) != 1:
        raise ValueError("command is missing or was edited after publication")
    commit = reader.get(ROOT + "/commits/" + history[0]["sha"]).data
    runs = read_all(reader, ROOT + "/actions/runs?" + urlencode({"head_sha": history[0]["sha"], "per_page": 100}), array_key="workflow_runs")
    runs = [r for r in runs if r.get("path") == ".github/workflows/jules-chat-semiauto.yml" and r.get("event") == "push"]
    if len(runs) != 1 or runs[0].get("run_attempt") != 1:
        raise ValueError("one dispatch run attempt required; no replay")
    return {"request": command, "claim": claim, "command_commit": commit, "dispatch_run": runs[0],
            "jules_direct_session_readback": "NOT_WIRED"}
