# Jules Non-Default Branch Launch Route

Updated: 2026-09-23
Status: STATIC CONTRACT READY / WORK VALIDATION PENDING

## Finding

The first Jules probationary task (Issue #7 -> PR #8) was started through the
GitHub Issue `jules` label route. Although Issue #7 explicitly named PR #4's
non-default branch/head/tree and prohibited fallback to `main`, Jules created
PR #8 from `main`.

Direct PR #4 tree -> PR #8 head tree comparison proved that the intended code
delta itself was only one allowed MODIFY. The blocker was launch/base
selection, not the semantic patch.

## Supported branch-selection route

Current Jules documentation describes the normal web task flow as:
1. select repository;
2. select the branch to base changes on;
3. submit the task.

Jules API types also model GitHub repository context with a required
`startingBranch`. The REST API route requires a Jules API key and is outside
this project's no-API-key safety preference.

Therefore the approved route for the next non-default-branch smoke is:

`GitHub durable command -> Work/Luna Cloud Browser -> Jules web UI -> exact
repo + exact branch selection -> fresh Jules task`

The GitHub Issue `jules` label route is not authorized for a non-default
target until it has an independently proven branch-binding mechanism.

## Required target

Repository:
`kamiyusense/multi-ai-council-phase0`

Target PR:
`#4`

Starting branch:
`feature/relay-transport-7070955470193506982`

Current expected head/tree must always be fresh-read immediately before launch.

## Fail-closed requirements

The command must require:
- `launch_route=WORK_CLOUD_BROWSER_JULES_UI`
- exact `starting_branch`
- `issue_label_launch=false`
- `branch_selection_evidence_required=true`
- fresh Jules task/session
- disposable workspace
- TREE_IDENTITY_V1
- retry=0
- fallback disabled
- one allowed path and MODIFY only

Before task submission, Work must verify the exact branch is selected in the
Jules web UI and preserve branch-selection transport evidence.

That UI evidence is not sufficient for final correctness. After Jules
publishes, the resulting commit must still satisfy:
- commit parent == expected target head
- target-relative tree diff == exact allowed path/operation
- no unrelated file changes
- deterministic post-change tests PASS

If branch selection is unavailable or ambiguous before task submission:
terminal BLOCKED/UNKNOWN; do not submit.

If publication ancestry is wrong:
terminal BLOCKED; do not merge/cherry-pick/rebase automatically.

## Prohibited alternatives

For this route:
- no GitHub Issue label launch
- no Jules REST API
- no API key creation/use
- no implicit/default branch
- no old Jules task reuse
- no same logical task retry
- no automatic fallback
- no Merge
- no direct main write
- no force push
