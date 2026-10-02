# Actions economy report (2026-10-02)

Source: the latest 500 workflow runs of the repository (2026-09-29 .. 2026-10-02, read via the Actions API). Static analysis of the workflow files is in the cleanup manifests. Nothing was disabled, deleted or changed in repository settings.

## Findings

| # | Finding | Evidence | Safe source-level fix | Status |
|---|---|---|---|---|
| 1 | `Phase 0 development lane status` ran on every PR event for every base branch; the job body only works for PRs #4/#25 | 250 runs, 227 skipped (91%); 247 of them before 2026-10-02T05:16Z | `pull_request_target.branches: [main]` | **Done on main (PR #235).** After the merge: 3 runs, 2 skipped, 1 success (sample too small to quantify) |
| 2 | `blue-work-reconcile-static.yml` listens to `push` on the experiment branch and `pull_request`, so one commit runs the full suite twice | 10 same-head pairs (pull_request+push) of 20 runs | drop the `push` trigger (the pull_request check already covers every head commit of PR #217) | Patch saved: `patches/pr217-blue-reconcile-single-trigger.patch` (applies cleanly to #217 `9d2a2302`). Owner = PR #217; not applied |
| 3 | Issue 110 contract workflows have the same push+pull_request pattern | 6 same-head pairs (topology 3, generation 3), 2 more single | same fix, owner = the Issue 110 branches | UNKNOWN owner decision (those PRs are D-class in the PR manifest) |
| 4 | Same head, same workflow, 2-3 `pull_request_target` runs (e.g. labelled/synchronize bursts) | 33 same-head groups of the lane-status workflow | falls with fix 1 for non-main bases | covered by fix 1 |
| 5 | Test workflow (`loop-status-signal-tests`) only runs when specific files change, so a PR that touches only the Jules request/claim contract ran **no tests** (PR #237 was exactly that) | PR #237 head `a10b10c`: no `test` check, only the skipped lane-status job | add the contract validators, readback workflow and their tests to its `paths` (+ text guard test) | **Done in PR #237** (`aa7f686`) |
| 6 | Carrier dispatch workflow: single concurrency group `phase0-chat-jules-semiauto`, `cancel-in-progress: false` | 61 runs, 3 failures (2026-09-30/10-01) | none: this serialization is a safety feature | keep; known limitation: GitHub keeps only one *pending* run per group, so two rapid commands can drop the first pending run (the quiet guard in PR #220 mitigates, cannot remove) |
| 7 | Failure-heavy lanes | failures: Relay exact-head 4, bounded OIDC proof 4, Issue 110 topology 4, control-plane 3, semi-auto 3 | not an economy problem; each failure was reviewed by its owner thread | informational |

## Not changed on purpose

- No safety test was removed or weakened. The trigger-economy tests are additive and text-based (CI has no YAML library).
- 68 workflows are registered but only 19 files exist on current branches (see `workflow_cleanup_manifest.md`); disabling registrations is an admin action for the human.
- `concurrency` on the carrier dispatch workflow is intentionally serializing.
