from datetime import datetime, timedelta, timezone
import unittest

from automation.command_bus.workspace_integrity import (
    PROFILE,
    attest_commit,
    attest_workspace,
    issue_mutation_lease,
    validate_operations,
    validate_precommit,
    validate_remote_readback,
)

NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
HEAD = "b" * 40
TREE = "c" * 40
COMMIT = "d" * 40


def expected(**changes):
    value = {
        "repo_full_name": "kamiyusense/multi-ai-council-phase0",
        "target_pr": 4,
        "target_branch": "feature/relay-transport-7070955470193506982",
        "expected_target_head": HEAD,
        "expected_target_tree": TREE,
        "remote_name": "origin",
        "remote_url": "git@github.com:kamiyusense/multi-ai-council-phase0.git",
    }
    value.update(changes)
    return value


def observed(**changes):
    value = {
        "repo_full_name": "kamiyusense/multi-ai-council-phase0",
        "target_pr": 4,
        "target_branch": "feature/relay-transport-7070955470193506982",
        "workspace_path": "/tmp/executor-1",
        "git_toplevel": "/tmp/executor-1",
        "remote_name": "origin",
        "remote_url": "git@github.com:kamiyusense/multi-ai-council-phase0.git",
        "observed_head": HEAD,
        "observed_head_tree": TREE,
        "observed_index_tree": TREE,
        "tracked_worktree_diff_empty": True,
        "cached_diff_empty": True,
        "untracked_paths": [],
        "skip_worktree_paths": [],
        "assume_unchanged_paths": [],
        "sparse_checkout_state": "disabled",
        "unmerged_paths": [],
        "submodule_state": "ABSENT",
        "status_porcelain_v2": "",
        "executor_instance_id": "executor-a",
        "executor_generation": 3,
        "workspace_attestation_id": "attest-001",
    }
    value.update(changes)
    return value


def policy(**changes):
    value = [
        {"path": "src/relay/**", "allowed_ops": ["ADD", "MODIFY"]},
        {"path": "src/providers/**", "allowed_ops": ["ADD", "MODIFY"]},
        {"path": "tests/relay/**", "allowed_ops": ["ADD", "MODIFY"]},
        {"path": "docs/RELAY_STATIC_CHECKPOINT.md", "allowed_ops": ["MODIFY"]},
    ]
    if "replace" in changes:
        return changes["replace"]
    return value


def clean_attestation():
    result = attest_workspace(expected(), observed())
    assert result.status == "PASS"
    return result


def lease():
    result, item = issue_mutation_lease(
        clean_attestation(), lease_id="lease-001", path_policy=policy(),
        now=NOW, ttl_seconds=600,
    )
    assert result.status == "PASS"
    assert item is not None
    return item


def candidate(**changes):
    value = {
        "baseline_head": HEAD,
        "baseline_tree": TREE,
        "candidate_index_tree": "e" * 40,
        "tests_pass": True,
        "compile_pass": True,
        "diff_check_pass": True,
        "mutation_started": True,
        "changes": [
            {"path": "src/relay/dispatcher.py", "op": "MODIFY", "old_path": None},
            {"path": "tests/relay/test_dispatcher.py", "op": "MODIFY", "old_path": None},
        ],
    }
    value.update(changes)
    return value


class WorkspaceIntegrityTests(unittest.TestCase):
    def test_clean_exact_workspace_passes(self):
        result = attest_workspace(expected(), observed())
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.evidence["expected_target_tree"], TREE)
        self.assertEqual(result.evidence["mutation_started"], False)

    def test_jules_incident_shape_correct_head_but_stale_tracked_file_blocks(self):
        # Reproduces the essential incident shape:
        # commit/HEAD/tree are canonical but tracked working bytes came from an
        # older workspace, so mutation must be blocked before the first edit.
        result = attest_workspace(
            expected(),
            observed(
                tracked_worktree_diff_empty=False,
                status_porcelain_v2="1 .M N... 100644 100644 100644 x y AGENTS.md",
            ),
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("tracked working tree differs from index/HEAD", result.reasons)
        self.assertFalse(result.evidence["mutation_started"])
        self.assertEqual(result.evidence["disposition"], "QUARANTINE_PERSISTENT_WORKSPACE")

    def test_correct_head_but_stale_index_tree_blocks(self):
        result = attest_workspace(expected(), observed(observed_index_tree="a" * 40))
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("index tree mismatch", result.reasons)

    def test_unexpected_untracked_path_blocks(self):
        result = attest_workspace(expected(), observed(untracked_paths=["stale/result.json"]))
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("unexpected untracked paths", result.reasons)

    def test_explicit_untracked_allowlist_is_narrow(self):
        result = attest_workspace(
            expected(allowed_untracked_paths=[".executor/attestation.json"]),
            observed(untracked_paths=[".executor/attestation.json"]),
        )
        self.assertEqual(result.status, "PASS")

    def test_assume_unchanged_blocks(self):
        result = attest_workspace(
            expected(), observed(assume_unchanged_paths=["src/relay/dispatcher.py"])
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_skip_worktree_blocks_when_sparse_not_supported(self):
        result = attest_workspace(
            expected(), observed(skip_worktree_paths=["src/relay/dispatcher.py"])
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_sparse_checkout_blocks(self):
        result = attest_workspace(expected(), observed(sparse_checkout_state="enabled"))
        self.assertEqual(result.status, "BLOCKED")

    def test_repo_remote_worktree_identity_mismatch_blocks(self):
        for changed in (
            {"repo_full_name": "other/repo"},
            {"remote_url": "git@github.com:other/repo.git"},
            {"git_toplevel": "/tmp/other"},
            {"target_branch": "main"},
        ):
            with self.subTest(changed=changed):
                self.assertEqual(
                    attest_workspace(expected(), observed(**changed)).status,
                    "BLOCKED",
                )

    def test_stale_base_commit_blocks(self):
        result = attest_workspace(expected(), observed(observed_head="a" * 40))
        self.assertEqual(result.status, "BLOCKED")

    def test_missing_integrity_observation_is_unknown(self):
        data = observed()
        del data["observed_index_tree"]
        result = attest_workspace(expected(), data)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertFalse(result.evidence["mutation_started"])

    def test_dirty_persistent_workspace_is_not_repaired(self):
        result = attest_workspace(
            expected(), observed(untracked_paths=["old.txt"]), workspace_kind="persistent"
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.evidence["disposition"], "QUARANTINE_PERSISTENT_WORKSPACE")
        self.assertFalse(result.evidence["repair_attempted"])
        self.assertFalse(result.evidence["destructive_cleanup_attempted"])

    def test_dirty_disposable_workspace_requests_recreation_not_repair(self):
        result = attest_workspace(
            expected(), observed(untracked_paths=["old.txt"]), workspace_kind="disposable"
        )
        self.assertEqual(result.status, "RECREATE_REQUIRED")
        self.assertEqual(result.evidence["disposition"], "RECREATE_NEW_WORKSPACE")
        self.assertFalse(result.evidence["repair_attempted"])

    def test_failed_attestation_cannot_issue_mutation_lease(self):
        blocked = attest_workspace(expected(), observed(cached_diff_empty=False))
        gate, item = issue_mutation_lease(
            blocked, lease_id="lease-x", path_policy=policy(), now=NOW
        )
        self.assertEqual(gate.status, "BLOCKED")
        self.assertIsNone(item)

    def test_target_move_after_attestation_blocks_precommit(self):
        result = validate_precommit(
            lease(), candidate(), {"head": "f" * 40, "tree": TREE}, now=NOW
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("target head moved", result.reasons)

    def test_target_tree_move_after_attestation_blocks_precommit(self):
        result = validate_precommit(
            lease(), candidate(), {"head": HEAD, "tree": "f" * 40}, now=NOW
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_expired_lease_blocks_precommit_without_rebase_or_retry(self):
        item = lease()
        result = validate_precommit(
            item, candidate(), {"head": HEAD, "tree": TREE},
            now=NOW + timedelta(seconds=601),
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("mutation lease expired", result.reasons)

    def test_change_outside_allowlist_blocks(self):
        bad = candidate(changes=[{"path": "AGENTS.md", "op": "MODIFY", "old_path": None}])
        result = validate_precommit(lease(), bad, {"head": HEAD, "tree": TREE}, now=NOW)
        self.assertEqual(result.status, "BLOCKED")

    def test_delete_inside_broad_path_is_denied_by_operation_policy(self):
        result = validate_operations(
            [{"path": "src/relay/dispatcher.py", "op": "DELETE", "old_path": None}],
            policy(),
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("DELETE not allowed for src/relay/dispatcher.py", result.reasons)

    def test_rename_requires_explicit_policy_for_both_paths(self):
        result = validate_operations(
            [{
                "path": "src/relay/new.py", "op": "RENAME",
                "old_path": "src/relay/old.py",
            }],
            policy(),
        )
        self.assertEqual(result.status, "BLOCKED")

    def test_precommit_passes_only_after_tests_and_operation_gate(self):
        result = validate_precommit(
            lease(), candidate(), {"head": HEAD, "tree": TREE}, now=NOW
        )
        self.assertEqual(result.status, "PASS")
        self.assertTrue(result.evidence["commit_permitted"])
        self.assertFalse(result.evidence["push_permitted"])

    def test_commit_parent_mismatch_blocks(self):
        item = lease()
        admitted = candidate()
        commit = {
            "sha": COMMIT,
            "parent_sha": "0" * 40,
            "tree_sha": admitted["candidate_index_tree"],
            "changes": admitted["changes"],
        }
        result = attest_commit(item, commit, admitted)
        self.assertEqual(result.status, "BLOCKED")
        self.assertFalse(result.evidence["push_permitted"])

    def test_commit_tree_must_equal_admitted_index_tree(self):
        item = lease()
        admitted = candidate()
        commit = {
            "sha": COMMIT,
            "parent_sha": HEAD,
            "tree_sha": "0" * 40,
            "changes": admitted["changes"],
        }
        result = attest_commit(item, commit, admitted)
        self.assertEqual(result.status, "BLOCKED")

    def test_ambiguous_push_readback_is_unknown_and_not_retry_signal(self):
        item = lease()
        admitted = candidate()
        commit = {
            "sha": COMMIT,
            "parent_sha": HEAD,
            "tree_sha": admitted["candidate_index_tree"],
            "changes": admitted["changes"],
        }
        att = attest_commit(item, commit, admitted)
        self.assertEqual(att.status, "PASS")
        remote = {
            "pr_head": COMMIT,
            "commit_sha": COMMIT,
            "parent_sha": HEAD,
            "tree_sha": admitted["candidate_index_tree"],
            "changes": att.changed,
            "readback_state": "AMBIGUOUS",
        }
        result = validate_remote_readback(att, remote)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertFalse(result.evidence["remote_readback_verified"])

    def test_successful_remote_readback_is_done_eligible(self):
        item = lease()
        admitted = candidate()
        commit = {
            "sha": COMMIT,
            "parent_sha": HEAD,
            "tree_sha": admitted["candidate_index_tree"],
            "changes": admitted["changes"],
        }
        att = attest_commit(item, commit, admitted)
        remote = {
            "pr_head": COMMIT,
            "commit_sha": COMMIT,
            "parent_sha": HEAD,
            "tree_sha": admitted["candidate_index_tree"],
            "changes": att.changed,
            "readback_state": "VERIFIED",
        }
        result = validate_remote_readback(att, remote)
        self.assertEqual(result.status, "PASS")
        self.assertTrue(result.evidence["remote_readback_verified"])
        self.assertEqual(result.evidence["retry_count"], 0)
        self.assertFalse(result.evidence["fallback_used"])

    def test_profile_constant_is_tree_identity_v1(self):
        self.assertEqual(PROFILE, "TREE_IDENTITY_V1")


if __name__ == "__main__":
    unittest.main()
