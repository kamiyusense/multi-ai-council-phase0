# Local night installation review — uninstalled callbacks, LIVE_NO_GO

Source PR: #398; batch source `ba250f12a83d5c4e48c6b2d1ec6b7d45038d9adf`.
Fresh main at batch start: `b6764a9eb5ef593aec58e321b8fd39d81adde951`.
These identify this development batch, not future execution pins. Re-read refs.
The containing commit and exact-head Actions receipts identify the final source.

## Actual development changes

- `symphony_native_binary_installation.place_reviewed_binary`: a create-only
  primitive around the existing qualification/placement packet. Requires exact
  packet SHA and independently injected installation approval. No CLI, acquisition,
  path default, loader execution, installer factory or runtime activation.
  Descriptor-anchored source/destination, bounded copy, inode/digest readback,
  parent fsync and O_EXCL prohibit overwrite. Any partial/conflicting target stays
  quarantined; no cleanup, automatic resume or retry. Tests copy synthetic ELF only.
- `symphony_sqlite_preparation.SQLiteSchemaPin`: optional independent exact DB
  name/user_version/schema hashes. Missing pins remain review material only;
  supplied pins require complete exact inventory match. Valid migration metadata
  and integrity cannot conceal a schema change. No schema/migration execution,
  seal creation or expanded database allowlist.
- `ReviewedOfficialRuntimeCallbacks.command_for_workspace`: prepares the exact
  quoted `codex app-server -c sqlite_home=...` command for the pinned Official
  Config command boundary. Exact clean dedicated workspace/branch/source HEAD,
  qualified native binary, auth inode, existing storage seal and independent
  schema pins are re-read before/after separate command/OS/storage approvals.
  All approval callbacks default to absent. No env/flag can install this callback.
- `before_cleanup`: calls existing authenticated observation/snapshot adapters,
  checks matching attempt, full-byte readback and exact workspace fingerprint.
  HOLD, wrong lifetime or untrustworthy source cannot release cleanup. The
  callback itself does not remove files or install a scheduler hook.

The original `ReviewedSQLiteStorage`, proof transport, G5/startup patches,
controller/operator workflows and historical evidence are preserved byte-exact.
The sealed Elixir fixture is unchanged: callback testing uses an isolated copy.
A failed first sealed-validator attempt is saved; it is not relabeled PASS.

## Actual runtime boundary and connection sites

Official upstream remains `openai/symphony@be10a1b79df723d6d7612b5651c8522704dafb2e`.
No scheduler, turn cap, retry/backoff, stall, concurrency or cleanup implementation
is replaced. The Python one-turn proof transport is not inserted into its loop.

The actual pinned/patched Elixir AppServer consumes the callback-generated
command in an isolated Config fixture. The fake Python executable records the
exact SQLite override. Same-process initialize/account/config precede one fake
thread and three fake turns. Native binary qualification is explicitly a
synthetic test seam in this case, not an ELF execution or real account proof.
The existing real Elixir startup harness separately covers its original 16 cases.

`before_cleanup` connects the existing G5/G7 signed fixture -> existing snapshot
-> full-byte reader -> duplicate/restart readback. Original cleanup remains the
caller's operation. Production attachment is **UNINSTALLED**: the pinned G5
terminal hook alone does not install a synchronous durable snapshot barrier.
A later reviewed runtime caller must invoke this callback before
`cleanup_issue_workspace` / `Workspace.remove`, and hold deletion on any failure.
The existing upstream before-remove shell hook must not be assumed to block
cleanup when it fails. No shell hook/WORKFLOW/config is enabled in this batch.

Command construction is a finite cold-store first-worker boundary, not an
admission on every turn. It deliberately rejects WAL/SHM and dirty workspaces.
Do not insert it into continuation or reuse its result as later-task authority.
Normal Official multi-turn behavior remains owned by the existing AppServer.
Each future fresh worker needs a current operator review; an installed warm-store
policy for concurrency/crash recovery is a separate prerequisite.

## Current host and release observations

Actual WSL2 execution is available through the permitted native execution route.
Normal Desktop exec failed before process creation with os error 2; no blind retry,
WSL shutdown/helper repair/settings change was performed. Its exact RCA is UNKNOWN.
Existing Elixir 1.19.5/OTP28 and Jason were found; no dependencies were installed.

Existing Codex bytes remain SHA256
`73b73b048546993298234a295de01ef2424e7a8b29def9d0ecb1ca7cb77500d4`.
It is ELF64 x86_64 with no PT_INTERP segment, owner1000, single-link, v9fs/mode0777.
This is not qualified native placement. No real Codex process runs this batch.

Official candidate release metadata was freshly read from
https://github.com/openai/codex/releases/tag/rust-v0.162.0-alpha.17.2 .
Candidate asset: `codex-x86_64-unknown-linux-musl.tar.gz`, ID621097584,
archive SHA256 `e537d5467761567f355f515187a6258c0e4c9d4039fbd23b7cff8c4048f2cdd1`.
Earlier separate read-only audit independently retrieved archive bytes in RAM and
matched the contained binary to the observed digest. That acquisition is historical;
this night batch does not repeat a real download, copy, chmod or execution.
Release is prerelease; a selected version, fresh authenticated acquisition,
signature/loader qualification and actual native source remain operator decisions.
A release URL or file digest is not a publisher-signature verification.

## SQLite source review and remaining contract

Candidate Codex source pin: `740e5af33c71225640e0c1c1555c514c2c93ab74`.
Original core migrations59, goals2, logs2, memory2, queue2 and thread-history8.
The native core uses state_5/logs_2/goals_1/memories_1/queue_1; thread_history_1
is opened lazily, and memories_v2_1 is another optional family. Current sealed
storage allowlist intentionally refuses unreviewed optional families. Do not
expand it merely to silence an error. Independently decide the exact first-worker
feature/DB inventory and expected migrations/schema before installing anything.

Migration pin, semantic schema review and seal approval are separate evidence.
New schema pins do not approve a seal, storage launch or LIVE. Source SQL contains
original table drops/backfills: never execute it on old Windows/auth databases.
Use the exact qualified Linux binary's original initialization only after separate
approval, in a NEW private native root, then quiescent metadata/integrity/schema
review. No current production store exists and no production seal is minted.

## OS resource boundary

A real existing pinned Docker image tests a disposable same-UID namespace with
network:none, read-only root/source, cap-drop ALL, no-new-privileges, no Docker
socket, only one writable workspace mount. Synthetic operator canary and real
host auth/storage are not mounted. Actual denied writes and canary preservation
are recorded. This proves that fixture namespace only, not an installed worker
sandbox, actual auth route or a production isolation callback.

The future operator/app-server can own its separate SQLite; model tools must only
write the reviewed workspace. Same UID +0700 alone is insufficient. Installation
must exclude observer key/event/ledger/snapshot/auth resources, inherited FDs,
Docker socket and host credentials from model tools; bind any permitted auth
reference separately and read-only without copying credentials. Do not create a
new OS account, chmod/chown existing resources or activate Docker worker settings
under this development authorization.

## Concrete next approval, sequence and stop positions

First human decision: approve a concrete native binary acquisition/placement
review only. Proposed, NOT SELECTED:
`/home/yuuki/.local/lib/new-chinponey/codex/0.162.0-alpha.17.2/codex`.
The parent does not yet exist; its closest existing native ancestor is owned by
UID1000/mode0755. Before any placement, independently approve acquisition source,
version/platform/digest, NEW private parent/source, protected roots and the exact
create-only packet. No existing executable/auth/config/DB is replaced. Stop after
readback and separately permitted loader/version proof; no app-server/model start.
The new primitive has no installed factory and is not invoked on a real binary.

Second, dependent review: select NEW SQLite root (proposal only
`/home/yuuki/.local/state/new-chinponey/codex-linux-v1`), exact original migration
inventory and schema pins; approve initialization, quiescence, integrity and
create-only seal separately. Preserve old DBs without access/repair/copy/migration.

Third: independently install command/storage approval callbacks, authenticated
issue map/event/snapshot/ledger roots, OS isolation and synchronous pre-cleanup
caller. Approve the exact WORKFLOW/config/runtime patch before applying it.
No candidate `true` fixture callback or PREPARE digest supplies that authority.

Fourth: separately authorize a fresh same-process read-only app-server diagnostic
on qualified native storage. Past account/config PASS is historical, not borrowed.
LIVE and production sender remain forbidden throughout these installation reviews.
WORKER_FIRST_LOCAL_READY remains NOT_ESTABLISHED; current development is STATIC.

## 0.162.1 placement safety correction (2026-10-15; installation NOT approved)

This supersedes the placement ordering described above; earlier results remain
historical. Candidate version is stable0.162.1, source commit
`092d3acd6bec3e3a14bdc7e7a2810ab628ab759d`. No actual binary is acquired,
placed or executed by this correction. No production callback is installed.

### Reservation, permission grant and failure preservation

`place_reviewed_binary` keeps the existing final-name O_EXCL/O_NOFOLLOW reservation
and descriptor-anchored copy. It now creates that leaf as0600 (nonexecutable).
The final name can therefore exist while incomplete, but is a quarantined,
nonexecutable reservation, NOT a published executable or activation receipt.
After bounded copying/fsync, it independently rereads all destination bytes,
checks SHA256/size/owner/mode/single-link and descriptor/named inode identities,
then requires a separately supplied trusted Sigstore verification callback.
After that callback it rereads bytes and identities again, checks the original
source and parent chains, and only then fchmod's the SAME open inode to0700.
Final native qualification/digest/inode/parent readback must succeed.

The later trusted caller must durably create/read back its create-only intent
before invoking placement and consume that one attempt even if failure occurs
before leaf creation. This primitive alone is not a durable attempt ledger.
Missing/ambiguous intent or outcome is GET-only; never invoke placement again.

No rename, overwrite, automatic retry, resume or deletion is added. Existing
partial/duplicate/colliding leaves stop before any new copy. Caught exceptions,
including KeyboardInterrupt, revoke execute permission on the created descriptor
if necessary, never by following a substituted pathname. If revocation/fsync
itself fails, the result is QUARANTINE_UNKNOWN, never success; preserve all files
and stop every executor. Hard kill/power loss before permission grant leaves a
nonexecutable leaf. A kill/power loss AFTER grant can leave fully verified0700
bytes without a completed receipt. That is UNKNOWN/GET-only, never authority to
execute, repeat placement or clean up. Filesystem/hardware durability failure is
not claimed solved by fsync.

Same-UID malicious writers/executors MUST be excluded for the entire operation,
including the verification-to-chmod/readback interval. O_EXCL excludes competing
create-only installers; it is not a lock against a same-UID process modifying an
existing file. Ownership/0700, descriptor checks and cooperative locks cannot
prove that exclusion. The operator must independently enforce an OS resource
boundary/no untrusted mounts or inherited writable descriptors, and quiesce
other installers. If that cannot be established, do not invoke placement.
This correction installs no such OS boundary. Model workers must remain stopped.

### Independent Sigstore contract; hash is not signature verification

`signature_check(readonly_fd, request)` is mandatory, has no default/factory and
must be injected by the trusted operator, never by worker/model/env inputs. The
read-only descriptor is the exact copied inode, still0600. A callback implementing
real verification must use reviewed trust roots and an independently reviewed
Sigstore verifier (e.g. existing, separately pinned Cosign verify-blob). Verify
signature, certificate chain and signing-time validity, transparency-log evidence,
exact certificate identity and issuer; keep unsafe skip/ignore options disabled.
Passing just a digest, booleanTrue, decoded certificate or bundle claims is refused.
The returned receipt must exactly bind the request/descriptor identity/blob hash,
release reference and installation packet, with all three verification results
strictly True. This validates a TRUSTED verifier's result, not a substitute
cryptographic algorithm. The installer does not authenticate arbitrary callbacks.
A real callback/trust-root/verifier installation is still UNINSTALLED/UNKNOWN.
The tests inject synthetic receipts and prove gating only, not real Sigstore PASS.

Official method reference: https://docs.sigstore.dev/cosign/verifying/verify/
For0.162.1 require exact identity (no broad identity regexp):
`https://github.com/openai/codex/.github/workflows/rust-release.yml@refs/tags/rust-v0.162.1`
and issuer `https://token.actions.githubusercontent.com`. Verification is read-only;
no signing, login or OIDC issuance is needed. If the existing verifier cannot
validate the release's legacy bundle/trust data, stop; do not install/upgrade tools
or disable certificate/transparency checks under this correction.

### Exact later one-time acquisition/placement approval proposal

Version/platform:0.162.1 / x86_64-unknown-linux-musl, standalone CLI archive:
https://github.com/openai/codex/releases/download/rust-v0.162.1/codex-x86_64-unknown-linux-musl.tar.gz
Archive SHA256 (NOT the executable digest):
`86f268d81b898f3e144c5ecff2ad2fda2c5802e042d6195b72538fe0fa125057`.
Corresponding executable signature bundle:
https://github.com/openai/codex/releases/download/rust-v0.162.1/codex-x86_64-unknown-linux-musl.sigstore

Approval would permit ONE acquisition/extraction/placement attempt, fresh remote
and Local readback first, within30minutes of its actual start. No retries/fallback.
It must name the containing reviewed PR commit and independently verified
executable SHA256, verifier/trust pins, actual protected roots and exact placement
packet before placement. Archive/member names, byte limits and absent paths are
checked before safe extraction; refuse links, devices, traversal, multiple or
unexpected members, automatic archive permission restoration and overwrite.
New contents are nonexecutable until hash AND independent signature verification;
only then may the extracted source be made0700 for the existing qualifier. The
installer separately re-verifies the copied nonexecutable destination before its
permission grant. Newly created directories are0700; existing ancestors/files
are never chmod/chown'd.

Exact proposed new write targets (none created now):
- New ancestors below `/home/yuuki/.local/lib/`: `new-chinponey`,
  `new-chinponey/acquisition`, `new-chinponey/acquisition/0.162.1`,
  `new-chinponey/codex`, `new-chinponey/codex/0.162.1`.
- `/home/yuuki/.local/lib/new-chinponey/acquisition/0.162.1/codex-x86_64-unknown-linux-musl.tar.gz`
- `/home/yuuki/.local/lib/new-chinponey/acquisition/0.162.1/codex-x86_64-unknown-linux-musl.sigstore`
- `/home/yuuki/.local/lib/new-chinponey/acquisition/0.162.1/codex`
- `/home/yuuki/.local/lib/new-chinponey/codex/0.162.1/codex`
- New operator-only review/receipt directory:
  `/home/yuuki/.local/state/new-chinponey/native-installation-0.162.1/`
  (new parent `new-chinponey` included); `review.json`, `intent.json`,
  `verification.json`, `outcome.json`, all create-only0600, no raw auth data.

Protected existing roots, never written/copied/migrated:
`/mnt/c/Users/yuuki/.codex`,
`/home/yuuki/projects/multi-ai-council-phase0`,
`/home/yuuki/symphony-worker-first-local-20261014/workspace`,
`/home/yuuki/symphony-worker-night-20261014/workspace`.
Freshly discovered operator key/event/ledger/snapshot roots must also be included
and disjoint; missing identities or unproven isolation stop that stage. The
proposed SQLite root is not included in this binary-only approval. Runtime config,
PATH/Desktop helper selection and existing executable files are not changed.

The current review has NO executable measurement/cryptographic verification or
exact real placement packet, because acquisition is forbidden. Such values must
not be fabricated from the archive digest. A bounded acquisition approval cannot
silently approve an unknown placement packet or replace independent approval.
Acquisition can stop at verification review; placement requires a trusted explicit
approval binding the resulting exact packet. Human need not relay progress, but
absence of that independent approval always blocks placement. No production
callback is installed by this development task or by the binary-only proposal.

Stop after placement/readback; no binary execution (even --version), app-server,
SQLite initialization/migration/seal, worker, LIVE or GitHub runtime sender.
All failure/unknown outcomes preserve acquisition files and the reserved leaf;
never resend, overwrite, delete, auto-repair or automatically revoke another
pathname's permissions. WORKER_FIRST_LOCAL_READY remains NOT_ESTABLISHED;
LIVE_NO_GO remains in force.
