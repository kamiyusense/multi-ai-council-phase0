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
from .claude_jules_dispatch import (
    EVIDENCE_ROOT, ClaudeJulesDispatcher, build_dispatch_intent, canonical_json,
    dispatch_receipt_path, next_unused_loop_number, sha256_of, validate_dispatch_intent,
    validate_policy,
)
from .claude_jules_inspection import InspectionStore, inspect_result, validate_small_repair
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
                 lane_id: str):
        self.client, self.refs, self.facts = client, refs, facts
        self.policy = validate_policy(policy)
        self.roadmap = validate_roadmap(roadmap)
        self.owner_reader, self.origin_loop_id, self.lane_id = owner_reader, origin_loop_id, lane_id
        self.data = self.policy["data_branch"]
        self.dispatcher = ClaudeJulesDispatcher(client=client, refs=refs, policy=policy, owner_reader=owner_reader)
        self.inbox = ResultEventInbox(client, data_branch=self.data)
        self.inspections = InspectionStore(client, data_branch=self.data)
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

    # -- one step -------------------------------------------------------------
    def step(self, *, now: str) -> StepResult:
        fence = self.dispatcher.controller_fence(self.origin_loop_id, now)
        if fence.status != "PASS":
            return StepResult("STOP", fence.status, f"owner fence: {fence.reason}")
        try:
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
            all_inspections = self.inspections.list_all()
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
                result = self.adoption.adopt(intent=latest, inspection=current, adopted_at=now)
                status_action = "ADOPT"
                if result.status == "ADOPTED":
                    return StepResult(status_action, "ADOPTED", result.reason, {"head_after": result.record["head_after"]})
                return StepResult("STOP" if result.status in {"BLOCKED", "UNKNOWN"} else status_action,
                                  result.status, result.reason)
            if decision == "CLAUDE_SMALL_REPAIR":
                return self._small_repair(latest, spec, current, mine, now=now)
            if decision in {"JULES_CORRECTIVE", "JULES_CORRECTIVE_REDUCED"}:
                attempt = sum(1 for i in intents if _family(i["task_id"]) == _family(spec["task_id"]))
                corrective = corrective_task_spec(spec, attempt=attempt, findings=current["findings"],
                                                  reduce_size=decision == "JULES_CORRECTIVE_REDUCED")
                return self._plan_and_dispatch(now=now, round_number=latest["origin_round"] + 1,
                                               attempt=1, spec=corrective)
            return StepResult("STOP", current["verdict"], f"human/investigation boundary: {current['reason']}")
        return self._inspect_new_result(latest, spec, now=now)

    def run_until_boundary(self, *, now: str, max_steps: int = 12) -> list[StepResult]:
        """Advance until waiting, stopping, completing or the step budget ends."""
        results: list[StepResult] = []
        for _ in range(max_steps):
            result = self.step(now=now)
            results.append(result)
            if result.action in {"WAIT", "STOP", "COMPLETE"} or result.status in {"PREPARED_NOT_AUTHORIZED", "UNKNOWN"}:
                break
        return results

    # -- phases ------------------------------------------------------------
    def _current_inspection(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        repaired = {r["repair_of"] for r in records if r.get("repair_of")}
        open_records = [r for r in records if r["candidate_head"] not in repaired]
        return sorted(open_records, key=lambda r: (r.get("repair_of") is not None, r["inspected_at"]))[-1]

    def _inspect_new_result(self, intent: dict[str, Any], spec: dict[str, Any], *, now: str) -> StepResult:
        request = intent["carrier_request"]
        try:
            events = [e for e in self.inbox.list_events() if e["command_id"] == request["command_id"]]
            prior = self.inspections.list_all()
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return StepResult("STOP", "UNKNOWN", f"durable event records unverifiable: {exc}")
        if not events:
            return StepResult("WAIT", "WAITING_FOR_RESULT", "no Jules result event recorded yet",
                              {"command_id": request["command_id"]})
        receipt = self._read_json(dispatch_receipt_path(request["command_id"]))
        observation = self.facts.dispatch_observation(request["command_id"])
        lineage = None
        for event in sorted(events, key=lambda e: e["pr_number"], reverse=True):
            verdict = verify_result_lineage(event, intent=intent, dispatch_receipt=receipt,
                                            dispatch_observation=observation,
                                            fresh_pr=self.facts.fresh_pr(event["pr_number"]))
            if verdict.status == "PASS":
                lineage = verdict.record
                break
            if verdict.status in {"BLOCKED", "UNKNOWN"}:
                return StepResult("STOP", verdict.status, f"result lineage: {verdict.reason}")
        if lineage is None:
            return StepResult("WAIT", "WAITING_FOR_RESULT", "only stale result heads recorded")
        return self._inspect(intent, spec, lineage, lineage["candidate_head"], now=now, repair_of=None)

    def _inspect(self, intent: dict[str, Any], spec: dict[str, Any], lineage: dict[str, Any], head: str,
                 *, now: str, repair_of: str | None) -> StepResult:
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
            prior_inspections=self.inspections.list_all(), inspected_at=now, repair_of=repair_of,
        )
        saved = self.inspections.persist(outcome.record)
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
        if next_round > self.policy["max_rounds"]:
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

    def next_roadmap_task(self) -> dict[str, Any] | None:
        adopted_families: set[str] = set()
        inspections = self.inspections.list_all()
        for intent in self._intents():
            state = self._adoption_state(intent, inspections)
            if state.status == "VERIFIED":
                adopted_families.add(_family(intent["task_id"]))
            elif state.status != "MISSING":
                raise ValueError(f"unverifiable adoption for {intent['carrier_request']['command_id']}: {state.reason}")
        for entry in self.roadmap["tasks"]:
            spec = entry["task_spec"]
            if spec["task_id"] in adopted_families:
                continue
            if all(dep in adopted_families for dep in entry["depends_on"]):
                return spec
            return None  # roadmap order is the dependency order; never skip ahead
        return None

    def _plan_and_dispatch(self, *, now: str, round_number: int, attempt: int,
                           spec: dict[str, Any] | None) -> StepResult:
        if round_number > self.policy["max_rounds"]:
            return StepResult("STOP", "MAX_ROUNDS", "max_rounds reached")
        if spec is None:
            try:
                spec = self.next_roadmap_task()
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                return StepResult("STOP", "UNKNOWN", f"roadmap position unverifiable: {exc}")
            if spec is None:
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
        pre = self.dispatcher.preflight(intent, now=now, dispatches_used=self._dispatches_used())
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
        if result.status == "BLOCKED" and result.record is not None:
            return StepResult(action, "BLOCKED", result.reason, details)  # receipt written; next step re-plans
        return StepResult("STOP", result.status, result.reason, details)
