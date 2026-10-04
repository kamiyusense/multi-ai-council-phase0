"""Post-adoption verification of the chatgpt-semi-auto DURABLE lane (offline, read-only).

Rebuilds the strict SF-8 gate from committed evidence instead of trusting the fact that the registry now
says DURABLE. Inputs are files in the repository plus one small dict of GitHub facts that a human or the
thread read back (``fresh``: target PR, Jules output PR, adoption run, Issue #33). This module reads no
network, calls no provider, writes nothing to GitHub and never touches the registry or Issue #33.

Honest scope notes (kept in the report, not hidden):

* ``registration_ready`` is identity/registration readiness. After the owner lease of proof 5 expired the
  durable projection is BLOCKED ("owner lease is expired"); the lane stays registrable, and it is not a
  liveness claim.
* The Jules output PR #286 keeps the recorded DEVIATION. Authentication success and exact-output
  conformity are separate facts.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import durable_adoption_approval as dap
from . import durable_adoption_approval_cli as cli
from . import signal_step7_live_proof as live
from .control_tower_durable_collector import ControlTowerDurableCollector
from .control_tower_registration import assess_lane_registration_readiness, assess_registration_readiness
from .github_backend import GitHubContent
from .lane_identity_adoption import registry_digest
from .sf8_readiness import CheckResult, REQUIRED_CHECKS, assess_durable_promotion_candidate, issue33_migration_ready

LANE = dap.LANE_ID
P5 = "docs/evidence/signal-step7-proof5"
CHAIN = f"{P5}/durable-chain"
APPROVAL = f"{P5}/durable-adoption-approval.json"
PRE_ADOPTION_DIGEST = "6af0268e17fd99adf4901e6a3be294c7e24c3b38241281a7b4cb0571b36b5eb0"
STATIC_TEST_REFS = {
    "negative_stale_mismatch_tests": "automation/command_bus/tests/test_durable_adoption_approval.py",
    "recovery_test": "automation/command_bus/tests/test_signal_step7_auto_publish.py",
}
_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|\+00:00)")


class _DirClient:
    """GitHubContentsClient over the committed durable-chain copy (read only)."""

    def __init__(self, root: Path):
        self.base = root / CHAIN

    def get(self, path: str, ref: str) -> GitHubContent | None:
        file = self.base / path
        return GitHubContent(path, file.read_text(encoding="utf-8"), "0" * 40) if file.is_file() else None

    def list(self, prefix: str, ref: str) -> list[GitHubContent]:
        folder = self.base / prefix
        if not folder.is_dir():
            return []
        return [GitHubContent(f"{prefix}{item.name}", item.read_text(encoding="utf-8"), "0" * 40)
                for item in sorted(folder.iterdir()) if item.is_file()]

    def create(self, *a: Any, **k: Any) -> Any:
        raise RuntimeError("read-only client")

    update = create


class _Target:
    def __init__(self, fresh_pr: dict[str, Any], repo: str):
        self.fresh_pr, self.repo = fresh_pr, repo

    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None:
        if self.fresh_pr.get("number") != pr_number or repository != self.repo:
            return None
        return {"repo": repository, "pr": pr_number, "head": self.fresh_pr.get("head_sha"),
                "state": self.fresh_pr.get("state"), "merged": self.fresh_pr.get("merged")}


class _Clock:
    def __init__(self, now: str):
        self.value = now

    def now(self) -> str:
        return self.value


def _load(root: Path, rel: str) -> Any:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _item(number: int, name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"n": number, "name": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def _iso(value: str) -> str:
    if not isinstance(value, str) or not _TS.fullmatch(value):
        raise ValueError("timestamp must be UTC ISO-8601")
    return value[:-1] + "+00:00" if value.endswith("Z") else value


def _collect(root: Path, fresh: dict[str, Any], now: str):
    collector = ControlTowerDurableCollector(
        _DirClient(root), ref="committed", target_reader=_Target(fresh["pr278"], live.REPOSITORY), clock=_Clock(now))
    return collector.collect_transition(LANE)


def verify(root: Path, fresh: dict[str, Any], now: str) -> dict[str, Any]:
    """Return the machine-readable post-adoption checkpoint. Pure given (files, fresh, now)."""
    now = _iso(now)
    production = _load(root, cli.REGISTRY_PATH)
    approval = _load(root, APPROVAL)
    receipt = _load(root, f"{P5}/live-terminal-receipt.json")
    evidence = _load(root, f"{P5}/live-proof-evidence.json")
    readback = _load(root, f"{P5}/jules-output-github-readback.json")
    candidate = _load(root, f"{P5}/adoption-candidate.json")
    items: list[dict[str, Any]] = []
    add = lambda n, name, ok, detail: items.append(_item(n, name, bool(ok), detail))

    entries = {e["loop_id"]: e["identity_state"] for e in production["loops"]}
    durable = [k for k, v in entries.items() if v == "DURABLE"]
    add(1, "registry_fresh_readback", True, f"digest {registry_digest(production)}")
    add(2, "exactly_one_durable_lane", len(durable) == 1, f"durable={durable}")
    add(3, "durable_lane_is_chatgpt_semi_auto", durable == [LANE], f"durable={durable}")
    others = {k: v for k, v in entries.items() if k != LANE}
    add(4, "other_lanes_placeholder_or_disabled_frozen", len(others) >= 1 and set(others.values()) <= {"PLACEHOLDER", "FROZEN"}
        and not cli.production_registry_guard(production, root), json.dumps(others, sort_keys=True))

    try:
        verified_lane = cli.verify_file(root / APPROVAL, root, approval["approved_at"])
        approval_ok, approval_detail = verified_lane == LANE, "valid as of its own issue time"
    except Exception as exc:  # fail closed with the code, never a trace
        approval_ok, approval_detail = False, f"{type(exc).__name__}:{getattr(exc, 'code', '')}"
    add(5, "committed_adoption_approval_valid", approval_ok, approval_detail)
    run = fresh["approval_run"]
    add(6, "approval_run_id", approval["approval_ref"] == f"github-actions:run/{run.get('id')}" and str(run.get("id")) == "37155730052",
        approval["approval_ref"])
    add(7, "approval_actor_and_triggering_actor", str(approval["approved_by_actor_id"]) == live.OWNER_ACTOR_ID
        and str(run.get("actor_id")) == live.OWNER_ACTOR_ID and str(run.get("triggering_actor_id")) == live.OWNER_ACTOR_ID,
        f"approval={approval['approved_by_actor_id']} run_actor={run.get('actor_id')} triggering={run.get('triggering_actor_id')}")
    add(8, "approval_attempt_one", approval["approval_run_attempt"] == 1 and run.get("run_attempt") == 1
        and run.get("conclusion") == "success" and run.get("event") == "workflow_dispatch" and run.get("head_branch") == "main",
        f"attempt={run.get('run_attempt')} conclusion={run.get('conclusion')}")
    add(9, "proof5_terminal_receipt_digest", approval["terminal_receipt_sha256"] == receipt.get("receipt_payload_sha256")
        and receipt.get("status") == "COMPLETE", approval["terminal_receipt_sha256"])
    add(10, "proof5_evidence_digest", approval["evidence_payload_sha256"] == evidence.get("evidence_payload_sha256")
        and receipt.get("evidence_payload_sha256") == evidence.get("evidence_payload_sha256"), approval["evidence_payload_sha256"])
    try:
        current_registry, proposed_registry = cli.registries_from_candidate(root)
    except cli.Stop:  # the production registry is no longer the committed candidate: fail closed, never raise
        current_registry = proposed_registry = None
    add(11, "approved_current_registry_digest", current_registry is not None
        and approval["current_registry_sha256"] == registry_digest(current_registry) == PRE_ADOPTION_DIGEST,
        approval["current_registry_sha256"])
    add(12, "approved_proposed_registry_digest", proposed_registry is not None
        and approval["proposed_registry_sha256"] == registry_digest(proposed_registry), approval["proposed_registry_sha256"])
    guard = cli.production_registry_guard(production, root)
    add(13, "adopted_row_equals_approved_entry_except_display_name", not guard,
        f"guard failures={guard}; production digest {registry_digest(production)}")
    try:
        if current_registry is None:
            raise dap.ApprovalError("REGISTRY_NOT_THE_CANDIDATE")
        dap.check_single_lane_diff(current_registry, proposed_registry, LANE)
        diff_ok = True
    except dap.ApprovalError:
        diff_ok = False
    add(14, "exact_one_lane_diff", diff_ok, "approved diff is only chatgpt-semi-auto.identity_state PLACEHOLDER->DURABLE")
    pr278 = fresh["pr278"]
    add(15, "proof5_target_head_tree", pr278.get("head_sha") == evidence.get("target_head") == candidate["proof"]["target_head"]
        and evidence.get("target_tree") == candidate["proof"]["target_tree"] and pr278.get("number") == evidence.get("target_pr")
        and pr278.get("state") == "open" and pr278.get("merged") is False,
        f"head={pr278.get('head_sha')} state={pr278.get('state')}")
    add(16, "provider_evidence", evidence.get("scope") == "LIVE" and evidence.get("provider_raw_state") == "IN_PROGRESS"
        and evidence.get("canonical_runtime_state") == "RUNNING" and bool(evidence.get("session_id"))
        and evidence.get("counters", {}).get("whole_proof_total") == {"authority_dispatch": 0, "jules_get": 2, "jules_post": 1},
        f"session={evidence.get('session_id')} raw={evidence.get('provider_raw_state')}")
    add(17, "owner_authority_evidence", bool(evidence.get("authority_evidence_sha256")) and str(evidence.get("authority_run_id")) == "37150285702"
        and str(evidence.get("authority_run_id")) != str(run.get("id")), f"authority_run={evidence.get('authority_run_id')}")

    state = _load(root, f"{CHAIN}/automation/command_bus/state/{LANE}.json")
    add(18, "runtime_transition_published", state.get("loop_id") == LANE and state.get("state") == evidence.get("canonical_runtime_state")
        and state.get("last_receipt_id") == f"dispatch-{dap.LOOP_COMMAND_ID}"
        and state.get("expected_target", {}).get("head") == pr278.get("head_sha"), f"state={state.get('state')}")
    proof_time = _iso(evidence["observed_at"])
    at_proof = _collect(root, fresh, proof_time)
    at_now = _collect(root, fresh, now)
    add(19, "collector_result", at_proof.status == "COLLECTED" and at_now.status == "COLLECTED"
        and at_proof.transition is not None and at_proof.transition.status == "VALID",
        f"as_of_proof={at_proof.status}/{at_proof.transition.status if at_proof.transition else None} at_now={at_now.status}")
    lane_proof = assess_lane_registration_readiness(production, LANE, at_proof.transition)
    lane_now = assess_lane_registration_readiness(production, LANE, at_now.transition)
    add(20, "lane_scoped_registration", lane_proof.status == "READY" and lane_now.status == "READY" and lane_now.ready_loop_ids == (LANE,),
        f"as_of_proof={lane_proof.status} at_now={lane_now.status}")
    global_ready = assess_registration_readiness(production, {LANE: at_now.transition} if at_now.transition else None)
    migration = issue33_migration_ready(global_ready.status)

    def result(name: str, ok: bool, ref: str, scope: str = "LIVE") -> CheckResult:
        return CheckResult("PASS" if ok else "FAIL", scope, ref)

    live_ref = f"{P5}/live-proof-evidence.json"
    live_ok = evidence.get("scope") == "LIVE" and receipt.get("status") == "COMPLETE"
    checks = {
        "stable_identity": result("stable_identity", live_ok and durable == [LANE] and approval_ok and state.get("loop_id") == LANE
                                  and evidence.get("lane_id") == LANE, live_ref),
        "prepared_persistence": result("prepared_persistence", live_ok and (root / P5 / "plan.bound.json").is_file()
                                       and candidate["proof"]["plan_sha256"] == live.plan_digest(_load(root, f"{P5}/plan.bound.json")),
                                       f"{P5}/plan.bound.json"),
        "canonical_receipt": result("canonical_receipt", live_ok and items[8]["status"] == "PASS" and receipt.get("rerun_allowed") is False,
                                    f"{P5}/live-terminal-receipt.json"),
        "provider_authentication": result("provider_authentication", live_ok and items[15]["status"] == "PASS"
                                          and str(evidence.get("provider_oidc_run_id")) == str(live.PROVIDER_OIDC_RUN_ID), live_ref),
        "owner_authority_authentication": result("owner_authority_authentication", live_ok and items[16]["status"] == "PASS", live_ref),
        "publisher_accepted": result("publisher_accepted", live_ok and items[17]["status"] == "PASS", live_ref),
        "collector_readback": result("collector_readback", live_ok and items[18]["status"] == "PASS", f"{CHAIN}/automation/command_bus/state/{LANE}.json"),
        "registration_ready": result("registration_ready", items[19]["status"] == "PASS", live_ref),
        "negative_stale_mismatch_tests": result("negative_stale_mismatch_tests", (root / STATIC_TEST_REFS["negative_stale_mismatch_tests"]).is_file(),
                                                STATIC_TEST_REFS["negative_stale_mismatch_tests"], "STATIC"),
        "recovery_test": result("recovery_test", (root / STATIC_TEST_REFS["recovery_test"]).is_file(),
                                STATIC_TEST_REFS["recovery_test"], "STATIC"),
    }
    gate = assess_durable_promotion_candidate(checks)
    add(21, "strict_sf8_post_adoption_gate", gate.status == "READY" and tuple(checks) == REQUIRED_CHECKS,
        f"{gate.status}; reasons={list(gate.reasons)}")
    add(22, "global_registration_not_wired", global_ready.status == "NOT_WIRED"
        and global_ready.placeholder_loop_ids == ("chat-work-semi-auto", "claude-jules-auto", "work-jules-auto") and migration == "NO",
        f"{global_ready.status}; issue33_migration_ready={migration}")
    issue = fresh["issue33"]
    add(23, "issue33_unchanged", issue.get("state") == "open" and issue.get("title_has_stopped") is True and issue.get("owner_none") is True
        and issue.get("updated_at") == "2026-10-02T09:35:13Z", f"updated_at={issue.get('updated_at')}")
    pr286 = fresh["pr286"]
    out = readback["output"]
    add(24, "jules_output_pr_286_unmerged_unchanged", pr286.get("merged") is False and pr286.get("state") == "open"
        and pr286.get("head_sha") == out.get("head_sha") == "847bc6a45b1eea873cf53d370e916de5f4a1d04f",
        f"head={pr286.get('head_sha')} merged={pr286.get('merged')}")
    classified = dap.classify_output(out, evidence)
    add(25, "recorded_deviation_unchanged", classified == (dap.OUTPUT_DEVIATION, dap.DEVIATION_MISSING_NEWLINE)
        and approval["accepted_deviation"] == dap.DEVIATION_MISSING_NEWLINE and readback.get("output_blob_bytes") == 21
        and readback.get("expected_content_bytes") == 22, f"{classified}")

    failed = [i["name"] for i in items if i["status"] != "PASS"]
    return {
        "schema_version": 1, "checkpoint_kind": "SIGNAL_SF9_POST_ADOPTION_CHECKPOINT", "lane_id": LANE, "now": now,
        "status": "PASS" if not failed else "FAIL", "failed_items": failed, "items": items,
        "required_checks": {name: {"status": r.status, "scope": r.scope, "evidence_ref": r.evidence_ref} for name, r in checks.items()},
        "strict_gate": gate.status, "lane_registration": {"as_of_proof": lane_proof.status, "at_now": lane_now.status},
        "durable_projection": {
            "as_of_proof": {"transition": at_proof.transition.status if at_proof.transition else None,
                            "display_state": at_proof.transition.projection.display_state if at_proof.transition and at_proof.transition.projection else None},
            "at_now": {"transition": at_now.transition.status if at_now.transition else None,
                       "display_state": at_now.transition.projection.display_state if at_now.transition and at_now.transition.projection else None,
                       "reason": at_now.transition.reason if at_now.transition else None},
            "note": "BLOCKED after the proof 5 owner lease expired; registration readiness is identity, not liveness"},
        "global_registration": global_ready.status, "issue33_migration_ready": migration,
        "fresh_github_facts": copy.deepcopy(fresh),
        "safety": {"new_jules_post": 0, "new_jules_get": 0, "provider_calls": 0, "workflow_dispatch": 0,
                   "registry_written": False, "issue33_written": False, "retry": 0, "fallback": "disabled"},
    }


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--write")
    args = parser.parse_args(argv)
    root = root or Path(__file__).resolve().parents[2]
    report = verify(root, json.loads(Path(args.fresh).read_text(encoding="utf-8")), args.now)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.write:
        out = Path(args.write)
        if out.exists():
            print(json.dumps({"status": "STOPPED", "code": "OUTPUT_ALREADY_EXISTS"}))
            return 1
        out.write_text(text, encoding="utf-8")
    print(json.dumps({"status": report["status"], "failed": report["failed_items"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
