# Symphony worker-first path: Local read-only preflight

**Purpose:** let Official Symphony's original worker/continuation loop be qualified
independently of GitHub publication controls. No GitHub branch-protection result
is required for *this read-only host diagnostic*. It **does not** remove any
rule/permission check from the real GitHub sender. Never report GitHub rules 403
as PASS.

## What this actually implements

\`automation/command_bus/scripts/symphony_worker_first_preflight.py\` runs only:

1. Local workspace canonical-path, fresh dedicated nondefault branch and exact
   40-character HEAD verification, with a clean working tree. It clears ambient
   \`GIT_*\` selectors for read-only Git commands.
2. Private, owned \`0700\`, verified native Linux ext filesystem scratch root.
   Scratch must not overlap workspace or original \`CODEX_HOME\`.
3. Strict reject if an API-key/base-URL metered selector exists in the parent
   process. The script never inspects credential values.
4. A fresh **ephemeral** SQLite directory under that private scratch root. The
   existing \`JsonlCodexAppServer.probe_read_only\` performs
   \`initialize → account/read(refreshToken=false) → config/read\` in one process.
   The ephemeral directory is removed after the read-only diagnostic. A finite
   isolated Python child uses umask 077 before reusing the sealed transport, so
   SQLite files are created as 0600 without changing the controller's mask.
5. Output only sanitized \`PASS_READONLY_NOT_ADMISSION\` or \`BLOCKED\`.
   No authentication payloads, token values, absolute local paths or stderr.

It never runs \`thread/start\`, \`turn/start\`, git push, branch creation,
GitHub API mutations, OIDC, or result adoption. A pass is **not** permission
to launch a worker. No schedule, issue selection, polling, timeout/retry,
same-thread continuation or stall behavior is changed in Official Symphony.

## Offline installation after separately reviewed host setup

Use a **fresh, dedicated** proof checkout/worktree on a branch named
\`codex/symphony-worker-proof-<fresh-id>\`. Review exact source HEAD before
the worker. Prepare an empty approved scratch *parent* on WSL native ext4
with mode \`0700\`; do not place it inside the workspace or \`CODEX_HOME\`.

From the repository root on the already authorized WSL host:

\`\`\`sh
python3 -m automation.command_bus.scripts.symphony_worker_first_preflight \
  --workspace /absolute/path/to/dedicated/clean/worker-worktree \
  --expected-head FULL_40_CHARACTER_REVIEWED_COMMIT \
  --scratch-parent /absolute/private/ext4/scratch-parent
\`\`\`

The preflight reads the local git HEAD; it does not query or change the remote.
For offline unit testing:

\`\`\`sh
python3 -m unittest automation.command_bus.tests.test_symphony_worker_first_preflight -v
\`\`\`

The existing WSL/Codex login state must already be usable. Do not request new
login, repair shared Windows SQLite databases, edit settings or use an API key.

## Separate worker-only LIVE boundary

Only after a specific one-LIVE authorization may a trusted Local operator:

- select a **fresh** Issue/campaign/workspace and independently pin the source,
  exact branch/HEAD and one allowed artifact;
- install the previously reviewed separate Codex SQLite store, approved worker
  launch callback and Official Symphony subscription startup patch;
- start Official Symphony once, allowing its native multi-turn and safe recovery
  behavior (do **not** replace it with the one-turn proof adapter);
- keep the worker isolated from GitHub write credentials, with **no** automatic
  commit/push/PR, stage/dispatch, OIDC, adoption or GitHub ref mutation;
- preserve local observer events and full snapshot **before** workspace cleanup;
  independently read back result bytes, IDs, and lifecycle records.

An unobserved terminal remains UNKNOWN; do not treat a local worker result as a
verified GitHub adoption receipt. Platform branch rules and minimal credential
reviews remain **BLOCKED/UNKNOWN** for the later GitHub publication stage.
Do not weaken existing \`constraints_reader\` or the operator sender.

## Known limitations and stop reasons

- WSL native ext4 scratch is required; Windows-mounted drvfs is not qualified.
- The diagnostic scratch directory is ephemeral, not the approved durable
  production SQLite installation. A real worker still needs that independent
  storage binding and fresh same-process admission.
- Clean local git status is not a complete security proof of ignored files or
  arbitrary program behavior. Worker sandbox/trusted runtime isolation is a
  separate installation responsibility.
- Parent process credentials/authorization and model quota are not established
  by checking the route; quota UNKNOWN is not exhaustion.
- A proof run cannot proceed from this script alone. **LIVE_NO_GO** until
  explicit operator authority and actual host installation are verified.

## Post-probe freshness

The diagnostic re-reads canonical paths, private scratch ownership/mode and native
filesystem, the authentication-home selector, metered environment selector names,
and exact branch/HEAD/clean status after the same-process account/config probe.
A change while the probe runs produces BLOCKED with local_branch_verified=false.
This closes a read-only reporting race; it is not worker admission, a durable
launch claim, or proof that future state cannot change. A later trusted Official
Symphony launch still needs its own fresh identity/binary/storage/authorization
binding and same-process subscription checks. No scheduling or continuation is
changed. Local host execution unavailable is UNKNOWN, never an inferred pass.

## Operator-owned OFF preparation seam

`symphony_worker_first_preparation.prepare_worker` composes the existing
`ReviewedSQLiteStorage` and exact `OperatorStaticHost`; it does not replace or
modify their sealed source, validators, workflows or receipts. The independent
operator supplies `WorkerPreparationReview`, storage review and clock. It binds
Issue/task/generations/scope, source branch/HEAD/clean workspace, canonical target
branch/HEAD, exact owned executable/digest, existing auth root, native private
sealed SQLite and observer/event/snapshot/ledger roots outside the workspace.

The entry records create-only INTENT, calls only the existing same-process
initialize/account/config read-only transport, then re-reads all bindings before
create-only OUTCOME. INTENT without a verified matching outcome is GET-only HOLD;
exact duplicates do not repeat the process. Expiry, changed identity, API routes,
paid config, untrusted storage, broad permissions and linked inputs fail closed.
It never reserves a campaign task or produces a worker/storage approval.

The prepared OFF host can subsequently exercise its existing authenticated
observer and verified pre-cleanup snapshot callbacks using synthetic events and
local records. Snapshot bytes survive disposable fixture cleanup and observer
restart. This is callable STATIC wiring, not a production host or GitHub sender.
The 20 new negative/integration tests use a fake JSONL process; they do not count
fake account evidence as current Local authentication or real model results.

Actual host readback on 2026-10-14 established WSL2 shell execution, Linux Codex
0.162.0-alpha.17.2, a separate private native scratch and same-process ChatGPT
account/config compatibility at starting PR HEAD b307334fe329af2e65566d4af61f3e941f0da546.
Original auth/config byte hashes matched before/after, and no thread/model was
started. The initial ephemeral files inherited 0644 inside their 0700 private
parent; the isolated child above addresses this without resealing old evidence.
Final exact-head diagnostics and test/artifact digests are recorded in the PR
checkpoint after commit; do not infer them from this historical observation.

`WORKER_FIRST_LOCAL_READY` remains unestablished until the independently approved
durable storage cutover and real operator/runtime attachment qualify. This Goal
does not install the proposed production SQLite root or supply its approval
callback. A successful disposable diagnostic and an OFF composition are not
that approval, and LIVE is not the only remaining boundary.
