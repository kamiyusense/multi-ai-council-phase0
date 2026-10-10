# Symphony / New Chinponey — G6 STATIC checkpoint

Date: 2026-10-10. Draft PR #320, `codex/symphony-inspired-minimal-controller`.
Fresh starting PR HEAD: `493663acaab069304574e3313f20bddc61a90ee2`.
Fresh starting main: `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0`.
Official Symphony pin: `be10a1b79df723d6d7612b5651c8522704dafb2e`.

G6 STATIC local result: PASS. This batch executes the inspection/adoption/recovery
bridge against credential-free in-memory Git. **Real result adoption 0; model or
provider LIVE 0.** Development commit/push to PR #320 is separately authorized.
Final commit, exact-head CI and downloaded artifact hashes are recorded in the
final PR checkpoint and exported report after publication; this document does
not pretend its own future commit hash or CI results are already known.

## Evidence and upstream responsibility

Fresh readback verified OPEN/Draft #320, both exact-starting-head CI runs,
main divergence, the latest G5.1 final checkpoint and CLOSED Issue #342.
Main-only commits: 78; PR-only commits: 39. The sole common changed path is
`docs/AUTONOMOUS_DEVELOPMENT_LOOP_NORTH_STAR.md`, which this batch does not edit.
Main has no Symphony-path changes since the merge base. No merge/rebase is needed.

G5.1 #342 real durable STARTED/TERMINAL is an immutable test reference. Its
WORKER_STOPPED remains UNKNOWN / RECOVERABLE_UNKNOWN. The integration test
restores its validated attempt, requires a separate actual RESULT, and leaves
that terminal and historical bytes unchanged. The real #342 artifact is never
adopted. The real ledger branch is untouched.

Official polling, selection, worker/workspace lifecycle, multi-turn,
continuation, retry/backoff, stall recovery and concurrency are unchanged.
The pinned observation patch is byte-identical and passes clean-pin apply/check.
The bridge never imports a dispatcher or inserts gates into worker turns.

## Manifest and inspection

`SYMPHONY_G6_RESULT_V1` binds repository/non-default target, campaign, attempt,
generation/attempt number/runner generation, task/Issue, worker_run_id,
workspace fingerprint, expected HEAD, request/scope revision, full source
inventory digest, per-path operation/before/after SHA-256/mode/type, and
verification evidence refs. The digest seals canonical JSON. Evidence contains
hashes and identities, never credentials or source secret material.

Independent reader contracts provide complete typed target/source inventories,
fresh task relevance/request revision and digest-bound verification results.
A worker's status or self-declared checks do not establish those authorities.
The core does not run a new CI engine. Missing/untrusted authority holds the
result, and no default ADOPT occurs. Known credential patterns are also scanned
in the manifest and changed bytes; the independent secret_scan attestation is
required, because a small pattern detector alone is not a universal secret scan.

The inspector validates the existing attempt hash chain and same worker/workspace,
then checks fresh canonical HEAD, current task, all actual changed paths, bytes,
classifications and required checks. Before CAS it reads/checks them again.

| Decision | Effect |
|---|---|
| ADOPT | Safe result may enter the STATIC object/ref/receipt flow automatically |
| STALE_REPLAN | HEAD changed; no Git write; existing kernel marks only this task STALE |
| ISOLATE_TASK | Invalid request, scope/protected path or held operation; independent tasks continue |
| HOLD_AUTHORITY | Missing trustworthy inventory, validity or verification; never DONE |
| CONFLICT | Digest/identity/ledger mismatch; no overwrite or default adoption |

`ADD`, `MODIFY`, `DELETE`, `RENAME`, `COPY`, `MODE_CHANGE`, `SYMLINK`, `SUBMODULE`,
`BINARY` and `UNCLASSIFIED` are classified from bytes and file type, not accepted
from declarations alone. Proof policy opens ADD/MODIFY with mode 100644. Other
classes are profile holds; future explicit policy can open them (DELETE opening
is tested). Exact paths and component-boundary prefixes are checked. Absolute,
traversal, separator aliases, repository-external and .git paths are rejected;
AGENTS.md/.env/.github/secrets are protected by profile. Full inventories catch
unexpected/unlisted files and file/directory collisions. Safe ADD/MODIFY and
corrective task identities flow without another human approval gate.

## Durable Git plan, receipts and recovery

Create-only records reuse the existing Contents client contract in a separate
adoption namespace. Result, immutable inspection revisions, accepted decision,
intent, object marker, pre-ref dispatch fence and terminal receipt are bound by
digests. A create-only lock binds repository/branch/exact expected HEAD to one
adoption owner. Conflicts never overwrite; uncertain record creation uses GET.

Candidate blobs/trees/commit are deterministic actual Git objects. Tests compare
all object identities with Git itself. The commit has exactly the expected
parent. Object creation is separate from branch adoption. Before the one fake
CAS call, the latest target and task/source/verification are inspected again.
Ref, candidate commit, tree and every blob are then read back before receipt.

A saved pre-ref fence does not prove whether a call was made. Recovery with that
fence uses only GET: matching candidate HEAD and objects creates the receipt;
old/unreadable/other HEAD remains typed RECOVERABLE_UNKNOWN. No ref resend occurs,
even after a crash between fence creation and the call. Content-addressed objects
can safely be recognized after pre-ref crashes. Existing terminal receipt replay
performs zero object/ref writes, even if the branch subsequently advances.

Only a verified receipt can feed task DONE into the existing campaign kernel.
The caller saves an existing durable campaign checkpoint. Duplicate checkpoint
replay is a NO-OP. Missing receipts never complete a task; stale replan and
uncertain-result isolation preserve independent work, and a later verified
receipt can recover the matching blocked attempt. No scheduler is added.

## Executed fault/restart matrix

| Case | Injected condition | Observed result |
|---|---|---|
| A | Crash after intent, before objects | ADOPTED on safe restore |
| B | Crash after deterministic objects, before ref | ADOPTED; no additional unique object creations |
| C | Successful ref reply lost, crash before receipt | ADOPTED by GET; ref resend 0 |
| D | Receipt exists, replay | NOOP_DUPLICATE; Git writes 0 |
| E | HEAD advanced before inspection | STALE_REPLAN; objects/ref writes 0 |
| F | Task invalid | ISOLATE_TASK; objects/ref writes 0 |
| G | DELETE in conservative proof profile | ISOLATE_TASK; objects/ref writes 0 |
| H | Scope-outside file | ISOLATE_TASK; independent synthetic task B ADOPTED |
| I | Result digest mismatch | CONFLICT; objects/ref writes 0 |
| J | Worker/attempt binding mismatch | CONFLICT; adoption 0 |

Additional cases cover fence-before-call death, unreadable post-write GET,
receipt creation reply loss, CAS-time races, source/task changes during object
creation, wrong/missing authority, ledger/receipt/object corruption, target-lock
competition, old-attempt receipts, custom default branches, corrective tasks,
checkpoint restart and G5.1 reference integration. All results are STATIC.

Validation: new G6 46 PASS; focused Symphony 200 PASS; full command bus 1,959 PASS
(one inherited platform skip); compileall PASS; diff/secret scan PASS. The new
suite runs in the exact-head Symphony workflow and full regression workflows.
The evidence directory contains observed counters, actual synthetic records,
complete sanitized test logs, machine checkpoint and SHA-256 manifest.

## Next boundary

[Next Local LIVE plan](SYMPHONY_G6_LOCAL_LIVE_PLAN.md) is prepare-only. No proof
Issue/branch/campaign or worker is launched now. The transport constructor rejects
non-STATIC adapters; production readers/verifier and an atomic expected-old-head
remote ref adapter still need reviewed integration before a separately approved
one-run LIVE. GitHub's [Update a reference API](https://docs.github.com/en/rest/git/refs#update-a-reference)
accepts sha/force; force=false gives fast-forward behavior, not a supplied old-SHA
comparison. A pre-read followed by that request is not called atomic CAS here.
The [git update-ref contract](https://git-scm.com/docs/git-update-ref) documents
old-value comparison locally; it is not a ready remote GitHub transport.

No main/default write, merge, force push, rewrite, branch deletion, billing,
credential, Secrets or permission operation is part of G6. Safety protects
productive continuation.
