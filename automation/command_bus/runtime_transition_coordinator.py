"""Provider-neutral, static Runtime Transition Publisher.

No live authority, provider verifier, or Status dispatcher is implemented here.
Trusted controller adapters must supply those boundaries explicitly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .github_backend import GitHubContentsClient
from .loop_owner import validate_owner_chain, validate_owner_event
from .loop_owner_backend import LoopOwnerGitHubBackend, owner_event_path
from .loop_owner_observation import provider_observation_path, validate_provider_observation
from .loop_status_transition import project_durable_transition
from .runtime_transition_evidence import validate_evidence_document
from .runtime_transition_writers import CanonicalEvidenceGitHubBackend, ProviderObservationGitHubBackend
from .validator import validate_receipt, validate_state


@dataclass(frozen=True)
class AuthorizedOwnerContext:
    loop_id: str
    owner_role: str
    holder_id: str
    generation: int
    fencing_token: int
    expected_repo: str
    expected_pr: int
    expected_target_head: str
    command_id: str
    correlation_id: str


@dataclass(frozen=True)
class VerifiedProviderObservation:
    observation: dict[str, Any]
    source_ref: str


@dataclass(frozen=True)
class TransitionRequest:
    owner_event: dict[str, Any]
    evidence_document: dict[str, Any]
    provider_observation_input: dict[str, Any] | None
    expected_prior_state: dict[str, Any]
    desired_state: dict[str, Any]


@dataclass(frozen=True)
class StatusRefreshPlan:
    loop_id: str
    state_ref: str
    event_id: str
    generation: int
    display_state: str
    transition_status: str


@dataclass(frozen=True)
class PublishResult:
    status: str
    stage: str
    reason: str
    status_plan: StatusRefreshPlan | None = None


class OwnerAuthority(Protocol):
    def authorize(self, event: dict[str, Any], prior_state: dict[str, Any], target: dict[str, Any], receipt: dict[str, Any], chain: list[dict[str, Any]]) -> AuthorizedOwnerContext | None: ...


class ProviderVerifier(Protocol):
    def verify(self, candidate: dict[str, Any], evidence: dict[str, Any], receipt: dict[str, Any]) -> VerifiedProviderObservation | None: ...


class TargetReader(Protocol):
    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None: ...


class StatusRefreshBoundary(Protocol):
    """Prepare-only boundary. Implementations used in this static batch do not dispatch."""

    def prepare(self, plan: StatusRefreshPlan) -> None: ...


class Clock(Protocol):
    def now(self) -> str: ...


class UtcClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _canonical_target(raw: dict[str, Any] | None, event: dict[str, Any], *, close: bool) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("target readback unavailable")
    repo = raw.get("repo", raw.get("repository"))
    pr = raw.get("pr", raw.get("pr_number"))
    head = raw.get("head")
    if repo != event["expected_repo"] or pr != event["expected_pr"] or head != event["expected_target_head"]:
        raise ValueError("fresh target PR identity/head mismatch")
    if not close:
        if raw.get("state") != "open" or raw.get("merged") is not False:
            raise ValueError("active owner requires an OPEN non-merged target PR")
    return {"repo": repo, "pr": pr, "head": head}


def _same_context(event: dict[str, Any], context: AuthorizedOwnerContext) -> bool:
    return isinstance(context, AuthorizedOwnerContext) and all(
        getattr(context, field) == event[field]
        for field in AuthorizedOwnerContext.__dataclass_fields__
    )


class RuntimeTransitionPublisher:
    def __init__(
        self,
        client: GitHubContentsClient,
        *,
        branch: str,
        target_reader: TargetReader,
        owner_authority: OwnerAuthority | None = None,
        provider_verifier: ProviderVerifier | None = None,
        status_boundary: StatusRefreshBoundary | None = None,
        clock: Clock | None = None,
    ):
        if not isinstance(branch, str) or not branch or branch in {"main", "master"}:
            raise ValueError("publisher requires a non-default data branch")
        self.client = client
        self.branch = branch
        self.target_reader = target_reader
        self.owner_authority = owner_authority
        self.provider_verifier = provider_verifier
        self.status_boundary = status_boundary
        self.clock = clock or UtcClock()
        self.owner_backend = LoopOwnerGitHubBackend(client, branch=branch)
        self.evidence_backend = CanonicalEvidenceGitHubBackend(client, branch=branch)
        self.observation_backend = ProviderObservationGitHubBackend(client, branch=branch)

    def _read_json(self, path: str) -> tuple[dict[str, Any], str]:
        content = self.client.get(path, self.branch)
        if content is None:
            raise ValueError(f"durable record missing: {path}")
        record = json.loads(content.text)
        if not isinstance(record, dict):
            raise ValueError(f"durable record is not a JSON object: {path}")
        return record, content.sha

    def _read_chain(self, loop_id: str) -> list[dict[str, Any]]:
        # The existing owner backend is the sole owner-event writer and reader.
        return self.owner_backend._read_chain(loop_id)

    def _validate_request(self, request: TransitionRequest) -> tuple[str, bool]:
        event = request.owner_event
        validate_owner_event(event)
        evidence_ref = validate_evidence_document(request.evidence_document)
        validate_state(request.expected_prior_state)
        validate_state(request.desired_state)
        if event["evidence_refs"] != [evidence_ref]:
            raise ValueError("owner generation must bind exactly this canonical evidence document")
        evidence = request.evidence_document
        for key in ("loop_id", "generation", "command_id", "correlation_id", "expected_repo", "expected_pr", "expected_target_head", "source_receipt_ref"):
            if evidence[key] != event[key]:
                raise ValueError(f"evidence/owner mismatch: {key}")
        if request.expected_prior_state["loop_id"] != event["loop_id"] or request.desired_state["loop_id"] != event["loop_id"]:
            raise ValueError("state loop identity mismatch")
        target = {"repo": event["expected_repo"], "pr": event["expected_pr"], "head": event["expected_target_head"]}
        if request.desired_state.get("expected_target") != target or request.desired_state.get("last_command_id") != event["command_id"] or request.desired_state.get("last_receipt_id") != event["source_receipt_id"]:
            raise ValueError("desired state is not bound to the owner generation")
        close = event["event_type"] in {"RELEASE", "TERMINAL"}
        if close and request.desired_state["state"] not in {"COMPLETE", "RECONCILED_LATE_RESULT", "HALTED", "EXPIRED"}:
            raise ValueError("closed owner generation requires an idle or stopped state")
        if not close and request.desired_state["state"] not in {"RUNNING", "WAITING_FOR_EVIDENCE", "VERIFYING_POST_AUTH"}:
            raise ValueError("active owner generation requires an active state")
        return evidence_ref, close

    def _validate_provider(
        self,
        request: TransitionRequest,
        receipt: dict[str, Any],
        evidence_ref: str,
        close: bool,
    ) -> dict[str, Any] | None:
        if close:
            if request.provider_observation_input is not None:
                raise ValueError("close generation must not invent an active observation")
            return None
        if self.provider_verifier is None:
            raise LookupError("provider verification authority is not wired")
        proposed = request.provider_observation_input
        if not isinstance(proposed, dict) or "verified" in proposed:
            raise ValueError("caller must not provide verified=true")
        candidate = {**proposed, "verified": True}
        validate_provider_observation(candidate)
        event = request.owner_event
        for event_key, observation_key in (("loop_id", "loop_id"), ("owner_role", "owner_role"), ("holder_id", "holder_id"), ("generation", "generation"), ("fencing_token", "fencing_token"), ("expected_repo", "expected_repo"), ("expected_pr", "expected_pr"), ("expected_target_head", "expected_target_head")):
            if candidate[observation_key] != event[event_key]:
                raise ValueError(f"provider observation owner mismatch: {event_key}")
        if candidate["evidence_ref"] != evidence_ref or candidate["state"] != request.evidence_document["provider_state"]:
            raise ValueError("provider observation evidence/state mismatch")
        proof = self.provider_verifier.verify(dict(proposed), request.evidence_document, receipt)
        if not isinstance(proof, VerifiedProviderObservation) or proof.observation != candidate or proof.source_ref != request.evidence_document["provider_readback"] or not proof.source_ref:
            raise LookupError("independent provider verification is unavailable or mismatched")
        return candidate

    def _publish_state(self, request: TransitionRequest, initial_sha: str, path: str) -> str:
        current, current_sha = self._read_json(path)
        if current == request.desired_state:
            return "RECOVERED"
        if current_sha != initial_sha or current != request.expected_prior_state:
            raise ValueError("state changed since fresh prior-state readback")
        try:
            self.client.update(path, _canonical(request.desired_state), current_sha, f"publish runtime state {request.owner_event['loop_id']}", self.branch)
        except Exception:
            pass  # Ambiguous CAS result: read back once, never resend.
        readback, _ = self._read_json(path)
        if readback != request.desired_state:
            raise RuntimeError("state CAS result is unverified; do not retry")
        return "ACCEPTED"

    def publish(self, request: TransitionRequest) -> PublishResult:
        stage = "validate"
        try:
            evidence_ref, close = self._validate_request(request)
            event = request.owner_event
            loop_id = event["loop_id"]
            state_path = f"automation/command_bus/state/{loop_id}.json"
            stage = "fresh_readback"
            prior_state, prior_sha = self._read_json(state_path)
            validate_state(prior_state)
            if prior_state not in (request.expected_prior_state, request.desired_state):
                return PublishResult("BLOCKED", stage, "durable state differs from expected prior and desired state")
            chain = self._read_chain(loop_id)
            generation = event["generation"]
            if generation <= len(chain):
                if generation != len(chain) or chain[-1] != event:
                    return PublishResult("BLOCKED", stage, "conflicting or stale existing owner generation")
                owner_already_present = True
            else:
                if generation != len(chain) + 1:
                    return PublishResult("BLOCKED", stage, "skipped owner generation")
                validate_owner_chain([*chain, event])
                owner_already_present = False
            target_raw = self.target_reader.read_target(event["expected_repo"], event["expected_pr"])
            if not isinstance(target_raw, dict):
                return PublishResult("UNKNOWN", stage, "fresh target PR readback unavailable")
            try:
                target = _canonical_target(target_raw, event, close=close)
            except ValueError as exc:
                return PublishResult("BLOCKED", stage, str(exc))
            if not owner_already_present and prior_state == request.desired_state:
                return PublishResult("BLOCKED", stage, "state advanced without the expected owner generation")
            receipt, _ = self._read_json(event["source_receipt_ref"])
            validate_receipt(receipt)
            for key in ("loop_id", "command_id", "correlation_id", "receipt_id"):
                expected = event["source_receipt_id"] if key == "receipt_id" else event[key]
                if receipt.get(key) != expected:
                    raise ValueError(f"source receipt/owner mismatch: {key}")
            if receipt.get("evidence_refs") != [evidence_ref]:
                raise ValueError("source receipt must already bind canonical evidence ref")
            if (not close or event["event_type"] == "RELEASE") and receipt["state"] != "DONE":
                raise ValueError("active/RELEASE owner requires DONE receipt")
            if self.owner_authority is None:
                return PublishResult("NOT_WIRED", "authority", "Loop owner authority is not configured")
            stage = "authority"
            authorized = self.owner_authority.authorize(event, prior_state, target, receipt, chain)
            if not _same_context(event, authorized):
                return PublishResult("NOT_WIRED", stage, "owner role/holder/generation has no matching authority")
            observation = self._validate_provider(request, receipt, evidence_ref, close)
            stage = "preflight_projection"
            proposed_observation_ref = provider_observation_path(loop_id, generation) if observation is not None else None
            preflight = project_durable_transition(
                request.desired_state, [*chain, event] if not owner_already_present else chain,
                receipt_ref=event["source_receipt_ref"], receipt=receipt,
                target=target, evidence_readbacks={evidence_ref: request.evidence_document},
                provider_observation_ref=proposed_observation_ref,
                provider_observation=observation, now=self.clock.now(), expected_loop_id=loop_id,
            )
            if preflight.status not in {"VALID", "TERMINAL"}:
                return PublishResult("UNKNOWN", stage, f"transition preflight failed: {preflight.reason}")

            stage = "evidence"
            evidence_write = self.evidence_backend.write(request.evidence_document)
            if evidence_write.status not in {"ACCEPTED", "RECOVERED"}:
                return PublishResult(evidence_write.status, stage, evidence_write.reason)
            if observation is not None:
                stage = "provider_observation"
                observation_write = self.observation_backend.write(observation)
                if observation_write.status not in {"ACCEPTED", "RECOVERED"}:
                    return PublishResult(observation_write.status, stage, observation_write.reason)

            stage = "owner_generation"
            if not owner_already_present:
                owner_write = self.owner_backend.append(event)
                if owner_write.status != "ACCEPTED":
                    recovered = self._read_chain(loop_id)
                    if recovered != [*chain, event]:
                        return PublishResult("UNKNOWN", stage, "owner append is unresolved; do not retry")
            recovered_chain = self._read_chain(loop_id)
            if recovered_chain != [*chain, event] and not (owner_already_present and recovered_chain == chain):
                return PublishResult("UNKNOWN", stage, "owner chain changed during publication")

            stage = "state_cas"
            self._publish_state(request, prior_sha, state_path)

            stage = "final_validation"
            final_state, _ = self._read_json(state_path)
            final_receipt, _ = self._read_json(event["source_receipt_ref"])
            final_evidence, _ = self._read_json(evidence_ref)
            if _canonical(final_evidence) != _canonical(request.evidence_document) or final_receipt != receipt:
                raise ValueError("evidence or source receipt changed before status boundary")
            observation_ref = None
            final_observation = None
            if observation is not None:
                observation_ref = provider_observation_path(loop_id, generation)
                final_observation, _ = self._read_json(observation_ref)
                if final_observation != observation:
                    raise ValueError("provider observation changed before status boundary")
            final_chain = self._read_chain(loop_id)
            fresh_target = _canonical_target(self.target_reader.read_target(event["expected_repo"], event["expected_pr"]), event, close=close)
            projection = project_durable_transition(
                final_state, final_chain,
                receipt_ref=event["source_receipt_ref"], receipt=final_receipt,
                target=fresh_target, evidence_readbacks={evidence_ref: final_evidence},
                provider_observation_ref=observation_ref,
                provider_observation=final_observation,
                now=self.clock.now(), expected_loop_id=loop_id,
            )
            if projection.status not in {"VALID", "TERMINAL"} or projection.projection is None or projection.event_id is None:
                return PublishResult("UNKNOWN", stage, f"final transition validation failed: {projection.reason}")
            plan = StatusRefreshPlan(loop_id, self.branch, projection.event_id, generation, projection.projection.display_state, projection.status)
            if self.status_boundary is None:
                return PublishResult("NOT_WIRED", "status_boundary", "durable publication verified; Status refresh boundary is not configured", plan)
            self.status_boundary.prepare(plan)
            return PublishResult("READY", "status_boundary", "durable publication verified; Status refresh prepared", plan)
        except LookupError as exc:
            return PublishResult("NOT_WIRED", stage, str(exc))
        except (ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
            return PublishResult("UNKNOWN", stage, str(exc))
