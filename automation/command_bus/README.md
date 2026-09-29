# Chat/Work GitHub command bus

> **MANDATORY BEFORE JULES DISPATCH:** read `docs/JULES_TASK_PROMPT_SPEC.md` before creating any new `automation/command_bus/jules_api_requests/*.json`. The prompt contract requires bounded scope, exact allowed paths, reuse-first, semantic acceptance criteria, negative/tamper tests, no vacuous tests, exact validation commands, and explicit stop conditions. Green Jules tests alone are not acceptance.

GitHub is the durable control plane. Commands and receipts are append-only; only loop state is mutable.
The processor validates the repository, the target PR, `expected_target_head` (the current head of `expected_pr`), correlation, expiry, STOP, terminal receipts, and the six-round ceiling before processing.
The carrier/implementation PR head is separate metadata and is never compared through `expected_target_head`.
Unknown or ambiguous conditions are blocked without retry or fallback.

Reviewer work is represented by append-only `review_request`, `review_claim`,
and `review_response` records. A reviewer is identified only by its instance,
generation, role, and capability; no Chat or thread ID is part of correctness.
Only one non-expired claim is active, stale generations and duplicate
responses are rejected, and Work consumes a response only after exact
loop/round/correlation/target-head validation. Missing, empty, or unverifiable
responses are `UNKNOWN` and fail closed.
Claims must expire strictly after their claim time and no later than the
request expiry. Request, claim, and response operations reuse the shared
`StateMachine` gate, so STOP, HALTED, EXPIRED, and the six-round ceiling block
progress. Records can be serialized and reconstructed in a fresh session
without a thread binding.

The GitHub-backed adapter maps records to `review_requests/<loop>/<request>.json`,
`review_claims/<loop>/<claim>.json`, `review_responses/<loop>/<response>.json`,
and `review_receipts/<loop>/<receipt>.json`; mutable loop state is stored at
`state/<loop>.json`. It rejects unsafe path components, duplicate append
writes, malformed or missing records, and invalid state readback.

The runtime is intentionally limited to `automation/command_bus/**`; it does not execute Jules, providers, live models, API keys, or GitHub workflows.


Durable-boundary hardening:
- every append/state write requires an independent branch readback; unverifiable
  writes return `UNKNOWN` and are not retried automatically;
- persisted request/response/receipt context is checked against loop, round,
  correlation, and target head, and claims/responses/receipts must reference
  durable predecessors in the same loop;
- the controller's connected GitHub capability is the production transport
  implementing `GitHubContentsClient`; no API key or repository secret is
  embedded in this package. The direct Chat thread remains an optional fast
  path and is not part of correctness.


## Exchangeable executor handoff

Implementation work is represented by durable executor-role records:
`execution_requests/<loop>/<request>.json`,
`execution_claims/<loop>/<claim>.json`,
`execution_results/<loop>/<result>.json`, and
`execution_receipts/<loop>/<receipt>.json`, sharing mutable `state/<loop>.json`.

The protocol is independent of Chat/thread/browser session identity. It supports
fresh-session recovery, generation-based executor replacement, exact
loop/round/correlation/target-head matching, and terminal receipt replay
protection. The current executable policy is intentionally `PREPARE_ONLY`:
`requires_live_model=true` or `execution_mode=LIVE` is rejected. A future
Jules/browser/ACP adapter must be separately authorized before it can perform a
live execution. Carrier PR head is not part of correctness; target PR head is.

Every request declares durable `target_role="executor"`, a provider-neutral
`executor_kind`, capability, objective, input/evidence references, allowed and
prohibited actions, and an explicit user-approval boundary. Request, claim,
result, and receipt records include matching `execution_*_id` aliases. Prepared
results prove that no model, external send, retry, fallback, or live start
occurred. All execution records are append-only; only loop state is mutable.


## Executor Workspace Integrity Gate — TREE_IDENTITY_V1

Mutable executors share a provider-neutral pre-mutation invariant implemented
in `workspace_integrity.py`. Correct HEAD identity alone is never sufficient.

Before mutation, TREE_IDENTITY_V1 requires controller-provided
`expected_target_head` and `expected_target_tree`, plus verified repository,
remote, branch/worktree identity. The observed HEAD tree and index tree must
both equal the expected target tree, tracked and cached diffs must be clean,
unexpected untracked files must be absent, and skip-worktree /
assume-unchanged / unsupported sparse-checkout or submodule state must fail
closed.

Persistent/shared workspace failures are quarantined. The gate never performs
`reset --hard`, `git clean`, auto-stash, auto-commit, rebase, or hidden
repair. A disposable workspace may return `RECREATE_REQUIRED`; the permitted
recovery is creation of a new disposable workspace followed by a fresh full
attestation, not repair of the suspect workspace.

Mutation admission uses a path + operation policy. ADD/MODIFY/DELETE/RENAME
are distinct capabilities; DELETE and RENAME are denied unless explicitly
listed for the exact matching policy. Before commit, the target head/tree are
revalidated and tests/compile/diff evidence must be PASS. Commit admission
requires parent == expected target head and commit tree == the already-admitted
candidate index tree. Push remains one normal fast-forward attempt only.
Ambiguous push is never retried; remote readback determines PASS or UNKNOWN.

The executor durable request can carry:

- `expected_target_tree`
- `requires_clean_workspace=true`
- `workspace_integrity_profile=TREE_IDENTITY_V1`
- `path_policy`
- `mutation_lease_ttl_seconds`

Claims may bind workspace attestation identity and observed HEAD/tree/index
tree. Results may reference workspace/commit attestations and the mutation
lease. Concrete target-tree identity is matched by the durable backend.
Legacy PREPARE_ONLY records that used `expected_target_tree=UNKNOWN` remain
recoverable, but a mutating executor must use a concrete target tree.

Regression coverage includes the Jules incident shape: HEAD and HEAD tree are
correct while tracked working-tree bytes are stale. That state is BLOCKED
before a mutation lease can be issued.


## Bounded static validation scope

`STATIC_VALIDATE_COMMAND_BUS` separates immutable-ish implementation material
from the append-only operational ledger.

Static blob verification/reconstruction includes only:

- direct `automation/command_bus/*.py`
- `automation/command_bus/README.md`
- `automation/command_bus/tests/**`
- `automation/command_bus/schema/**`

Operational record families such as commands, events, evidence, receipts,
states, reviewer records, reviewer wake reservations, and executor records are
not all re-downloaded for every unit-test run. The active command/state/receipt
and any required predecessor records are read and validated directly through
their durable protocol.

This keeps static validation bounded even when GitHub history grows. A new
unclassified blob area under `automation/command_bus/**` is not silently
ignored: `validation_scope.py` classifies it as UNKNOWN and validation fails
closed until the area is explicitly assigned to the static or ledger scope.
