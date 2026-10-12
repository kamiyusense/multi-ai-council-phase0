# G6.1 CI recovery / G6.2 STATIC readiness checkpoint

Repository `kamiyusense/multi-ai-council-phase0`; workbench Draft PR #343,
`claude/symphony-g61-production-wiring-static`. Starting fresh GitHub HEAD
`36ba85e4a9fc7f7ac280c33548b96a74cc451e37`; main
`702497c6b464a3b1ab09441b21fc6f96bd3bb2d0`; PR #320
`8c53c505a21318c6133da0bef85af18ae3711103`. No merge or main write.
PR #320 integration is deferred: #343 remains the isolated stacked workbench;
no integration is needed to qualify these seams. PR #344 is outside scope.

## G6.1 CI recovery and evidence integrity

Run **38014884249 FAILED**, exclusively at exact-diff validation: original
Windows test log lines 1025 and 1671 ended in a space. GitHub's Linux job ran
244 focused and 2,003 full tests successfully (one full-suite skip). Only those
two spaces were removed; the Windows failures/errors were not rewritten.
The original bytes are preserved in deterministic gzip under
`evidence/symphony-g61-ci-recovery`; decompressed SHA-256 is
`c62b01fcf572560d8087f94080db3145712d370d4a7ec66ac8c9761506df6a70`.
Published log SHA-256 is
`bd2f073a690f6ff7deca9c9e37c5245183984851ee04f7a85664a006c2fbadc0`.

Normal commit/FF push **c0c88b05bc21652fb7b9a76355b91ed0ffebbb3f** passed exact-head
Symphony CI **38022596258**. Every step/log was inspected and artifact
**11657969624** was downloaded and verified against GitHub's archive digest:
`d52bd99854d5d0835407351c4a3c7244760d2beca3305e21ac1a31151f133717`.
The old checkpoint's diff-PASS declaration is historical, not accepted as proof;
the failed run and original Windows failure set remain preserved.
The G6.1 manifest now indexes current reviewed implementation bytes. Its
original version is separately archived under G6.2 evidence.

## Independent review and bounded repairs

GitHub's [official updateRefs contract](https://docs.github.com/en/graphql/reference/git#updaterefs)
confirms the expected-old `beforeOid` comparison and atomic ref updates.
The request keeps exactly one non-zero before/after pair with force=false.
Actual mutation semantics/rulesets remain LIVE UNKNOWN; no mutation was sent.

| Boundary | Reviewed change / evidence |
|---|---|
| Git objects | Preparation re-hashes all local objects and reconstructs the tree from the full file inventory before any mock POST. Returned wrong OID prevents ref publication. |
| Ref CAS | Default/repository identity is re-read immediately before the single mock ref call. Drift after the durable fence yields UNKNOWN with zero ref calls; no resend on restart. Server CAS remains necessary for races. |
| Snapshot | Only top-level `.git` can be excluded; caller exclusions can no longer hide mutations. Duplicate IDs bind campaign, attempt, worker, workspace, inventory, exclusions and anomalies. |
| Snapshot publication | Fully written/fsynced temp objects become canonical by create-only hard link; unique temp names prevent same-process collisions. Directory entries are fsynced before close-gate release. Crashed temp bytes are never treated as canonical. |
| Link races | Descriptor-anchored traversal and no-follow opens reject concurrent file/directory replacement. Junction/reparse entries and incomplete inventories keep the close gate shut. Unsupported secure filesystem primitives fail closed. |
| Source identity | Wiring binds loaded snapshots to durable campaign/attempt/worker/workspace, including after Official workspace deletion. |
| Target inventory | Tree/blob hashes plus actual blob size are verified; false/missing size metadata cannot bypass limits. |
| Verifier authority | Record self-hashes establish integrity only. The new reader requires a separately pinned verifier workflow, exact successful run/attempt/job/steps, and independently fetched archive bytes matching GitHub's digest. |

The independent attestation binds candidate commit, result/source/scope digests,
expected target HEAD, run attempt and job ID. Missing/failed/skipped checks,
worker self-PASS, changed workflow, wrong heads/archives, rebound records and
incomplete pagination are refused. The worker supplies neither verifier trust
configuration nor authoritative CI/archive reads. Built-in parsing does not
execute worker code; the pattern supplement never substitutes for external
secret_scan. An actual independent candidate verifier/archive GET integration
must be qualified before LIVE; these tests exercise the contract with mocks.

## G6.2 production preparation stays OFF

`PrepareOnlyGitHubTransport` uses the existing inspector and readers, verifies
fresh target/task/source/check bindings, constructs deterministic Git Database
requests plus one updateRefs request, then rechecks HEAD/task before returning
`PREPARED_OFF`. The plan is digest-bound and explicitly unauthorized to send.
It holds no write sender. Constructor LIVE mode is refused; changing mode or
static_only properties cannot enable execute/put_candidate/compare_and_swap.

The existing G6 append-only result/inspection/intent/target lock/objects/fence/
receipt and recovery bridge remains the mock execution authority. No second
scheduler, retry engine or campaign state machine was added. Signed lifecycle
TERMINAL remains UNKNOWN observation evidence; it alone never grants adoption
or task DONE. Task-specific HOLD/ISOLATE/STALE do not stop independent work.

## STATIC validation and remaining boundary

New G6.2 suite: 30 tests. Focused Symphony: 274. Full command bus: 2,033,
with one inherited platform skip. Actual logs, observed 18-case fault matrix,
synthetic ledger records, checkpoint and SHA-256 manifests are stored under
`evidence/symphony-g62-static`. The CI runs the G6.2 suite and verifies all
three manifests, original FAIL bytes and unchanged upstream observation patch.
Blue offline validation now also accepts the stacked Symphony base branch.
Final exact-head CI IDs/results are filled by the read-back PR checkpoint;
committed evidence does not invent a future commit SHA or CI success.

**Official Symphony behavior changes: NO.** Its pin remains
`be10a1b79df723d6d7612b5651c8522704dafb2e`; unchanged G5.1 patch SHA-256:
`404b4001d279351c8b800816142862ee47dfd209615b0f9211fbe6ccc5170f3b`.
Patch applicability checked on clean pin. Polling, scheduling, continuation,
retry/backoff, stall recovery, concurrency and cleanup are untouched.
Historical G4/G5/G5.1/G6 evidence and real ledgers are immutable.

**LIVE/model/provider count 0; real result adoption 0; actual updateRefs 0.**
The prepare-only adapter is not a write-capable client and cannot be enabled
through configuration. STATIC readiness is not LIVE permission. Before a
separately authorized one-run proof, qualify the restricted sender and real
independent candidate verifier, fresh rules/identities/subscription routes and
complete the [Local LIVE preflight](SYMPHONY_G62_LOCAL_LIVE_PREFLIGHT.md).
Safety protects productive continuation.
