"""BWJ-5 captured independent-review gates over the existing reviewer ledger.

Semantic judgment is supplied by an independent reviewer, never inferred from
green tests. This adapter only checks bindings and prerequisites; no model is
called and no result is adopted. MOCK records do not prove independent review.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .blue_work_reconcile_prepare import _positive, _sha, _time
from .jules_result_lineage import LineageDecision
from .jules_api_request import _validate_path
from .reviewer import ReviewerLedger, consume_response, validate_review_request


@dataclass(frozen=True)
class ResultReviewGate:
    status: str
    reason: str
    decision: str | None = None
    response: dict | None = None
    recovered_records: dict | None = None
    adopted: bool = False


def assess_result_review(*, lineage: LineageDecision, request: dict, reviewer_records: dict,
                         current_result: dict, changed_files: Any, files_complete: Any,
                         allowed_paths: list[str], checks: Any, implementer_id: str,
                         now: datetime) -> ResultReviewGate:
    try:
        if not isinstance(lineage, LineageDecision) or lineage.status != "VERIFIED_SNAPSHOT":
            raise ValueError("verified captured source lineage required")
        validate_review_request(request)
        if (not _positive(lineage.result_pr) or not _sha(lineage.result_head) or not _sha(lineage.result_tree)
                or not isinstance(lineage.allowed_paths, tuple) or not lineage.allowed_paths):
            raise ValueError("verified lineage result identity/scope unavailable")
        result_id = f"{lineage.lane}-jules-result-pr{lineage.result_pr}-{lineage.result_head}"
        if (request["request_id"] != result_id or request["loop_id"] != result_id
                or request["correlation_id"] != result_id or request["round"] != 1
                or request["expected_target_head"] != lineage.result_head
                or request["expected_target_tree"] != lineage.result_tree):
            raise ValueError("review request differs from verified source result")
        if tuple(allowed_paths) != lineage.allowed_paths:
            raise ValueError("review allowlist differs from verified source command")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware current time required")
        if _time(request["expires_at"]) <= now:
            raise ValueError("review request expired")
        if not isinstance(current_result, dict) or not _sha(current_result.get("head")) or not _sha(current_result.get("tree")):
            raise ValueError("fresh result HEAD/tree unavailable")
        if current_result["head"] != request["expected_target_head"] or current_result["tree"] != request["expected_target_tree"]:
            return ResultReviewGate("STALE", "reviewed result HEAD/tree moved")
        if files_complete is not True or not isinstance(changed_files, list) or not changed_files:
            raise ValueError("complete nonempty changed files required")
        if not isinstance(allowed_paths, list) or not allowed_paths:
            raise ValueError("source allowed paths required")
        for path in allowed_paths:
            _validate_path(path)
        seen_paths = set()
        for row in changed_files:
            if not isinstance(row, dict) or row.get("filename") not in allowed_paths or row.get("filename") in seen_paths:
                return ResultReviewGate("BLOCKED", "unexpected/duplicate changed path")
            seen_paths.add(row["filename"])
            if row.get("status") not in {"added", "modified"} or row.get("symlink") is not False:
                return ResultReviewGate("BLOCKED", "delete/rename/symlink or unverified file mode")
        if not isinstance(checks, list) or not checks:
            raise ValueError("exact-head check evidence required")
        covered = set()
        for check in checks:
            if (not isinstance(check, dict) or check.get("head_sha") != current_result["head"]
                    or check.get("tree_sha") != current_result["tree"] or not isinstance(check.get("evidence_ref"), str)
                    or not check["evidence_ref"] or check.get("status") != "completed"):
                raise ValueError("test check binding/evidence unavailable")
            if check.get("conclusion") != "success":
                return ResultReviewGate("BLOCKED", "exact-head test check did not succeed")
            covered.add(check.get("kind"))
        if not {"unit", "negative", "compile", "diff"} <= covered:
            raise ValueError("required unit/negative/compile/diff evidence missing")
        if not isinstance(implementer_id, str) or not implementer_id:
            raise ValueError("implementer identity unavailable")
        if not isinstance(reviewer_records, dict) or set(reviewer_records) != {"requests", "claims", "responses", "receipts"}:
            raise ValueError("complete reviewer ledger required")
        ledger = ReviewerLedger.from_records(deepcopy(reviewer_records))
        reqs = [r for r in ledger.requests if r["request_id"] == request["request_id"]]
        responses = [r for r in ledger.responses if r["request_id"] == request["request_id"]]
        if reqs != [request] or len(responses) != 1:
            raise ValueError("exact one request/response readback required")
        response = responses[0]
        circular = {'review-request:' + request['request_id'], 'review-response:' + response['response_id']}
        circular.update('review-receipt:' + r['receipt_id'] for r in ledger.receipts
                        if r.get('request_id') == request['request_id'] and isinstance(r.get('receipt_id'), str))
        references = request['evidence_refs'] + response['evidence_refs'] + [c['evidence_ref'] for c in checks]
        if any(reference in circular for reference in references):
            return ResultReviewGate('BLOCKED', 'review cannot use its own request/response/consumption as proof of success')
        if response["reviewer_instance_id"] == implementer_id:
            return ResultReviewGate("BLOCKED", "implementer cannot be independent reviewer")
        if response["reviewer_role"] != request["reviewer_role"] or response["review_kind"] != "JULES_RESULT":
            raise ValueError("review role/kind mismatch")
        claims = [c for c in ledger.claims if c["request_id"] == request["request_id"]]
        owners = [c for c in claims if c["reviewer_instance_id"] == response["reviewer_instance_id"]
                  and c["reviewer_generation"] == response["reviewer_generation"]]
        submitted = _time(response["submitted_at"])
        if submitted > now or len(owners) != 1 or not _positive(response["reviewer_generation"]):
            raise ValueError("review response owner/time ambiguous")
        owner = owners[0]
        if not (_time(owner["claimed_at"]) <= submitted < _time(owner["expires_at"]) <= _time(request["expires_at"])):
            raise ValueError("response outside owning claim lifetime")
        if any(c is not owner and _time(c["claimed_at"]) <= submitted < _time(c["expires_at"]) for c in claims):
            raise ValueError("overlapping independent reviewer claims")
        if any(c["reviewer_generation"] > response["reviewer_generation"] and _time(c["claimed_at"]) <= now for c in claims):
            raise ValueError("reviewer generation superseded before consumption")
        terminal = [r for r in ledger.receipts if r.get("request_id") == request["request_id"]]
        if len(terminal) > 1:
            raise ValueError("duplicate reviewer consumption receipts")
        for receipt in ledger.receipts:
            if receipt.get("request_id") == request["request_id"] and any(receipt.get(k) != response.get(k) for k in
                    ("response_id", "loop_id", "round", "correlation_id", "expected_target_head", "expected_target_tree")):
                raise ValueError("review consumption receipt binding mismatch")
        result = consume_response(ledger, request["request_id"], loop_id=request["loop_id"], round=request["round"],
                                  correlation_id=request["correlation_id"], expected_target_head=current_result["head"],
                                  expected_target_tree=current_result["tree"], now=now)
        if result.status == "NO-OP":
            return ResultReviewGate("NO_OP", "captured review already consumed", recovered_records=ledger.export_records())
        if result.status != "VALID":
            raise ValueError("existing reviewer rejected binding: " + result.reason)
        return ResultReviewGate("VALIDATED", "captured independent-review contract; no semantic review executed or adoption performed",
                               result.record["decision"], result.record, ledger.export_records())
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return ResultReviewGate("UNKNOWN", str(exc))
