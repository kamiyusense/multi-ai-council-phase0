"""STATIC pieces for a first bounded LIVE proof of the stable lane ``claude-jules-auto`` (Claude -> Jules).

Everything here is pure: no network, no provider call, no registry or Issue write, no workflow dispatch.

* ``validate_proof_plan`` / ``build_proof_plan``: the one-shot plan (one Jules POST, one fresh Jules GET, one Loop A
  budget slot, retry 0, fallback disabled). A plan without an explicit human LIVE authorization is valid but UNAUTHORIZED
  and can never be used to run (``require_authorized=True`` refuses it).
* ``runtime_facts_from_dispatch``: the Claude AUTO runtime's durable facts under the stable lane id, for
  ``lane_runtime_export.export_lane_runtime``. The Loop number, carrier lane label, work branch and Jules session stay
  worker evidence, never identity.
* ``build_terminal_receipt``: the once-only proof receipt (rerun never allowed).
* ``build_adoption_candidate`` and ``validate_adoption_approval``: the adoption contract for this lane only, bound to the proof
  receipt, the evidence digest and the exact current/proposed registry digests. ``prepare_adoption_approval`` only
  builds the record a human-run issuer would commit: nothing is issued here and no issuer workflow exists for this lane.

The Chat -> Jules proof/adoption modules are unchanged: only the lane-generic ``check_single_lane_diff`` is reused.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .claude_jules_dispatch import RECEIPT_PROFILE as DISPATCH_RECEIPT_PROFILE, canonical_json, sha256_of
from .claude_jules_live_budget import LOOP_A_LIVE_BUDGET
from .control_tower import validate_registry
from .durable_adoption_approval import ApprovalError, KNOWN_AUTHORITY_RUN_IDS, check_single_lane_diff
from .lane_identity_adoption import registry_digest
from .control_tower_registration import assess_lane_registration_readiness
from .lane_runtime_export import STABLE_ID_OWNER, ExportError, export_lane_runtime

LANE = "claude-jules"
LANE_ID = "claude-jules-auto"
ID_OWNER = STABLE_ID_OWNER[LANE]
PLAN_KIND = "CLAUDE_JULES_STABLE_LANE_PROOF_PLAN_V1"
RECEIPT_KIND = "CLAUDE_JULES_STABLE_LANE_PROOF_RECEIPT_V1"
CANDIDATE_KIND = "CLAUDE_JULES_ADOPTION_CANDIDATE_V1"
APPROVAL_KIND = "CLAUDE_JULES_DURABLE_ADOPTION_APPROVAL_V1"
PROOF_TASK_ID = "claude-jules-stable-lane-proof-1"
LIMITS = {"jules_post": 1, "jules_get": 1, "live_budget_slots": 1, "retry": 0}
LOOP_A_SLOTS_USED_BEFORE = 4  # Loops 128-131, ledger on claude/claude-jules-autoloop-data (never deleted)
FORBIDDEN_LOOP_NUMBERS = (128, 129, 130, 131)  # spent; also never a stable id
# Chat -> Jules approval run 37155730052 and every identity-proof run can never approve this lane.
FORBIDDEN_APPROVAL_RUN_IDS = KNOWN_AUTHORITY_RUN_IDS | frozenset({"37155730052"})
ACTIVE_RAW_STATES = frozenset({"QUEUED", "PLANNING", "IN_PROGRESS", "RUNNING"})
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TS = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_DIGITS = re.compile(r"^[0-9]{1,24}$")
_PLAN_KEYS = frozenset({
    "schema_version", "plan_kind", "lane_id", "id_owner", "proof_task_id", "origin_loop_id", "origin_generation",
    "repository", "default_branch", "target_branch", "target_pr", "target_head", "target_tree", "allowed_path",
    "allowed_content", "limits", "loop_a_slots_used_before", "forbidden_session_ids", "forbidden_loop_numbers",
    "retry", "fallback", "expires_at", "live_authorization", "plan_sha256",
})
_AUTH_KEYS = frozenset({"approved_by", "approval_ref", "scope", "max_dispatches", "expires_at"})


class ProofError(ValueError):
    """Fail-closed refusal with a stable machine code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _time(value: Any, code: str) -> datetime:
    if not isinstance(value, str) or not _TS.fullmatch(value):
        raise ProofError(code)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _digest(record: dict[str, Any], key: str) -> str:
    return sha256_of({k: v for k, v in record.items() if k != key})


def build_proof_plan(
    *, origin_loop_id: str, origin_generation: int, repository: str, default_branch: str, target_branch: str,
    target_pr: int, target_head: str, target_tree: str, allowed_path: str, allowed_content: str, expires_at: str,
    forbidden_session_ids: list[str], live_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = {
        "schema_version": 1, "plan_kind": PLAN_KIND, "lane_id": LANE_ID, "id_owner": ID_OWNER,
        "proof_task_id": PROOF_TASK_ID, "origin_loop_id": origin_loop_id, "origin_generation": origin_generation,
        "repository": repository, "default_branch": default_branch, "target_branch": target_branch,
        "target_pr": target_pr, "target_head": target_head, "target_tree": target_tree,
        "allowed_path": allowed_path, "allowed_content": allowed_content, "limits": dict(LIMITS),
        "loop_a_slots_used_before": LOOP_A_SLOTS_USED_BEFORE, "forbidden_session_ids": sorted(forbidden_session_ids),
        "forbidden_loop_numbers": list(FORBIDDEN_LOOP_NUMBERS), "retry": 0, "fallback": "disabled",
        "expires_at": expires_at, "live_authorization": live_authorization,
    }
    plan["plan_sha256"] = _digest(plan, "plan_sha256")
    return validate_proof_plan(plan, registry=None)


def validate_proof_plan(plan: Any, *, registry: dict[str, Any] | None, now: str | None = None,
                        require_authorized: bool = False) -> dict[str, Any]:
    """Return the plan iff it is exactly one bounded proof of ``claude-jules-auto``; else raise ``ProofError``."""
    if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS:
        raise ProofError("PLAN_SHAPE")
    if plan["schema_version"] != 1 or plan["plan_kind"] != PLAN_KIND:
        raise ProofError("PLAN_KIND")
    if plan["lane_id"] != LANE_ID or plan["id_owner"] != ID_OWNER or plan["proof_task_id"] != PROOF_TASK_ID:
        raise ProofError("PLAN_WRONG_LANE")
    if plan["plan_sha256"] != _digest(plan, "plan_sha256"):
        raise ProofError("PLAN_DIGEST")
    origin = plan["origin_loop_id"]
    if not isinstance(origin, str) or not origin or origin == LANE_ID or origin.isdecimal():
        raise ProofError("PLAN_ORIGIN_IS_NOT_A_DISTINCT_LOOP")
    if isinstance(plan["origin_generation"], bool) or not isinstance(plan["origin_generation"], int) or plan["origin_generation"] < 1:
        raise ProofError("PLAN_ORIGIN_GENERATION")
    if plan["limits"] != LIMITS or (plan["retry"], plan["fallback"]) != (0, "disabled"):
        raise ProofError("PLAN_LIMITS")
    if plan["loop_a_slots_used_before"] != LOOP_A_SLOTS_USED_BEFORE or LOOP_A_SLOTS_USED_BEFORE + 1 > LOOP_A_LIVE_BUDGET:
        raise ProofError("PLAN_BUDGET")
    if plan["forbidden_loop_numbers"] != list(FORBIDDEN_LOOP_NUMBERS):
        raise ProofError("PLAN_FORBIDDEN_LOOPS")
    if not isinstance(plan["forbidden_session_ids"], list) or not all(
            isinstance(s, str) and _DIGITS.fullmatch(s) for s in plan["forbidden_session_ids"]):
        raise ProofError("PLAN_FORBIDDEN_SESSIONS")
    if plan["target_branch"] in (plan["default_branch"], "", None) or not isinstance(plan["target_branch"], str):
        raise ProofError("PLAN_TARGET_BRANCH")
    for key in ("target_head", "target_tree"):
        if not isinstance(plan[key], str) or not _SHA40.fullmatch(plan[key]):
            raise ProofError("PLAN_SHA", key)
    if isinstance(plan["target_pr"], bool) or not isinstance(plan["target_pr"], int) or plan["target_pr"] < 1:
        raise ProofError("PLAN_TARGET_PR")
    if str(plan["target_pr"]) == LANE_ID or not plan["allowed_path"] or not plan["allowed_content"]:
        raise ProofError("PLAN_ALLOWED_OUTPUT")
    expires = _time(plan["expires_at"], "PLAN_EXPIRES")
    auth = plan["live_authorization"]
    if auth is not None:
        if not isinstance(auth, dict) or set(auth) != _AUTH_KEYS or auth["max_dispatches"] != 1:
            raise ProofError("PLAN_AUTHORIZATION_SHAPE")
        if not all(isinstance(auth[k], str) and auth[k] for k in ("approved_by", "approval_ref", "scope")):
            raise ProofError("PLAN_AUTHORIZATION_SHAPE")
        if _time(auth["expires_at"], "PLAN_AUTHORIZATION_EXPIRES") > expires:
            raise ProofError("PLAN_AUTHORIZATION_OUTLIVES_PLAN")
    if require_authorized:
        if auth is None:
            raise ProofError("PLAN_UNAUTHORIZED", "no explicit human LIVE authorization")
        if now is None or _time(now, "NOW") >= min(expires, _time(auth["expires_at"], "PLAN_AUTHORIZATION_EXPIRES")):
            raise ProofError("PLAN_EXPIRED")
    if registry is not None:
        entries = [e for e in validate_registry(registry) if e.loop_id == LANE_ID]
        if len(entries) != 1 or not entries[0].enabled or entries[0].identity_state != "PLACEHOLDER":
            raise ProofError("PLAN_REGISTRY_ROW", "the lane must be one enabled PLACEHOLDER row before its proof")
    return plan


def runtime_facts_from_dispatch(
    plan: dict[str, Any], *, dispatch_receipt: dict[str, Any], session: dict[str, Any], holder_id: str,
    claimed_at: str, expires_at: str, observed_at: str, observation_expires_at: str, round_number: int = 1,
) -> dict[str, Any]:
    """The Claude AUTO runtime's facts under the stable id, ready for ``export_lane_runtime`` (pure)."""
    validate_proof_plan(plan, registry=None)
    receipt = dispatch_receipt
    if not isinstance(receipt, dict) or receipt.get("profile") != DISPATCH_RECEIPT_PROFILE or receipt.get("state") != "DISPATCHED":
        raise ProofError("DISPATCH_RECEIPT_NOT_DISPATCHED")
    if receipt.get("origin_loop_id") != plan["origin_loop_id"] or receipt.get("origin_generation") != plan["origin_generation"]:
        raise ProofError("DISPATCH_RECEIPT_ORIGIN")
    if (receipt.get("target_branch"), receipt.get("expected_target_head"), receipt.get("expected_target_tree")) != (
            plan["target_branch"], plan["target_head"], plan["target_tree"]):
        raise ProofError("DISPATCH_RECEIPT_TARGET")
    if (receipt.get("retry_count"), receipt.get("fallback_used")) != (0, False):
        raise ProofError("DISPATCH_RECEIPT_RETRY_OR_FALLBACK")
    loop_number = receipt.get("loop_id")
    if str(loop_number).rsplit("-", 1)[-1].isdigit() and int(str(loop_number).rsplit("-", 1)[-1]) in FORBIDDEN_LOOP_NUMBERS:
        raise ProofError("DISPATCH_RECEIPT_SPENT_LOOP")
    session_id = session.get("session_id")
    if not isinstance(session_id, str) or not _DIGITS.fullmatch(session_id) or session_id in plan["forbidden_session_ids"]:
        raise ProofError("SESSION_ID_REFUSED")
    raw = session.get("provider_raw_state")
    if raw not in ACTIVE_RAW_STATES or session.get("starting_branch") != receipt.get("work_branch"):
        raise ProofError("SESSION_NOT_ACTIVE_ON_WORK_BRANCH")
    command_id, correlation = receipt["command_id"], f"claude-jules-corr-{receipt['intent_id']}"
    base = f"automation/command_bus/%s/{LANE_ID}/"
    evidence_ref = f"{base % 'evidence'}{command_id}.json"
    receipt_ref = f"{base % 'receipts'}000001.json"
    event = {
        "schema_version": 1, "event_id": "owner-event-1", "event_type": "ACQUIRE", "loop_id": LANE_ID,
        "owner_role": "AUTO", "holder_id": holder_id, "generation": 1, "fencing_token": 1, "previous_generation": None,
        "claimed_at": claimed_at.replace("Z", "+00:00"), "expires_at": expires_at.replace("Z", "+00:00"),
        "expected_repo": plan["repository"], "expected_pr": plan["target_pr"], "expected_target_head": plan["target_head"],
        "command_id": command_id, "correlation_id": correlation, "source_receipt_id": f"dispatch-{command_id}",
        "source_receipt_ref": receipt_ref, "evidence_refs": [evidence_ref],
    }
    return {
        "stable_lane_id": LANE_ID,
        "state": {"schema_version": 1, "loop_id": LANE_ID, "state": "RUNNING", "round": round_number,
                  "max_rounds": 6, "expires_at": expires_at.replace("Z", "+00:00"), "stop_requested": False,
                  "last_command_id": command_id, "last_receipt_id": f"dispatch-{command_id}",
                  "expected_target": {"repo": plan["repository"], "pr": plan["target_pr"], "head": plan["target_head"]},
                  "retry_policy": 0},
        "owner_events": [event],
        "receipt": {"receipt_id": f"dispatch-{command_id}", "loop_id": LANE_ID, "command_id": command_id,
                    "correlation_id": correlation, "state": "DONE", "executed_once": True, "retry_count": 0,
                    "fallback_used": False, "evidence_refs": [evidence_ref]},
        "evidence": {"provider_raw_state": raw, "result_state": "NONE", "dispatch_intent_sha256": receipt["intent_sha256"],
                     "plan_sha256": plan["plan_sha256"], "proof_task_id": PROOF_TASK_ID,
                     "create_time": session.get("create_time"), "update_time": session.get("update_time")},
        "provider_observation": {
            "schema_version": 1, "observation_id": "provider-observation-1", "verified": True, "loop_id": LANE_ID,
            "owner_role": "AUTO", "holder_id": holder_id, "generation": 1, "fencing_token": 1,
            "expected_repo": plan["repository"], "expected_pr": plan["target_pr"], "expected_target_head": plan["target_head"],
            "state": "RUNNING", "evidence_ref": evidence_ref, "observed_at": observed_at.replace("Z", "+00:00"),
            "expires_at": observation_expires_at.replace("Z", "+00:00")},
        "target": {"repo": plan["repository"], "pr": plan["target_pr"], "head": plan["target_head"], "tree": plan["target_tree"]},
        "worker_evidence": {"jules_session_id": session_id, "loop_number": loop_number, "lane_label": receipt.get("lane_id"),
                            "work_branch": receipt.get("work_branch"), "origin_loop_id": plan["origin_loop_id"]},
    }


def build_terminal_receipt(plan: dict[str, Any], *, status: str, code: str, export_summary: dict[str, Any] | None,
                           lane_registration: str, counters: dict[str, int]) -> dict[str, Any]:
    """The once-only receipt of the proof. COMPLETE needs a READY lane registration; anything else is UNKNOWN/STOPPED."""
    validate_proof_plan(plan, registry=None)
    if status not in {"COMPLETE", "STOPPED", "UNKNOWN"}:
        raise ProofError("RECEIPT_STATUS")
    if any(counters.get(name, 0) > limit for name, limit in LIMITS.items()):
        raise ProofError("BUDGET_EXCEEDED")
    if status == "COMPLETE" and (export_summary is None or lane_registration != "READY"):
        raise ProofError("COMPLETE_NEEDS_READY_REGISTRATION")
    receipt = {
        "schema_version": 1, "receipt_kind": RECEIPT_KIND, "lane_id": LANE_ID, "proof_task_id": PROOF_TASK_ID,
        "plan_sha256": plan["plan_sha256"], "status": status, "code": code, "lane_registration": lane_registration,
        "evidence_sha256": (export_summary or {}).get("evidence_sha256"), "counters": dict(counters),
        "rerun_allowed": False, "retry": 0, "fallback": "disabled",
        "production_registry_written": False, "issue33_written": False,
    }
    receipt["receipt_payload_sha256"] = _digest(receipt, "receipt_payload_sha256")
    return receipt


def build_adoption_candidate(plan: dict[str, Any], receipt: dict[str, Any], *, current_registry: dict[str, Any],
                             proposed_registry: dict[str, Any]) -> dict[str, Any]:
    """Prepare-only candidate: one PLACEHOLDER->DURABLE change of this lane, bound to the proof. Nothing is written."""
    validate_proof_plan(plan, registry=None)
    if receipt.get("receipt_kind") != RECEIPT_KIND or receipt.get("status") != "COMPLETE" or receipt.get("rerun_allowed") is not False \
            or receipt.get("plan_sha256") != plan["plan_sha256"] or receipt.get("receipt_payload_sha256") != _digest(receipt, "receipt_payload_sha256"):
        raise ProofError("CANDIDATE_RECEIPT")
    try:
        check_single_lane_diff(current_registry, proposed_registry, LANE_ID)
    except ApprovalError as exc:
        raise ProofError("CANDIDATE_REGISTRY_DIFF", exc.code) from None
    candidate = {
        "schema_version": 1, "candidate_kind": CANDIDATE_KIND, "lane_id": LANE_ID, "proof_task_id": PROOF_TASK_ID,
        "transition": "PLACEHOLDER->DURABLE", "plan_sha256": plan["plan_sha256"],
        "terminal_receipt_sha256": receipt["receipt_payload_sha256"], "evidence_sha256": receipt["evidence_sha256"],
        "current_registry_sha256": registry_digest(current_registry), "proposed_registry_sha256": registry_digest(proposed_registry),
        "human_approval_required": True, "registry_write_allowed": False,
    }
    candidate["candidate_sha256"] = _digest(candidate, "candidate_sha256")
    return candidate


_APPROVAL_KEYS = frozenset({
    "schema_version", "approval_kind", "approval_id", "lane_id", "proof_task_id", "transition", "candidate_sha256",
    "terminal_receipt_sha256", "evidence_sha256", "current_registry_sha256", "proposed_registry_sha256",
    "approved_by_actor_id", "approved_at", "valid_until", "approval_ref", "approval_run_attempt", "decision", "retry", "fallback",
})
_REF = re.compile(r"^github-actions:run/([0-9]{1,20})$")


def prepare_adoption_approval(candidate: dict[str, Any], *, approved_by_actor_id: str, approved_at: str,
                              valid_until: str, approval_run_id: str) -> dict[str, Any]:
    """Build (never issue) the approval record a human-run issuer would commit for this lane."""
    approval = {
        "schema_version": 1, "approval_kind": APPROVAL_KIND, "approval_id": f"adopt-durable-{LANE_ID}-{approval_run_id}",
        "lane_id": LANE_ID, "proof_task_id": PROOF_TASK_ID, "transition": candidate["transition"],
        "candidate_sha256": candidate["candidate_sha256"], "terminal_receipt_sha256": candidate["terminal_receipt_sha256"],
        "evidence_sha256": candidate["evidence_sha256"], "current_registry_sha256": candidate["current_registry_sha256"],
        "proposed_registry_sha256": candidate["proposed_registry_sha256"], "approved_by_actor_id": approved_by_actor_id,
        "approved_at": approved_at, "valid_until": valid_until, "approval_ref": f"github-actions:run/{approval_run_id}",
        "approval_run_attempt": 1, "decision": "ADOPT_DURABLE", "retry": 0, "fallback": "disabled",
    }
    return approval


def validate_adoption_approval(
    approval: Any, *, candidate: dict[str, Any], current_registry: dict[str, Any], proposed_registry: dict[str, Any],
    allowed_approver_ids: frozenset[str], now: str, applied_approval_ids: frozenset[str] = frozenset(),
) -> str:
    """Return the adopted lane id or raise ``ProofError``. Pure; an identity-proof run is never an approval."""
    if not isinstance(approval, dict) or set(approval) != _APPROVAL_KEYS:
        raise ProofError("APPROVAL_SHAPE")
    if approval["schema_version"] != 1 or approval["approval_kind"] != APPROVAL_KIND:
        raise ProofError("APPROVAL_KIND")
    if approval["lane_id"] != LANE_ID or approval["proof_task_id"] != PROOF_TASK_ID or candidate.get("lane_id") != LANE_ID:
        raise ProofError("APPROVAL_WRONG_LANE")
    if approval["decision"] != "ADOPT_DURABLE" or approval["transition"] != "PLACEHOLDER->DURABLE" \
            or (approval["retry"], approval["fallback"]) != (0, "disabled") or approval["approval_run_attempt"] != 1:
        raise ProofError("APPROVAL_DECISION")
    if candidate.get("candidate_sha256") != _digest(candidate, "candidate_sha256"):
        raise ProofError("CANDIDATE_DIGEST")
    for key in ("candidate_sha256", "terminal_receipt_sha256", "evidence_sha256", "current_registry_sha256", "proposed_registry_sha256"):
        if not _SHA256.fullmatch(str(approval[key])) or approval[key] != candidate.get(key):
            raise ProofError("APPROVAL_DIGEST", key)
    if approval["current_registry_sha256"] != registry_digest(current_registry) \
            or approval["proposed_registry_sha256"] != registry_digest(proposed_registry):
        raise ProofError("APPROVAL_REGISTRY_DIGEST")
    try:
        check_single_lane_diff(current_registry, proposed_registry, LANE_ID)
    except ApprovalError as exc:
        raise ProofError("APPROVAL_REGISTRY_DIFF", exc.code) from None
    match = _REF.fullmatch(str(approval["approval_ref"]))
    if match is None or approval["approval_id"] != f"adopt-durable-{LANE_ID}-{match.group(1)}":
        raise ProofError("APPROVAL_REF")
    if match.group(1) in FORBIDDEN_APPROVAL_RUN_IDS:
        raise ProofError("APPROVAL_RUN_NOT_AN_APPROVAL", "an identity-proof or another lane's approval run cannot approve this lane")
    if approval["approval_id"] in applied_approval_ids:
        raise ProofError("APPROVAL_ALREADY_APPLIED")
    if str(approval["approved_by_actor_id"]) not in allowed_approver_ids:
        raise ProofError("APPROVAL_ACTOR")
    issued, until, current = _time(approval["approved_at"], "APPROVAL_TIME"), _time(approval["valid_until"], "APPROVAL_TIME"), _time(now, "NOW")
    if not issued <= current < until:
        raise ProofError("APPROVAL_EXPIRED")
    return LANE_ID


# ---------------------------------------------------------------------------------------------------------------
# One-shot driver. Every effect goes through an injected port; with fakes it is fully STATIC. It performs at most
# ONE dispatch call and ONE session read, never retries, and writes a once-only attempt marker before the first
# irreversible step, so a second run (or a crashed first run) is refused instead of repeated.
# ---------------------------------------------------------------------------------------------------------------
DATA_DIR = "docs/evidence/claude-jules-stable-lane-proof-1"
ATTEMPT_MARKER_PATH = f"{DATA_DIR}/attempt-marker.json"
TERMINAL_RECEIPT_PATH = f"{DATA_DIR}/terminal-receipt.json"


class ProofPorts(Protocol):
    def create_once(self, path: str, document: dict[str, Any]) -> str:
        """Create-only write on the data branch with readback. Return CREATED, or EXISTS when identical or different."""

    def dispatch(self, plan: dict[str, Any]) -> dict[str, Any]:
        """The existing ClaudeJulesDispatcher.dispatch for the already-prepared intent. Returns the dispatch receipt."""

    def read_session(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """ONE bounded Jules GET (no activities). Sanitized dict out."""

    def collect(self, loop_id: str) -> Any:
        """ControlTowerDurableCollector.collect_transition over the data branch the chain files were written to."""

    def now(self) -> str: ...


@dataclass
class ProofCounters:
    jules_post: int = 0
    jules_get: int = 0
    live_budget_slots: int = 0
    retry: int = 0
    events: list[str] = field(default_factory=list)

    def spend(self, name: str) -> None:
        if getattr(self, name) + 1 > LIMITS[name] or name == "retry":
            raise ProofError("BUDGET_EXCEEDED", name)
        setattr(self, name, getattr(self, name) + 1)
        self.events.append(name)

    def as_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in LIMITS}


@dataclass(frozen=True)
class ProofRun:
    status: str  # COMPLETE / STOPPED / UNKNOWN
    code: str
    receipt: dict[str, Any] | None
    candidate: dict[str, Any] | None
    counters: dict[str, int]


def run_stable_lane_proof(plan: dict[str, Any], *, current_registry: dict[str, Any], proposed_registry: dict[str, Any],
                          ports: ProofPorts, holder_id: str = "claude-auto", request: dict[str, Any] | None = None) -> ProofRun:
    """Run the one bounded proof through the injected ports. Never raises for an operational failure."""
    counters = ProofCounters()
    now = ports.now()
    try:  # nothing is written until the plan is valid, authorized, unexpired and the lane row is still PLACEHOLDER
        validate_proof_plan(plan, registry=current_registry, now=now, require_authorized=True)
        check_single_lane_diff(current_registry, proposed_registry, LANE_ID)
    except (ProofError, ApprovalError) as exc:
        return ProofRun("STOPPED", getattr(exc, "code", "PLAN_REFUSED"), None, None, counters.as_dict())

    def finish(status: str, code: str, summary: dict[str, Any] | None = None, registration: str = "NOT_WIRED") -> ProofRun:
        receipt = build_terminal_receipt(plan, status=status, code=code, export_summary=summary,
                                         lane_registration=registration, counters=counters.as_dict())
        ports.create_once(TERMINAL_RECEIPT_PATH, receipt)  # a failed proof is terminal too: no rerun
        candidate = None
        if status == "COMPLETE":
            candidate = build_adoption_candidate(plan, receipt, current_registry=current_registry, proposed_registry=proposed_registry)
        return ProofRun(status, code, receipt, candidate, counters.as_dict())

    marker = {"schema_version": 1, "marker_kind": "CLAUDE_JULES_STABLE_LANE_PROOF_ATTEMPT_V1", "lane_id": LANE_ID,
              "proof_task_id": PROOF_TASK_ID, "plan_sha256": plan["plan_sha256"], "attempted_at": now, "rerun_allowed": False}
    try:
        if ports.create_once(ATTEMPT_MARKER_PATH, marker) != "CREATED":
            return ProofRun("STOPPED", "ALREADY_ATTEMPTED", None, None, counters.as_dict())  # no dispatch, no read
    except Exception:
        return ProofRun("STOPPED", "ATTEMPT_MARKER_UNVERIFIED", None, None, counters.as_dict())
    try:
        counters.spend("live_budget_slots")
        counters.spend("jules_post")
        receipt = ports.dispatch(plan)  # exactly one call, never repeated
        if not isinstance(receipt, dict) or receipt.get("state") != "DISPATCHED":
            return finish("UNKNOWN", "DISPATCH_NOT_PROVEN")
        counters.spend("jules_get")
        observed = ports.read_session(receipt)  # exactly one call, never repeated
        facts = runtime_facts_from_dispatch(
            plan, dispatch_receipt=receipt, session=observed, holder_id=holder_id,
            claimed_at=_zulu(now), expires_at=_zulu_plus(now, hours=2), observed_at=_zulu(now),
            observation_expires_at=_zulu_plus(now, hours=1))
        exported = export_lane_runtime(
            LANE, registry=proposed_registry,
            request=request or {"origin_loop_id": plan["origin_loop_id"], "command_id": receipt["command_id"],
                                "target_branch": plan["target_branch"], "target_repo": plan["repository"]},
            durable_context={"loop_id": LANE_ID, "id_owner": ID_OWNER, "correlation_id": facts["owner_events"][0]["correlation_id"],
                             "target_pr": plan["target_pr"]},
            runtime_facts=facts)
        for path, document in exported.chain_files.items():
            if ports.create_once(path, document) not in {"CREATED", "EXISTS"}:
                return finish("UNKNOWN", "CHAIN_WRITE_UNVERIFIED", exported.summary)
        collection = ports.collect(LANE_ID)
        transition = getattr(collection, "transition", None)
        if getattr(collection, "status", None) != "COLLECTED" or transition is None or transition.status != "VALID":
            return finish("UNKNOWN", "TRANSITION_NOT_VALID", exported.summary)
        registration = assess_lane_registration_readiness(proposed_registry, LANE_ID, transition)
        if registration.status != "READY":
            return finish("UNKNOWN", "LANE_REGISTRATION_NOT_READY", exported.summary, registration.status)
        return finish("COMPLETE", "OK", exported.summary, "READY")
    except (ProofError, ExportError, ValueError, KeyError, TypeError) as exc:
        return finish("UNKNOWN", getattr(exc, "code", type(exc).__name__))
    except Exception as exc:  # an ambiguous external failure is never retried
        return finish("UNKNOWN", f"AMBIGUOUS:{type(exc).__name__}")


def _zulu(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zulu_plus(value: str, *, hours: int) -> str:
    from datetime import timedelta
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(hours=hours)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class LiveProofPorts:
    """Glue from the existing live objects to ``ProofPorts``. Constructing the real objects is the only step left for LIVE.

    * ``client``: a GitHubContentsClient (``get``/``list``/``create``) bound to the proof data branch.
    * ``dispatcher``: the existing ``ClaudeJulesDispatcher`` and ``intent`` its already-prepared dispatch intent
      (its policy carries the human authorization, its ledger takes the one Loop A slot).
    * ``session_id_source``: returns the single accepted Jules session id of the dispatched command (the existing
      carrier job-log reader); ``session_reader``: the existing ``read_active_session(session_id, expected_branch=)``
      port, one bounded GET.
    * ``collector``: a ``ControlTowerDurableCollector`` reading the same data branch.
    """

    def __init__(self, *, client: Any, data_branch: str, dispatcher: Any, intent: dict[str, Any], dispatches_used: int,
                 session_id_source: Any, session_reader: Any, collector: Any, clock: Any):
        self.client, self.data_branch, self.dispatcher, self.intent = client, data_branch, dispatcher, intent
        self.dispatches_used, self.session_id_source, self.session_reader = dispatches_used, session_id_source, session_reader
        self.collector, self.clock = collector, clock

    def create_once(self, path: str, document: dict[str, Any]) -> str:
        text = canonical_json(document)
        existing = self.client.get(path, self.data_branch)
        if existing is not None:
            return "EXISTS"
        try:
            self.client.create(path, text, f"Claude Jules stable lane proof: {path}", self.data_branch)
        except Exception:
            pass  # an ambiguous create is decided by the readback only, never resent
        readback = self.client.get(path, self.data_branch)
        if readback is None:
            raise ProofError("WRITE_NOT_PROVEN", path)
        return "CREATED" if canonical_json(json.loads(readback.text)) == text else "EXISTS"

    def dispatch(self, plan: dict[str, Any]) -> dict[str, Any]:
        result = self.dispatcher.dispatch(self.intent, now=self.clock.now(), dispatches_used=self.dispatches_used)
        record = dict(result.record or {})
        record.setdefault("state", result.status)
        return record

    def read_session(self, receipt: dict[str, Any]) -> dict[str, Any]:
        session_id = self.session_id_source(receipt["command_id"])
        if not isinstance(session_id, str):
            raise ProofError("SESSION_ID_NOT_SINGLE")
        snapshot = self.session_reader.read_active_session(session_id, expected_branch=receipt["work_branch"])
        return {"session_id": session_id, **snapshot}

    def collect(self, loop_id: str) -> Any:
        return self.collector.collect_transition(loop_id)

    def now(self) -> str:
        return self.clock.now()
