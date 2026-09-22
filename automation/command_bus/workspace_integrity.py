"""Provider-neutral executor workspace integrity gates.

TREE_IDENTITY_V1 proves that a mutable executor starts from the canonical
target tree, not merely from a commit whose name matches the expected HEAD.
The module is pure validation logic: it never repairs a workspace, runs a
provider, mutates GitHub, or retries an ambiguous write.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from typing import Any, Iterable


PROFILE = "TREE_IDENTITY_V1"
ALLOWED_OPS = frozenset({"ADD", "MODIFY", "DELETE", "RENAME"})
TERMINAL_MUTATION_BLOCK = frozenset({"BLOCKED", "UNKNOWN", "RECREATE_REQUIRED"})


@dataclass(frozen=True)
class IntegrityResult:
    status: str
    reasons: tuple[str, ...]
    evidence: dict[str, Any]


@dataclass(frozen=True)
class MutationLease:
    lease_id: str
    expected_target_head: str
    expected_target_tree: str
    executor_instance_id: str
    executor_generation: int
    path_policy: tuple[dict[str, Any], ...]
    issued_at: datetime
    expires_at: datetime
    workspace_attestation_id: str


@dataclass(frozen=True)
class CommitAttestation:
    status: str
    reasons: tuple[str, ...]
    commit_sha: str | None
    parent_sha: str | None
    commit_tree: str | None
    changed: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]


_REQUIRED_EXPECTED = {
    "repo_full_name",
    "target_pr",
    "target_branch",
    "expected_target_head",
    "expected_target_tree",
    "remote_name",
    "remote_url",
}
_REQUIRED_OBSERVED = {
    "repo_full_name",
    "target_pr",
    "target_branch",
    "workspace_path",
    "git_toplevel",
    "remote_name",
    "remote_url",
    "observed_head",
    "observed_head_tree",
    "observed_index_tree",
    "tracked_worktree_diff_empty",
    "cached_diff_empty",
    "untracked_paths",
    "skip_worktree_paths",
    "assume_unchanged_paths",
    "sparse_checkout_state",
    "unmerged_paths",
    "submodule_state",
    "status_porcelain_v2",
    "executor_instance_id",
    "executor_generation",
    "workspace_attestation_id",
}


def attest_workspace(
    expected: dict[str, Any],
    observed: dict[str, Any],
    *,
    workspace_kind: str = "persistent",
) -> IntegrityResult:
    """Validate commit/index/worktree identity before the first mutation."""
    missing_expected = sorted(_REQUIRED_EXPECTED - expected.keys())
    missing_observed = sorted(_REQUIRED_OBSERVED - observed.keys())
    if missing_expected or missing_observed:
        return IntegrityResult(
            "UNKNOWN",
            tuple(
                [f"missing expected field: {x}" for x in missing_expected]
                + [f"missing observed field: {x}" for x in missing_observed]
            ),
            _evidence(expected, observed, workspace_kind, "NO_MUTATION"),
        )

    reasons: list[str] = []
    for key in ("repo_full_name", "target_pr", "target_branch", "remote_name", "remote_url"):
        if observed.get(key) != expected.get(key):
            reasons.append(f"{key} mismatch")

    if observed["workspace_path"] != observed["git_toplevel"]:
        reasons.append("workspace path is not git toplevel")
    if observed["observed_head"] != expected["expected_target_head"]:
        reasons.append("HEAD mismatch")
    if observed["observed_head_tree"] != expected["expected_target_tree"]:
        reasons.append("HEAD tree mismatch")
    if observed["observed_index_tree"] != expected["expected_target_tree"]:
        reasons.append("index tree mismatch")
    if observed["tracked_worktree_diff_empty"] is not True:
        reasons.append("tracked working tree differs from index/HEAD")
    if observed["cached_diff_empty"] is not True:
        reasons.append("cached/index diff is not empty")
    if observed["unmerged_paths"]:
        reasons.append("unmerged entries present")

    allowed_untracked = set(expected.get("allowed_untracked_paths", []))
    unexpected_untracked = sorted(
        path for path in observed["untracked_paths"] if path not in allowed_untracked
    )
    if unexpected_untracked:
        reasons.append("unexpected untracked paths")

    if observed["skip_worktree_paths"]:
        reasons.append("skip-worktree paths present")
    if observed["assume_unchanged_paths"]:
        reasons.append("assume-unchanged paths present")
    if observed["sparse_checkout_state"] not in {False, "disabled", "DISABLED", None}:
        reasons.append("sparse checkout is not authorized by TREE_IDENTITY_V1")
    if observed["submodule_state"] not in {"ABSENT", None}:
        reasons.append("submodules are not supported by TREE_IDENTITY_V1")

    for key in (
        "tracked_worktree_diff_empty",
        "cached_diff_empty",
        "untracked_paths",
        "skip_worktree_paths",
        "assume_unchanged_paths",
        "unmerged_paths",
    ):
        if observed.get(key) is None:
            return IntegrityResult(
                "UNKNOWN",
                (f"{key} could not be verified",),
                _evidence(expected, observed, workspace_kind, "NO_MUTATION"),
            )

    if reasons:
        status = "RECREATE_REQUIRED" if workspace_kind == "disposable" else "BLOCKED"
        disposition = (
            "RECREATE_NEW_WORKSPACE"
            if workspace_kind == "disposable"
            else "QUARANTINE_PERSISTENT_WORKSPACE"
        )
        return IntegrityResult(
            status, tuple(reasons), _evidence(expected, observed, workspace_kind, disposition)
        )

    evidence = _evidence(expected, observed, workspace_kind, "MUTATION_GATE_PASS")
    evidence.update({
        "expected_target_head": expected["expected_target_head"],
        "expected_target_tree": expected["expected_target_tree"],
        "observed_head": observed["observed_head"],
        "observed_head_tree": observed["observed_head_tree"],
        "observed_index_tree": observed["observed_index_tree"],
        "unexpected_untracked_paths": [],
        "mutation_started": False,
    })
    return IntegrityResult("PASS", (), evidence)


def issue_mutation_lease(
    attestation: IntegrityResult,
    *,
    lease_id: str,
    path_policy: Iterable[dict[str, Any]],
    now: datetime | None = None,
    ttl_seconds: int = 900,
) -> tuple[IntegrityResult, MutationLease | None]:
    if attestation.status != "PASS":
        return IntegrityResult(
            "BLOCKED",
            ("workspace attestation did not pass",),
            {"mutation_started": False, "retry_count": 0, "fallback_used": False},
        ), None
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
        return IntegrityResult("UNKNOWN", ("invalid mutation lease ttl",), {}), None
    policies = tuple(_normalize_policy(path_policy))
    if not policies:
        return IntegrityResult("BLOCKED", ("path policy is required",), {}), None

    evidence = attestation.evidence
    issued = now or datetime.now(timezone.utc)
    lease = MutationLease(
        lease_id=lease_id,
        expected_target_head=evidence["expected_target_head"],
        expected_target_tree=evidence["expected_target_tree"],
        executor_instance_id=evidence["executor_instance_id"],
        executor_generation=evidence["executor_generation"],
        path_policy=policies,
        issued_at=issued,
        expires_at=issued + timedelta(seconds=ttl_seconds),
        workspace_attestation_id=evidence["workspace_attestation_id"],
    )
    return IntegrityResult(
        "PASS", (), {
            "lease_id": lease_id,
            "mutation_started": False,
            "retry_count": 0,
            "fallback_used": False,
        }
    ), lease


def validate_precommit(
    lease: MutationLease,
    candidate: dict[str, Any],
    current_target: dict[str, Any],
    *,
    now: datetime | None = None,
) -> IntegrityResult:
    at = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    if at >= lease.expires_at:
        reasons.append("mutation lease expired")
    if current_target.get("head") != lease.expected_target_head:
        reasons.append("target head moved")
    if current_target.get("tree") != lease.expected_target_tree:
        reasons.append("target tree moved")
    if candidate.get("baseline_head") != lease.expected_target_head:
        reasons.append("candidate baseline head mismatch")
    if candidate.get("baseline_tree") != lease.expected_target_tree:
        reasons.append("candidate baseline tree mismatch")
    if not candidate.get("candidate_index_tree"):
        reasons.append("candidate index tree missing")
    if candidate.get("tests_pass") is not True:
        reasons.append("tests not proven PASS")
    if candidate.get("compile_pass") is not True:
        reasons.append("compile/static checks not proven PASS")
    if candidate.get("diff_check_pass") is not True:
        reasons.append("diff check not proven PASS")

    op_result = validate_operations(candidate.get("changes"), lease.path_policy)
    if op_result.status != "PASS":
        reasons.extend(op_result.reasons)

    if reasons:
        return IntegrityResult("BLOCKED", tuple(reasons), {
            "mutation_started": bool(candidate.get("mutation_started")),
            "commit_permitted": False,
            "push_permitted": False,
        })
    return IntegrityResult("PASS", (), {
        "mutation_started": bool(candidate.get("mutation_started")),
        "candidate_index_tree": candidate["candidate_index_tree"],
        "commit_permitted": True,
        "push_permitted": False,
    })


def validate_operations(
    changes: Any,
    path_policy: Iterable[dict[str, Any]],
) -> IntegrityResult:
    if not isinstance(changes, list):
        return IntegrityResult("UNKNOWN", ("candidate changes unavailable",), {})
    try:
        policies = tuple(_normalize_policy(path_policy))
    except (TypeError, ValueError) as exc:
        return IntegrityResult("UNKNOWN", (str(exc),), {})

    reasons: list[str] = []
    normalized: list[dict[str, Any]] = []
    for change in changes:
        if not isinstance(change, dict):
            reasons.append("malformed change entry")
            continue
        path = change.get("path")
        op = change.get("op")
        old_path = change.get("old_path")
        if not isinstance(path, str) or not path or op not in ALLOWED_OPS:
            reasons.append("malformed change operation")
            continue
        policy = _policy_for(path, policies)
        if policy is None or op not in policy["allowed_ops"]:
            reasons.append(f"{op} not allowed for {path}")
        if op == "RENAME":
            if not isinstance(old_path, str) or not old_path:
                reasons.append("rename missing old_path")
            else:
                old_policy = _policy_for(old_path, policies)
                if old_policy is None or "RENAME" not in old_policy["allowed_ops"]:
                    reasons.append(f"RENAME not allowed for {old_path}")
        normalized.append({"path": path, "op": op, "old_path": old_path})

    if reasons:
        return IntegrityResult("BLOCKED", tuple(reasons), {"changes": normalized})
    return IntegrityResult("PASS", (), {"changes": normalized})


def attest_commit(
    lease: MutationLease,
    commit: dict[str, Any],
    candidate: dict[str, Any],
) -> CommitAttestation:
    reasons: list[str] = []
    if commit.get("parent_sha") != lease.expected_target_head:
        reasons.append("commit parent mismatch")
    if commit.get("tree_sha") != candidate.get("candidate_index_tree"):
        reasons.append("commit tree differs from admitted candidate index tree")

    op_result = validate_operations(commit.get("changes"), lease.path_policy)
    if op_result.status != "PASS":
        reasons.extend(op_result.reasons)

    status = "BLOCKED" if reasons else "PASS"
    evidence = {
        "workspace_attestation_id": lease.workspace_attestation_id,
        "lease_id": lease.lease_id,
        "retry_count": 0,
        "fallback_used": False,
        "push_permitted": not reasons,
    }
    return CommitAttestation(
        status=status,
        reasons=tuple(reasons),
        commit_sha=commit.get("sha"),
        parent_sha=commit.get("parent_sha"),
        commit_tree=commit.get("tree_sha"),
        changed=tuple(op_result.evidence.get("changes", [])),
        evidence=evidence,
    )


def validate_remote_readback(
    attestation: CommitAttestation,
    remote: dict[str, Any],
) -> IntegrityResult:
    if attestation.status != "PASS" or not attestation.commit_sha:
        return IntegrityResult("BLOCKED", ("commit attestation did not pass",), {
            "remote_readback_verified": False,
        })
    required = {"pr_head", "commit_sha", "parent_sha", "tree_sha", "changes", "readback_state"}
    missing = sorted(required - remote.keys())
    if missing:
        return IntegrityResult(
            "UNKNOWN", tuple(f"missing remote field: {x}" for x in missing),
            {"remote_readback_verified": False},
        )
    if remote["readback_state"] != "VERIFIED":
        return IntegrityResult("UNKNOWN", ("remote write/readback is ambiguous",), {
            "remote_readback_verified": False,
        })
    reasons: list[str] = []
    if remote["pr_head"] != attestation.commit_sha or remote["commit_sha"] != attestation.commit_sha:
        reasons.append("remote head/commit mismatch")
    if remote["parent_sha"] != attestation.parent_sha:
        reasons.append("remote parent mismatch")
    if remote["tree_sha"] != attestation.commit_tree:
        reasons.append("remote tree mismatch")
    if tuple(remote["changes"]) != attestation.changed:
        reasons.append("remote changed operations mismatch")
    if reasons:
        return IntegrityResult("BLOCKED", tuple(reasons), {
            "remote_readback_verified": False,
        })
    return IntegrityResult("PASS", (), {
        "remote_readback_verified": True,
        "retry_count": 0,
        "fallback_used": False,
    })


def _normalize_policy(path_policy: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(path_policy, (str, bytes)) or path_policy is None:
        raise ValueError("path policy must be a collection")
    normalized: list[dict[str, Any]] = []
    for item in path_policy:
        if not isinstance(item, dict):
            raise ValueError("malformed path policy")
        path = item.get("path")
        ops = item.get("allowed_ops")
        if not isinstance(path, str) or not path or not isinstance(ops, (list, tuple, set)):
            raise ValueError("malformed path policy")
        op_set = frozenset(ops)
        if not op_set or not op_set <= ALLOWED_OPS:
            raise ValueError("invalid path policy operations")
        normalized.append({"path": path, "allowed_ops": op_set})
    return normalized


def _policy_for(path: str, policies: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [p for p in policies if fnmatchcase(path, p["path"])]
    if not matches:
        return None
    matches.sort(key=lambda p: len(p["path"]), reverse=True)
    return matches[0]


def _evidence(
    expected: dict[str, Any],
    observed: dict[str, Any],
    workspace_kind: str,
    disposition: str,
) -> dict[str, Any]:
    return {
        "workspace_integrity_profile": PROFILE,
        "workspace_kind": workspace_kind,
        "disposition": disposition,
        "workspace_attestation_id": observed.get("workspace_attestation_id"),
        "executor_instance_id": observed.get("executor_instance_id"),
        "executor_generation": observed.get("executor_generation"),
        "workspace_path": observed.get("workspace_path"),
        "expected_target_head": expected.get("expected_target_head"),
        "expected_target_tree": expected.get("expected_target_tree"),
        "mutation_started": False,
        "repair_attempted": False,
        "destructive_cleanup_attempted": False,
        "retry_count": 0,
        "fallback_used": False,
    }
