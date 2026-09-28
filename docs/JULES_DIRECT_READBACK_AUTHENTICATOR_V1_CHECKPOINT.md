# Jules direct-readback authenticator v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`97ac263fc63ddc7242ae22b471eb7ff880005504`

Issue #33 remained the deployed single-loop STOPPED display.

PR #100 provider-source normalization may still be open independently.
This authenticator branch does not depend on PR #100 implementation files; it
implements the existing generic VerificationSourceAuthenticator contract.

## Why this exists

The generic provider verifier deliberately refuses to trust a normalized JSON
source by itself.

A production Jules path therefore needs an authenticator that gets fresh
provider-side and GitHub-side facts independently of the caller-supplied source.

Jules' official REST API documents:

`GET /v1alpha/sessions/{sessionId}`

for retrieving one session by ID, including session state, createTime and source
context.

Reference:

`https://jules.google/docs/api/reference/sessions`

No Jules API call is executed by this PR.

## Added

`automation/command_bus/jules_direct_readback_authenticator.py`

The class:

`JulesDirectReadbackAuthenticator`

implements the existing VerificationSourceAuthenticator shape.

It requires three injected dependencies:

- JulesSessionReader
- JulesTargetReader
- Clock

The module itself performs no network I/O and stores no credential.

## Authentication flow

For one normalized VERIFIED provider source:

1. validate the existing provider-verification-source schema;
2. require the caller's expected context to match the normalized source;
3. parse the opaque `jules-session:<id>` source ref;
4. require the source to be within its observed/expires time window;
5. fresh-read the Jules Session by session ID;
6. require exact session resource name / optional id / createTime;
7. require the provider-side repository source;
8. obtain provider-side starting branch;
9. fresh-read the target GitHub PR by expected repository/PR;
10. require exact repository / PR / head / branch;
11. require target OPEN / not merged;
12. require bounded direct-readback proof refs;
13. only then return VerifiedSourceAttestation.

Any mismatch returns None.

## Conservative provider-state mapping

For source provider_state:

`RUNNING`

the direct Jules session state is accepted only when it is one of:

- QUEUED
- PLANNING
- IN_PROGRESS

The authenticator deliberately does not reinterpret:

- COMPLETED
- FAILED
- PAUSED
- AWAITING_PLAN_APPROVAL
- AWAITING_USER_FEEDBACK

as RUNNING.

This avoids turning a waiting/terminal provider state into active liveness by
guessing.

If future product behavior requires a richer mapping, it must be an explicit
reviewed change.

## Target binding

The direct target readback must prove:

- exact repository;
- exact PR number;
- exact commit head;
- exact branch matching Jules startingBranch;
- state = open;
- merged = false.

A provider session alone therefore cannot authenticate stale or moved target
context.

## Proof refs

The source must contain at least these direct-readback identifiers:

- `jules-session:<session_id>`
- `github-pr:<expected_pr>`
- `github-head:<expected_target_head>`

These strings are locators/audit references only.

They are not the trust source.

Trust comes from the injected fresh readers and exact comparisons.

## Tests

Mock coverage includes:

- exact Jules + GitHub readbacks return VerifiedSourceAttestation;
- missing session reader -> fail closed;
- missing target reader -> fail closed;
- missing clock -> fail closed;
- QUEUED / PLANNING / IN_PROGRESS are accepted for RUNNING;
- COMPLETED / FAILED / PAUSED / AWAITING_* are rejected for RUNNING;
- session name/id/createTime/repository/branch mismatch -> fail closed;
- target repo/PR/head/branch/state/merged mismatch -> fail closed;
- source verification_state != VERIFIED -> fail before readback;
- expected context mismatch -> fail before readback;
- expired/future source -> fail before provider read;
- missing required direct-readback proof refs -> fail closed;
- non-RUNNING provider state is not invented.

## Production boundary

This PR provides the authentication logic, not the live transport adapter.

A production implementation still needs an injected JulesSessionReader that
performs the authenticated Jules GET Session request.

Jules' official API currently authenticates requests with an API key in the
`x-goog-api-key` header.

Reference:

`https://jules.google/docs/api/reference/authentication/`

No API key is created, displayed, changed, committed or used by this PR.

## GitHub Actions note

GitHub Actions OIDC and artifact attestations are possible future hardening
options for proving workflow provenance.

GitHub documents workflow/run/repository/ref/SHA claims in Actions OIDC and
Sigstore-backed artifact attestations.

References:

- `https://docs.github.com/en/actions/reference/security/oidc`
- `https://docs.github.com/en/actions/concepts/security/artifact-attestations`

This PR does not request `id-token: write` or `attestations: write` and does
not change workflow permissions.

## Explicitly not performed

- no Jules API GET;
- no Jules API POST;
- no API key use/change;
- no workflow permission expansion;
- no artifact attestation generation;
- no owner authority issuance;
- no runtime ledger write;
- no provider observation write;
- no Status dispatch;
- no Issue #33 mutation;
- no registry identity promotion;
- no final stable loop_id selection;
- no Merge in this batch.

## Remaining boundary

After this static authenticator is verified, the remaining provider-side work is
a concrete production JulesSessionReader transport and approved secret use.

Owner authority remains a separate trust path.

Therefore:

- Jules provider authentication logic: STATIC IMPLEMENTED
- live Jules reader transport: NOT_WIRED
- owner authority production source: NOT_WIRED
- live durable ACQUIRE: NOT_WIRED

## Exact-head verification

- exact tested PR head:
  `9786ea4d66be0f928a5c7dbd9581107320c6bea9`
- GitHub Actions run:
  `36400187843` — **SUCCESS**
- focused Status/runtime/validation suite:
  **301/301 PASS**
- full command-bus suite:
  **730/730 PASS**
- command-bus JSON schemas parsed:
  **22/22 PASS**
- Python compileall:
  **PASS**
- `git diff --check`:
  **PASS**
- representative tests present in the exact-head CI log:
  - fresh Jules + GitHub readbacks return attestation;
  - only QUEUED / PLANNING / IN_PROGRESS authenticate RUNNING;
  - target repo/PR/head/branch/open-state must match;
  - expired/future source fails before provider read.
- tested head -> current head compare:
  to be read back after this documentation-only evidence commit.
- live Jules execution:
  **NONE**
- Issue #33 live mutation:
  **NONE**
