# Production installation readiness — review proposal, not activation

This STATIC PR starts at fresh main `e5498abf55a386c6a8c11aa7069727cd2fc66030`.
PRs #320, #343, #364 and #382 were independently read back as merged. Merged code
is not an installed runtime. No production path, setting, credential or workflow
is switched by this PR. Official Symphony remains the sole scheduler and owns
polling, continuation, retry/backoff, stall recovery, concurrency and cleanup.

## Durable SQLite installation contract

The existing Windows Codex DBs are preserved. The host-recovery receipt proves
that Windows/WSL migration checksums differ; the pinned first migration matches
CRLF vs LF. This PR does not repair or convert old databases. `CODEX_HOME` still
points at the existing authentication/configuration home; only `sqlite_home`
is separated. Official configuration reference:
https://learn.chatgpt.com/docs/config-file/config-reference .

Proposed durable location: `/home/yuuki/.local/state/new-chinponey/codex-linux-v1`.
This is an installation proposal; that production directory is NOT created or
selected in this batch. It must be outside model workspaces and outside/beside,
not inside, `CODEX_HOME`. The parent is operator-owned, directory 0700, files
0600, real native WSL ext4, with no symlinks, hardlinks or unapproved files.
Backups belong in another approved private native directory, never GitHub.

Installation after separate approval:

1. Stop/confirm absence of writers for the selected new store. Do not stop or
   alter Desktop's existing DB. Pin the exact reviewed Linux Codex executable
   and its SHA-256. A different binary is a new storage/migration review.
2. Create the NEW empty private root with restrictive umask. Keep the existing
   auth/config reference; do not copy auth.json, settings or old databases.
3. Initialize through that exact Codex binary with a process-local `sqlite_home`
   override. Send initialize, account/read(refreshToken=false) and
   config/read(includeLayers=false) only. This is not a model admission.
4. Inspect migration metadata and integrity. Independently approve the observed
   migration inventory SHA-256 for this binary. Seal once with
   `ReviewedSQLiteStorage.seal_initialized`; missing/partial/conflicting seals
   fail closed, never overwrite. A repeated matching seal is a NOOP.
5. On each process restart, re-read the seal, owner/mode, canonical root, DB inode
   identities, binary digest and migration digest. Reuse the SAME separate
   store. Never reinitialize, reset or copy a Windows DB on failure.
6. Supply a separately reviewed worker-storage approval callback from the trusted
   installer. Diagnostic success or a caller's LIVE flag cannot supply this
   approval. `JsonlCodexAppServer(production_storage=...)` validates the binding
   before launch and still obtains fresh account/config in that SAME process
   before any model work. The default LIVE flag remains OFF. This adapter is a
   component proof transport, not a replacement for Official Symphony's loop.
7. For Official Symphony, apply the separately reviewed `symphony_subscription_startup.patch`
   to the clean pinned upstream after the existing G5 observation patch. It adds
   account/config reads before thread creation in the SAME app-server process
   and strips observer/GitHub/API authority from the child. All other AppServer
   behavior and all scheduler code remain unchanged. Then inject the approved fixed Codex app-server command
   with its process-local SQLite override at installation, retaining the upstream
   AppServer multi-turn lifecycle. Do not copy the one-turn proof runner into
   the scheduler, cap normal turns, or add a second scheduling layer.

The callback interfaces are real executable adapters, but production callbacks,
root selection and activation authority are NOT installed. Filesystem checks
assume trusted operator control of the parent and no concurrent path replacement.
The runtime sandbox must keep these paths outside worker writable roots; 0700
alone is not isolation from another process running as the same OS user.

## Crash, backup and restore

Readiness performs SQLite read-only quick_check and queries only migration
metadata, never thread/account contents. WAL existence is recovery-needed state,
not automatic corruption. The synthetic crash fixture preserves committed WAL
across abrupt process exit. Read-only WAL access may maintain private shared
memory; immutable main-file-only inspection is not a WAL recovery proof.

Backup requires an independently asserted quiescent store (all writers stopped),
no remaining WAL/SHM, current seal and an empty separate 0700 destination. Use
SQLite's backup API into exclusively created 0600 DB files. Backups are
multi-database snapshots requiring quiescence; absence of WAL alone does not
prove quiescence. A partial backup is quarantined, never resumed or overwritten.
Restore goes into a NEW root with fresh independently reviewed identity/seal;
verify integrity/migrations before an explicitly approved cutover. Never restore
in place, overwrite existing storage, reinitialize corrupt DBs, or mix binaries.
Operational retention/deletion and Windows support remain deferred decisions.

## Subscription boundary

Real read-only initialization/account/config proof is recorded independently
from mocked worker tests. Neither is authorization for LIVE. Before worker work,
fresh same-process ChatGPT account and requiresOpenaiAuth are required, standard
OpenAI configuration only, no API-key selectors, custom endpoint, paid fallback,
overages or automatic credits. UNKNOWN quota telemetry is not EXHAUSTED.
No actual thread/start or turn/start is sent in this batch. Storage migration
failure blocks that process; it does not change upstream retry policy or prevent
independent STATIC work.

## Existing operator connection inventory

| Connection | Reused implementation / authority | Installed now? |
| --- | --- | --- |
| Independent source/review | RuntimePins + IndependentReviewReader, exact Git blob and canonical bytes | No production review pins |
| Runtime/job identity | GitHubJobContextReader, fresh run/job/workflow/main GETs | Adapter exists |
| Same-job OIDC | MemoryOnlyOIDCRequest + attach_reviewed_runtime, one attempt, signature/claims checked in memory | OFF, never called for real |
| Minimum credential | ReviewedNarrowCapabilityFactory + scoped create-only ledger client | No approved production callback |
| Durable issuer/nonce | Existing issuer INTENT, nonce claim, shared copy/PID fences | STATIC tested |
| Immutable stage | validate_stage, source inventory and candidate object-byte validation | No real stage created |
| Independent verifier | PinnedVerifierExecutor / candidate verifier, bounded pinned offline image, trusted source tests | No real qualified candidate |
| Exact write | Existing expected beforeOid/afterOid, force:false single-ref capability | No real updateRefs |
| Ledger/restart | AppendOnlyAdoptionStore + GET-only receipt recovery | STATIC tested |
| Worker separation | Subscription environment filter, root separation, no GitHub/operator authority in child | Guard maintained |

The existing G7.2/G7.3 integration tests already cover mock lifecycle observer,
immutable snapshots, verification, candidate construction, mocked CAS/ledger,
restart/readback and next-task selection, including concurrent/lost/stale/tampered
paths. A real Elixir fixture runs the exact pinned/patched AppServer against a fake
JSONL subprocess, covering three same-thread turns, conservative bad-account/
endpoint/fallback rejection, private-notification suppression and child authority
removal. Original good-case turn count is compared with the patch (delta 0).
No actual Codex model participates in those simulated turns.
New tests target the previously missing persistent storage/startup connection;
this PR does not duplicate an autonomous engine or invent a new mock framework.
Real runtime readback, stage preflight, OIDC, constrained capability and restart
components are validated in their existing integration fixtures. Mock signatures
and mock CAS are explicitly not production evidence.

## GitHub protection and minimal activation delta (DOCUMENT ONLY)

Fresh repository is PRIVATE. Existing development OAuth reports repo/workflow
scopes; this is broad development access, NOT an approved narrow runtime token.
Actions default GITHUB_TOKEN permission is read; workflow approval is disabled.
REST classic protection, rulesets and effective-rules APIs return plan-related
403. Free read-only GraphQL branchProtectionRules returns totalCount=0 for
classic rules; this does NOT prove effective rules, allowed proof refs, app token
scope or runtime write capability. Those remain UNKNOWN; constraints_reader must
not supply rules_complete:true based on admin metadata or this document.
Official protected-branch availability:
https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches .

| Future reviewed change | Minimum scope | Present batch |
| --- | --- | --- |
| Authorizer job activation | Exact independently reviewed main/source/job/review pins, environment approval if chosen | hard if:false retained |
| OIDC permission | id-token:write ONLY in reviewed authorizer job; it does not itself grant contents writes | not added |
| Candidate verifier activation | contents:read, credential-free independent fixed test route; exact reviewed stage dispatch | OFF, no dispatch |
| Runtime writer credential | Approved single-repository short-lived contents:write + metadata:read, explicit token injection in memory | not acquired/granted |
| Ref/ledger constraints | Independently inspect actual effective rules and approve exact nondefault target/ledger refs; default branch deny enforced independently | UNKNOWN, write blocked |
| SQLite installation | Approve concrete native root, executable/migration pins and separate worker storage callback | proposal only |

GitHub contents:write is repository-wide, not a path-limited right. Application
allowlists constrain this adapter but do not replace GitHub branch protections.
No authority is minted from dispatch inputs/candidate code. JWTs are not logged,
saved, copied to argv/env, or exported as evidence. Uncertain issuance/writes are
never blindly resent; durable issuer/nonce state allows GET-only recovery.
Official OIDC permissions and conditions:
https://docs.github.com/en/actions/concepts/security/openid-connect .

Both operator workflows remain byte-identical to starting main: job if:false,
contents:read, no id-token:write. API registered/active status is not activation.
No workflow dispatch, production staging ref, Git Database POST, updateRefs,
result adoption, model LIVE, secrets/settings/permissions/billing change occurs.

## Final human boundary and first LIVE sequence

Review/merge this STATIC Draft PR only after independent exact-head review.
Bundle a separate approval for the concrete SQLite installation and exact
operator activation diff/credential/ref policy; confirm the unresolved platform
rules instead of claiming 403 PASS. A later separately reviewed activation PR
must wire trusted callbacks, source/review pins and nondefault refs, retaining
worker/operator separation and same-job memory-only issuance. Do not simply
remove if:false: the installation CLI still deliberately exits NOT_INSTALLED.
Only after that installation evidence exists, request an explicit bounded first
LIVE campaign with fresh Issue/campaign/workspace and fresh same-process
subscription checks. This batch does not activate, dispatch or adopt anything.
