"""Operator entry point for the ONE bounded Claude -> Jules stable-lane proof.

``plan`` and ``check`` have no side effect beyond reading GitHub. ``run`` is the irreversible step: it needs an
explicitly authorized unexpired plan, the Jules key in ``JULES_API_KEY``, and the typed confirmation
``CLAUDE_JULES_PROOF_CONFIRM=RUN_ONCE_<plan_sha256>``. It performs one dispatch and one Jules GET, never retries, and
leaves a once-only terminal receipt on the data branch. It never writes main, the production registry or Issue #33.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

from .claude_jules_autoloop import ClaudeJulesAutoLoop, StepResult
from .claude_jules_dispatch import validate_policy
from .claude_jules_lane_proof import (
    LANE_ID, LOOP_A_SLOTS_USED_BEFORE, ProofError, build_proof_plan, run_stable_lane_proof,
    validate_proof_plan,
)
from .claude_jules_lane_proof_launcher import build_live_proof_ports
from .claude_jules_live import CarrierQuietGuard, LiveResultFacts
from .claude_jules_live_adapter import GitHubRestReader, GitLiveClient
from .claude_jules_live_budget import LiveBudgetLedger
from .loop_owner_backend import LoopOwnerGitHubBackend

# Sessions of every earlier LIVE run: never read or reused by this proof.
OLD_SESSION_IDS = [
    "301196275118188780", "5943440322658150300", "11944164406087664763", "569271609782168660", "7218641455365522473",
]
REGISTRY_PATH = "automation/command_bus/config/control_tower_registry.json"
CARRIER_WAIT_SECONDS = 15 * 60


class ZuluClock:
    """UTC clock in the ``...Z`` form the proof plan requires (never the +00:00 form)."""

    def now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PrepareOnlyLoop(ClaudeJulesAutoLoop):
    """The real planner, but the dispatch is captured instead of sent: the proof driver does the one dispatch."""

    captured: dict[str, Any] | None = None

    def _dispatch(self, intent: dict[str, Any], *, now: str, resumed: bool) -> StepResult:
        self.captured = intent
        return StepResult("PREPARED", "PREPARED", "dispatch intent captured; nothing sent")


def proposed_registry_for(current: dict[str, Any]) -> dict[str, Any]:
    proposed = copy.deepcopy(current)
    for row in proposed["loops"]:
        if row["loop_id"] == LANE_ID:
            row["identity_state"] = "DURABLE"
    return proposed


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _zulu_plus(now: str, delta: timedelta) -> str:
    return (datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ") + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def command_plan(args: argparse.Namespace, clock: Any) -> dict[str, Any]:
    policy = validate_policy(_load(args.policy))
    git = GitLiveClient(args.repo_dir)
    target = policy["allowed_target_branches"][0]
    head = git.get_branch_head(target)
    tree = git.get_commit_tree(head) if head else None
    if head is None or tree is None or len(policy["allowed_target_branches"]) != 1:
        raise ProofError("TARGET_SNAPSHOT_UNAVAILABLE")
    now = clock.now()
    authorization = None
    if args.authorized_by:
        expires = _zulu_plus(now, timedelta(minutes=args.valid_minutes))
        authorization = {"approved_by": args.authorized_by, "approval_ref": args.approval_ref,
                         "scope": "claude-jules-auto bounded LIVE proof x1", "max_dispatches": 1, "expires_at": expires}
    return build_proof_plan(
        origin_loop_id=args.origin_loop_id, origin_generation=args.origin_generation,
        repository=policy["target_repo"], default_branch=policy["default_branch"], target_branch=target,
        target_pr=policy["expected_pr"], target_head=head, target_tree=tree, allowed_path=args.allowed_path,
        allowed_content=args.allowed_content, expires_at=_zulu_plus(now, timedelta(minutes=args.valid_minutes)),
        forbidden_session_ids=OLD_SESSION_IDS, live_authorization=authorization)


def _registries(repo_dir: str) -> tuple[dict[str, Any], dict[str, Any]]:
    current = _load(os.path.join(repo_dir, REGISTRY_PATH))
    return current, proposed_registry_for(current)


def command_check(args: argparse.Namespace, clock: Any) -> dict[str, Any]:
    plan, (current, _) = _load(args.plan), _registries(args.repo_dir)
    validate_proof_plan(plan, registry=current, now=clock.now(), require_authorized=True)
    return {"plan_sha256": plan["plan_sha256"], "ok": True, "confirm_text": f"RUN_ONCE_{plan['plan_sha256']}"}


def command_run(args: argparse.Namespace, clock: Any) -> dict[str, Any]:
    plan, policy, roadmap = _load(args.plan), validate_policy(_load(args.policy)), _load(args.roadmap)
    current, proposed = _registries(args.repo_dir)
    validate_proof_plan(plan, registry=current, now=clock.now(), require_authorized=True)
    if os.environ.get("CLAUDE_JULES_PROOF_CONFIRM") != f"RUN_ONCE_{plan['plan_sha256']}":
        raise ProofError("CONFIRMATION_MISSING")
    key = os.environ.get("JULES_API_KEY", "")
    if not key:
        raise ProofError("JULES_KEY_MISSING")
    git, rest = GitLiveClient(args.repo_dir, message_trailer=args.trailer), GitHubRestReader(policy["target_repo"])
    used = len(LiveBudgetLedger(git, data_branch=policy["data_branch"]).slots())
    if used != LOOP_A_SLOTS_USED_BEFORE:
        raise ProofError("BUDGET_COUNT_UNEXPECTED", f"{used} slots used, expected {LOOP_A_SLOTS_USED_BEFORE}")
    scratch = os.path.join(tempfile.gettempdir(), "claude-jules-lane-proof")
    loop = PrepareOnlyLoop(
        client=git, refs=git, policy=policy, owner_reader=LoopOwnerGitHubBackend(git, branch=policy["data_branch"]),
        roadmap=roadmap, facts=LiveResultFacts(git=git, rest=rest, policy=policy, scratch_dir=scratch),
        origin_loop_id=plan["origin_loop_id"], lane_id=args.lane_id,
        carrier_guard=CarrierQuietGuard(git=git, rest=rest, carrier_branch=policy["carrier_branch"],
                                        isolated_targets=tuple(policy["allowed_target_branches"]),
                                        data_branch=policy["data_branch"]))
    prepared = loop.step(now=clock.now())
    intent = loop.captured
    if prepared.status != "PREPARED" or intent is None:
        raise ProofError("INTENT_NOT_PREPARED", f"{prepared.status}: {prepared.reason}")
    request = intent["carrier_request"]
    # The plan binds the exact target snapshot; refuse BEFORE the irreversible dispatch if the target moved.
    if (request.get("target_branch"), intent["origin_loop_id"], intent["origin_generation"]) != (
            plan["target_branch"], plan["origin_loop_id"], plan["origin_generation"]):
        raise ProofError("INTENT_DOES_NOT_MATCH_PLAN")
    if git.get_branch_head(plan["target_branch"]) != plan["target_head"]:
        raise ProofError("TARGET_MOVED_SINCE_PLAN")
    ports = build_live_proof_ports(
        repo_dir=args.repo_dir, policy=policy, intent=intent, jules_api_key=key, dispatches_used=used,
        scratch_dir=scratch, clock=clock, carrier_wait_seconds=CARRIER_WAIT_SECONDS)
    run = run_stable_lane_proof(plan, current_registry=current, proposed_registry=proposed, ports=ports,
                                request=None)
    return {"status": run.status, "code": run.code, "counters": run.counters, "receipt": run.receipt,
            "candidate": run.candidate}


def main(argv: list[str] | None = None, clock: Any | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude_jules_lane_proof_cli")
    parser.add_argument("command", choices=["plan", "check", "run"])
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--policy")
    parser.add_argument("--roadmap")
    parser.add_argument("--plan")
    parser.add_argument("--origin-loop-id")
    parser.add_argument("--origin-generation", type=int)
    parser.add_argument("--lane-id")
    parser.add_argument("--allowed-path", default="docs/CLAUDE_JULES_STABLE_LANE_PROOF_NOTE.md")
    parser.add_argument("--allowed-content", default="docs-only live-proof marker note")
    parser.add_argument("--authorized-by", default="")
    parser.add_argument("--approval-ref", default="")
    parser.add_argument("--valid-minutes", type=int, default=120)
    parser.add_argument("--trailer", default="")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    clock = clock or ZuluClock()
    try:
        result = {"plan": command_plan, "check": command_check, "run": command_run}[args.command](args, clock)
    except ProofError as exc:  # a refusal is a clean, secret-free stop
        print(json.dumps({"status": "REFUSED", "code": exc.code, "detail": str(exc)}, ensure_ascii=False))
        return 2
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0 if result.get("status", "OK") in {"OK", "COMPLETE"} or args.command != "run" else 1


if __name__ == "__main__":
    sys.exit(main())
