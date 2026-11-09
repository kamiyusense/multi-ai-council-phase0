# Worker-first Cloud → Local installation review packet (2026-10-14)

## Current boundary and source of truth

Repository: `kamiyusense/multi-ai-council-phase0`; Draft PR #398.
Cloud source: `0f4a0b530646bd12010056d3df5c753a33605547`.
Fresh main readback at batch start: `06b1a48c2c2893d582db12127eb70f2476bcd1da`.
Re-read both refs before use; these are historical evidence, not future pins.

This batch supplies **PREPARE_ONLY** native-binary placement and SQLite review
packets, plus stricter OFF worker preparation. It does not install/copy/download
or execute an actual Codex binary, initialize production SQLite, create a
production migration seal, provide approval callbacks, launch a worker or enable
a GitHub sender. An ELF header check is not publisher authentication or proof
that the OS loader can run the executable. A release URL is a pinned input; its
provenance remains `PINNED_INPUT_NOT_AUTHENTICATED`. Verify the acquisition receipt
and digest independently before any separately authorized installation.

Historical Local checkpoint:
https://github.com/kamiyusense/multi-ai-council-phase0/pull/398#issuecomment-6160573230
Its `LOCAL_EXEC_PASS / LOCAL_READONLY_PASS` are historical real WSL evidence.
Cloud fixtures do not refresh them. `WORKER_FIRST_LOCAL_READY` remains unestablished.
`PUBLICATION_AUTHORITY_UNKNOWN / LIVE_NO_GO` remain in force.

Proposed paths `/home/yuuki/.local/lib/new-chinponey/codex/0.162.0-alpha.17.2/codex`
and `/home/yuuki/.local/state/new-chinponey/codex-linux-v1` are **uninstalled
proposals**, not defaults. Actual paths/version must come from a fresh operator
review. Never move, copy, repair or delete original auth/config/SQLite.

## Components and scheduler boundary

| Responsibility | Existing component / new finite seam |
| --- | --- |
| Scheduler, retry/backoff, stall, concurrency, workspace lifecycle | Official Symphony, pinned `be10a1b79df723d6d7612b5651c8522704dafb2e` in `symphony_upstream_reference.json` |
| Same-process subscription before first thread | Existing `symphony_subscription_startup.patch`, applied after the G5 observer patch |
| Binary qualification / placement proposal | New `symphony_native_binary_preparation.py`; no installer |
| Storage migration pin / seal / separately approved worker arguments | Existing `ReviewedSQLiteStorage`; byte unchanged |
| Quiescent migration review material | New `symphony_sqlite_preparation.py`; no seal creation |
| Repository, issue/task, campaign/generations, scope, heads, workspace, binary, storage, observer roots, expiry, duplicate guard | Existing `prepare_worker`, now binds native binary filesystem and descriptor/inode identity plus event size/mtime/ctime |
| Worker run identity | Operator issue map + authenticated G5 STARTED binds the scheduler-generated run ID; no run ID/admission minted by a preparation packet |
| Snapshot and independent adoption | Existing G6/G7/OperatorStaticHost adapters; production runtime attachments still uninstalled |
| Publication authority | Existing sender OFF; effective rules, narrow credentials and signed approvals still UNKNOWN/uninstalled |

No scheduler or launcher is added. The one-turn Python proof transport remains a
finite diagnostic/test seam. Do not place it inside Official Symphony's worker
loop. Source comparison tests apply/reverse the exact startup patch and verify
that thread/turn code is unchanged. The existing real Elixir harness compares
three same-thread fake turns to upstream; run it only with available reviewed
Elixir/Jason dependencies. Absence of those dependencies is UNKNOWN, not PASS.

## One Local batch: inputs and stop policy

These commands are for a later, authorized Local operator. They are **not run on
the user's PC by this Cloud task**. Use native Linux shell in a verified clean
checkout. All `task_*` variables are explicit operator inputs; the `:?` guards
stop on missing inputs. Do not source worker-authored shell configuration. Do not
paste passwords/tokens. No commands below install, replace, delete or launch a
model. Store packets only in an operator-owned private location, outside Git,
auth storage and model workspaces. Paths and database schema fingerprints are
private review material, not public artifacts.

### A. Host preflight

Prerequisites: working native WSL/Linux executor and existing repository.
Inputs: `task_repo`, independently pinned `task_source_head`,
`task_workspace`, `task_scratch_parent`, `task_auth_home`.

```bash
uname -s
id -u
git -C "${task_repo:?}" status --short --branch
git -C "${task_repo:?}" rev-parse HEAD
git -C "${task_repo:?}" ls-remote origin refs/heads/main refs/heads/codex/symphony-worker-first-preflight-20261013
stat -c '%u %a %n' "${task_scratch_parent:?}" "${task_auth_home:?}"
stat -f -c '%T' "${task_scratch_parent:?}"
```

PASS: actual executor works; current HEAD/branch are pinned and clean; scratch is
owned 0700 native ext storage; scratch/auth/workspace disjoint. UNKNOWN/STOP:
`os error 2`, dirty/incorrect checkout, unverified ownership/FS, any route selector
or path drift. Recovery: preserve files; record failing execution path; no WSL
shutdown, helper repair, config rewrite, reset/clean or random retries.

### B. Native Codex executable qualification and placement proposal

Prerequisites: independently acquired, digest-pinned **native Linux** source in
an operator-controlled path; existing private destination parent. Source may not
be an executable on v9fs/Windows mount, symlink, hardlink, setid/shared-writable
file or file inside auth/workspace. No source download occurs here.
Inputs: source, proposed absent destination, SHA-256, exact official release URL,
auth and workspace protected roots. No version/path default is assumed.

```bash
python -m automation.command_bus.scripts.symphony_installation_review binary \
  --source "${task_binary_source:?}" \
  --destination "${task_binary_destination:?}" \
  --expected-sha256 "${task_binary_sha256:?}" \
  --source-reference "${task_binary_release_reference:?}" \
  --protected-root "${task_auth_home:?}" \
  --protected-root "${task_workspace:?}"
```

Expected: `SYMPHONY_BINARY_PLACEMENT_REVIEW_V1`, packet SHA-256, exact source
bytes/digest/inode/owner/mode, parent identities, destination absent,
`installation_started:false`. PASS is only prepare-only filesystem qualification.
STOP: existing/partial destination, invalid provenance input, digest mismatch,
non-native FS, links, ownership/mode or ancestry drift. Recovery: GET/readback
only, preserve any partial installation, no overwrite/resume/delete. After a
**separate concrete acquisition/placement approval**, an independently reviewed
create-only installer is still required; this PR deliberately does not supply
an installer. Re-run this proposal immediately before placement and independently
run `qualify_native_binary(actual_path, expected_sha256)` after placement. Never
use a packet as install/LIVE authority. `codex --version`/loader testing also needs
the later explicitly permitted execution boundary.

### C. SQLite installation readiness

Prerequisites: independently selected NEW private native root, outside auth and
workspace; exact qualified binary. New root initialization is a separate approved
operation, using the original Codex migrations; not performed by the packet CLI.
Inputs: private `task_storage_review_json` with **exactly** these fields:

```json
{
  "root": "operator-selected new native absolute root",
  "auth_home": "existing auth home, unchanged",
  "executable": "qualified native absolute codex",
  "executable_sha256": "independently verified 64-hex digest",
  "migration_sha256": "independently reviewed inventory digest",
  "workspace_roots": ["fresh dedicated absolute workspace"]
}
```

```bash
python -m automation.command_bus.scripts.symphony_installation_review sqlite \
  --review-json "${task_storage_review_json:?}"
```

Expected: `SYMPHONY_SQLITE_MIGRATION_REVIEW_V1`, both SQLite checks `ok`, expected
migration pin, exact inode/mode/owner inventory and schema fingerprints.
PASS: independently pinned migrations match in a quiescent new store, files0600,
root0700, no unexpected files or WAL/SHM. `schema_compatibility` explicitly means
migration pin match only, not unrestricted semantic-schema approval.
STOP: empty/uninitialized store, old auth DB selection, incomplete/changed
migration, corrupt DB, extra files, WAL, links or drift. Recovery: preserve store;
use existing independently reviewed WAL/crash procedure for **the new store**;
never immutable-inspect a live WAL, reinitialize, repair or copy original DBs.

### D. Migration seal review

Prerequisites: C packet, exact binary/acquisition review, schema/expected outcome
review, actual writer quiescence and independent installation reviewer.
Run C again and compare packet identity/hash and migration/schema manifests.
Reviewer decides whether these **exact** bytes/paths/binary/migrations may be
sealed. `ReviewedSQLiteStorage.seal_initialized()` may be called only by a trusted
operator installer with an independent approval callback; CLI never invokes it.
A fixture callback returning True is not production approval.

Expected: no production seal from this Cloud batch. After separately approved
sealing, C reports `existing_seal_verified:true`; exact duplicate sealing is
NOOP. STOP: stale/partial/conflicting seal, unexpected DB, changed version/digest,
lost quiescence or unknown approval. Recovery: preserve current seal; no overwrite
or auto-migration. Restore, if separately approved, uses another NEW root and a
fresh review/seal; never restore in place. SQLite backup requires explicit
quiescence and a new empty private root, not absence of WAL alone.

### E. Observer/snapshot attachment

Prerequisites: trusted operator-owned key, event stream, snapshot and ledger
roots, all disjoint from workspace/auth/SQLite; existing issue map matching task,
campaign, generation and target HEAD. Never copy the key into worker environment.
Run model-free connection regression first:

```bash
python -m unittest automation.command_bus.tests.test_symphony_worker_first_preparation \
  automation.command_bus.tests.test_symphony_g72_runtime \
  automation.command_bus.tests.test_symphony_g73_host \
  automation.command_bus.tests.test_symphony_production_observer -v
```

Expected: STARTED-only remains unresolved, late TERMINAL safely reconciles,
snapshot bytes survive cleanup, restart and duplicate receipt produce NOOP,
stale target/generation and observer mismatch stop adoption. PASS here is MOCK.
Real attachment requires external installer/configuration and independent
readback; it is **UNINSTALLED**. STOP: unbound identity, changed roots/key/events,
partial snapshot, expired proof or missing terminal. Recovery: authenticated
GET/replay of durable events; no redispatch or adoption on UNKNOWN.

### F. Official Symphony runtime integration

Prerequisites: exact clean upstream pin, G5 patch, startup patch, sealed separate
SQLite, independent installer and runtime sandbox excluding operator resources
from worker writes. Never trust 0700 alone against same-uid malicious writers.

```bash
python -m unittest automation.command_bus.tests.test_symphony_subscription_startup_patch -v
python -m automation.command_bus.scripts.check_symphony_subscription_startup \
  --elixir "${task_elixir_path:?}" --jason-ebin "${task_jason_ebin:?}"
```

Expected: baseline and patched fake AppServer each keep three turns in one
thread; continuation delta0, same-process account/config before first thread,
rejected API/paid selectors, no authority in child. PASS is **real Elixir + fake
JSONL only**, not scheduler/model LIVE. STOP: pin/patch/dependency mismatch or
changed continuation. Recovery: preserve reviewed source, isolate failed fixture.
Production command injection/callbacks and launch remain **not installed**;
`prepare_worker(review=..., storage=..., host=..., now=...)` accepts only the
existing STATIC host and returns no runtime launch capability.

### G. Read-only subscription verification

Prerequisites: fresh A–F independent readback, exact native executable,
separate approved storage/diagnostic scratch and existing signed-in subscription.
Requires explicit later authorization for actual read-only app-server execution;
Cloud does not borrow its account as evidence for the user's host.

```bash
python -m automation.command_bus.scripts.symphony_worker_first_preflight \
  --workspace "${task_workspace:?}" --expected-head "${task_source_head:?}" \
  --scratch-parent "${task_scratch_parent:?}" --codex "${task_qualified_binary:?}"
```

Expected: `PASS_READONLY_NOT_ADMISSION`, initialize/account(refreshToken=false)/
config(includeLayers=false) in the **same process**, temporary diagnostic SQLite
only, zero threads/models/GitHub writes. This diagnostic does not install durable
SQLite or prove worker readiness. STOP: paid/API selector, changed auth/head,
unknown route or execution failure. Recovery: preserve original auth/config/DB;
no sign-in, billing fallback, account reset or retry of uncertain execution.

### H. Limited LIVE proof readiness (no launch command)

Prerequisites: actual current host/binary/storage seal/runtime attachments;
independent signed model admission, bounded Issue/campaign/worker/generations/
scope/source and target HEAD/nondefault branch/expiry/duplicate guard; reviewed
subscription boundary and artifact-only first proof. Re-run STATIC gates:

```bash
python -m automation.command_bus.scripts.validate_symphony_operator_static
python -m unittest discover -s automation/command_bus/tests -t . -v
git diff --check
```

Expected now: `LIVE_NO_GO`, production sender OFF,
`PUBLICATION_AUTHORITY_UNKNOWN`; there is no model-launch command in this packet.
Only a separately approved Local proof may later use Official Symphony's real
worker lifecycle. GitHub automated publication additionally needs independently
verified effective rules and narrow operator capability, which a development
push or private-repo rules403 cannot prove. STOP on any unsigned/expired/stale or
UNKNOWN authority. Recovery: durable authenticated readback; retry0/fallback
 disabled for ambiguous external writes/model launches. No Merge or main write.

## Deferred decisions and limits

1. Exact binary acquisition provenance/version/digest, actual destination and
   safe create-only placement implementation: independent review required.
2. Exact new SQLite root, initialization, migration/schema seal and worker-storage
   callback: separate independent operator approval required.
3. Actual Official command injection, observer/event/snapshot attachments and
   OS-level worker/operator isolation: uninstalled, must be tested on Local.
4. Limited first subscription worker LIVE: prohibited in this Cloud batch; fresh
   explicit signed admission needed later, after 1–3.
5. Production GitHub rules/capability: UNKNOWN; sender remains OFF. Does not block
   independent worker-only STATIC work.

Cloud filesystem is not the user's ext4 filesystem. Synthetic ELF is never
executed. Native-FS and system-owner observations are injected fixture seams;
production checks remain strict. No copied credentials or production seals.
Repository evidence directory contains sanitized test/hash/checkpoint data only.
No dependency on chat/thread/session IDs. Follow `AGENTS.md` Japanese reply and
single-block copy-text display rules in every later handover.
