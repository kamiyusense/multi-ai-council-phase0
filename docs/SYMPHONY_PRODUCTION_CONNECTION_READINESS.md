# Production connection readiness — 2026-10-12

Result: **PRELIVE_BLOCKED / INSTALLATION_NOT_ACTIVATED / LIVE_NO_GO**.
This implementation is a reviewable connection layer, not an activation or a
claim that one production run can currently launch. No real model/thread,
OIDC issuance, runtime GitHub mutation, candidate adoption or Merge occurred.

## Fresh source and scope

Starting main: `c989aeb08018684ed092c6ce9b78a434903e4b8c`.
Merged ancestors: #320 `ff09d0c4fba2f34a58272543c3b369a001a52952`,
#343 `d1f47a7ae79dd222a4a878a2d8f7c1fb3b0f986a`,
#364 `c989aeb08018684ed092c6ce9b78a434903e4b8c`.
Development branch: `codex/symphony-production-connection-v1`.
Existing checkouts and historical evidence remain intact. No earlier terminal
receipt is replayed. The raw user work order is preserved byte-exact locally;
its digest is in this batch's checkpoint.

## Connected code and independently observed limits

| Part | Concrete connection | Evidence / remaining boundary |
|---|---|---|
| A: installed Codex | `JsonlCodexAppServer.probe_read_only` shares the existing JSONL initialize/account/config path; account refresh is false; a later worker must read afresh in its own process | Actual installed binary version/schema observed; actual initialize fails before account/config; subscription **UNKNOWN** |
| A: schema adapter | thread/start uses installed `sandbox` and `ephemeral`; turn/start uses `sandboxPolicy` with network false and exact writable root | Real generated schema plus mock request capture; actual thread/start/turn/start **NOT EXECUTED** |
| B: review | `IndependentReviewReader` GETs a separate reviewed main/source pin and validates exact path, Git blob SHA, SHA-256 and canonical unsigned bytes | No candidate-selected path/source; no production approval record installed; a file hash alone is not approval |
| B: runtime | `GitHubJobContextReader` independently GETs repository/run/job/workflow/current main and binds actor, first attempt, manual main event and exact source | REST-shaped integration tests; actual approved production job **NOT CREATED** |
| B: memory JWT | `MemoryOnlyOIDCRequest` performs one explicit same-job audience-bound request after fresh context; `attach_reviewed_runtime` calls existing `attach_same_job` | Durable issuer intent precedes request, signature verification precedes capability; all token tests are mocks; **NO REAL OIDC REQUEST** |
| B: narrow capability | `ReviewedNarrowCapabilityFactory` requires independently approved credential/permission callbacks; private capability exposes fixed objects, exact CAS and scoped create-only ledger only | All real wire calls are mocked; no runtime credential acquired; no generic client exposed to worker |
| B: durable ownership | `AppendOnlyAdoptionStore` distinguishes concurrent owners with internal random operation claim; sender requires owning nonce create, duplicate never grants send | Actual in-memory races/lost-reply/fork tests; immutable legacy record readback retained |
| C: independent verifier | `PinnedVerifierExecutor` derives commands from existing authenticated source/snapshot route, rechecks pins, runs cached images offline, bounds output/time | **Three real Docker invocations PASS** on explicitly synthetic inputs; candidate code is never executed; no real worker qualification |
| C: artifact provenance | Existing `GitHubArtifactArchive` / `OperatorCandidateVerifier.read` retain strict run/job/head/archive/blob checks | Local Docker archive is not uploaded or adopted; separate automatic STATIC CI artifact GET/hash is diagnostic evidence only |
| D: stage / launch | Existing `validate_stage` freezes all baseline bytes except the one approved artifact; collision is GET-only | No stage ref created; no dispatch; both production workflow job conditions stay `${{ false }}`; CLI remains `NOT_INSTALLED` |

Official Symphony's scheduler, tracker polling, selection, retry/backoff,
continuation, stall recovery, concurrency, workspaces and observer patch are
unchanged. The one-turn proof adapter remains a strict proof profile, not a new
scheduler or a replacement for Official Symphony's productive continuation.

## Actual host diagnosis

WSL Linux and installed `codex-cli 0.162.0-alpha.17.2` were observed. The binary
emitted 317 public JSON-schema files. A read-only initialize request failed with
SQLite-related stderr and process exit 1, before any account/config response.
Only safe keyword/type/length diagnostics and filesystem metadata were saved;
no stderr body, database content, auth file, email, JWT or secret was saved.
There were three bounded diagnostic initialize attempts while distinguishing
stdio/client formatting; **thread starts 0, model turns 0**. No settings, database,
login or credential repair was attempted. The installed account and effective
subscription route remain UNKNOWN, not exhausted quota. Quota was not queried.

The Windows-mounted synthetic workspace could not pass fixture preparation.
New generated Docker inputs were prepared in native WSL storage instead;
existing Windows inputs were preserved. This was a STATIC preparation repair,
not another LIVE launch. Actual cached Python and gitleaks images ran with
network none, uid 65534, readonly source/candidate, dropped capabilities,
no-new-privileges, bounded CPU/memory/PIDs and no credential/socket mounts.
Only return codes and output digests survived. The fixture lifetime is explicitly
synthetic; its in-memory attestation is not production authority.

## Platform permission evidence

Repository readback reports owner/admin/push metadata, but that is not a direct
operator approval, a credential capability proof, or proof of branch rules.
Main protection, rulesets and main rules GETs return **403 → UNKNOWN**. Nothing
was changed to obtain those rights. Workflow API state is `active` (registered);
execution is independently hard OFF in the actual YAML. Removing a job condition
alone still reaches `NOT_INSTALLED` and cannot authorize a sender.

Minimum future installation requirements and the remaining reviewed installer
connections are in [activation review](SYMPHONY_PRODUCTION_ACTIVATION_REVIEW.md).
Until effective branch rules/credential scope and approved pins are independently
established, existing constraints gates refuse issuance and sending.

## Test and evidence contract

Baseline main passed 2861 tests (one Windows ACL test skipped). New tests exercise
actual adapter logic using explicit mock HTTP/token/subprocess boundaries:
independent source/context, same-job attachment, false permissions, OIDC mismatch,
wrong HEAD/actor/rerun, lost reply, duplicate and concurrent ownership, immutable
legacy records, scoped create-only ledger, exact CAS, and no model admission from
read-only probe. Imported helper TestCases are not rediscovered as extra tests.

A regression exposed an old expectation that an acknowledged deleted binding
could be recreated. The updated test holds UNKNOWN without another create,
then resumes by restoring the exact original fixture record and GET replay.
Historical evidence still verifies the old test/source at its original Git pin;
no historical manifest or receipt is resealed. New source and evidence have a
separate current manifest. Counts, logs and hashes are in
`docs/evidence/symphony-production-connection/`; final development HEAD, remote
blob/tree and automatic CI artifact hashes are appended to the Draft PR.

## First one-LIVE plan — preparation only

1. Resolve this host's SQLite initialization failure through separately reviewed
   host repair; then get fresh account/read and config/read in the same process,
   refresh false, no API keys/custom endpoints/paid fallback. Stop if UNKNOWN.
2. Independently review exact new merged installation source, public issuer/JWKS,
   effective GitHub credential/rules, runtime pins and memory-only boundaries.
3. Review a separate activation change and authorize its installation/permissions;
   no removal of OFF guards is included in this development PR.
4. Grant one fresh LIVE with new Issue/campaign/workspace/proof/ledger identities,
   exact starting HEAD, one approved artifact and bounded observer/cleanup plan.
   Never reuse #336/#341 or prior terminal receipts.
5. Run Official Symphony once with natural continuation; capture durable real
   STARTED/worker-lifecycle TERMINAL and observer-only restart duplicate NOOP.
6. Preserve exact candidate snapshot/objects; independently approve immutable
   stage lease and manual exact-head verifier job before any stage/dispatch.
7. GET uploaded artifact and hash, check all source/candidate/target/scope pins;
   separately approve exact sender envelope. One expected-beforeOid force:false
   nondefault CAS at most; uncertain write means readback, never blind resend.

These are distinct future approval boundaries. This plan does not authorize
LIVE, OIDC, staging, dispatch, candidate adoption or publication now.

Protocol reference: [official Codex app-server documentation](https://learn.chatgpt.com/docs/app-server).
The installed binary schema, not a recalled API version, governs adapter fields.
