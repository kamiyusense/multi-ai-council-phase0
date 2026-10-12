# Production activation review — proposal only, OFF

**PRELIVE_BLOCKED.** No executable activation diff is applied. Production
workflows, Secrets, permissions, settings, branches, login and billing are unchanged.
This review describes the smallest separate installation/activation change;
a self-hash, PR comment, workflow input or repository ADMIN never grants it.

## Permission delta for independent human review

| Job / role | Current effective declaration | Proposed minimum, only after approval |
|---|---|---|
| Authorizer | Job hard OFF; contents:read; no id-token | Same manual main workflow; job-local contents:read, actions:read for context GETs, id-token:write solely for the one bound JWT request |
| Candidate verifier | Job hard OFF; contents:read; no id-token | Read trusted pinned main source and exact candidate snapshot; actions:read as needed for independent provenance; artifact upload only; **no contents:write or id-token** |
| Narrow operator sender/ledger | No credential/permission callback installed | Explicit approved ephemeral repo-scoped credential with contents:write only for objects, reviewed nondefault result ref, create-only ledger; actions:read for provenance, issues:read for task validity as needed; no administration/secrets/workflow/settings permissions |
| Worker | Subscription-only; no operator credential | No GitHub token/JWT/observer key/paid selectors; no commit/push/adoption authority |

GitHub contents:write is repository-level, not an enforceable path-only token.
Application namespace checks do not replace platform branch protection/rules.
The exact approved source of the ephemeral credential and a verified independent
permission/rules reader must be installed separately; no API key, long-lived
secret, token discovery, permission escalation or paid route is supplied here.
403 protection/rules responses remain a blocking UNKNOWN.

## Proposed wiring delta (not runnable / not applied)

1. Independently install main source commit, exact workflow path/id, numeric job
   and first run, actor id, separate `operator_reviews/` record pin and SHA-256.
   Actual runtime IDs must come from approved job context, not dispatch input.
2. Use read-only GitHub HTTP to build `IndependentReviewReader` and
   `GitHubJobContextReader`; constrain their injected credential to reads.
3. In the same approved job, inject platform request URL/bearer directly in
   memory into `MemoryOnlyOIDCRequest`; never write the resulting JWT into env,
   argv, files, logs, artifacts or PR comments. No callback currently executes.
4. Inject reviewed public issuer/JWKS and expected claims into the existing
   `GitHubOIDCEnvelopeSignatureVerifier`. A successful schema check cannot replace
   cryptographic signature/claims validation.
5. Install `ScopedOperatorLedgerClient` on the reviewed nondefault ledger and
   exact issuer/adoption namespaces, and `AppendOnlyAdoptionStore` for issuer
   intent/nonce ownership. Unknown or existing intent is GET-only recovery.
6. Independently validate effective platform rules/credential rights; inject
   `ReviewedNarrowCapabilityFactory` only after that evidence. The callback is
   an approved installer trust boundary, not a metadata-derived permission gate.
7. Call `attach_reviewed_runtime` with exact requested bytes; existing attachment
   compares independent reviewed bytes and context, validates all bindings,
   creates durable issuer fence, requests once, verifies signature, then binds
   the capability. It returns a transport; it does not publish/adopt/dispatch.
8. Separately reviewed stage lease must pass existing `validate_stage` across
   **all** baseline files, approved artifact, source/head/ref/expiry and collision.
   Stage creation and dispatch remain unimplemented and unapproved here.
9. Trusted candidate job imports operator source only; `PinnedVerifierExecutor`
   runs existing `run_real_verifier_job` on an exact authenticated snapshot in
   cached digest-pinned offline containers. Upload the two existing attestation
   members only. Independently GET actual run/job/ZIP and seal that actual ZIP
   digest before `OperatorCandidateVerifier.read` can qualify anything.
10. Remove OFF and replace NOT_INSTALLED only in a separately reviewed activation
    PR after the host, runtime, source and permission evidence above is complete.
    Do not connect the static adoption bridge to the real sender: that bridge's
    static-only rejection remains intact. Any real orchestration/adoption is a
    separate narrow review/authorization, not an automatic next step.

## Launch review must explicitly reject

Wrong repository/default ref/actor/source/workflow/rerun/head/scope, missing
review or callbacks, false/UNKNOWN rules, reused nonce/issuer intent, duplicate
CAS, wrong object or workspace, expired/stale subscription evidence, unverified
provider, API keys/paid route, candidate-owned scripts/config, unsigned artifacts,
lost replies, oversized output, redirects and copied process authority.

## Human decisions remaining

- Approve appropriate host repair and independently verify fresh subscription
  account/config. No repair of auth or SQLite is bundled with this PR.
- Establish branch protection/rules and exact ephemeral credential capability
  through a supported read-only/approved operator channel; resolve 403 UNKNOWN.
- Review source/runtime/independent review record and public issuer trust pins.
- Review/install the separate activation change and minimum job permissions.
- Grant one bounded LIVE later; grant any stage/dispatch/send/adoption separately.

References: [GitHub OIDC security](https://docs.github.com/en/actions/reference/security/oidc),
[OIDC deployment hardening](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-cloud-providers).
