# Verifier source contract v1 — static checkpoint

## Baseline

- Baseline main: `3e14cb41ce3a30f9b17e3ac4837fe587caf89e25`.
- PR #66 was merged before this batch.
- PR #68 is an independent unmerged Status dispatch/readback branch and is not
  a dependency of this branch.
- Issue #33 remains a display surface; this batch does not mutate it.

## Purpose

The existing runtime publisher already requires independent
`AuthorityGrantVerifier` and `ProviderVerifier` interfaces. This batch defines
what source material those verifier roles may consume without declaring any
particular production system trustworthy.

A JSON record is never sufficient merely because it contains
`verification_state=VERIFIED`.

## Implemented

`runtime_verifier_sources.py` adds:

- normalized Authority verification-source contract;
- normalized Provider verification-source contract;
- structural validators with bounded secret-free proof references;
- injected `VerificationSourceReader` interface;
- injected `VerificationSourceAuthenticator` interface;
- `VerifiedSourceAttestation`, which must independently bind source kind,
  source id, source ref and observation time;
- `SourceBoundAuthorityGrantVerifier`, implementing the existing authority
  verifier contract;
- `SourceBoundProviderVerifier`, implementing the existing provider verifier
  contract.

Verification succeeds only after:

1. source readback exists;
2. source structure is valid;
3. source context matches the existing grant/evidence/receipt/observation;
4. source state is VERIFIED;
5. the independent authenticator returns an exact matching attestation.

Missing reader, missing authenticator, rejected authenticator, mismatched source,
mismatched attestation, malformed source or UNKNOWN/REJECTED source all fail
closed.

## Schemas / fixtures

Added schemas:

- `authority_verification_source.schema.json`
- `provider_verification_source.schema.json`

Added deterministic fixtures under
`automation/command_bus/tests/fixtures/verifier_sources/`.

Fixtures are test material only and do not establish production trust.

## Explicitly not implemented

- no production authority-grant issuer;
- no production source reader;
- no production authenticator;
- no claim that GitHub JSON presence proves verification;
- no provider/model/Jules/Claude execution;
- no Status workflow dispatch;
- no Issue #33 mutation;
- no ownership acquisition/handoff/takeover;
- no Merge or default-branch write.

## Production boundary remains UNKNOWN

The real independently trustworthy source for authority and provider verification
is still unresolved. This branch intentionally defines only the contract and
fail-closed integration points.

## Exact-head verification

- Exact tested code head:
  `f5093122bd2de93f09aee460b12767769bb116e5`.
- GitHub Actions run:
  `36371154522` — **SUCCESS**.
- Focused Status/runtime/validation suite:
  **154/154 PASS**.
- Full command-bus suite:
  **441/441 PASS**.
- Command-bus JSON schemas parsed:
  **18/18 PASS**.
- Python compileall:
  **PASS**.
- `git diff --check`:
  **PASS**.
- PR #69 was OPEN / mergeable=true at exact-head readback.
- Any commit after this exact tested head must be documentation-only and compared
  before Merge.
