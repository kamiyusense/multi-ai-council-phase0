"""Reuse the original BWJ snapshot and production reviewer helpers in mocks."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from automation.command_bus.loop_id_claim import DUPLICATE_GUARD
from automation.command_bus.cloud_work_lanes import lane_identity
from automation.command_bus.reviewer import ReviewerLedger, claim_request, submit_response
from automation.command_bus.work_closed_loop_prepare import prepare_static_cycle

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures/blue_work_reconcile/input.json"
REPO = "kamiyusense/multi-ai-council-phase0"
HEAD, BASE, TREE = "a" * 40, "c" * 40, "d" * 40

PROMPT = """Loop candidate — bounded MEDIUM STATIC receipt regression.
Goal:
Prove a receipt for another PR cannot terminate a command. No architecture expansion.
Read first:
- automation/command_bus/blue_work_reconcile_prepare.py
- automation/command_bus/tests/test_blue_receipt_binding.py
Allowed changed paths only:
- automation/command_bus/tests/test_blue_receipt_binding.py
Hard scope / Do Not Touch:
- retry=0; fallback=disabled; no Merge; no live provider, model, Work or Jules calls.
- no default-branch write, force push, deletion, settings, credentials or billing changes.
Reuse-first:
Reuse the original BWJ fixture and existing receipt parser; do not duplicate policy.
Required semantics:
Assert UNKNOWN when the same command ID has a receipt for another PR.
Negative/tamper cases:
Wrong PR, HEAD and worker generation; malformed receipt; duplicate command.
Acceptance criteria:
Direct observable assertions; no vacuous tests; only the allowed test file changes.
Validation:
python -m unittest automation.command_bus.tests.test_blue_receipt_binding -v
python -m unittest discover -s automation/command_bus/tests -t . -v
python -m compileall -q automation/command_bus
git diff --check
Publication:
Normal isolated Jules PR only after all required checks succeed; no Merge.
Stop and report instead of guessing if:
Target snapshot moved, paths need expansion, evidence is UNKNOWN or any approval boundary is reached.
"""


def snapshot(lane="blue", *, decision="PASS", with_review=True):
    wake = json.loads(FIXTURE.read_text())
    metadata = lane_identity(lane)
    del wake["lineage"]
    command_id = "relay-dev-loop-900-mock-source"
    branch = "jules-work/" + command_id
    result = wake["result_pr"]
    result["base"]["ref"] = wake["event"]["pull_request"]["base"]["ref"] = branch
    carrier_number = {"blue": 167, "yellow": 165, "green": 166, "red": 171}[lane]
    carrier_branch = f"cloud-work/carrier-{lane}-v1"
    wake["carrier_pr"]["number"] = carrier_number
    wake["carrier_pr"]["head"]["ref"] = carrier_branch
    wake["carrier_pr"]["labels"] = [{"name": metadata["label"]}]
    wake["worker_state"].update(lane=lane, carrier_pr=carrier_number, carrier_branch=carrier_branch)
    wake["protocol"].update(lane=lane, command_prefix=metadata["command_prefix"])
    request = {"schema_version": 2, "profile": "JULES_CHAT_SEMIAUTO_V2", "command_id": command_id,
               "target_repo": REPO, "target_branch": "experiment/blue-work-autonomous-development",
               "work_branch": branch, "expected_target_head": BASE, "expected_target_tree": "e" * 40,
               "allowed_paths": ["automation/command_bus/tests/test_blue_receipt_binding.py"], "prompt": PROMPT,
               "created_at": "2026-10-01T10:00:00Z", "expires_at": "2026-10-01T11:00:00Z", "retry": 0,
               "fallback": "disabled", "merge_allowed": False, "force_push_allowed": False}
    claim = {"schema_version": 3, "loop_number": 900, "loop_id": "900", "task_id": "mock-source",
             "command_id": command_id, "target_branch": request["target_branch"], "expected_target_head": BASE,
             "expected_target_tree": "e" * 40, "work_branch": branch, "state": "CLAIMED",
             "claimed_at": "2026-10-01T09:59:00Z", "duplicate_guard": DUPLICATE_GUARD,
             "retry": 0, "fallback": "disabled", "lane_id": metadata["jules_lane"],
             "lane_display": {"blue": "💙", "yellow": "💛", "green": "💚", "red": "❤️"}[lane]}
    acceptance = {"name": "sessions/12345", "createTime": "2026-10-01T10:01:00Z",
                  "sourceContext": {"source": "sources/github/" + REPO, "githubRepoContext": {"startingBranch": branch}}}
    session = deepcopy(acceptance)
    session.update(state="COMPLETED", outputs=[{"pullRequest": {"url": f"https://github.com/{REPO}/pull/42"}}])
    source = {"request": request, "claim": claim,
              "command_commit": {"sha": "f" * 40, "files": [{"filename": f"automation/command_bus/jules_api_requests/{command_id}.json", "status": "added"}]},
              "dispatch_run": {"id": 50, "head_sha": "f" * 40, "path": ".github/workflows/jules-chat-semiauto.yml",
                               "event": "push", "run_attempt": 1, "status": "completed", "conclusion": "success", "repository": {"full_name": REPO}},
              "dispatch_job": {"id": 51, "run_id": 50, "head_sha": "f" * 40, "status": "completed", "conclusion": "success"},
              "dispatch_log": "2026-10-01T10:01:00.000Z Jules session accepted: sessions/12345\n2026-10-01T10:01:01.000Z Jules session timing read back: sessions/12345 at 2026-10-01T19:01:00+09:00\n",
              "acceptance": acceptance, "session_readback": session, "result_pr": deepcopy(result),
              "result_commit": {"sha": HEAD, "tree": {"sha": TREE}},
              "comparison": {"status": "ahead", "base_commit": {"sha": BASE, "commit": {"tree": {"sha": request["expected_target_tree"]}}}, "merge_base_commit": {"sha": BASE}, "total_commits": 1, "commits": [{"sha": HEAD}]}}
    proposal = {"task_id": "mock-next", "prompt": PROMPT, "allowed_paths": request["allowed_paths"], "expires_at": wake["expires_at"]}
    review = {"current_result": {"head": HEAD, "tree": TREE}, "evidence_refs": ["fixture://diff", "fixture://tests"],
              "changed_files": [{"filename": request["allowed_paths"][0], "status": "modified", "symlink": False}],
              "files_complete": True, "checks": [{"kind": kind, "head_sha": HEAD, "tree_sha": TREE,
                  "status": "completed", "conclusion": "success", "evidence_ref": "fixture://" + kind} for kind in ("unit", "negative", "compile", "diff")],
              "implementer_id": "mock-jules-implementer", "records": None}
    inputs = {"source_mode": "MOCK", "lane": lane, "source": source, "wake": wake, "review": review,
              "next_snapshot": {"target": {"repository": REPO, "branch": request["target_branch"], "head": BASE,
                    "tree": "e" * 40, "expected_head": BASE, "expected_tree": "e" * 40},
                    "tree_entries": [{"path": "automation/command_bus/loop_id_claims/900.json", "type": "blob"}],
                    "branch_refs": [{"ref": "refs/heads/" + branch}], "ledger_complete": True}}
    if with_review:
        req = prepare_static_cycle(inputs, now=NOW)["review_request"]
        ledger = ReviewerLedger()
        ledger.append_request(req)
        claimed = claim_request(ledger, req["request_id"], claim_id="mock-review-owner", reviewer_instance_id="mock-independent-work",
                                reviewer_generation=1, role="reviewer", claimed_at=NOW)
        if claimed.status != "CLAIMED":
            raise AssertionError(claimed)
        response = submit_response(ledger, req["request_id"], response_id="mock-review-response", reviewer_instance_id="mock-independent-work",
                         reviewer_generation=1, decision=decision, evidence_refs=review["evidence_refs"], loop_id=req["loop_id"],
                         round=req["round"], correlation_id=req["correlation_id"], expected_target_head=HEAD, expected_target_tree=TREE,
                         rationale_summary="MOCK semantic review only: receipt binding and negative cases inspected.",
                         next_command_proposal=proposal, model_route_evidence={"route": "MOCK", "live_model_used": False}, submitted_at=NOW)
        if response.status != "ACCEPTED":
            raise AssertionError(response)
        review["records"] = ledger.export_records()
    return inputs
