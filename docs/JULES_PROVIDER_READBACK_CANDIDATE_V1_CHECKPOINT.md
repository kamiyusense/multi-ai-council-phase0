# Jules provider readback candidate v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`97ac263fc63ddc7242ae22b471eb7ff880005504`

PR #94 / #95 were already merged before this batch.

Issue #33 remained the deployed single-loop STOPPED display.

No Jules API call, provider/model execution, owner publication, authority grant,
runtime state write, or Issue mutation is performed in this batch.

## Purpose

Bridge the existing durable Semi-Auto ACQUIRE prepare bundle to the already
merged source-bound provider verification contract without inventing a new trust
mechanism.

Existing main already provides:

- `SourceBoundProviderVerifier`;
- normalized provider verification-source contract;
- injected `VerificationSourceReader`;
- injected independent `VerificationSourceAuthenticator`;
- fail-closed behavior when authenticator/source is missing or mismatched.

This batch only normalizes Jules Session GET evidence for that contract.

## Raw Jules state is preserved

Added:

`automation/command_bus/jules_provider_readback_candidate.py`

A Jules Session GET is converted into a
`JulesProviderReadbackCandidate`.

The adapter preserves the Jules `state` exactly.

It does not map:

- QUEUED -> RUNNING;
- COMPLETED -> RUNNING;
- any unknown state -> healthy.

This prevents presentation/provider convenience mapping from becoming runtime
correctness.

## Session identity / time binding

The candidate requires:

- exact Session id matching the ACQUIRE bundle;
- Session GET `createTime` exactly matching the owner claim timestamp;
- timezone-aware Session GET `updateTime`;
- updateTime not before acceptance;
- updateTime strictly inside the owner lease.

Private Jules/GitHub URLs in the raw response are not retained.

Safe opaque refs only are retained:

- `jules-session:<session_id>`
- `jules-api:sessions/<session_id>`

## Active ACQUIRE binding

Added:

`bind_jules_active_provider_readback()`

A candidate may be rebound into active durable ACQUIRE evidence only when the
raw Jules state is exactly:

`RUNNING`

QUEUED and COMPLETED remain observable candidates but are not accepted as
active-owner proof.

The binding updates the existing prepared:

- runtime evidence `provider_state`;
- runtime evidence `observed_at`;
- provider observation input `state`;
- provider observation input `observed_at`;
- TransitionRequest evidence/observation members.

The timestamp used is the later Session GET `updateTime`.

The adapter does **not** retroactively claim that the provider was RUNNING at
the earlier Session acceptance time.

## Provider verification source material

`build_provider_verification_source()` builds the normalized source document
expected by the existing `SourceBoundProviderVerifier`.

Even when the document contains:

`verification_state = VERIFIED`

that string is not authority or verification by itself.

The existing verifier still requires an independently injected
`VerificationSourceAuthenticator` to return an exact matching
`VerifiedSourceAttestation`.

Expected behavior:

```text
source says VERIFIED
+ authenticator missing
= no provider verification

source says VERIFIED
+ authenticator rejects
= no provider verification

source says VERIFIED
+ exact independent attestation
+ exact evidence/receipt/observation binding
= VerifiedProviderObservation
```

UNKNOWN / REJECTED sources never invoke successful verification even if an
authenticator object exists.

## Tests

Added coverage for:

- RUNNING Session GET -> bounded UNKNOWN source candidate;
- raw QUEUED / COMPLETED state preservation;
- later RUNNING readback rebinds evidence/observation time;
- source text VERIFIED without authenticator -> no verification;
- rejecting authenticator -> no verification;
- exact independent attestation -> VerifiedProviderObservation;
- QUEUED / COMPLETED cannot bind active ACQUIRE;
- Session id mismatch -> fail closed;
- Session createTime mismatch -> fail closed;
- updateTime before acceptance -> fail closed;
- updateTime at/after lease expiry -> fail closed;
- private URL content is not persisted;
- UNKNOWN / REJECTED source states remain non-verifying;
- input Session GET object is not mutated.

## Relationship to authority

This batch does not solve owner authority.

The existing durable owner authority path still separately requires:

- append-only authority grant;
- exact owner/event/target/receipt binding;
- independent `AuthorityGrantVerifier`;
- independent source authentication.

Provider verification and owner authority remain independent trust boundaries.

## Explicitly not performed

- no live Jules Session GET;
- no Jules API call;
- no provider/model execution;
- no Secrets read/change;
- no runtime state/receipt/evidence/owner/provider-observation write;
- no authority grant;
- no provider source persistence;
- no live authenticator wiring;
- no Status workflow dispatch;
- no Issue #33 mutation;
- no registry PLACEHOLDER -> DURABLE promotion;
- no final stable loop_id assignment;
- no Merge in this batch.

## Remaining live boundary

For ChatGPT Semi-Auto, remaining production work is now concentrated in:

1. explicitly adopt a stable durable loop_id;
2. persist the initial PREPARED state and canonical dispatch receipt;
3. persist/read a normalized Jules provider source;
4. connect a real independently trustworthy provider-source authenticator;
5. issue and persist a matching owner authority grant;
6. connect a real independently trustworthy authority-source authenticator;
7. only then publish ACQUIRE;
8. collect/read back the durable transition;
9. only then consider Control Tower identity_state=DURABLE.

Until independent trust sources are wired:

`ChatGPT Semi-Auto durable ACQUIRE = PREPARE_ONLY / NOT_WIRED`

## Exact-head verification

- exact tested PR head:
  `ad2438c891353bba6426041ce353261f3d9464fe`
- GitHub Actions run:
  `36443292614` — **SUCCESS**
- focused Status/runtime/validation suite:
  **318/318 PASS**
- full command-bus suite:
  **731/731 PASS**
- command-bus JSON schemas parsed:
  **22/22 PASS**
- Python compileall:
  **PASS**
- `git diff --check`:
  **PASS**
- representative provider-readback tests were present in the exact-head CI log:
  - later RUNNING readback rebinds evidence/observation to Session GET updateTime;
  - source text VERIFIED without authenticator grants no verification;
  - rejecting/missing authenticator grants no verification;
  - exact independent attestation is required;
  - QUEUED / COMPLETED cannot bind active ACQUIRE;
  - private URL content is not persisted.
- initial failed run:
  `36443127777` failed only because the test expected a source-reader call even
  though the existing verifier correctly short-circuits when authenticator is
  absent. The test expectation was corrected; no runtime/live write occurred.
- tested head -> current head compare:
  to be read back after this documentation-only evidence commit.
- live Jules execution:
  **NONE**
- Issue #33 live mutation:
  **NONE**
