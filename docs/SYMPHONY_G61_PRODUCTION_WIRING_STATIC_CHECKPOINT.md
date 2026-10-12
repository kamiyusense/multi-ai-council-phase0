# Symphony / New Chinponey — G6.1 Production Wiring STATIC checkpoint

Date: 2026-10-10. Branch `claude/symphony-g61-production-wiring-static`, created
from Draft PR #320 head `8c53c505a21318c6133da0bef85af18ae3711103` (fresh
readback: OPEN/Draft, both exact-head CI runs green). PR #320's branch, main,
G5/G5.1/G6 evidence and ledgers are not modified.

G6.1 STATIC local result: PASS. **Model/provider LIVE 0. Symphony worker
launches 0. Real Git adoption 0. GitHub writes from G6.1 code 0.** The only
network traffic was read-only GraphQL introspection/queries and REST GETs.

## 1. Atomic expected-head ref update: GraphQL `updateRefs`

Verified from the official schema by read-only introspection (committed as
`tests/fixtures/symphony_g61/graphql-updaterefs-schema.json`):

- `updateRefs` (not deprecated): "All updates are performed atomically, meaning
  that if one of them is rejected, no other ref will be modified."
- `RefUpdate.beforeOid`: "the given reference needs to point to the given value
  before performing any updates." `force` defaults to `false` (fast-forward only).
- `UpdateRefsPayload` contains only `clientMutationId`: the reply never proves
  the new ref value, so the outcome is always resolved by a ref GET.
- The singular `updateRef` / REST `PATCH git/refs` have no old-value input and
  are not used. `createCommitOnBranch.expectedHeadOid` exists but GitHub writes
  its own author/committer/signature, so the commit would not equal the
  deterministic candidate the inspector verified; not used.

`beforeOid` is optional in the schema, so `prepare_update_refs` always sets it
and refuses: default/main/master/HEAD, `refs/…` names, zero OIDs (create/delete),
no-op updates, force, more than one ref. `GitHubGitTransport.compare_and_swap`
sends exactly one request and never retries; any non-`SUCCESS_REPLY` raises and
the G6 bridge then reads the ref.

Read-only permission check (no write): `gh` token scopes `repo, workflow,
read:org, gist`; `viewerPermission` ADMIN; repository node id `R_kgDOUi8NPg`;
default branch `main`. So `contents:write` for `updateRefs` is expected to be
**authorized but was not exercised**. Rulesets/branch rules: the API returned
403 (plan does not expose it) → **UNKNOWN**.

## 2. Result bytes survive Symphony workspace cleanup

`WorkspaceSnapshotStore.capture` runs *before* the proof Issue is closed. It
scans the workspace without following links (top-level `.git` excluded),
writes each file create-only into `objects/sha256/<aa>/<digest>` outside the
workspace, rescans to prove the workspace did not change during capture
(otherwise `UNSTABLE`), publishes a create-only digest-sealed manifest, and reads
every object back. Only `VERIFIED`/`NOOP_DUPLICATE` opens the close gate; a
duplicate is NOOP only if every stored byte still verifies. Nested `.git`,
junctions, special files and unsafe names are recorded as anomalies and make the
source `complete=False` (inspector holds). Official Symphony cleanup is
unchanged; tests delete the workspace and adopt/replay from the snapshot.
The `workspace_fingerprint` uses the G5 observer's derivation (`sha256(path)`).

## 3. Authenticated readers

`ReadOnlyGitHubHttp` (the only concrete network client) refuses non-GET REST
and any GraphQL `mutation`/`subscription` before sending, and is
`static_only=False`, so `GitHubGitTransport` rejects it (`NOT_WIRED`).

- `GitHubTargetReader.read()`: repo identity + configured default branch, ref,
  commit, recursive tree; rebuilds and re-hashes every tree object and every
  blob. Truncated or over limits → `complete=False`, never a smaller inventory.
  `read_at(expected_head)` gives the base for manifest generation, so a target
  that advanced first still produces a durable `STALE_REPLAN`.
- `GitHubTaskValidityReader`: the Issue must contain exactly one
  ` ```symphony-task ` JSON block `{protocol, task_id, request, scope}` with
  `scope.request_digest == digest(request)`; author and last editor must be
  trusted logins. OPEN → valid; CLOSED needs explicit
  `symphony:adopt-after-close` (closing never implies validity);
  NOT_PLANNED/DUPLICATE or `symphony:invalid|superseded|done-elsewhere` →
  invalid; otherwise `None` → hold.

Real read-only qualification (`scripts/symphony_g61_readonly_smoke.py`, 143
requests, 0 writes): full 134-file branch inventory equals local Git bytes;
PR #320 tree (1,581 files) hash-verified and correctly reported incomplete
under a 100-file limit; a real unsigned UTC commit rebuilt byte-identical to
`git cat-file` (GitHub **strips** the trailing message newline in its echo — the
reconstruction accepts only the variant that hashes to the OID); the Issue
GraphQL query is accepted; write attempts refused offline.

## 4. Independent verification contract

`assemble_verification` yields the G6 `VerificationEvidence`. Records are sealed
and bound to result/source/expected-head/scope digests; the verifier must be
configured trusted, not the worker, and of an allowed kind per check:
`syntax` (built-in parse-only, or external CI), `tests` (external CI only —
worker code is never executed here), `secret_scan` (external only),
`secret_pattern_scan` (built-in known-pattern supplement; never satisfies
`secret_scan`). Missing, conflicting, rebound, tampered or untrusted records →
untrusted → inspector holds. The manifest predeclares `sym-g61-check:<name>` refs.

## 5. Wiring and regression matrix

`wire_adoption` composes snapshot → source, target reader, Issue validity,
verification, and `GitHubGitTransport` (Git Database objects + `updateRefs`)
into the unchanged G6 `StaticAdoptionBridge`; `generate_result_manifest`
derives mutations from bytes (renames are DELETE+ADD and stay held).
Executed matrix (workspace deleted before every restart; `regression-matrix-observed.json`):

| Case | Condition | First / restart | updateRefs calls |
|---|---|---|---|
| K01 | adopt, cleanup, replay | ADOPTED / NOOP_DUPLICATE | 1 |
| K02 | crash after intent | crash / ADOPTED | 1 |
| K03 | crash after objects | crash / ADOPTED | 1 |
| K04 | crash after pre-ref fence | crash / UNKNOWN | 0 |
| K05 | crash after applied ref | crash / ADOPTED (GET) | 1 |
| K06 | reply lost after apply | ADOPTED / NOOP_DUPLICATE | 1 |
| K07 | request lost before apply | UNKNOWN / UNKNOWN | 1 |
| K08 | other writer at write time | UNKNOWN / UNKNOWN (other head kept) | 1 |
| K09 | stale HEAD | STALE_REPLAN | 0 |
| K10 | scope-outside file | ISOLATE_TASK | 0 |
| K11 | manifest tampered | CONFLICT | 0 |
| K12 | snapshot bytes tampered | HOLD_AUTHORITY | 0 |
| K13 | GitHub returns foreign object sha | UNKNOWN | 0 |

Never more than one `updateRefs` per adoption; main unchanged in every case.

## Validation

New G6.1 suite 44 tests PASS (1 symlink test skips on Windows, runs on Linux);
G6 46 PASS. Full command bus on Windows: 2,001 run; the 24 failures/errors are
byte-identical to the untouched base commit's run (pre-existing Windows
platform issues, 1,959 run) — Linux CI is authoritative. compileall and
`git diff --check` PASS. CI workflow now includes the G6.1 suite and paths.

## Remaining UNKNOWN / next boundary (stop before LIVE)

- Real `updateRefs` behaviour (error shape on `beforeOid` mismatch, rulesets)
  and real Git Database `POST git/commits` byte determinism (does GitHub keep
  the trailing newline we send?) are not exercised. A mismatch fails closed:
  returned sha ≠ local candidate → no ref call.
- K04 (fence saved, call unknown) stays UNKNOWN by G6 rule. Because
  `updateRefs` is atomic on `beforeOid`, a single re-arm would be non-destructive,
  but it is still a retry and needs an explicit design/approval decision.
- A live write-capable HTTP client is intentionally not implemented.
  `static_only` must not be flipped without review and the separate one-run
  LIVE authorization described in the G6 Local LIVE plan.
- External `tests`/`secret_scan` runners are a contract only; producing real
  attestations for a real candidate is part of LIVE.
- Large targets: full inventories cost one blob GET per file (cached by OID);
  limits make large trees `complete=False` (hold) rather than partial.
