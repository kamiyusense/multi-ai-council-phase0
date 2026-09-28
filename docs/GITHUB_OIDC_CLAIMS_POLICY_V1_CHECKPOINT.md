# GitHub OIDC claims policy v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`97ac263fc63ddc7242ae22b471eb7ff880005504`

PR #106 remains open and independently contains the Jules Session GET provider
readback candidate work.

This batch is independent of PR #106 and does not depend on its code.

Issue #33 remains the deployed single-loop STOPPED display.

## Purpose

Prepare the post-cryptographic-verification claims policy for a possible future
GitHub Actions OIDC trust source without enabling OIDC or changing workflow
permissions.

This batch does not:

- request an OIDC token;
- parse a JWT;
- verify a JWT signature;
- download or trust JWKS;
- grant provider verification;
- grant owner authority.

It only checks exact expected claims after a future cryptographic verifier has
already established token authenticity.

## Official GitHub facts used

GitHub's current OIDC reference documents custom claims including:

- repository
- repository_id
- repository_owner_id
- ref
- sha
- workflow_ref
- workflow_sha
- event_name
- run_id
- run_attempt
- runner_environment
- job_workflow_ref for reusable workflows

GitHub also documents that requesting an OIDC JWT requires:

`id-token: write`

and that this permission enables token retrieval without granting write access
to other GitHub resources.

No permission change is made here.

References:

- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.github.com/en/actions/concepts/security/openid-connect

## Implemented

Added:

`automation/command_bus/github_oidc_claims_policy.py`

The module exposes:

- `GitHubOidcExpectedContext`
- `GitHubOidcClaimsPolicyDecision`
- `evaluate_github_oidc_claims_policy()`

Result states:

- MATCH
- BLOCKED

MATCH means only:

`the supplied claims match the configured policy`

It does **not** mean:

- JWT signature verified;
- GitHub issuer key verified;
- provider authenticated;
- owner authority granted;
- RuntimeTransitionPublisher may write.

## Exact context binding

The policy requires exact matches for:

- issuer = `https://token.actions.githubusercontent.com`
- audience
- subject
- repository
- repository_id
- repository_owner_id
- ref
- SHA
- workflow_ref
- workflow_sha
- event_name
- run_id
- run_attempt = `1`
- runner_environment = `github-hosted`
- repository_visibility

If a reusable workflow is expected, `job_workflow_ref` must be explicitly
configured and match exactly.

If no reusable workflow is expected but the claim is present, the policy blocks
rather than silently widening the trust surface.

## Retry-zero binding

The project policy is retry=0.

Therefore the OIDC policy accepts only:

`run_attempt = 1`

A re-run token does not match this policy even if other claims are identical.

This does not cancel or prevent a re-run at GitHub level. It only refuses to
treat a re-run as matching the future production trust policy.

## Subject handling

The policy does not construct, normalize, or guess `sub`.

The expected subject is explicit policy input.

This is intentional because GitHub documents subject-format behavior and
customization separately, including newer immutable default subject formats.

A subject string is accepted only when it exactly matches the configured
expected value.

## Temporal claims

The policy requires integer NumericDate-style values for:

- nbf
- iat
- exp

It requires:

- nbf <= iat
- iat <= now
- nbf <= now
- now < exp
- iat < exp

No undocumented fixed token lifetime is assumed.

## Extra claims

Unknown/additional OIDC claims are ignored by this policy.

Only required security-relevant claims are matched.

This avoids failing merely because GitHub adds a new supported claim while
preserving exact checking of the bounded trust context.

## Tests

Added:

`automation/command_bus/tests/test_github_oidc_claims_policy.py`

Coverage includes:

- exact context -> MATCH;
- issuer mismatch -> BLOCKED;
- audience mismatch -> BLOCKED;
- subject mismatch -> BLOCKED;
- repository / repository ID / owner ID mismatch -> BLOCKED;
- ref / SHA mismatch -> BLOCKED;
- workflow ref / workflow SHA mismatch -> BLOCKED;
- event mismatch -> BLOCKED;
- run ID mismatch -> BLOCKED;
- run_attempt > 1 -> BLOCKED;
- self-hosted runner -> BLOCKED;
- visibility mismatch -> BLOCKED;
- required-claim absence -> BLOCKED;
- future/not-yet-valid/expired malformed temporal claims -> BLOCKED;
- jti required;
- extra unrelated claim accepted;
- reusable workflow identity must be explicit;
- subject is exact policy input and is never inferred;
- malformed expected policy -> BLOCKED;
- claims input is not mutated;
- policy MATCH does not expose provider/owner verification proof fields.

## Relationship to PR #106

PR #106 normalizes Jules Session GET readback and preserves the independent
`VerificationSourceAuthenticator` requirement.

This OIDC policy is a possible future building block for that independent trust
path.

It does not wire PR #106 into production and does not authorize OIDC.

## Remaining OIDC boundary

A future production implementation would still require separate explicit
approval before:

1. adding `id-token: write`;
2. requesting a real GitHub OIDC token;
3. implementing cryptographic JWT/JWKS verification;
4. binding a verified token to one normalized provider/authority source;
5. creating a concrete `VerificationSourceAuthenticator`;
6. allowing RuntimeTransitionPublisher to use that proof.

None of those happen in this batch.

## Explicitly not performed

- no workflow permission change;
- no `id-token: write`;
- no `attestations: write`;
- no OIDC token request;
- no JWT parsing;
- no signature/JWKS verification;
- no production authenticator;
- no authority grant;
- no Jules/API/provider/model execution;
- no runtime ledger write;
- no Status dispatch;
- no Issue #33 mutation;
- no PLACEHOLDER -> DURABLE promotion;
- no Merge in this batch.

## Evidence to fill after exact-head CI

- exact tested PR head: PENDING
- GitHub Actions run: PENDING
- focused tests: PENDING
- full command-bus tests: PENDING
- schema parse: PENDING
- compileall: PENDING
- git diff --check: PENDING
- tested head -> current head compare: PENDING
- OIDC token requests: MUST REMAIN ZERO
- workflow permission changes: MUST REMAIN NONE
- Issue #33 live mutation: MUST REMAIN NONE
