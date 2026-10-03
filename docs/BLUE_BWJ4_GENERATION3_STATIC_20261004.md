# BWJ-4 generation 3: separately approved one-shot transport proof

## Authority and scope

User approval received 2026-10-04 06:55:06 JST covers the necessary generation-3
activation/authorization PR after exact-head CI and inspection, its Merge, and
one new transport-only workflow activation. Authorization expires 12:50 JST
the same day, within six hours. This document does not expand that approval.

- New identity: `blue-bwj4-20261003T220252Z-transport-proof-01`.
- Proof generation: **3**; active worker generation: **1**, unchanged.
- Candidate JSON is disabled; active authorization requires inspected Merge.
- Existing `Blue BWJ-4 one-shot read-only transport proof` is reused unchanged.
- Activation/run/review/logical Blue wake/terminal receipt: at most one each.
- Provider CREATE/GET/model, Jules submit/GET, claim reservation, next command,
  target mutation/adoption/retry: **0**. Fallback: **disabled**.
- No new service, token, secret, worker setting or workflow permission change.

## Fresh starting readback

Repository ID `1378815294`, owner/name `kamiyusense/multi-ai-council-phase0`.
Initial main `3602efe921a00474001d5075446027c4712bccee`, tree
`d3873700bd2b7011b43324ca3da91c49339cb7b1`.
During STATIC preparation unrelated Signal/Relay merges advanced main to
`dc84111e01725aa115c40872b7cb1ec81242e3fb`, tree
`2d56f499cb846ca87b43460d9fc837fa82eb8b8a`. Their complete 25-path diff did
not touch the Blue proof implementation/workflow/authorization or carriers.
The candidate is based on this fresh main; future execution binds fresh values.

Target #172 OPEN/unmerged, `cloud-work/replacement-proof-v1`, HEAD
`0e7d96df29cfedbe4f95de444e4f7a9a7efd6577`, tree
`815045e5162b717c14a833ca0104c885cfbc1feb`.
Unique Blue carrier #167 OPEN/unmerged, `cloud-work/carrier-blue-v1`, HEAD
`5f9e210bc17ed695610e23b1c1699e11f5c8ed4b`, tree
`91b0fecc3be70a894f98e8cda89f32006e467f0a`.
Worker-state blob `17d4d62ad8eacc6118325eb4eb98cc72d1c0e70c`, active generation 1.
Workflow blob `16c9564b4b9c612fbf8a84cbb039d00bc0c08cfb` remains unchanged.
All values must be fresh-read again before dispatch; carrier HEAD is distinct
from expected target HEAD. No carrier or target branch is edited by this PR.

## Exact consumed history: never replay

| Proof | Run / job | Attempt | Terminal cause | Review / wake / receipt |
| --- | --- | --- | --- | --- |
| generation 1, `blue-bwj4-20261002T212217Z-transport-proof-01` | 37147398998 / 111274071729 | 1 | FAIL, canonical pagination scope violation | 0 / 0 / 0 |
| generation 2, `blue-bwj4-20261003T194515Z-transport-proof-01` | 37155471365 / 111297860366 | 1 | FAIL, final main drift during preflight | 0 / 0 / 0 |

Both activations are consumed. No rerun, failed-job rerun, same-ID dispatch,
direct review completion or manual receipt is permitted. Neither is promoted
to PASS. Their failed preflight, skipped durable attempt/POST, and empty
artifact collections were fresh-read. Generation-2 terminal checkpoint:
https://github.com/kamiyusense/multi-ai-council-phase0/pull/288#issuecomment-5973204298
The retained local generation-2 log snapshot has SHA-256
`32098448552978bef4e29991b1211375f856b60fe909c72cb582f61128f96baf`;
a hash is not origin authentication. GitHub run/job/commit are authoritative.

## Minimal change and static verification

The existing exact history verifier is reused for each of two explicit consumed
FAIL identities. Only generations 1, 2 and 3 are accepted. Generation 3 demands
the exact ordered two-entry authorization lineage, all three run identities,
attempt 1, exact old origin/head/workflow/actor/jobs/pre-POST failure steps and
empty old artifact collections. Generation-2 historical authorization must
still retain generation 1. Incomplete, extra, duplicate or rerun history stops.
Durable attempt and pre-POST validation bind generation and the same lineage.
Both old command/receipt identities must remain absent on Blue's carrier.

Initial/repeated/final main fences, workflow/auth/target/carrier/state/record
fences and exclusive post-consumed marker are retained. No fence is relaxed.
The generation-2 final-main-drift failure has a direct fake-reader regression.
Canonical pagination remains restricted to exact repository ID 1378815294;
endpoint/filter/host/scheme/encoding/redirect/credential drift remains rejected.

Offline tests reuse existing fakes: prepare → durable local attempt → fake
review → fake Work receipt → unchanged target. Missing receipt stays UNKNOWN,
duplicate receipt/review is rejected, and a valid receipt does not by itself
authenticate the wake origin. No HTTP sender or real Work is invoked by mocks.
Focused local verification: 66 tests passed, zero failures/errors.
Full regression on current main dc84111e: 1583 tests, failures/errors 0, skip 1;
compileall and diff check PASS. Four-lane STATIC soak: 32 virtual loops,
invariant violations 0, external execution 0. BWJ-4/5/6 boundary MOCK PASS,
provider/model/review/wake/claim/Jules/external/permission/network/process 0.
Exact-head Actions results are recorded in the PR checkpoint after completion;
totals are observations, not fixed limits.
Known skip: Windows-only production bootstrap ACL boundary on Linux.

## Activation and evidence

Before Merge: inspect exact PR HEAD/diff, CI/artifacts and current-main changes.
Before dispatch: fresh main/tree/workflow/auth/code blobs, repository, unique
carrier/protocol/worker generation, target/head/tree, complete two-run history,
all carrier records, new identity absent, expiry, active/queued Actions and
observable auto-merge states. Repeat these bindings immediately before clicking.
Unobservable external human intent is not a guarantee of no concurrent Merge;
the exact runtime main fence stays authoritative and consumes a drifted run.

Dispatch only on main, with fresh `approved_main`, sealed new `proof_id`, and
fresh `approved_workflow_blob`; click once. Any ambiguous write: readback only,
no resend. ATTEMPTING artifact must exist and be verified before the sole review
POST. Read back run/job/attempt/head/steps/logs/artifact/digest, exact review,
independent intended worker origin, one bound timely terminal receipt and
target HEAD/tree before/after. Review or Actions success alone is not PASS.
Missing receipt or independently unverifiable wake is UNKNOWN; main drift is
FAIL/activation consumed. No new proof is created after a failed LIVE attempt.

Checkpoint on this PR records CI and later LIVE outcome. Old checkpoints remain
intact. Recovery uses GitHub records, never resends an ambiguous operation.
Rollback: do not dispatch; after any activation, retain all evidence and use a
new ordinary non-default PR to disable authorization. No direct-main write,
branch deletion, force push or automatic rollback Merge is permitted.

BWJ-0–3 remain reused STATIC-ready. BWJ-4 is still unproven until complete LIVE
evidence; BWJ-5 additional LIVE and BWJ-7 remain out of scope. Production Jules
Session source authentication remains NOT_WIRED.
