"""One finite BWJ STATIC turn, using BWJ-1/2 and existing review contracts.

Outputs are artifacts, never send authority. No loop runner, queue, scheduler,
network, provider, adoption, reservation, review posting or command writing.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from .blue_work_wake_prepare import CarrierSnapshot
from .blue_work_reconcile_prepare import prepare_reconciled_wake, prepare_result_review_request
from .jules_result_lineage import verify_result_lineage
from .next_jules_prepare import prepare_next_jules
from .work_result_review import assess_result_review


def prepare_static_cycle(snapshot: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {"execution_mode": "PREPARE_ONLY", "source_authentication": "NOT_WIRED",
                              "external_send_attempted": False, "model_executed": False,
                              "adoption_performed": False, "claim_reserved": False}
    try:
        if not isinstance(snapshot, dict) or snapshot.get("source_mode") not in {"MOCK", "CAPTURED"}:
            raise ValueError("explicit MOCK/CAPTURED source mode required")
        result["source_mode"] = snapshot["source_mode"]
        if snapshot["source_mode"] == "CAPTURED":
            result.update(status="BLOCKED", reason="captured JSON is not authenticated provider evidence; source verifier NOT_WIRED")
            return result
        lane = snapshot["lane"]
        lineage = verify_result_lineage(lane=lane, **snapshot["source"], now=now)
        result["lineage"] = asdict(lineage)
        if lineage.status != "VERIFIED_SNAPSHOT":
            result.update(status="UNKNOWN", reason="source lineage unavailable")
            return result
        inputs = dict(snapshot["wake"])
        if inputs.get("result_pr") != snapshot["source"]["result_pr"]:
            raise ValueError("wake and lineage result readbacks disagree")
        inputs["lineage"] = lineage.lineage
        inputs["protocol"] = CarrierSnapshot(**inputs["protocol"])
        plan = prepare_reconciled_wake(**inputs, lane=lane, now=now)
        result["wake"] = asdict(plan)
        result["status"] = plan.status
        if plan.status != "PREPARED":
            return result
        review_input = snapshot["review"]
        review_request = prepare_result_review_request(plan, target_tree=review_input["current_result"]["tree"],
                                                       evidence_refs=review_input["evidence_refs"],
                                                       expires_at=inputs["expires_at"], now=now)
        result["review_request"] = review_request
        if review_input.get("records") is None:
            result["review"] = {"status": "NOT_EXECUTED", "reason": "independent review required"}
            return result
        review = assess_result_review(lineage=lineage, request=review_request, reviewer_records=review_input["records"],
                                      current_result=review_input["current_result"], changed_files=review_input["changed_files"],
                                      files_complete=review_input["files_complete"], allowed_paths=snapshot["source"]["request"]["allowed_paths"],
                                      checks=review_input["checks"], implementer_id=review_input["implementer_id"], now=now)
        result["review"] = asdict(review)
        if review.status != "VALIDATED" or review.decision != "PASS":
            result["status"] = review.status if review.status != "VALIDATED" else "BLOCKED"
            return result
        proposal = review.response["next_command_proposal"]
        if proposal is None:
            result["status"] = "COMPLETE"
            result["reason"] = "no next useful bounded task proposed"
            return result
        # The next task comes from the captured review, not a second caller task.
        next_plan = prepare_next_jules(lane=lane, **proposal, **snapshot["next_snapshot"],
                                       review_decision=review.decision, now=now)
        result["next_task"] = asdict(next_plan)
        result["status"] = next_plan.status
        return result
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        result.update(status="UNKNOWN", reason=str(exc))
        return result
