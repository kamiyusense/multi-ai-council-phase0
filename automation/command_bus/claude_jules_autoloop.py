"""Claude AUTO controller for the Claude x Jules loop (resumable from GitHub).

One ``step`` re-derives the whole loop position from durable GitHub records
only (dispatch intents/receipts, result events, inspections, adoption
receipts, task specs and the owner chain), performs at most one bounded
action, and returns.  No Chat, thread, browser or Jules session id is state:
a brand-new Claude session constructing this class against the same records
continues exactly where the previous one stopped.

Composition of existing parts:
  verdict/preparation   -> claude_loop (make_structured_verdict,
                           prepare_next_action, prepare_jules_semiauto_bundle)
  carrier contract      -> jules_carrier_current validators, existing workflow
  origin binding/store  -> claude_jules_origin_binding(_store)
  owner fencing         -> loop_owner chain via LoopOwnerGitHubBackend
  adoption gate         -> jules_publication.fast_forward_allowed

Model work (running tests, semantic review, writing a small repair) is
supplied by an injected ``ResultFactsCollector``; the controller only accepts
its evidence through the fail-closed inspection contract.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from .claude_jules_adoption import SafeAdoption, adoption_receipt_path
from .claude_jules_campaign import (
    RECOVERABLE_UNKNOWN, TRANSIENT_UNKNOWN, campaign_policy_from_legacy,
    classify_boundary, validate_campaign_policy,
)
from .claude_jules_campaign_state import (
    CampaignStateStore, build_deferred_decision_event, build_task_blocked_event,
)
from .claude_jules_dispatch import (
    EVIDENCE_ROOT, ClaudeJulesDispatcher, build_dispatch_intent, canonical_json,
    dispatch_receipt_path, next_unused_loop_number, sha256_of, validate_dispatch_intent,
    validate_policy,
)
from .claude_jules_handover import append_decision, decide_auto_resume
from .claude_jules_inspection import InspectionStore, inspect_result, validate_small_repair
from .claude_jules_reinspection import ReinspectionStore
from .claude_jules_result_event import ResultEventInbox, verify_result_lineage
from .claude_jules_task_prompt import (
    corrective_task_spec, path_policy, render_task_prompt, validate_task_spec,
)
from .claude_loop import (
    BackendMode, make_structured_verdict, numbered_command_id, prepare_jules_semiauto_bundle,
    prepare_jules_semiauto_request, prepare_loop_claim, prepare_next_action,
)

ROADMAP_PROFILE = "CLAUDE_AUTO_JULES_ROADMAP_V1"
MAX_ATTEMPTS_PER_ROUND = 2
REQUEST_LIFETIME = timedelta(minutes=90)
# Jules normally answers within an hour; after this a dispatch with no result PR
# (Jules failure, no publication, lost event) stops for a human instead of waiting forever.
RESULT_DEADLINE = timedelta(hours=6)
TERMINAL_STOP = {"STOP_HUMAN", "INVESTIGATE"}


@dataclass(frozen=True)
class StepResult:
    action: str
    status: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class ResultFactsCollector(Protocol):
    def dispatch_observation(self, command_id: str) -> dict[str, Any] | None: ...
    def fresh_pr(self, pr_number: int) -> dict[str, Any] | None: ...
    def compare(self, base: str, head: str) -> dict[str, Any] | None: ...
    def commit_tree(self, sha: str) -> str | None: ...
    def run_tests(self, head: str) -> dict[str, Any] | None: ...
    def test_sources(self, head: str, paths: list[str]) -> dict[str, str] | None: ...
    def review(self, intent: dict[str, Any], spec: dict[str, Any], head: str) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...
    def small_repair(self, intent: dict[str, Any], inspection: dict[str, Any]) -> str | None: ...


def validate_roadmap(roadmap: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(roadmap, dict) or set(roadmap) != {"schema_version", "profile", "roadmap_id", "tasks"}:
        raise ValueError("roadmap keys mismatch")
    if roadmap["schema_version"] != 1 or roadmap["profile"] != ROADMAP_PROFILE:
        raise ValueError("unsupported roadmap")
    seen: set[str] = set()
    for entry in roadmap["tasks"]:
        if not isinstance(entry, dict) or set(entry) != {"task_spec", "depends_on"}:
            raise ValueError("roadmap task entry malformed")
        spec = validate_task_spec(entry["task_spec"])
        if spec["task_id"] in seen or re.search(r"-fix[0-9]+$", spec["task_id"]):
            raise ValueError("roadmap task ids must be unique base ids")
        if any(dep not in seen for dep in entry["depends_on"]):
            raise ValueError("roadmap dependencies must reference earlier tasks")
        seen.add(spec["task_id"])
    return roadmap


def _family(task_id: str) -> str:
    return re.sub(r"-fix[0-9]+$", "", task_id)


def task_spec_path(task_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", task_id or ""):
        raise ValueError("unsafe task id")
    return f"{EVIDENCE_ROOT}/claude-auto-task-specs/{task_id}.json"


class ClaudeJulesAutoLoop:
    def __init__(self, *, client: Any, refs: Any, policy: dict[str, Any], owner_reader: Any,
                 roadmap: dict[str, Any], facts: ResultFactsCollector, origin_loop_id: str,
                 lane_id: str, carrier_guard: Any = None, campaign_policy: dict[str, Any] | None = None):
        self.client, self.refs, self.facts = client, refs, facts
        self.policy = validate_policy(policy)
        self.explicit_campaign_policy = campaign_policy is not None
        self.campaign_policy = (campaign_policy_from_legacy(self.policy, origin_loop_id)
                                if campaign_policy is None else validate_campaign_policy(campaign_policy))
        self.roadmap = validate_roadmap(roadmap)
        self.owner_reader, self.origin_loop_id, self.lane_id = owner_reader, origin_loop_id, lane_id
        self.data = self.policy["data_branch"]
        self.campaign_state = CampaignStateStore(
            client, data_branch=self.data, campaign_id=self.campaign_policy["campaign_id"])
        dispatch_policy = dict(self.policy, max_rounds=self.campaign_policy["max_rounds"])
        self.dispatcher = ClaudeJulesDispatcher(
            client=client, refs=refs, policy=dispatch_policy, owner_reader=owner_reader,
            carrier_guard=carrier_guard,
        )
        self.inbox = ResultEventInbox(client, data_branch=self.data)
        self.inspections = InspectionStore(client, data_branch=self.data)
        self.reinspections = ReinspectionStore(client, data_branch=self.data)
        self.adoption = SafeAdoption(client=client, refs=refs, policy=policy)

    # -- durable reads ------------------------------------------------------
    def _read_json(self, path: str, branch: str | None = None) -> dict[str, Any] | None:
        content = self.client.get(path, branch or self.data)
        return None if content is None else json.loads(content.text)

    def _intents(self) -> list[dict[str, Any]]:
        prefix = f"{EVIDENCE_ROOT}/claude-auto-dispatch-intents/"
        records = [validate_dispatch_intent(json.loads(c.text)) for c in self.client.list(prefix, self.data)]
        mine = [r for r in records if r["origin_loop_id"] == self.origin_loop_id]
        return sorted(mine, key=lambda r: (r["origin_round"], r["attempt"]))

    def _spec(self, task_id: str) -> dict[str, Any] | None:
        record = self._read_json(task_spec_path(task_id))
        return None if record is None else validate_task_spec(record)

    def _store_spec(self, spec: dict[str, Any]) -> str:
        path = task_spec_path(spec["task_id"])
        existing = self.client.get(path, self.data)
        if existing is not None:
            return "RECOVERED" if json.loads(existing.text) == spec else "COLLISION"
        try:
            self.client.create(path, canonical_json(spec), f"Claude AUTO task spec {spec['task_id']}", self.data)
        except Exception:
            pass
        readback = self.client.get(path, self.data)
        return "CREATED" if readback is not None and json.loads(readback.text) == spec else "UNKNOWN"

    def _owner_generation(self) -> int | None:
        read = self.owner_reader.read_chain(self.origin_loop_id)
        if getattr(read, "status", None) != "READ" or not isinstance(read.record, dict):
            return None
        return read.record.get("generation")

    def _try_owner_resume(self, *, now: str, fence: Any) -> StepResult | None:
        if fence.status != "BLOCKED" or "owner lease expired" not in fence.reason:
            return None
        read_events = getattr(self.owner_reader, "read_events", None)
        if read_events is None:
            return StepResult("STOP", "UNKNOWN", "owner backend cannot read full chain for safe resume")
        try:
            chain = read_events(self.origin_loop_id)
            intents = self._intents()
            half_written = sum(
                1 for intent in intents
                if self._read_json(dispatch_receipt_path(intent["carrier_request"]["command_id"])) is None
            )
            targets = self.policy["allowed_target_branches"]
            if len(targets) != 1:
                return StepResult("STOP", "BLOCKED", "safe owner resume requires exactly one target branch")
            target_head = self.refs.get_branch_head(targets[0])
            if target_head is None:
                return StepResult("STOP", "UNKNOWN", "target head unavailable during owner resume")
            decision = decide_auto_resume(
                owner_chain=chain, auto_holder=self.policy["holder_id"],
                half_written_intents=half_written, target_head=target_head, now=now,
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, RuntimeError) as exc:
            return StepResult("STOP", "UNKNOWN", f"owner resume evidence unverifiable: {exc}")
        if decision.status != "ELIGIBLE":
            return StepResult("STOP", decision.status, f"owner resume: {decision.reason}")
        appended = append_decision(self.owner_reader, decision)
        if appended.status != "APPENDED":
            return StepResult("STOP", appended.status, f"owner resume append: {appended.reason}")
        return StepResult(
            "RECOVER_OWNER", "RECOVERED", appended.reason,
            {"generation": appended.event["generation"] if appended.event else None},
        )

    def _campaign_timeout(self, *, now: str) -> StepResult | None:
        """Enforce wall-clock timeout only for explicit new campaign policies.

        The deadline is re-derived from the earliest durable dispatch intent,
        so restarts need no session memory. Legacy callers keep their historical
        behavior because they did not opt into a campaign timeout contract.
        """
        if not self.explicit_campaign_policy:
            return None
        intents = self._intents()
        if not intents:
            return None
        try:
            started = min(
                datetime.fromisoformat(item["prepared_at"].replace("Z", "+00:00"))
                for item in intents
            )
            current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            return StepResult("STOP", "UNKNOWN", f"campaign timeout evidence unverifiable: {exc}")
        deadline = started + timedelta(seconds=self.campaign_policy["campaign_timeout_seconds"])
        if current < deadline:
            return None
        return StepResult(
            "STOP", "CAMPAIGN_TIMEOUT",
            "explicit campaign wall-clock timeout reached; durable state is preserved for inspection",
            {"started_at": started.isoformat(), "deadline": deadline.isoformat()},
        )

    def _wait_details(self, *, now: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        return {
            **(details or {}),
            "next_check_at": (
                current + timedelta(seconds=self.campaign_policy["idle_check_interval_seconds"])
            ).isoformat(),
        }

    def defer_decision(
        self, *, decision_id: str, question: str, options: list[str], reason: str,
        selected_safe_default: str, reversibility: str, affected_scope: str,
        reconsider_condition: str, now: str,
    ) -> StepResult:
        """Persist a reversible safe default without stopping the campaign."""
        try:
            event = build_deferred_decision_event(
                campaign_id=self.campaign_policy["campaign_id"],
                decision_id=decision_id,
                question=question,
                options=options,
                reason=reason,
                selected_safe_default=selected_safe_default,
                reversibility=reversibility,
                affected_scope=affected_scope,
                reconsider_condition=reconsider_condition,
                recorded_at=now,
            )
            saved = self.campaign_state.persist(event)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return StepResult("STOP", "UNKNOWN", f"deferred decision unverifiable: {exc}")
        if saved not in {"CREATED", "RECOVERED"}:
            return StepResult("STOP", "UNKNOWN", f"deferred decision record {saved}")
        return StepResult(
            "DEFER_DECISION", "DEFERRED", "safe reversible default recorded; campaign may continue",
            {"decision_id": decision_id, "selected_safe_default": selected_safe_default,
             "campaign_event_id": event["event_id"]},
        )

    # -- one step -------------------------------------------------------------
    def step(self, *, now: str) -> StepResult:
        fence = self.dispatcher.controller_fence(self.origin_loop_id, now)
        if fence.status != "PASS":
            recovery = self._try_owner_resume(now=now, fence=fence)
            if recovery is None:
                return StepResult("STOP", fence.status, f"owner fence: {fence.reason}")
            if recovery.status != "RECOVERED":
                return recovery
            fence = self.dispatcher.controller_fence(self.origin_loop_id, now)
            if fence.status != "PASS":
                return StepResult("STOP", fence.status, f"owner fence after resume: {fence.reason}")
        try:
            timeout = self._campaign_timeout(now=now)
            if timeout is not None:
                return timeout
            intents = self._intents()
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return StepResult("STOP", "UNKNOWN", f"durable intent records unverifiable: {exc}")
        if not intents:
            return self._plan_and_dispatch(now=now, round_number=1, attempt=1, spec=None)
        latest = intents[-1]
        request = latest["carrier_request"]
        command_id = request["command_id"]
        spec = self._spec(latest["task_id"])
        if spec is None or sha256_of(spec) != latest["task_spec_sha256"]:
            return StepResult("STOP", "UNKNOWN", "task spec for the latest intent is missing or altered")
        try:
            blocked_tasks = self.campaign_state.blocked_tasks()
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return StepResult("STOP", "UNKNOWN", f"campaign state unverifiable: {exc}")
        if _family(spec["task_id"]) in blocked_tasks:
            return self._plan_and_dispatch(
                now=now, round_number=latest["origin_round"] + 1, attempt=1, spec=None)
        receipt = self._read_json(dispatch_receipt_path(command_id))
        if receipt is None:
            return self._dispatch(latest, now=now, resumed=True)
        if receipt.get("state") == "BLOCKED":
            if latest["attempt"] >= MAX_ATTEMPTS_PER_ROUND:
                return StepResult("STOP", "BLOCKED", f"dispatch blocked twice: {receipt.get('reason')}")
            return self._plan_and_dispatch(now=now, round_number=latest["origin_round"],
                                           attempt=latest["attempt"] + 1, spec=spec)
        if receipt.get("state") != "DISPATCHED":
            return StepResult("STOP", "UNKNOWN", f"unexpected dispatch receipt state {receipt.get('state')}")

        try:
            all_inspections = self._all_inspections()
            adopted = self._adoption_state(latest, all_inspections)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return StepResult("STOP", "UNKNOWN", f"durable inspection/adoption records unverifiable: {exc}")
        if adopted.status == "VERIFIED":
            return self._after_adoption(latest, now=now)
        if adopted.status != "MISSING":
            return StepResult("STOP", "UNKNOWN", f"adoption record: {adopted.reason}")
        mine = [r for r in all_inspections if r["command_id"] == command_id]
        if any(r["intent_sha256"] != latest["intent_sha256"] for r in mine):
            return StepResult("STOP", "BLOCKED", "inspection record bound to another dispatch intent")
        if mine:
            current = self._current_inspection(mine)
            decision = current["decision"]
            if decision == "ADOPT_CANDIDATE":
                # Adoption fast-forwards the canonical target and cannot be undone:
                # re-check the owner/lease right before the write, not only at step start.
                recheck = self.dispatcher.controller_fence(self.origin_loop_id, now)
                if recheck.status != "PASS":
                    return StepResult("STOP", recheck.status, f"owner fence before adoption: {recheck.reason}")
                result = self.adoption.adopt(intent=latest, inspection=current, adopted_at=now)
                status_action = "ADOPT"
                if result.status == "ADOPTED":
                    return StepResult(status_action, "ADOPTED", result.reason, {"head_after": result.record["head_after"]})
                return StepResult("STOP" if result.status in {"BLOCKED", "UNKNOWN"} else status_action,
                                  result.status, result.reason)
            if decision == "CLAUDE_SMALL_REPAIR":
                return self._small_repair(latest, spec, current, mine, now=now)
            if decision in {"JULES_CORRECTIVE", "JULES_CORRECTIVE_REDUCED"}:
                return self._corrective_or_block(
                    latest, spec, current, intents, now=now,
                    reduce_size=decision == "JULES_CORRECTIVE_REDUCED",
                )
            if decision == "STOP_HUMAN":
                return self._corrective_or_block(
                    latest, spec, current, intents, now=now, reduce_size=True,
                )
            if decision == "INVESTIGATE":
                boundary = classify_boundary("UNKNOWN", current["reason"])
                if boundary is not None and boundary.retry_safe:
                    return self._reinspect_unknown(latest, spec, current, now=now)
            return StepResult("STOP", current["verdict"], f"human/investigation boundary: {current['reason']}")
        return self._inspect_new_result(latest, spec, now=now)

    def run_until_boundary(self, *, now: str, max_steps: int = 12) -> list[StepResult]:
        """Advance through safe recovery until a real boundary or the step budget ends."""
        results: list[StepResult] = []
        recovery_attempts = 0
        for _ in range(max_steps):
            result = self.step(now=now)
            boundary = classify_boundary(result.status, result.reason)
            if boundary is not None:
                result = StepResult(
                    result.action, result.status, result.reason,
                    dict(result.details, boundary_class=boundary.kind),
                )
            results.append(result)
            if result.action in {"WAIT", "COMPLETE"} or result.status == "PREPARED_NOT_AUTHORIZED":
                break
            if (boundary is not None and boundary.retry_safe
                    and recovery_attempts < self.campaign_policy["max_transient_retries"]):
                recovery_attempts += 1
                continue
            if result.action == "STOP" or result.status == "UNKNOWN":
                break
        return results

    # -- phases ------------------------------------------------------------
    def _all_inspections(self) -> list[dict[str, Any]]:
        return self.reinspections.extend_all(self.inspections.list_all())

    def _current_inspection(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        repaired = {r["repair_of"] for r in records if r.get("repair_of")}
        open_records = [r for r in records if r["candidate_head"] not in repaired]
        return sorted(open_records, key=lambda r: (r.get("repair_of") is not None, r["inspected_at"]))[-1]

    def _inspect_new_result(self, intent: dict[str, Any], spec: dict[str, Any], *, now: str) -> StepResult:
        request = intent["carrier_request"]
        try:
            events = [e for e in self.inbox.list_events() if e["command_id"] == request["command_id"]]
            prior = self._all_inspections()
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return StepResult("STOP", "UNKNOWN", f"durable event records unverifiable: {exc}")
        if not events:
            deadline = (datetime.fromisoformat(intent["prepared_at"])
                        + timedelta(seconds=self.campaign_policy["task_timeout_seconds"]))
            if datetime.fromisoformat(now.replace("Z", "+00:00")) >= deadline:
                return self._block_task(
                    intent, spec,
                    f"no Jules result PR recorded by {deadline.isoformat()}; the dispatch slot stays consumed",
                    now=now,
                )
            return StepResult(
                "WAIT", "WAITING_FOR_RESULT", "no Jules result event recorded yet",
                self._wait_details(now=now, details={"command_id": request["command_id"]}),
            )
        receipt = self._read_json(dispatch_receipt_path(request["command_id"]))
        try:
            observation = self.facts.dispatch_observation(request["command_id"])
            fresh = {e["pr_number"]: self.facts.fresh_pr(e["pr_number"]) for e in events}
        except Exception as exc:  # evidence transport/record failure is never a pass
            return StepResult("STOP", "UNKNOWN", f"dispatch/PR evidence unverifiable: {exc}")
        lineage = None
        for event in sorted(events, key=lambda e: e["pr_number"], reverse=True):
            verdict = verify_result_lineage(event, intent=intent, dispatch_receipt=receipt,
                                            dispatch_observation=observation,
                                            fresh_pr=fresh[event["pr_number"]])
            if verdict.status == "PASS":
                lineage = verdict.record
                break
            if verdict.status in {"BLOCKED", "UNKNOWN"}:
                return StepResult("STOP", verdict.status, f"result lineage: {verdict.reason}")
        if lineage is None:
            return StepResult(
                "WAIT", "WAITING_FOR_RESULT", "only stale result heads recorded",
                self._wait_details(now=now),
            )
        ready = getattr(self.facts, "review_ready", None)
        if ready is not None and not ready(intent, spec, lineage["candidate_head"]):
            return StepResult(
                "WAIT", "AWAITING_CLAUDE_REVIEW",
                "result lineage verified; Claude's independent review record is not written yet",
                self._wait_details(
                    now=now,
                    details={"command_id": request["command_id"], "head": lineage["candidate_head"]},
                ),
            )
        return self._inspect(intent, spec, lineage, lineage["candidate_head"], now=now, repair_of=None)

    def _reinspect_unknown(self, intent: dict[str, Any], spec: dict[str, Any],
                           current: dict[str, Any], *, now: str) -> StepResult:
        if current.get("repair_of") is not None:
            return self._block_task(intent, spec, "repair evidence stayed UNKNOWN after safe investigation", now=now)
        base = self.inspections.get(current["command_id"], current["candidate_head"])
        if base is None:
            return StepResult("STOP", "UNKNOWN", "legacy base inspection missing for reinspection")
        try:
            attempts = len(self.reinspections.all_versions(base)) - 1
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return StepResult("STOP", "UNKNOWN", f"reinspection history unverifiable: {exc}")
        if attempts >= self.campaign_policy["max_transient_retries"]:
            return self._block_task(intent, spec, "transient evidence retry budget exhausted", now=now)

        request = intent["carrier_request"]
        try:
            events = [e for e in self.inbox.list_events() if e["command_id"] == request["command_id"]]
            receipt = self._read_json(dispatch_receipt_path(request["command_id"]))
            observation = self.facts.dispatch_observation(request["command_id"])
            fresh = {e["pr_number"]: self.facts.fresh_pr(e["pr_number"]) for e in events}
        except Exception as exc:
            return StepResult("STOP", "UNKNOWN", f"reinspection evidence unavailable: {exc}")
        lineage = None
        for event in sorted(events, key=lambda e: e["pr_number"], reverse=True):
            verdict = verify_result_lineage(
                event, intent=intent, dispatch_receipt=receipt,
                dispatch_observation=observation, fresh_pr=fresh[event["pr_number"]],
            )
            if verdict.status == "PASS" and verdict.record["candidate_head"] == current["candidate_head"]:
                lineage = verdict.record
                break
        if lineage is None:
            return StepResult("STOP", "UNKNOWN", "same-head lineage unavailable for reinspection")
        ready = getattr(self.facts, "review_ready", None)
        if ready is not None and not ready(intent, spec, current["candidate_head"]):
            return StepResult(
                "WAIT", "AWAITING_CLAUDE_REVIEW", "reinspection review evidence is not ready",
                self._wait_details(now=now, details={"head": current["candidate_head"]}),
            )
        return self._inspect(
            intent, spec, lineage, current["candidate_head"], now=now, repair_of=None,
            reinspection_base=base,
        )

    def _inspect(self, intent: dict[str, Any], spec: dict[str, Any], lineage: dict[str, Any], head: str,
                 *, now: str, repair_of: str | None,
                 reinspection_base: dict[str, Any] | None = None) -> StepResult:
        request = intent["carrier_request"]
        compare = self.facts.compare(request["expected_target_head"], head)
        tree = self.facts.commit_tree(head)
        changed = [f.get("path") for f in (compare or {}).get("files", []) if isinstance(f, dict)]
        tests = [p for p in changed if isinstance(p, str) and p.endswith(".py") and "/tests/" in f"/{p}"]
        observations, findings = self.facts.review(intent, spec, head)
        outcome = inspect_result(
            intent=intent, task_spec=spec, lineage=lineage, compare=compare, candidate_tree=tree,
            test_evidence=self.facts.run_tests(head), changed_test_sources=self.facts.test_sources(head, tests),
            acceptance_observations=observations, reviewer_findings=findings,
            prior_inspections=self._all_inspections(), inspected_at=now, repair_of=repair_of,
        )
        saved = (self.inspections.persist(outcome.record) if reinspection_base is None
                 else self.reinspections.persist(base=reinspection_base, inspection=outcome.record))
        if saved not in {"CREATED", "RECOVERED"}:
            return StepResult("STOP", "UNKNOWN", f"inspection record {saved}")
        return StepResult("INSPECT", outcome.verdict, outcome.record["reason"],
                          {"decision": outcome.decision, "head": head})

    def _small_repair(self, intent: dict[str, Any], spec: dict[str, Any], inspection: dict[str, Any],
                      records: list[dict[str, Any]], *, now: str) -> StepResult:
        repairs = sum(1 for r in records if r.get("repair_of"))
        repaired = self.facts.small_repair(intent, inspection)
        if repaired is None:
            return StepResult("STOP", "UNKNOWN", "small repair produced no verifiable head")
        compare = self.facts.compare(inspection["candidate_head"], repaired)
        state, reason = validate_small_repair(inspection=inspection, task_spec=spec,
                                              repair_compare=compare, repairs_already_made=repairs)
        if state != "PASS":
            return StepResult("STOP", state, reason)
        lineage = {"command_id": intent["carrier_request"]["command_id"], "session_id": "claude-small-repair",
                   "workflow_run_id": "none", "candidate_head": repaired}
        return self._inspect(intent, spec, lineage, repaired, now=now, repair_of=inspection["candidate_head"])

    def _after_adoption(self, intent: dict[str, Any], *, now: str) -> StepResult:
        next_round = intent["origin_round"] + 1
        if next_round > self.campaign_policy["max_rounds"]:
            return StepResult("STOP", "MAX_ROUNDS", "max_rounds reached after adoption")
        return self._plan_and_dispatch(now=now, round_number=next_round, attempt=1, spec=None)

    def _adoption_state(self, intent: dict[str, Any], inspections: list[dict[str, Any]]) -> Any:
        """VERIFIED / MISSING / UNKNOWN for one dispatch, never trusting mere existence."""
        raw = self._read_json(adoption_receipt_path(intent["carrier_request"]["command_id"]))
        if raw is None:
            return self.adoption.verify_adopted(intent=intent, inspection=None)  # MISSING
        referenced = raw.get("inspection_sha256") if isinstance(raw, dict) else None
        match = [r for r in inspections if r["inspection_sha256"] == referenced
                 and r["command_id"] == intent["carrier_request"]["command_id"]]
        return self.adoption.verify_adopted(intent=intent, inspection=match[0] if len(match) == 1 else None)

    def _roadmap_position(self) -> tuple[dict[str, Any] | None, list[str]]:
        adopted_families: set[str] = set()
        inspections = self._all_inspections()
        for intent in self._intents():
            state = self._adoption_state(intent, inspections)
            if state.status == "VERIFIED":
                adopted_families.add(_family(intent["task_id"]))
            elif state.status != "MISSING":
                raise ValueError(f"unverifiable adoption for {intent['carrier_request']['command_id']}: {state.reason}")
        blocked = self.campaign_state.blocked_tasks()
        remaining: list[str] = []
        ready: dict[str, Any] | None = None
        for entry in self.roadmap["tasks"]:
            spec = entry["task_spec"]
            task_id = spec["task_id"]
            if task_id in adopted_families:
                continue
            remaining.append(task_id)
            if ready is None and task_id not in blocked and all(dep in adopted_families for dep in entry["depends_on"]):
                ready = spec
        return ready, remaining

    def next_roadmap_task(self) -> dict[str, Any] | None:
        return self._roadmap_position()[0]

    def _corrective_or_block(
        self, intent: dict[str, Any], spec: dict[str, Any], inspection: dict[str, Any],
        intents: list[dict[str, Any]], *, now: str, reduce_size: bool,
    ) -> StepResult:
        family = _family(spec["task_id"])
        family_dispatches = sum(1 for item in intents if _family(item["task_id"]) == family)
        correctives_used = max(0, family_dispatches - 1)
        family_failures = sum(
            1 for item in self._all_inspections()
            if _family(item["task_id"]) == family and item["verdict"] in {"FAIL_MINOR", "FAIL_MAJOR"}
        )
        if family_failures >= self.campaign_policy["max_consecutive_failures"]:
            return self._block_task(
                intent, spec,
                f"consecutive failure budget exhausted after {family_failures} failure(s): {inspection['reason']}",
                now=now,
            )
        if correctives_used >= self.campaign_policy["max_corrective_rounds_per_task"]:
            return self._block_task(
                intent, spec,
                f"corrective budget exhausted after {correctives_used} corrective round(s): {inspection['reason']}",
                now=now,
            )
        corrective = corrective_task_spec(
            spec, attempt=family_dispatches, findings=inspection["findings"],
            reduce_size=reduce_size,
        )
        return self._plan_and_dispatch(
            now=now, round_number=intent["origin_round"] + 1, attempt=1, spec=corrective,
        )

    def _block_task(self, intent: dict[str, Any], spec: dict[str, Any], reason: str, *, now: str) -> StepResult:
        task_id = _family(spec["task_id"])
        event = build_task_blocked_event(
            campaign_id=self.campaign_policy["campaign_id"],
            task_id=task_id,
            reason=reason,
            evidence_ref=f"dispatch-intent:{intent['intent_sha256']}",
            recorded_at=now,
        )
        saved = self.campaign_state.persist(event)
        if saved not in {"CREATED", "RECOVERED"}:
            return StepResult("STOP", "UNKNOWN", f"campaign blocker record {saved}")
        return StepResult(
            "BLOCK_TASK", "TASK_BLOCKED", reason,
            {"task_id": task_id, "campaign_event_id": event["event_id"]},
        )

    def _plan_and_dispatch(self, *, now: str, round_number: int, attempt: int,
                           spec: dict[str, Any] | None) -> StepResult:
        if round_number > self.campaign_policy["max_rounds"]:
            return StepResult("STOP", "MAX_ROUNDS", "max_rounds reached")
        if spec is None:
            try:
                spec, remaining = self._roadmap_position()
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                return StepResult("STOP", "UNKNOWN", f"roadmap position unverifiable: {exc}")
            if spec is None:
                if remaining:
                    return StepResult(
                        "STOP", "TASK_BLOCKED",
                        "remaining roadmap tasks are blocked or depend on blocked/unadopted tasks",
                        {"remaining_tasks": remaining},
                    )
                return StepResult("COMPLETE", "COMPLETE", "no remaining roadmap task is eligible")
        generation = self._owner_generation()
        if not isinstance(generation, int):
            return StepResult("STOP", "UNKNOWN", "owner generation unavailable")
        target = self.policy["allowed_target_branches"][0] if len(self.policy["allowed_target_branches"]) == 1 else None
        if target is None:
            return StepResult("STOP", "BLOCKED", "exactly one granted target branch is required")
        head = self.refs.get_branch_head(target)
        tree = self.refs.get_commit_tree(head) if head else None
        if head is None or tree is None:
            return StepResult("STOP", "UNKNOWN", "target snapshot unavailable")
        try:
            intent = self._build_intent(spec, now=now, round_number=round_number, attempt=attempt,
                                        generation=generation, head=head, tree=tree)
        except (KeyError, TypeError, ValueError) as exc:
            return StepResult("STOP", "BLOCKED", f"cannot prepare dispatch: {exc}")
        dispatches_used = self._dispatches_used()
        campaign_budget = self.campaign_policy["dispatch_provider_budget"]
        if campaign_budget is not None and dispatches_used >= campaign_budget:
            return StepResult(
                "STOP", "PREPARED_NOT_AUTHORIZED",
                "campaign dispatch/provider budget exhausted before carrier write",
                {"command_id": intent["carrier_request"]["command_id"], "intent": intent},
            )
        pre = self.dispatcher.preflight(intent, now=now, dispatches_used=dispatches_used)
        if pre.status == "WAIT":
            return StepResult(
                "WAIT", "CARRIER_BUSY", pre.reason, self._wait_details(now=now)
            )  # nothing written; plan again later
        if pre.status != "PASS":
            return StepResult("STOP", pre.status, pre.reason,
                              {"command_id": intent["carrier_request"]["command_id"], "intent": intent})
        stored = self._store_spec(spec)
        if stored not in {"CREATED", "RECOVERED"}:
            return StepResult("STOP", "UNKNOWN" if stored == "UNKNOWN" else "BLOCKED", f"task spec record {stored}")
        return self._dispatch(intent, now=now, resumed=False)

    def _build_intent(self, spec: dict[str, Any], *, now: str, round_number: int, attempt: int,
                      generation: int, head: str, tree: str) -> dict[str, Any]:
        created = datetime.fromisoformat(now.replace("Z", "+00:00"))
        expires = (created + REQUEST_LIFETIME).isoformat()
        loop_number = next_unused_loop_number(self.client, self.policy["carrier_branch"])
        command_id = numbered_command_id(loop_number, spec["task_id"])
        correlation = f"{self.origin_loop_id}-round-{round_number}"
        verdict = make_structured_verdict(
            verdict_id=f"{self.origin_loop_id}-r{round_number}-a{attempt}", loop_id=self.origin_loop_id,
            round=round_number, generation=generation, correlation_id=correlation,
            mode=BackendMode.JULES_BACKEND.value, decision="CONTINUE",
            expected_target_head=head, expected_target_tree=tree,
            reasons=[f"roadmap/corrective task {spec['task_id']}"],
            evidence_refs=[f"task-spec:{sha256_of(spec)}"],
            next_prompt=render_task_prompt(spec, loop_label=f"Loop {loop_number:03d}"),
        )
        prepared = prepare_next_action(verdict, expected_repo=self.policy["target_repo"],
                                       expected_pr=self.policy["expected_pr"], expires_at=expires,
                                       path_policy=path_policy(spec))
        if prepared.status != "PREPARED":
            raise ValueError(prepared.reason)
        common = dict(target_branch=self.policy["allowed_target_branches"][0],
                      default_branch=self.policy["default_branch"], created_at=created.isoformat(),
                      command_id=command_id)
        carrier = prepare_jules_semiauto_request(prepared.request, **common)
        if carrier.status != "PREPARED":
            raise ValueError(carrier.reason)
        claim = prepare_loop_claim(carrier.request, lane_id=self.lane_id, claimed_at=created.isoformat())
        if claim.status != "PREPARED":
            raise ValueError(claim.reason)
        bundle = prepare_jules_semiauto_bundle(prepared.request, claim.request, **common)
        if bundle.status != "PREPARED":
            raise ValueError(bundle.reason)
        return build_dispatch_intent(
            origin_loop_id=self.origin_loop_id, origin_round=round_number, origin_correlation_id=correlation,
            origin_generation=generation, attempt=attempt, task_id=spec["task_id"],
            task_spec_sha256=sha256_of(spec), carrier_request=bundle.request["carrier_request"],
            carrier_claim=claim.request, origin_binding=bundle.request["origin_binding"],
            prepared_at=created.isoformat(),
        )

    def _dispatches_used(self) -> int:
        used = 0
        for other in self._intents():
            receipt = self._read_json(dispatch_receipt_path(other["carrier_request"]["command_id"]))
            if receipt is not None and receipt.get("state") == "DISPATCHED":
                used += 1
        return used

    def _dispatch(self, intent: dict[str, Any], *, now: str, resumed: bool) -> StepResult:
        result = self.dispatcher.dispatch(intent, now=now, dispatches_used=self._dispatches_used())
        action = "RESUME_DISPATCH" if resumed else "DISPATCH"
        details = {"command_id": intent["carrier_request"]["command_id"], "intent_id": intent["intent_id"]}
        if result.status in {"DISPATCHED", "NO-OP"}:
            return StepResult(action, result.status, result.reason, details)
        if result.status == "WAIT":
            return StepResult(
                "WAIT", "CARRIER_BUSY", result.reason,
                self._wait_details(now=now, details=details),
            )  # resumes from the same intent
        if result.status == "BLOCKED" and result.record is not None:
            return StepResult(action, "BLOCKED", result.reason, details)  # receipt written; next step re-plans
        return StepResult("STOP", result.status, result.reason, details)
