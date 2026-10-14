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
