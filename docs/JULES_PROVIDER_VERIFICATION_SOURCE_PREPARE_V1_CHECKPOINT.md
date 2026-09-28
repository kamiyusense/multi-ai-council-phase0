# Jules provider verification source prepare v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`97ac263fc63ddc7242ae22b471eb7ff880005504`

Fresh readback showed PR #94 and PR #95 already merged before this batch.
PR #93 and PR #98 had also advanced main with Claude -> Jules Semi-Auto bridge work.

Issue #33 remained:

`🚦 Phase 0 Loop Status — ⚫ STOPPED`

with zero comments.

No live Control Tower migration or provider execution is performed here.

## Purpose

The durable Semi-Auto ACQUIRE prepare adapter can now produce:

- owner generation 1 ACQUIRE;
- canonical dispatch receipt;
- canonical provider evidence;
- provider observation input;
- PREPARED -> RUNNING TransitionRequest.

However, the existing RuntimeTransitionPublisher still requires an independent
ProviderVerifier.

The repository contains the generic source-bound verifier contract, but no
production Jules authenticator.

This batch adds only a **normalization layer** from Jules Semi-Auto material into
that verifier-source contract.

It deliberately does **not** authenticate the provider.

## Added

`automation/command_bus/jules_provider_verification_source.py`

The normalizer accepts:

- prepared provider observation input;
- canonical runtime evidence;
- canonical dispatch receipt;
- exact Jules session id;
- bounded safe opaque proof refs.

It emits the existing Provider Verification Source shape.

## Verification state

The output always starts as:

`verification_state = UNKNOWN`

The prepare module has no API that can promote a source to VERIFIED.

An explicit helper named `mark_provider_source_verified()` exists only to fail
closed with a RuntimeError, documenting that trust promotion is unavailable in
this layer.

## Exact binding

The source is bound to:

- source_ref = `jules-session:<session_id>`;
- provider_kind = JULES;
- provider_state from canonical evidence;
- observation id;
- loop_id;
- owner role / holder;
- generation / fencing token;
- repository / target PR / target head;
- command / correlation;
- canonical source receipt;
- canonical evidence ref;
- observed_at / expires_at;
- bounded safe opaque proof references.

Mismatched receipt/evidence/observation/session bindings fail closed.

## Proof refs

Proof refs must be:

- 1..32 items;
- unique;
- safe opaque refs;
- free of URL syntax.

Examples of syntactically acceptable refs include:

- `jules-session:<id>`
- `github-actions-run:<id>`

Syntactic acceptance is not authentication.

## Independent Authenticator remains mandatory

The generic `SourceBoundProviderVerifier` still requires both:

- VerificationSourceReader;
- VerificationSourceAuthenticator.

The tests prove:

```text
normalized source = UNKNOWN
+ source reader
+ authenticator = None
=> verifier returns None
```

Even if a caller mutates an in-memory source document to say:

`verification_state = VERIFIED`

the verifier still returns None when the independent authenticator is absent.

Therefore JSON self-assertion cannot grant provider trust.

## Tests

Coverage includes:

- exact normalized source binding;
- source always starts UNKNOWN;
- prepare layer cannot mark VERIFIED;
- missing authenticator never verifies;
- caller-mutated VERIFIED source still fails without authenticator;
- session id/source_ref mismatch fails;
- empty/duplicate/URL proof refs fail;
- caller-supplied `verified=true` observation fails;
- receipt/evidence/context mismatch fails.

## Explicitly not performed

- no production VerificationSourceReader;
- no production VerificationSourceAuthenticator;
- no Jules API call;
- no provider/model execution;
- no owner authority issuance;
- no provider observation write;
- no runtime state write;
- no Status dispatch;
- no Issue #33 mutation;
- no registry identity promotion;
- no final stable loop_id assignment;
- no Merge in this batch.

## Remaining live trust boundary

For ChatGPT Semi-Auto durable ownership, production integration still requires:

1. explicit stable durable loop_id adoption;
2. PREPARED state persistence;
3. canonical dispatch receipt persistence;
4. an independently authorized owner authority source;
5. a production Jules VerificationSourceReader;
6. a production Jules VerificationSourceAuthenticator;
7. RuntimeTransitionPublisher publication;
8. durable collector readback;
9. only then Control Tower identity promotion.

The exact production trust source / authenticator remains:

`JULES-PROVIDER-AUTHENTICATOR-001 = UNKNOWN`

This is a real trust-boundary blocker and is not guessed in this PR.

## Evidence to fill after exact-head CI

- exact tested PR head: PENDING
- GitHub Actions run: PENDING
- focused tests: PENDING
- full command-bus tests: PENDING
- schema parse: PENDING
- compileall: PENDING
- git diff --check: PENDING
- tested head -> current head compare: PENDING
- live Jules execution: MUST REMAIN NONE
- Issue #33 live mutation: MUST REMAIN NONE
