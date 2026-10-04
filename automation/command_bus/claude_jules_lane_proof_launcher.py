"""Production-object wiring for the bounded Claude -> Jules stable-lane proof.

Importing this module performs no I/O. build_live_proof_ports only constructs
existing adapters; it does not dispatch, call Jules, write GitHub, flip the
registry, or publish Issue #33. The irreversible proof remains exclusively in
run_stable_lane_proof and still requires an explicitly authorized,
unexpired plan.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .claude_jules_dispatch import ClaudeJulesDispatcher, validate_dispatch_intent
from .claude_jules_lane_proof import LiveProofPorts, ProofError
from .claude_jules_live import CarrierQuietGuard, LiveResultFacts
from .claude_jules_live_adapter import GitHubRestReader, GitLiveClient
from .control_tower_durable_collector import ControlTowerDurableCollector
from .loop_owner_backend import LoopOwnerGitHubBackend
from .signal_step7_live_proof_cli import JulesActiveSessionGetReader, SystemClock

_SESSION_ID = re.compile(r"^[0-9]{1,32}$")


class StableLaneTargetReader:
    """Fresh PR reader in the shape required by ControlTowerDurableCollector."""

    def __init__(self, rest: Any, repository: str):
        self.rest, self.repository = rest, repository

    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None:
        if repository != self.repository:
            return None
        pr = self.rest.pull(pr_number)
        if not isinstance(pr, dict) or pr.get("number") != pr_number:
            return None
        head = (pr.get("head") or {}).get("sha")
        if not isinstance(head, str):
            return None
        return {
            "repo": repository,
            "pr": pr_number,
            "head": head,
            "state": pr.get("state"),
            "merged": bool(pr.get("merged") or pr.get("merged_at")),
        }


class StableLaneSessionReader:
    """Normalize the existing Jules GET reader into the proof runtime-facts shape."""

    def __init__(self, reader: Any):
        self.reader = reader

    def read_active_session(self, session_id: str, *, expected_branch: str) -> dict[str, Any]:
        snapshot = self.reader.read_active_session(session_id, expected_branch=expected_branch)
        if not isinstance(snapshot, dict):
            raise ProofError("SESSION_SHAPE")
        context = snapshot.get("sourceContext")
        github = context.get("githubRepoContext") if isinstance(context, dict) else None
        state = snapshot.get("state")
        branch = github.get("startingBranch") if isinstance(github, dict) else None
        create_time = snapshot.get("createTime")
        update_time = snapshot.get("updateTime")
        if not all(isinstance(v, str) and v for v in (state, branch, create_time)):
            raise ProofError("SESSION_SHAPE")
        if update_time is not None and not isinstance(update_time, str):
            raise ProofError("SESSION_SHAPE")
        return {
            "provider_raw_state": state,
            "starting_branch": branch,
            "create_time": create_time,
            "update_time": update_time,
        }


class CarrierSessionIdSource:
    """Resolve exactly one Jules session from the verified carrier run evidence."""

    def __init__(self, facts: Any, *, wait_seconds: int = 0, interval_seconds: int = 10,
                 sleep: Any = time.sleep, monotonic: Any = time.monotonic):
        self.facts = facts
        self.wait_seconds, self.interval_seconds = wait_seconds, interval_seconds
        self.sleep, self.monotonic = sleep, monotonic

    def __call__(self, command_id: str) -> str:
        # The carrier workflow finishes some time after the dispatch push. Waiting only re-reads GitHub (never Jules);
        # a completed run that did not succeed ends the wait at once, and the wait is bounded.
        deadline = self.monotonic() + self.wait_seconds
        while True:
            observation = self.facts.dispatch_observation(command_id)
            if isinstance(observation, dict) or self.monotonic() >= deadline:
                break
            self.sleep(self.interval_seconds)
        if not isinstance(observation, dict) or observation.get("conclusion") != "success":
            raise ProofError("CARRIER_SESSION_NOT_SINGLE")
        session_id = observation.get("session_id")
        if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
            raise ProofError("CARRIER_SESSION_NOT_SINGLE")
        return session_id


def build_live_proof_ports(
    *,
    repo_dir: str,
    policy: dict[str, Any],
    intent: dict[str, Any],
    jules_api_key: str,
    dispatches_used: int,
    scratch_dir: str,
    clock: Any | None = None,
    carrier_wait_seconds: int = 0,
) -> LiveProofPorts:
    """Construct the existing production adapters without performing any effect.

    Calling this function is STATIC construction only. Network/file/GitHub
    effects begin only later when a caller explicitly invokes the proof driver.
    """
    if not isinstance(dispatches_used, int) or isinstance(dispatches_used, bool) or dispatches_used < 0:
        raise ValueError("dispatches_used must be a non-negative integer")
    if not isinstance(policy, dict):
        raise ValueError("policy must be an object")
    default_branch = policy.get("default_branch")
    data_branch = policy.get("data_branch")
    repository = policy.get("target_repo")
    carrier_branch = policy.get("carrier_branch")
    targets = policy.get("allowed_target_branches")
    if not all(isinstance(v, str) and v for v in (default_branch, data_branch, repository, carrier_branch)):
        raise ValueError("policy is missing repository/branch fields")
    if data_branch == default_branch:
        raise ValueError("proof data branch must not be the default branch")
    if not isinstance(targets, list) or not targets or any(not isinstance(v, str) or not v for v in targets):
        raise ValueError("allowed_target_branches must be a non-empty string list")

    intent = validate_dispatch_intent(intent)
    request = intent["carrier_request"]
    if request.get("target_repo") != repository or request.get("target_branch") not in targets:
        raise ValueError("intent is outside the live proof policy")

    clock = clock or SystemClock()
    git = GitLiveClient(repo_dir)
    rest = GitHubRestReader(repository)
    owner_reader = LoopOwnerGitHubBackend(git, branch=data_branch)
    carrier_guard = CarrierQuietGuard(
        git=git,
        rest=rest,
        carrier_branch=carrier_branch,
        isolated_targets=tuple(targets),
        data_branch=data_branch,
    )
    dispatcher = ClaudeJulesDispatcher(
        client=git,
        refs=git,
        policy=policy,
        owner_reader=owner_reader,
        carrier_guard=carrier_guard,
    )
    facts = LiveResultFacts(git=git, rest=rest, policy=policy, scratch_dir=scratch_dir)
    session_source = CarrierSessionIdSource(facts, wait_seconds=carrier_wait_seconds)
    session_reader = StableLaneSessionReader(JulesActiveSessionGetReader(jules_api_key))
    collector = ControlTowerDurableCollector(
        git,
        ref=data_branch,
        target_reader=StableLaneTargetReader(rest, repository),
        clock=clock,
    )
    return LiveProofPorts(
        client=git,
        data_branch=data_branch,
        dispatcher=dispatcher,
        intent=intent,
        dispatches_used=dispatches_used,
        session_id_source=session_source,
        session_reader=session_reader,
        collector=collector,
        clock=clock,
    )
