"""Static, fail-closed orchestration boundary for Claude night loops.

This module prepares durable executor records only.  It never starts Claude,
Jules, a browser, a provider, or a GitHub write.  The two backends are
deliberately explicit: ``JULES_BACKEND`` delegates a prepared next prompt to
the existing Jules command path; ``CLAUDE_BACKEND`` describes a prepared
Claude-only coding step for the no-Jules contingency.  There is no fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Iterable

from .executor import make_executor_request
from .claude_admission_gate import (
    CONTAINER_INTERNAL, HOST_LOOPBACK,
    prepare_transport as prepare_admission_transport,
)


class BackendMode(str, Enum):
    JULES_BACKEND = "JULES_BACKEND"
    CLAUDE_BACKEND = "CLAUDE_BACKEND"


class VerdictDecision(str, Enum):
    CONTINUE = "CONTINUE"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GateResult:
    status: str
    reason: str


@dataclass(frozen=True)
class LoopResult:
    status: str
    reason: str
    request: dict[str, Any] | None = None


def validate_machine_gate(
    *,
    mode: str,
    loop_id: str,
    round: int,
    max_rounds: int,
    expected_target_head: str,
    observed_target_head: str,
    expected_target_tree: str,
    observed_target_tree: str,
    retry: int = 0,
    fallback: str = "disabled",
    merge_requested: bool = False,
    default_branch_write: bool = False,
    force_push: bool = False,
    destructive_delete: bool = False,
    live_model_requested: bool = False,
    external_send_requested: bool = False,
) -> GateResult:
    """Validate the common gate before any backend-specific preparation."""
    if mode not in {item.value for item in BackendMode}:
        return GateResult("BLOCKED", "unknown backend mode; explicit mode required")
    if not loop_id or not isinstance(round, int) or isinstance(round, bool) or round < 1:
        return GateResult("BLOCKED", "invalid loop identity or round")
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or not 1 <= max_rounds <= 6:
        return GateResult("BLOCKED", "max_rounds must be between 1 and 6")
    if round > max_rounds:
        return GateResult("BLOCKED", "loop cap reached")
    if not expected_target_head or expected_target_head != observed_target_head:
        return GateResult("BLOCKED", "fresh target head readback mismatch")
    if not expected_target_tree or expected_target_tree != observed_target_tree:
        return GateResult("BLOCKED", "fresh target tree readback mismatch")
    if retry != 0 or fallback != "disabled":
        return GateResult("BLOCKED", "unsafe retry/fallback policy")
    if any((merge_requested, default_branch_write, force_push, destructive_delete)):
        return GateResult("BLOCKED", "merge/default-branch/force-push/delete is prohibited")
    if live_model_requested or external_send_requested:
        return GateResult("BLOCKED", "live model or external send is not authorized")
    return GateResult("PASS", "common machine gate passed")


def make_structured_verdict(
    *,
    verdict_id: str,
    loop_id: str,
    round: int,
    correlation_id: str,
    mode: str,
    decision: str,
    expected_target_head: str,
    expected_target_tree: str,
    reasons: Iterable[str],
    evidence_refs: Iterable[str],
    next_prompt: str | None = None,
    terminal: bool = False,
) -> dict[str, Any]:
    """Create the provider-neutral structured verdict contract."""
    verdict = {
        "schema_version": 1,
        "verdict_id": verdict_id,
        "loop_id": loop_id,
        "round": round,
        "correlation_id": correlation_id,
        "backend_mode": mode,
        "decision": decision,
        "reasons": list(reasons),
        "next_prompt": next_prompt,
        "evidence_refs": list(evidence_refs),
        "expected_target_head": expected_target_head,
        "expected_target_tree": expected_target_tree,
        "terminal": terminal,
        "retry": 0,
        "fallback": "disabled",
        "execution_mode": "PREPARE_ONLY",
        "model_executed": False,
        "external_send_attempted": False,
    }
    _validate_verdict(verdict)
    return verdict


def prepare_next_action(
    verdict: dict[str, Any], *, expected_repo: str, expected_pr: int,
    expires_at: str, path_policy: Iterable[dict[str, Any]],
    existing_terminal_receipts: Iterable[dict[str, Any]] = (),
) -> LoopResult:
    """Turn one validated verdict into one durable prepare-only request."""
    try:
        _validate_verdict(verdict)
        receipts = list(existing_terminal_receipts)
        if any(
            isinstance(receipt, dict)
            and receipt.get("state") == "CONSUMED"
            and (receipt.get("loop_id"), receipt.get("round"), receipt.get("correlation_id"),
                 receipt.get("expected_target_head"), receipt.get("expected_target_tree"))
            == (verdict["loop_id"], verdict["round"], verdict["correlation_id"],
                verdict["expected_target_head"], verdict["expected_target_tree"])
            for receipt in receipts
        ):
            return LoopResult("NO-OP", "terminal receipt already exists")
        if verdict["decision"] != VerdictDecision.CONTINUE.value:
            return LoopResult("NO-OP", "verdict is terminal or non-actionable")
        prompt = verdict["next_prompt"]
        policies = list(path_policy)
        if not policies or any(
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str) or not item["path"]
            or not isinstance(item.get("allowed_ops"), list) or not item["allowed_ops"]
            for item in policies
        ):
            return LoopResult("BLOCKED", "explicit TREE_IDENTITY_V1 path policy required")
        is_jules = verdict["backend_mode"] == BackendMode.JULES_BACKEND.value
        kind = "jules-api" if is_jules else "claude"
        request = make_executor_request(
            request_id=f"exec-{verdict['verdict_id']}",
            loop_id=verdict["loop_id"], round=verdict["round"],
            correlation_id=verdict["correlation_id"],
            executor_role="implementation",
            executor_kind=kind,
            action=("PREPARE_JULES_API_REQUEST" if is_jules else "CLAUDE_SELF_LOOP_PREPARE_ONLY"),
            objective=prompt,
            input_refs=list(verdict["evidence_refs"]),
            evidence_refs=list(verdict["evidence_refs"]),
            allowed_actions=["prepare-only"],
            prohibited_actions=["live-model", "external-send", "merge", "default-branch-write", "force-push", "delete"],
            expected_repo=expected_repo, expected_pr=expected_pr,
            expected_target_head=verdict["expected_target_head"],
            expected_target_tree=verdict["expected_target_tree"],
            workspace_integrity_profile="TREE_IDENTITY_V1",
            requires_clean_workspace=True,
            path_policy=policies,
            expires_at=expires_at,
            execution_mode="PREPARE_ONLY",
            requires_live_model=False, requires_github_write=False,
            capability="prepare-only",
        )
        return LoopResult("PREPARED", "single prepare-only action created", request)
    except (KeyError, TypeError, ValueError) as exc:
        return LoopResult("UNKNOWN", str(exc))


def prepare_claude_transport(*, mode: str, dispatch_id: str, gate_base_url: str,
                             transport_mode: str = HOST_LOOPBACK,
                             live_model: bool = False, external_send: bool = False) -> dict[str, Any]:
    """Attach a static gate environment contract to a Claude-role preparation.

    This is only a preflight description. It cannot start a process or contact
    either the gate or a model provider.
    """
    if mode != BackendMode.CLAUDE_BACKEND.value:
        return {"status": "BLOCKED", "reason": "Claude gate transport requires CLAUDE_BACKEND"}
    return prepare_admission_transport(dispatch_id=dispatch_id, gate_base_url=gate_base_url,
                                       transport_mode=transport_mode,
                                       retry=0, fallback="disabled", live_model=live_model,
                                       external_send=external_send)


def _validate_verdict(verdict: dict[str, Any]) -> None:
    required = {
        "schema_version", "verdict_id", "loop_id", "round", "correlation_id",
        "backend_mode", "decision", "reasons", "next_prompt", "evidence_refs",
        "expected_target_head", "expected_target_tree", "terminal", "retry",
        "fallback", "execution_mode", "model_executed", "external_send_attempted",
    }
    if not isinstance(verdict, dict) or set(verdict) != required:
        raise ValueError("invalid structured verdict")
    if verdict["schema_version"] != 1:
        raise ValueError("unsupported verdict schema")
    if verdict["backend_mode"] not in {item.value for item in BackendMode}:
        raise ValueError("invalid verdict backend mode")
    if verdict["decision"] not in {item.value for item in VerdictDecision}:
        raise ValueError("invalid verdict decision")
    if not all(isinstance(verdict[key], str) and verdict[key] for key in (
        "verdict_id", "loop_id", "correlation_id", "expected_target_head", "expected_target_tree"
    )):
        raise ValueError("invalid verdict identity")
    for key in ("expected_target_head", "expected_target_tree"):
        if not re.fullmatch(r"[0-9a-f]{40}", verdict[key]):
            raise ValueError(f"invalid {key}")
    if isinstance(verdict["round"], bool) or not isinstance(verdict["round"], int) or not 1 <= verdict["round"] <= 6:
        raise ValueError("invalid verdict round")
    for key in ("reasons", "evidence_refs"):
        if not isinstance(verdict[key], list) or any(not isinstance(item, str) or not item for item in verdict[key]):
            raise ValueError(f"invalid verdict {key}")
    if verdict["decision"] == VerdictDecision.CONTINUE.value:
        if not isinstance(verdict["next_prompt"], str) or not verdict["next_prompt"].strip():
            raise ValueError("continue verdict requires non-empty next_prompt")
        if verdict["terminal"] is not False:
            raise ValueError("continue verdict must be non-terminal")
    else:
        if verdict["next_prompt"] is not None:
            raise ValueError("terminal verdict must not carry next_prompt")
        if verdict["terminal"] is not True:
            raise ValueError("non-continue verdict must be terminal")
    if verdict["retry"] != 0 or verdict["fallback"] != "disabled":
        raise ValueError("unsafe verdict policy")
    if verdict["execution_mode"] != "PREPARE_ONLY" or verdict["model_executed"] is not False or verdict["external_send_attempted"] is not False:
        raise ValueError("live verdict is not authorized")
