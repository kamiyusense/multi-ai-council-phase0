# Executor Workspace Integrity Gate — Research-backed proposal

Updated: 2026-09-23
Repository: kamiyusense/multi-ai-council-phase0
Scope: all mutable executors (Work / Jules / Codex / Claude / future agents)
Status: DESIGN PROPOSAL — no live provider/Jules execution authorized

## 0. Why this proposal exists

The Jules incident proved that these statements are not equivalent:

- executor task is alive
- executor HEAD equals the expected target commit
- executor committed tree is safe
- executor index is clean
- executor working tree matches HEAD
- executor is actually starting from the canonical GitHub tree

The incident commit used the correct parent commit but still produced a stale/regressive tree. Therefore an executor can have the right parent/HEAD identity and still carry stale tracked files or staged/index state into the next commit.

The invariant we actually need is:

```text
before first mutation:

canonical GitHub target commit/tree
= executor HEAD commit/tree
= executor index tree
= executor tracked working tree

and:
- no unexpected untracked files
- no hidden index flags that can mask tracked-file drift
- correct repo/worktree/remote identity
```

A failure at this gate must stop mutation. Do not "repair" an uncertain persistent workspace automatically.

## 1. External precedent / similar failures

### 1.1 Claude Code: HEAD/worktree can diverge immediately after provisioning

Anthropic issue #79755 reports a Claude-managed worktree where git-tracked files were overwritten with files from another checkout after worktree creation. The worktree HEAD was valid, but tracked working files no longer matched that HEAD. This is almost the same failure class as our Jules incident.

Implication:
- HEAD equality alone is insufficient.
- HEAD tree SHA equality alone is also insufficient if the working tree is not verified.
- tracked working files must be compared against the index/HEAD before mutation.

Source:
https://github.com/anthropics/claude-code/issues/79755

### 1.2 Claude Code: stale worktree base

Issues #57768 / #51545 / #48095 report worktrees created from a stale/default-branch commit instead of the current parent/session HEAD. Reported impact includes agents seeing old files and "fixing" them, causing regressions when integrated.

Implication:
- expected base must be captured by the controller.
- executor must prove it starts from exactly that base.
- base selection must not be inferred from origin/HEAD/default branch.

Sources:
https://github.com/anthropics/claude-code/issues/57768
https://github.com/anthropics/claude-code/issues/51545
https://github.com/anthropics/claude-code/issues/48095

### 1.3 Claude Code: cleanup can miss untracked state

Issue #35862 documents worktree cleanup logic that used status modes hiding untracked files and could therefore treat a workspace as clean when agent outputs were still present.

Implication:
- do not use `git status -uno` or equivalent for integrity decisions.
- enumerate untracked files explicitly.
- cleanup and mutation gates are different; both need complete state visibility.

Source:
https://github.com/anthropics/claude-code/issues/35862

### 1.4 Aider: preserve pre-existing dirty work separately

Aider detects dirty files before editing and commits pre-existing dirty changes separately, so user edits are not silently mixed with AI edits.

Implication for this project:
- the general lesson is "never silently mix pre-existing state with agent edits".
- however, auto-committing unknown dirty state is NOT appropriate for Phase 0 because contamination could be legitimized.
- our safer default is BLOCKED/UNKNOWN + quarantine/recreate.

Source:
https://aider.chat/docs/git.html

### 1.5 SWE-agent / GitHub Actions: disposable environments are aggressively normalized

SWE-agent resets its task repository to a clean base commit before each attempt.
GitHub's checkout action defaults `clean=true`, which executes destructive clean/reset before fetching.

Implication:
- destructive normalization is common and effective only when the environment is disposable.
- our persistent/external executor workspaces must not use `reset --hard` / `git clean` automatically.
- if we can create a fresh disposable worktree/clone from the canonical target commit, prefer recreation over in-place repair.

Sources:
https://github.com/SWE-agent/SWE-agent/blob/main/sweagent/environment/swe_env.py
https://github.com/actions/checkout/blob/main/action.yml

### 1.6 Zed / OpenHands: per-agent worktree isolation

Zed recommends separate Git worktrees for parallel agent threads and creates new worktrees in detached HEAD state to avoid branch sharing.
OpenHands agent-server uses per-conversation worktrees for Git-backed workspaces.

Implication:
- one mutable executor should own one isolated worktree.
- shared root checkout mutation should be avoided.
- identity of the concrete worktree path must be part of the attestation.

Sources:
https://github.com/zed-industries/zed/blob/main/docs/src/ai/parallel-agents.md
https://github.com/OpenHands/OpenHands/issues/15974

## 2. Comparison with the current proposed gate

The proposed sequence:

```text
GitHub current PR head
-> executor fetch/readback
-> executor HEAD == PR head
-> executor HEAD tree == GitHub tree
-> working tree clean
-> staged diff = 0
-> untracked check
-> edit
-> allowed-path check
-> tests
-> re-read target head
-> commit
-> parent == expected target head
-> commit diff allowed
-> push
-> remote readback
```

is directionally correct and significantly stronger than common HEAD-only guards.

The research adds four important upgrades:

1. verify index identity explicitly, not only "staged diff = 0";
2. detect hidden index modes / sparse-worktree conditions;
3. treat failed preflight as quarantine/recreate, not automatic in-place repair;
4. add a second immutable attestation after commit and a remote admission/readback gate.

## 3. Proposed P0 invariant: canonical workspace identity

Before any mutation, compute a Workspace Attestation.

Required fields:

```text
repo_full_name
target_pr
target_branch
expected_target_head
expected_target_tree

executor_instance_id
executor_generation
workspace_path
git_toplevel
git_dir
git_common_dir
remote_name
remote_url

observed_head
observed_head_tree
observed_index_tree

status_porcelain_v2
tracked_worktree_diff_empty
cached_diff_empty
untracked_paths
skip_worktree_paths
assume_unchanged_paths
sparse_checkout_state
submodule_state

attestation_state
failure_reasons[]
created_at
expires_at
```

Required equality:

```text
observed_head == expected_target_head

observed_head_tree
== expected_target_tree
== observed_index_tree
```

Required cleanliness:

```text
tracked worktree diff = empty
cached/index diff = empty
unexpected untracked paths = empty
unmerged entries = empty
```

If any value cannot be obtained or verified:
`UNKNOWN / NO MUTATION`.

## 4. Recommended Git checks

These are conceptual checks; implementation may use equivalent Git plumbing.

### Identity

```text
git rev-parse --show-toplevel
git rev-parse --absolute-git-dir
git rev-parse --git-common-dir
git rev-parse HEAD
git rev-parse HEAD^{tree}
git remote get-url origin
git worktree list --porcelain -z
```

### Index tree

```text
git write-tree
```

`git write-tree` serializes the current index into a tree object. Comparing it with `HEAD^{tree}` is stronger and easier to record than merely saying "no staged diff".

### Tracked working tree

Use a command that compares HEAD/index/working tree with exit status, for example:

```text
git diff-index --quiet HEAD --
git diff --cached --quiet HEAD --
```

Also capture machine-readable status:

```text
git status --porcelain=v2 -z --untracked-files=all
```

Do not use `-uno`.

### Untracked paths

Explicitly enumerate:

```text
git ls-files --others --exclude-standard -z
```

Policy:
- default: any unexpected untracked path blocks mutation.
- a very small task-specific allowlist may be permitted only if deterministic and documented.

### Hidden index flags

Detect:
- skip-worktree
- assume-unchanged

Use `git ls-files -t` / `git ls-files -v` or equivalent parsing.

Policy:
- if sparse checkout is not explicitly part of the executor contract, any skip-worktree path blocks mutation.
- assume-unchanged on tracked files blocks mutation.
- if sparse checkout is explicitly supported in the future, the expected sparse specification itself must be attested.

### Submodules

If the target contains submodules, do not trust the superproject tree alone.

Record and verify submodule commit state explicitly. If not implemented, presence of active submodules should fail closed for mutating executors.

## 5. Important nuance: HEAD-tree equality is not enough

If:

```text
HEAD == expected_target_head
HEAD^{tree} == GitHub expected tree
```

then the local commit object itself is correct.

But that does NOT prove:
- the index equals HEAD;
- the working tree equals the index;
- tracked files were not overwritten after checkout;
- untracked files cannot collide with the edit;
- skip-worktree/assume-unchanged is not masking files.

That is exactly the failure family documented in Claude Code #79755.

Therefore the gate must prove all three layers:

```text
commit tree
index tree
working tree
```

not just the commit.

## 6. No automatic "repair" of uncertain persistent workspaces

### Persistent/shared executor workspace

If pre-mutation integrity fails:

```text
state = BLOCKED or UNKNOWN
mutation_started = false
retry = 0
fallback = disabled
```

Do NOT:
- reset --hard
- git clean
- rebase
- auto-stash
- auto-commit dirty state
- auto-resolve

Preserve evidence and isolate the workspace.

### Disposable workspace

For a truly disposable worktree/container with no user data and explicit lifecycle ownership, safe normalization may be implemented by throwing the workspace away and recreating it from the canonical target commit.

Preferred:

```text
discard disposable workspace object
-> create NEW worktree/clone from expected_target_head
-> run full attestation
```

rather than mutating the suspect workspace back into shape.

This follows the effective pattern used by SWE-agent / CI while staying compatible with this project's no-destructive-clean policy for persistent state.

## 7. Mutation lease / TOCTOU protection

Passing the preflight once is not enough because PR #4 can move while an executor is editing.

Create a short-lived mutation lease containing:

```text
lease_id
expected_target_head
expected_target_tree
executor_instance_id
executor_generation
allowed_paths
issued_at
expires_at
```

Rules:

1. workspace attestation must bind to the same expected target head/tree;
2. immediately before commit, re-read GitHub PR #4 head;
3. if current head != expected_target_head, no commit/push;
4. lease expiry before commit => stop;
5. no automatic rebase/retry.

This generalizes the target-head mismatch behavior that already protected the system during the Jules incident.

## 8. Post-mutation local admission gate

Before commit:

```text
current GitHub target head == expected_target_head
changed_paths subset allowed_paths
no prohibited paths
no unexpected deletes/renames
tests pass
compile/static checks pass
git diff --check pass
```

Additionally compare the candidate index against the baseline:

```text
baseline = expected_target_head
candidate_index_tree = git write-tree
candidate_changed_paths = diff(baseline, candidate_index_tree)
```

This catches accidental stale-tree deletion even if the executor only intended one doc edit.

### Deletion/rename policy

Because the Jules incident manifested as massive deletions, add a conservative default:

- deletion is denied unless the task contract explicitly allows that exact path;
- rename is denied unless explicitly allowed or proven as expected;
- a "small docs change" may not delete source modules or unrelated docs.

An allowed-path glob by itself is not enough. Mutation type matters.

Recommended per-path capabilities:

```text
path
allowed_ops = {ADD, MODIFY, DELETE, RENAME}
```

Default:
`DELETE/RENAME = denied`.

## 9. Commit object admission gate

After creating the local commit, before push, verify:

```text
commit.parent == expected_target_head
commit.diff.paths subset allowed_paths
commit.diff.operations allowed by per-path policy
commit.tree == expected post-mutation tree
commit does not contain unrelated stale reversions
```

Write a Commit Attestation:

```text
commit_sha
parent_sha
commit_tree
baseline_tree
changed_paths
changed_ops
test_evidence
workspace_attestation_id
lease_id
admission_state
```

A commit that fails admission must not be pushed.

## 10. Remote admission / compare-and-swap behavior

Push must be:
- normal fast-forward only;
- never force;
- never force-with-lease as a workaround;
- one attempt only.

Because the produced commit has parent = expected_target_head, a concurrent remote advance should make a normal non-force push fail rather than overwrite it.

If push result is ambiguous:
- do not retry;
- remote readback first;
- if not provable, UNKNOWN.

After successful push:

```text
read PR head
read remote commit
verify remote commit parent
verify remote commit tree
verify remote changed paths/ops
verify PR target relationship
verify no unrelated file was changed
```

Only then persist DONE receipt.

## 11. Recommended architecture change

Add a reusable executor safety component, not Jules-specific logic.

Suggested module:

```text
automation/command_bus/workspace_integrity.py
```

Core concepts:

```text
WorkspaceAttestation
MutationLease
PathPolicy
CommitAttestation
IntegrityResult
```

Suggested APIs:

```python
attest_workspace(expected, executor_context) -> IntegrityResult
issue_mutation_lease(attestation, path_policy) -> MutationLease
validate_precommit(lease, candidate_state, current_target) -> IntegrityResult
attest_commit(lease, commit) -> IntegrityResult
validate_remote_readback(attestation, remote_state) -> IntegrityResult
```

Do not put provider/Jules brand logic in this module.

## 12. Integration with current executor contract

Extend execution request with:

```text
expected_target_tree
requires_clean_workspace = true
workspace_integrity_profile = "TREE_IDENTITY_V1"
path_policy
mutation_lease_ttl
```

Extend claim with:

```text
workspace_attestation_id
workspace_path_fingerprint
observed_head
observed_tree
observed_index_tree
```

Extend result with:

```text
workspace_attestation_ref
commit_attestation_ref
mutation_lease_id
mutation_started
target_head_revalidated
push_attempted
remote_readback_verified
```

Persist attestations/evidence as append-only records.

## 13. Event/command behavior

For any command capable of target source mutation:

```text
request
-> claim
-> workspace attestation
-> lease
-> mutation
-> tests
-> target head re-read
-> precommit admission
-> commit
-> commit attestation
-> fast-forward push
-> remote readback
-> terminal receipt
-> COMPLETE
```

If workspace attestation fails before edit:
- result BLOCKED/UNKNOWN
- no commit
- no push
- no retry
- no target mutation

If target advances after edit but before commit:
- preserve local evidence
- do not rebase
- do not push
- result BLOCKED/UNKNOWN
- fresh executor/generation may later start from the new canonical head under a new request.

## 14. Regression test matrix

P0 tests should simulate at least:

1. clean exact workspace -> PASS;
2. correct HEAD but stale tracked working file -> BLOCK;
3. correct HEAD but stale staged/index tree -> BLOCK;
4. correct HEAD/tree but unexpected untracked file -> BLOCK;
5. assume-unchanged path carrying different content -> BLOCK;
6. skip-worktree path when sparse mode not authorized -> BLOCK;
7. wrong remote/repo identity -> BLOCK;
8. wrong worktree path / wrong branch -> BLOCK;
9. stale base commit -> BLOCK;
10. target PR moves after attestation -> BLOCK;
11. target moves after tests but before commit -> BLOCK;
12. candidate changes file outside allowlist -> BLOCK;
13. candidate deletes unrelated file inside a broad allowlist -> BLOCK by operation policy;
14. commit parent != expected_target_head -> BLOCK;
15. non-fast-forward push -> no retry;
16. ambiguous push -> readback then UNKNOWN if unresolved;
17. successful remote readback -> DONE;
18. receipt replay -> NO-OP;
19. dirty persistent workspace -> no reset/clean;
20. disposable stale workspace -> recreate new workspace, never repair in place.

Add a dedicated regression reproducing the Jules incident shape:

```text
baseline commit B
HEAD = B
working tree contents copied from older commit A
agent modifies one checkpoint doc
candidate commit parent = B
without gate: huge regression diff
with TREE_IDENTITY_V1: blocked before first edit
```

## 15. What not to copy from precedent

Do not directly adopt:
- SWE-agent / actions destructive reset+clean on persistent workspaces;
- Aider's auto-commit of unknown dirty state;
- Claude worktree workarounds that rely only on HEAD equality;
- any automatic rebase/resync after mutation;
- any hidden retry.

Use their lessons, not their unsafe-for-this-project defaults.

## 16. Prioritized implementation recommendation

### P0 — implement now

1. WorkspaceAttestation and TREE_IDENTITY_V1
2. index tree == HEAD tree
3. tracked/untracked/hidden-flag checks
4. repo/remote/worktree identity
5. fail-closed persistent workspace behavior
6. expected_target_tree added to executor contract
7. precommit target-head revalidation
8. path + mutation-operation policy
9. commit parent/diff admission
10. remote readback
11. incident regression fixture

### P1 — next

1. disposable-workspace recreation adapter
2. mutation lease expiry/generation
3. submodule attestation
4. explicit sparse-checkout profile if ever needed
5. attestation evidence schema + recovery validation

### P2 — later

1. cross-platform path fingerprint hardening
2. filesystem-level content hash manifest for selected critical paths
3. optional signed/hashed attestation bundle
4. metrics for repeated workspace-integrity failures

## 17. Decision

Adopt the user's refined principle:

> A mutable executor must prove that it starts from the exact canonical target tree, not merely that its HEAD names the expected commit.

Strengthen it to:

> Mutation is authorized only when repo identity, HEAD commit/tree, index tree, tracked working tree, untracked state, hidden index flags, target lease, path policy, commit parent/diff, and remote readback are all verified. Any uncertainty fails closed.

This should be a common executor invariant for Jules / Work / Codex / Claude, not a provider-specific workaround.
