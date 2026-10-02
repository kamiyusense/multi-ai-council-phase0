# Signal Roadmap Step 7-10 prepare-only checkpoint (2026-10-03 JST)

Base: main 25a6488 (fresh readback). Nothing here promotes the production registry, writes Issue #33, merges a PR, or runs any LIVE call. Counters this batch: Jules sessions 0, Jules GET 0, authority reruns 0, OIDC reruns 0, provider/model LIVE 0.

## Step 7 - bind recorded LIVE evidence to the authenticators
| Path | Result | Why |
| --- | --- | --- |
| Owner authority (run 37031275812) | PASS, execution lineage only | A finished manual-dispatch run is immutable. `RecordedRunReader` (digest-bound sanitized readback + exact workflow text, no reusable-workflow call) feeds the unchanged `verify_oidc_workflow_execution` and `OidcBoundAuthorityAuthenticator`: workflow_dispatch, main, exact SHA 4ddb040, attempt 1, actor == triggering actor == 20355232, allowlisted. No durable grant for a real loop event exists yet. |
| Provider (Session 301196275118188780) | lineage VERIFIED, live authentication BLOCKED | A past IN_PROGRESS observation cannot satisfy `JulesDirectReadbackAuthenticator`. Computed blockers: no target PR existed at observation (authenticator needs an open PR with exact head); no durable owner event / fencing token / receipt / evidence refs existed at observation; no sanitized sourceContext / startingBranch / updateTime recorded (PR #246 fixes this only for future runs); the authenticator needs a fresh session read now. The freshness check was not weakened. |

`authority run != provider session` is enforced; same-run/same-source is rejected. Failure injection (tampered digest, push event, rerun, wrong workflow/ref/SHA, split actors, wrong actor, reusable workflow call, stale run, unexpected changed path, changed output head, retry/GET math) is covered in `test_recorded_live_evidence.py`.

**Conclusion: one new LIVE proof is required** (provider authentication cannot be completed from existing evidence).

## Minimal single-LIVE plan (NOT approved; will not start without explicit human approval)
- Prerequisite STATIC work (no LIVE): a bounded runner that authenticates inside the same run that reads Jules; use the adoption candidate registry (DURABLE `chatgpt-semi-auto`) only as an input file on a non-default data branch, never the production registry.
- Order: (1) fresh main readback; (2) create the target branch and an open Draft target PR; record exact head/tree; (3) one human `workflow_dispatch` of the issuer (new run id; run 37031275812 is reserved for the adoption record, one use per purpose); (4) PREPARED state, owner event and grant on the data branch; (5) exactly one Jules session POST, startingBranch = isolated work branch, allowed path `docs/evidence/signal-active-proof-2/PROOF.md`, one-line content; (6) in the publish run, the authenticator performs one fresh GET (`include_activities=false`, sanitized evidence saved by PR #246 code) while the state is QUEUED/PLANNING/IN_PROGRESS; (7) publish, collector readback, registration readiness against the candidate registry; (8) terminal receipt.
- Limits: POST 1, GET <= 2 (1 authenticator read + 1 spare), retry 0, fallback disabled, no sendMessage/approvePlan, no merge of the Jules PR, no production registry or Issue #33 write.
- Stop: any mismatch, a non-active state at the read, timeout, or unknown write outcome => UNKNOWN, read back, never resend; never rerun the same Actions run.
- Evidence: sanitized JSON + digests under `docs/evidence/` on a dedicated branch and an Actions artifact.

## Steps 8-10 (prepare-only)
- Step 8: production-shape chain (publisher -> collector -> registration) runs STATIC with the real recorded authority execution plus a fixture provider: publisher READY, collector COLLECTED, fixture registration READY. These are STATIC passes, not LIVE. Production registry registration: NOT_WIRED.
- Step 9: adoption record + registry diff candidate for `chatgpt-semi-auto` (`docs/evidence/signal-sf8/adoption-record-candidate-*.json`, `registry-candidate-*-durable.json`); the validator accepts it against the current production registry digest; stale / duplicate / wrong-lane / numeric / already-DURABLE cases are rejected. No DURABLE PR was created because readiness is NOT_READY. Production registry stays PLACEHOLDER.
- Step 10: Issue #33 migration prepare artifact `issue33-migration-prepare-20261003.json`: NOT_WIRED, `ISSUE33_MIGRATION_READY = NO`, blockers, CAS write conditions and recovery plan. Issue #33 is STOPPED (owner NONE) and was not written.

## Readiness (machine-readable: `docs/evidence/signal-sf8/readiness-report-20261003.json`)
DURABLE promotion candidate: NOT_READY. stable_identity NOT_RUN; provider_authentication BLOCKED; registration_ready BLOCKED (production NOT_WIRED); owner_authority_authentication PASS/LIVE (execution lineage); prepared_persistence, canonical_receipt, publisher_accepted, collector_readback PASS but STATIC (not LIVE); negative/recovery tests PASS.

Design finding: `stable_identity` and `registration_ready` are evaluated on the production registry, so they can only pass after the adoption merge, which should itself follow readiness. Follow-up: evaluate those two checks against the candidate registry before the merge. Not changed here.

## Human decisions left
A. Merge the `chatgpt-semi-auto` PLACEHOLDER -> DURABLE adoption (only after the single LIVE proof passes). B. Migrate Issue #33 (only after A). C. Approve ONE additional LIVE proof (required: existing evidence is not reusable for provider authentication) and one more human dispatch of the issuer.
