"""DURABLE_ADOPTION_APPROVAL_V1: a human decision, kept apart from the authority proof.

Two different things must never stand in for each other:

* an authority / identity proof (an owner-dispatched OIDC issuer run) says WHO started a run;
* a DURABLE adoption approval says a human read the proof 5 result, saw its recorded output
  deviation, and decided to use the authentication evidence to move ONE lane from PLACEHOLDER to
  DURABLE.

This module is pure: it reads nothing, writes nothing and calls no provider. The approval is bound to
the exact lane, proof, terminal receipt, evidence digest, current registry digest and proposed registry
digest. It does not change the Jules output checker: the output stays DEVIATION and the approval only
acknowledges one narrow, named deviation.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from . import signal_step7_live_proof as live
from .control_tower import validate_registry
from .lane_identity_adoption import registry_digest

APPROVAL_KIND = "DURABLE_ADOPTION_APPROVAL_V1"
DECISION = "ADOPT_DURABLE"
TRANSITION = "PLACEHOLDER->DURABLE"
LANE_ID = live.LANE_ID
PROOF_TASK_ID = live.PROOF_TASK_ID
LOOP_NUMBER = 136
LOOP_COMMAND_ID = f"relay-dev-loop-{LOOP_NUMBER}-{PROOF_TASK_ID}"
OUTPUT_EXACT = "EXACT"
OUTPUT_DEVIATION = "DEVIATION"
# Only this one named deviation can be acknowledged. Anything else is refused, never widened.
DEVIATION_MISSING_NEWLINE = "MISSING_TRAILING_NEWLINE_ONLY"
ACCEPTED_DEVIATIONS = frozenset({DEVIATION_MISSING_NEWLINE})
DEVIATION_OTHER = "OTHER"
CONTENT_REASON = "proof content is not the exact allowed content"
APPROVAL_VALIDITY = timedelta(hours=24)

# Runs of the owner-authority issuer and of the provider OIDC proof. They prove identity only and can
# never be an adoption approval (the approval comes from its own workflow run).
KNOWN_AUTHORITY_RUN_IDS = frozenset({
    "36981004299", "37031275812", "37083931810", "37084792474", "37096169353", "37098007717", "37150285702",
}) | frozenset(live.RESERVED_AUTHORITY_RUNS)

_KEYS = frozenset({
    "schema_version", "approval_kind", "approval_id", "lane_id", "proof_task_id", "loop_number",
    "transition", "terminal_receipt_sha256", "evidence_payload_sha256", "current_registry_sha256",
    "proposed_registry_sha256", "output_assessment", "accepted_deviation", "approved_by_actor_id",
    "approved_at", "valid_until", "approval_ref", "approval_run_attempt", "decision", "retry", "fallback",
})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ACTOR = re.compile(r"[0-9]{1,20}")
_REF = re.compile(r"github-actions:run/([0-9]{1,20})")
_ID = re.compile(r"adopt-durable-[a-z0-9-]{1,60}-([0-9]{1,20})")
_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


class ApprovalError(ValueError):
    """Fail-closed refusal with a stable machine code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _time(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not _TS.fullmatch(value):
        raise ApprovalError(code)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def zulu(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify_output(output: Any, evidence: dict[str, Any]) -> tuple[str, str | None]:
    """Recompute the output assessment from the GitHub readback (never from a stored verdict)."""
    reasons = live.assess_output_readback(output, evidence=evidence)
    if not reasons:
        return OUTPUT_EXACT, None
    if reasons == (CONTENT_REASON,) and isinstance(output, dict) \
            and output.get("changed_file_content") is not None \
            and output["changed_file_content"] + "\n" == evidence.get("allowed_content"):
        return OUTPUT_DEVIATION, DEVIATION_MISSING_NEWLINE
    return OUTPUT_DEVIATION, DEVIATION_OTHER


def check_single_lane_diff(current: dict[str, Any], proposed: dict[str, Any], lane: str) -> None:
    """Only ``identity_state`` of ``lane`` may change, PLACEHOLDER -> DURABLE; every other byte is equal."""
    try:
        before_entries = validate_registry(current)
        after_entries = validate_registry(proposed)
    except Exception as exc:  # the registry validator is the source of truth for shape
        raise ApprovalError("REGISTRY_INVALID", type(exc).__name__) from None
    before = {e.loop_id: e for e in before_entries}
    after = {e.loop_id: e for e in after_entries}
    if set(before) != set(after) or len(after) != len(after_entries) or lane not in before:
        raise ApprovalError("REGISTRY_LANE_SET_CHANGED")
    if before[lane].identity_state != "PLACEHOLDER" or after[lane].identity_state != "DURABLE":
        raise ApprovalError("LANE_NOT_PLACEHOLDER_TO_DURABLE")
    for loop_id, entry in before.items():
        if loop_id == lane:
            if replace(entry, identity_state="DURABLE") != after[loop_id]:
                raise ApprovalError("MORE_THAN_IDENTITY_STATE_CHANGED")
        elif entry != after[loop_id]:
            raise ApprovalError("OTHER_LANE_CHANGED", loop_id)
    if lane.isdecimal():
        raise ApprovalError("NUMERIC_LANE_ID")


def durable_lanes(registry: dict[str, Any]) -> tuple[str, ...]:
    return tuple(e.loop_id for e in validate_registry(registry) if e.identity_state == "DURABLE")


def validate_durable_adoption_approval(
    approval: Any, *, receipt: dict[str, Any], evidence: dict[str, Any], readback_output: Any,
    current_registry: dict[str, Any], proposed_registry: dict[str, Any], proof_completed_at: str,
    allowed_approver_ids: frozenset[str], now: str,
    applied_approval_ids: frozenset[str] = frozenset(),
    approval_run_ids_in_use: frozenset[str] = frozenset(),
) -> str:
    """Return the adopted lane id, or raise ``ApprovalError``. Nothing is written."""
    if not isinstance(approval, dict) or set(approval) != _KEYS:
        raise ApprovalError("APPROVAL_SHAPE")
    if approval["schema_version"] != 1 or approval["approval_kind"] != APPROVAL_KIND:
        raise ApprovalError("APPROVAL_KIND")
    if approval["decision"] != DECISION or approval["transition"] != TRANSITION:
        raise ApprovalError("APPROVAL_DECISION")
    if (approval["retry"], approval["fallback"]) != (0, "disabled"):
        raise ApprovalError("APPROVAL_RETRY_OR_FALLBACK")
    lane = approval["lane_id"]
    if lane != LANE_ID or evidence.get("lane_id") != LANE_ID or receipt.get("lane_id") != LANE_ID:
        raise ApprovalError("WRONG_LANE")
    if approval["proof_task_id"] != PROOF_TASK_ID:
        raise ApprovalError("WRONG_PROOF")
    loop = approval["loop_number"]
    if isinstance(loop, bool) or loop != LOOP_NUMBER:
        raise ApprovalError("WRONG_LOOP")
    # the proof itself: finished, once, never rerunnable
    if receipt.get("status") != "COMPLETE" or receipt.get("code") != "NONE" or receipt.get("rerun_allowed") is not False \
            or receipt.get("additional_jules_get_allowed") is not False \
            or receipt.get("additional_jules_post_allowed") is not False:
        raise ApprovalError("PROOF_NOT_COMPLETE")
    for field in ("terminal_receipt_sha256", "evidence_payload_sha256", "current_registry_sha256",
                  "proposed_registry_sha256"):
        if not isinstance(approval[field], str) or not _SHA256.fullmatch(approval[field]):
            raise ApprovalError("DIGEST_SHAPE", field)
    if approval["terminal_receipt_sha256"] != receipt.get("receipt_payload_sha256"):
        raise ApprovalError("WRONG_TERMINAL_RECEIPT_DIGEST")
    if approval["evidence_payload_sha256"] != evidence.get("evidence_payload_sha256") \
            or receipt.get("evidence_payload_sha256") != evidence.get("evidence_payload_sha256"):
        raise ApprovalError("WRONG_EVIDENCE_DIGEST")
    if approval["current_registry_sha256"] != registry_digest(current_registry):
        raise ApprovalError("STALE_CURRENT_REGISTRY")
    if approval["proposed_registry_sha256"] != registry_digest(proposed_registry):
        raise ApprovalError("WRONG_PROPOSED_REGISTRY")
    check_single_lane_diff(current_registry, proposed_registry, lane)
    # output conformity is a separate fact; the approval may acknowledge exactly one named deviation
    assessment, deviation = classify_output(readback_output, evidence)
    if approval["output_assessment"] != assessment:
        raise ApprovalError("OUTPUT_ASSESSMENT_MISMATCH")
    accepted = approval["accepted_deviation"]
    if assessment == OUTPUT_EXACT:
        if accepted is not None:
            raise ApprovalError("DEVIATION_ACKNOWLEDGED_WITHOUT_DEVIATION")
    else:
        if accepted is None:
            raise ApprovalError("DEVIATION_NOT_ACKNOWLEDGED")
        if accepted not in ACCEPTED_DEVIATIONS or accepted != deviation:
            raise ApprovalError("DEVIATION_TYPE_MISMATCH")
    # who and which run
    actor = approval["approved_by_actor_id"]
    if not isinstance(actor, str) or not _ACTOR.fullmatch(actor) or actor not in allowed_approver_ids:
        raise ApprovalError("WRONG_ACTOR")
    ref = approval["approval_ref"]
    match = _REF.fullmatch(ref) if isinstance(ref, str) else None
    if match is None:
        raise ApprovalError("APPROVAL_REF_SHAPE")
    run_id = match.group(1)
    if run_id in KNOWN_AUTHORITY_RUN_IDS:
        raise ApprovalError("AUTHORITY_RUN_IS_NOT_AN_ADOPTION_APPROVAL")
    if approval["approval_run_attempt"] != 1 or isinstance(approval["approval_run_attempt"], bool):
        raise ApprovalError("APPROVAL_RERUN")
    approval_id = approval["approval_id"]
    id_match = _ID.fullmatch(approval_id) if isinstance(approval_id, str) else None
    if id_match is None or id_match.group(1) != run_id:
        raise ApprovalError("APPROVAL_ID_NOT_BOUND_TO_RUN")
    if approval_id in applied_approval_ids or ref in approval_run_ids_in_use or run_id in approval_run_ids_in_use:
        raise ApprovalError("DUPLICATE_APPROVAL")
    # time: after the proof finished, bounded, and not stale
    approved = _time(approval["approved_at"], "APPROVED_AT_SHAPE")
    valid_until = _time(approval["valid_until"], "VALID_UNTIL_SHAPE")
    completed = _time(proof_completed_at, "PROOF_COMPLETED_AT_SHAPE")
    current = _time(now, "NOW_SHAPE")
    if approved <= completed:
        raise ApprovalError("APPROVAL_BEFORE_PROOF_COMPLETE")
    if valid_until <= approved or valid_until - approved > APPROVAL_VALIDITY:
        raise ApprovalError("APPROVAL_VALIDITY_WINDOW")
    if current < approved:
        raise ApprovalError("APPROVAL_FROM_THE_FUTURE")
    if current > valid_until:
        raise ApprovalError("APPROVAL_EXPIRED")
    return lane


def build_approval(
    *, run_id: str, actor_id: str, run_attempt: int, now: str, receipt: dict[str, Any],
    evidence: dict[str, Any], readback_output: Any, current_registry: dict[str, Any],
    proposed_registry: dict[str, Any],
) -> dict[str, Any]:
    """The record the issuer workflow writes. It is validated by the caller before it is saved."""
    assessment, deviation = classify_output(readback_output, evidence)
    moment = _time(now, "NOW_SHAPE")
    return {
        "schema_version": 1, "approval_kind": APPROVAL_KIND,
        "approval_id": f"adopt-durable-{LANE_ID}-{run_id}",
        "lane_id": LANE_ID, "proof_task_id": PROOF_TASK_ID, "loop_number": LOOP_NUMBER,
        "transition": TRANSITION,
        "terminal_receipt_sha256": receipt.get("receipt_payload_sha256"),
        "evidence_payload_sha256": evidence.get("evidence_payload_sha256"),
        "current_registry_sha256": registry_digest(current_registry),
        "proposed_registry_sha256": registry_digest(proposed_registry),
        "output_assessment": assessment,
        "accepted_deviation": deviation if assessment == OUTPUT_DEVIATION and deviation in ACCEPTED_DEVIATIONS else None,
        "approved_by_actor_id": actor_id, "approved_at": zulu(moment), "valid_until": zulu(moment + APPROVAL_VALIDITY),
        "approval_ref": f"github-actions:run/{run_id}", "approval_run_attempt": run_attempt,
        "decision": DECISION, "retry": 0, "fallback": "disabled",
    }
