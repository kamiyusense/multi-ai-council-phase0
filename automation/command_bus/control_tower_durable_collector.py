"""Read-only durable transition collector for Control Tower.

This module performs no GitHub/provider writes and does not invent loop IDs.
It reuses the existing durable transition validator:

  state + owner chain -> exact fetch plan
  -> receipt/evidence/provider readbacks
  -> fresh target readback
  -> independent durable-record readback check
  -> project_durable_transition()

The collector is transport-neutral. Production code must inject a
GitHubContentsClient and a fresh target reader. Tests use deterministic fakes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .control_tower import validate_registry
from .github_backend import GitHubContent, GitHubContentsClient
from .loop_owner import validate_owner_chain, validate_owner_event
from .loop_status_transition import TransitionProjectionResult, project_durable_transition
from .loop_status_transition_cli import build_fetch_plan
from .validator import validate_state

_ROOT = "automation/command_bus"
_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_OWNER_FILE = re.compile(r"^([0-9]{6,})\.json$")
_MAX_OWNER_GENERATIONS = 100
_MAX_EVIDENCE_REFS = 32


class DurableTargetReader(Protocol):
    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None: ...


class CollectorClock(Protocol):
    def now(self) -> str: ...


@dataclass(frozen=True)
class DurableTransitionCollection:
    status: str
    reason: str
    loop_id: str
    transition: TransitionProjectionResult | None = None
    fetch_plan: dict[str, Any] | None = None


@dataclass(frozen=True)
class ControlTowerTransitionInventory:
    status: str
    reason: str
    transitions: Mapping[str, TransitionProjectionResult]
    collections: Mapping[str, DurableTransitionCollection]


class ControlTowerDurableCollector:
    def __init__(
        self,
        client: GitHubContentsClient,
        *,
        ref: str,
        target_reader: DurableTargetReader,
        clock: CollectorClock,
    ):
        if not isinstance(ref, str) or not ref or "\n" in ref or "\r" in ref:
            raise ValueError("collector ref is invalid")
        self.client = client
        self.ref = ref
        self.target_reader = target_reader
        self.clock = clock

    def collect_transition(self, loop_id: str) -> DurableTransitionCollection:
        if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
            return DurableTransitionCollection(
                "BLOCKED",
                "unsafe durable loop_id",
                str(loop_id),
            )

        try:
            state_path = f"{_ROOT}/state/{loop_id}.json"
            state = self._read_json(state_path)
            validate_state(state)
            if state["loop_id"] != loop_id:
                raise ValueError("state loop/path mismatch")

            chain = self._read_owner_chain(loop_id)
            plan = build_fetch_plan(state, chain, expected_loop_id=loop_id)
            if len(plan["evidence_refs"]) > _MAX_EVIDENCE_REFS:
                raise ValueError("evidence ref count exceeds bounded maximum")

            receipt = self._read_json(plan["receipt_ref"])
            evidence = {
                ref: self._read_json(ref)
                for ref in plan["evidence_refs"]
            }
            observation_ref = plan["provider_observation_ref"]
            observation = (
                self._read_json(observation_ref)
                if observation_ref is not None
                else None
            )

            target_raw = self.target_reader.read_target(
                plan["expected_repo"],
                plan["expected_pr"],
            )
            target = self._normalize_target(target_raw, plan)

            # Detect a transition snapshot that changed while it was being read.
            if self._read_json(state_path) != state:
                raise ValueError("durable state changed during collection")
            if self._read_owner_chain(loop_id) != chain:
                raise ValueError("owner chain changed during collection")
            if self._read_json(plan["receipt_ref"]) != receipt:
                raise ValueError("source receipt changed during collection")
            for ref, document in evidence.items():
                if self._read_json(ref) != document:
                    raise ValueError(f"evidence changed during collection: {ref}")
            if observation_ref is not None:
                if self._read_json(observation_ref) != observation:
                    raise ValueError("provider observation changed during collection")

            target_again = self._normalize_target(
                self.target_reader.read_target(
                    plan["expected_repo"],
                    plan["expected_pr"],
                ),
                plan,
            )
            if target_again != target:
                raise ValueError("target changed during collection")

            transition = project_durable_transition(
                state,
                chain,
                receipt_ref=plan["receipt_ref"],
                receipt=receipt,
                target=target,
                evidence_readbacks=evidence,
                provider_observation_ref=observation_ref,
                provider_observation=observation,
                now=self.clock.now(),
                expected_loop_id=loop_id,
                last_durable_progress=(
                    f"generation {plan['generation']}; "
                    f"receipt {state.get('last_receipt_id', 'UNKNOWN')}"
                ),
            )
            if transition.status == "UNKNOWN":
                return DurableTransitionCollection(
                    "UNKNOWN",
                    transition.reason,
                    loop_id,
                    transition,
                    plan,
                )
            if transition.projection is None or transition.owner_decision is None:
                return DurableTransitionCollection(
                    "UNKNOWN",
                    "accepted durable transition is incomplete",
                    loop_id,
                    transition,
                    plan,
                )
            return DurableTransitionCollection(
                "COLLECTED",
                "durable transition readbacks are stable and verified",
                loop_id,
                transition,
                plan,
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return DurableTransitionCollection(
                "UNKNOWN",
                str(exc),
                loop_id,
            )

    def collect_registry(
        self,
        registry: dict[str, Any],
    ) -> ControlTowerTransitionInventory:
        try:
            entries = validate_registry(registry)
        except (ValueError, TypeError, KeyError, AssertionError) as exc:
            return ControlTowerTransitionInventory(
                "BLOCKED",
                f"registry invalid: {exc}",
                {},
                {},
            )

        enabled = tuple(entry for entry in entries if entry.enabled)
        if not enabled:
            return ControlTowerTransitionInventory(
                "NOT_WIRED",
                "no enabled Control Tower lanes",
                {},
                {},
            )

        placeholders = tuple(
            entry.loop_id
            for entry in enabled
            if entry.identity_state != "DURABLE"
        )
        if placeholders:
            return ControlTowerTransitionInventory(
                "NOT_WIRED",
                "enabled Control Tower lane identity is not DURABLE: "
                + ",".join(placeholders),
                {},
                {},
            )

        transitions: dict[str, TransitionProjectionResult] = {}
        collections: dict[str, DurableTransitionCollection] = {}
        for entry in enabled:
            collected = self.collect_transition(entry.loop_id)
            collections[entry.loop_id] = collected
            if collected.status != "COLLECTED" or collected.transition is None:
                return ControlTowerTransitionInventory(
                    collected.status,
                    f"lane {entry.loop_id}: {collected.reason}",
                    dict(transitions),
                    dict(collections),
                )
            transitions[entry.loop_id] = collected.transition

        return ControlTowerTransitionInventory(
            "READY",
            "all enabled DURABLE lanes collected from stable durable readbacks",
            transitions,
            collections,
        )

    def _read_json(self, path: str) -> dict[str, Any]:
        content = self.client.get(path, self.ref)
        if content is None:
            raise ValueError(f"durable record missing: {path}")
        if not isinstance(content, GitHubContent) or content.path != path:
            raise ValueError(f"durable record path mismatch: {path}")
        value = json.loads(content.text)
        if not isinstance(value, dict):
            raise ValueError(f"durable record is not a JSON object: {path}")
        return value

    def _read_owner_chain(self, loop_id: str) -> list[dict[str, Any]]:
        prefix = f"{_ROOT}/loop_owner_events/{loop_id}/"
        contents = self.client.list(prefix, self.ref)
        if (
            not isinstance(contents, list)
            or not contents
            or len(contents) > _MAX_OWNER_GENERATIONS
        ):
            raise ValueError("owner generation count is empty or exceeds bounded maximum")

        parsed: list[tuple[int, dict[str, Any]]] = []
        seen_paths: set[str] = set()
        for content in contents:
            if not isinstance(content, GitHubContent):
                raise ValueError("owner listing contains invalid entry")
            if content.path in seen_paths:
                raise ValueError("duplicate owner ledger path")
            seen_paths.add(content.path)
            if not content.path.startswith(prefix):
                raise ValueError("owner ledger listing escaped prefix")
            name = content.path[len(prefix):]
            match = _OWNER_FILE.fullmatch(name)
            if match is None:
                raise ValueError("unexpected owner ledger filename")
            generation = int(match.group(1))
            if name != f"{generation:06d}.json":
                raise ValueError("owner generation filename is not canonical")
            record = json.loads(content.text)
            if not isinstance(record, dict):
                raise ValueError("owner event is not a JSON object")
            validate_owner_event(record)
            if record["loop_id"] != loop_id:
                raise ValueError("owner loop/path mismatch")
            if record["generation"] != generation:
                raise ValueError("owner generation/path mismatch")
            parsed.append((generation, record))

        parsed.sort(key=lambda pair: pair[0])
        return validate_owner_chain(record for _, record in parsed)

    @staticmethod
    def _normalize_target(
        raw: dict[str, Any] | None,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("fresh target readback unavailable")
        repo = raw.get("repo", raw.get("repository"))
        pr = raw.get("pr", raw.get("pr_number"))
        head = raw.get("head")
        if repo != plan["expected_repo"] or pr != plan["expected_pr"]:
            raise ValueError("fresh target PR identity mismatch")
        if not isinstance(head, str):
            raise ValueError("fresh target head is missing")
        if plan["event_type"] in {"ACQUIRE", "RENEW", "HANDOFF"}:
            if raw.get("state") != "open" or raw.get("merged") is not False:
                raise ValueError("active durable owner requires an OPEN non-merged target")
        return {"repo": repo, "pr": pr, "head": head}
