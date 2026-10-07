# Chat/Work GitHub command bus

## Static Symphony-inspired controller core

`symphony_controller.py` provides an opt-in single-dispatch polling loop over
the existing executor request/claim/result/receipt protocol. Only requests
marked `SYMPHONY_INSPIRED_STATIC_V1` with complete generation and logical
identity are eligible. The adapter requires a non-default durable write branch,
uses fresh target and carrier reads, and preserves the command bus's
PREPARE_ONLY, retry-zero, fallback-disabled and readback rules. The controller
admits the built-in static fake and the exact `CodexAppServerAgentRunner` type;
objects that merely expose `live_enabled=True` are rejected. The Codex adapter
is OFF by default and enforces one turn, one model-start attempt, retry zero,
and fallback disabled. The concrete GitHub Contents transport sends no
automatic retry; the executor backend remains responsible for durable record
validation and write readback. The existing executor schema remains
PREPARE_ONLY with `model_executed=false`; it is never reused for LIVE results.
`symphony_live_store.py` adds separate command, claim, and terminal-result
schemas under `symphony_live/`, with create-only writes and exact readback.
Missing result verification is terminal UNKNOWN, and the next poll cannot
replay a claimed or terminal command. The one-round LIVE proof still requires
fresh GitHub readback and all remote postconditions. See [the design and
limitations](../../docs/SYMPHONY_INSPIRED_MINIMAL_ORCHESTRATOR.md).

> **MANDATORY BEFORE JULES DISPATCH:** read `docs/JULES_TASK_PROMPT_SPEC.md` before creating any new `automation/command_bus/jules_api_requests/*.json`. The prompt contract requires bounded scope, exact allowed paths, reuse-first, semantic acceptance criteria, negative/tamper tests, no vacuous tests, exact validation commands, and explicit stop conditions. Green Jules tests alone are not acceptance.

## Jules Loop ID claim — mandatory duplicate guard

Before creating any new `automation/command_bus/jules_api_requests/*.json`, the
controller MUST reserve the numeric Loop ID with an append-only create-only file:

`automation/command_bus/loop_id_claims/<NNN>.json`

Rules:

- fresh-read existing loop claims, Jules command records, and matching
  `jules-work/relay-dev-loop-<NNN>-*` branches before selecting a number;
- create exactly one claim file for the chosen number **before** dispatch;
- claim creation is create-only: never overwrite, delete, or recycle a claim;
- if the claim path already exists, that number is taken even if the earlier
  task later stops or fails; choose another unused number;
- if claim-write success is ambiguous, read back the exact path before doing
  anything else; do not blindly retry;
- a claim binds the intended command ID, work branch, and expected target HEAD;
- the Jules command must use the same Loop number/command/branch as the durable
  claim;
- branch existence alone is not a sufficient claim, but a pre-existing matching
  branch must be checked for conflict before claiming;
- retry=0 / fallback=disabled applies to the claim/dispatch route as well.

This prevents two independent Chat/Work/controller paths from both naming
different work `Loop 058`-style identifiers. Gaps in numbering are acceptable;
reusing a claimed number is not.

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

## Claude night-loop preparation

`claude_loop.py` defines explicit `JULES_BACKEND` and `CLAUDE_BACKEND` modes.
Both prepare records through the existing executor contract. Requests bind the
fresh target head and tree, `TREE_IDENTITY_V1`, and an explicit path policy;
the existing Jules API closed loop remains the only Jules dispatch route.
The module does not start either model or dispatch externally. It requires
`retry=0`, `fallback=disabled`, and rejects unsafe actions and rounds above six.
Terminal receipt matching reuses the executor receipt fields.


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
- `automation/command_bus/config/**`
- `automation/command_bus/docker/**`

Operational record families such as commands, events, evidence, receipts,
states, reviewer records, reviewer wake reservations, and executor records are
not all re-downloaded for every unit-test run. The active command/state/receipt
and any required predecessor records are read and validated directly through
their durable protocol.

This keeps static validation bounded even when GitHub history grows. A new
unclassified blob area under `automation/command_bus/**` is not silently
ignored: `validation_scope.py` classifies it as UNKNOWN and validation fails
closed until the area is explicitly assigned to the static or ledger scope.

## Claude admission gate (static only)

`claude_admission_gate.py` provides a host-owned atomic SQLite claim that
admits at most one generation POST per in-process host-registered dispatch;
all later attempts are denied before upstream connect. The optional loop
integration `claude_loop.prepare_claude_transport()` is a preflight description
only and cannot launch a process. Count-token requests are denied locally,
health checks are local, and unknown routes fail closed. Validation used only
loopback fake providers. Production upstream is pinned to the exact Anthropic
HTTPS origin and requires a separately identified production state store;
fake upstreams require an explicit test-only connector. The Compose manifest
requires an explicit human-gated runtime launch. Claude has internal-only network access, while the gate alone has a
separately controlled egress network and no published host port. Images and
Claude Code version are pinned; Dockerfile-specific ignore files restrict the
build contexts. The Claude launcher fails closed unless explicitly enabled
with valid one-dispatch metadata. The Gate entrypoint only opens an existing
store and never bootstraps it. A separate `gate-bootstrap` service now declares
the one-time receipt-backed initialization route behind the exact
`human-gate-bootstrap` profile, a required confirmation argument,
`network_mode: none`, and the fixed non-root identity. Its receipt is mounted outside the
`gate-state` named volume via the external host-control directory. Nested mount
ordering and volume ownership still require checks for each deployment.
Effective host firewall behavior, production store ACL verification on Windows,
backup rollback protection, automatic model fallback behavior, and a complete
real Claude response remain unproven. One 2026-09-28 Claude process ended before
the Gate due to a missing sandbox dependency; the Gate recorded zero upstream
requests. Claude OAuth succeeded. No Jules execution occurred. See
`docs/CLAUDE_ADMISSION_GATE_DESIGN.md` for constraints and blockers.
`prepare_transport` separates strict `HOST_LOOPBACK` from opt-in
`CONTAINER_INTERNAL`, which accepts only the freshly validated Compose endpoint
`http://gate:8080`. The container contract requires an externally supplied
expected store UUID; an empty/replaced volume must fail closed. Production
store creation is a separate explicit one-time operation with an external
receipt; normal production open never bootstraps. Windows production ACL
verification remains blocked. This gate remains prepare/static-only and does
not launch Claude or perform the bootstrap. See
`docs/CLAUDE_ADMISSION_GATE_DESIGN.md`.

### Credential-free bubblewrap component proof

Docker Engine 29.8.0 denied bubblewrap's
`clone(CLONE_NEWNS|CLONE_NEWUSER|SIGCHLD)` under its default seccomp profile.
The `claude` service alone uses
`docker/claude-runtime/claude-bwrap-seccomp-amd64.json`. It starts from the
profile vendored in Moby commit `3ce5872b7950c63ba2ffbc5123101019ff3e6682`
(Git blob `ea5a494afb8d64898fa0f4f47ae0c4f5ba9cbbc9`) and adds only the
observed amd64 clone flags, eight observed mount flag combinations, `pivot_root`,
and `umount2(MNT_DETACH)`. The validator pins the resulting file hash and
rejects other runtime security options, added capabilities, or applying this
profile to Gate/bootstrap services. The profile is applied by Docker Compose;
it is excluded from the image build context.

A network-none, UID/GID 1000:1000 component container with no mounts or
credentials failed under Docker's default profile and passed with the pinned
profile. Its mount and user namespaces differed from the outer container;
direct connection to a reserved test IP and lookup of an invalid domain both
failed. A request for an additional PID namespace was denied. No Claude Code
process or Anthropic request was made during this component proof. The prior
real attempt remains terminal FAILED; this component result does not authorize
a new dispatch or real-model run. See Issue #23 for the LIVE checkpoints.

## Durable Loop owner and Status transition

`loop_owner_events/<loop_id>/<generation>.json` is the append-only owner ledger.
`generation` is monotonic and is also the fencing token. The chain keeps only
`loop_id`, target repository, and target PR fixed. Each generation has its own
target head, command/correlation identity, lease window, source receipt, and
evidence so RENEW/HANDOFF can follow an advanced target head without reusing
older proof.

Source receipts use an explicit
`automation/command_bus/receipts/<loop_id>/<file>.json` locator. Evidence uses
`automation/command_bus/evidence/<loop_id>/<file>.json`;
`loop_status_evidence.py` requires an exact non-empty readback for every
required evidence path.

`loop_owner_backend.py` is create-only. It accepts only the exact next
generation, performs event readback and complete-chain readback, never updates
an existing generation, and never retries automatically. ACQUIRE starts the
chain, RENEW keeps the same owner, HANDOFF fences the previous owner, and
RELEASE/TERMINAL close the chain. RELEASE requires a DONE receipt. TERMINAL
binds its terminal receipt to that generation's source receipt.

`loop_owner_observation.py` defines the provider observation for an active
generation. Active ACQUIRE/RENEW/HANDOFF requires a fresh verified observation.
A verified RELEASE/TERMINAL close does not require an active observation.

`loop_status_transition.py` binds state, owner chain, receipt, fresh target,
evidence readbacks, and active provider observation before Status projection.
State `last_command_id` and `last_receipt_id` must bind the latest owner
generation. A non-active state whose owner chain was not closed is forced to
BLOCKED instead of appearing IDLE.

The production transition caller and live observation writer are still not
connected. Issue #33 therefore remains fail-closed until those layers exist.
PR activity, Chat silence, and commit timestamps are not ownership signals.


## Autonomous Symphony / New Chinponey policy kernel

The strict one-shot Symphony proof remains intact. Autonomous-loop product
semantics live separately in `symphony_autonomous_policy.py` and `symphony_autonomous_runtime.py`.

These modules are STATIC-only and do not start Codex or perform GitHub writes.
They provide configurable policy profiles, typed UNKNOWN recovery, stale-target
replan semantics, subscription-only gating, serializable campaign/task state,
corrective task identities, blocker isolation, duplicate-result suppression and
guarded restart reclaim. This lets the long-running controller grow without
turning proof-only one-turn/retry-zero limits into permanent architecture.


### Durable autonomous campaign checkpoints

`symphony_campaign_store.py` persists Track-B campaign state as create-only,
hash-linked checkpoints on a non-default branch. A stale controller must present
the latest revision before appending. Ambiguous creates are never resent; exact
readback can resolve success, and a fresh controller can later restore a
checkpoint whose original response was unverifiable.


### STATIC durable multi-round controller

`symphony_autonomous_controller.py` connects the autonomous kernel to the
create-only campaign store and proves claim-before-dispatch/result-checkpoint
continuation across multiple tasks. Its admitted runner/observer/replanner/quota
adapters are exact built-in STATIC fixtures, so this integration cannot start a
model or provider. It is the seam where an explicitly authorized production
adapter can later be attached without changing campaign semantics.


### Pinned upstream reuse baseline

`symphony_upstream_reference.json` and
`docs/SYMPHONY_UPSTREAM_REUSE_MATRIX.md` pin the inspected upstream Symphony
baseline and separate what should be reused from what Track B intentionally
hardens. Retry/backoff/stall valves now mirror the pinned upstream defaults
without enabling any LIVE transport.


### Autonomous attempt evidence ledger

`symphony_attempt_store.py` is intentionally separate from the existing
PREPARE_ONLY executor ledger. It records create-only attempt INTENT, observed
STARTED evidence and TERMINAL evidence, with deterministic path-safe identities
and predecessor digests. It cannot dispatch a model/provider.

On restart it distinguishes `CLAIMED_UNSTARTED`,
`STARTED_UNRESOLVED` and `TERMINAL`. A STARTED_UNRESOLVED attempt is never
blindly redispatched. An unstarted intent can only be reclaimed after explicit
proof that the old attempt is stopped or fenced.

### Attempt reconciliation / crash-safe STATIC continuation

`symphony_attempt_reconciler.py` restores attempt evidence before the controller
selects more work. Verified TERMINAL repairs a missing campaign result checkpoint;
late TERMINAL can recover the matching isolated BLOCKED task. STARTED_UNRESOLVED
is never redispatched. Unstarted reclaim appends a bound retirement and uses a
new attempt ID. Read recovery has append-only observation evidence.

The controller now writes INTENT -> RUNNING -> simulated start -> STARTED ->
fixture -> TERMINAL -> result checkpoint -> next task. Ordinary runner/read
faults isolate or consume bounded read retries while independent work continues.
Tests include crash/ambiguity boundaries and thirty rounds across five fresh
controllers. `symphony_upstream_event_adapter.py` receives stall/status event
envelopes without implementing a second detector or enabling upstream retry.
Production event authentication remains NOT_WIRED and LIVE remains disabled.
See `docs/SYMPHONY_ATTEMPT_RECOVERY_STATIC_CHECKPOINT.md` for the precise boundary.
