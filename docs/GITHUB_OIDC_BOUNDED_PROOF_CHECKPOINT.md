# One-shot GitHub-hosted OIDC workflow identity proof

This is a bounded proof on PR #107's existing feature branch, not a provider
or owner-authority proof. User approval is limited to this one OIDC request.
No repository settings, secrets, Issue #33, Control Tower identity, or runtime
data are changed. PR #107 is not merged by this work.

## Source and expected identity

Fresh main at design time: `6d1e9b02a89faee2387009079b2485d5c9705f1b`.
Repository readback: ID `1378815294`, owner ID `20355232`, private,
created 2026-09-20; OIDC subject customization `use_default=true`.
GitHub's current documentation says repositories created after 2026-07-15
use the immutable `owner@id/repo@id` default subject. The proof requires that
exact subject, the reviewed branch/ref, workflow path and SHA, first run
attempt, GitHub-hosted runner, repo/owner IDs, private visibility, and the
custom audience. A changed setting or claim fails closed; no retry occurs.

Official references:

- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/actions/reference/workflows-and-actions/variables
- https://token.actions.githubusercontent.com/.well-known/openid-configuration

`workflow_dispatch` requires a workflow on the default branch. Since this new
proof workflow must remain on a non-default PR branch, a path-filtered `push`
of the workflow file is used for the single proof run. The proof job is
additionally limited to run attempt 1 and the exact reviewed commit message.
No manual rerun or fallback is authorized.

## Verification and evidence

The proof process requests one token using GitHub's runner-provided OIDC
endpoint and bearer credential. Both stay in memory. It fetches GitHub's
fixed issuer metadata/JWKS over HTTPS, selects one `kid`, verifies RS256 with
Node's built-in crypto, and only then passes claims in memory to the existing
Python post-signature claims policy. No decoded token, subject, actor, jti,
bearer credential, or raw claims are printed or written.

The only artifact is `oidc-identity-proof-<run_id>` containing
`oidc-proof-evidence.json` for seven days. It holds bounded PASS/UNKNOWN flags,
safe claim *names*, repository/workflow/ref/run/commit identifiers, and a
SHA-256 digest over canonical sanitized evidence. It explicitly says
`provider_fact_verified=false` and `owner_authority_issued=false`.
The artifact and Actions run must be read back after the single execution.

`github_oidc_workflow_evidence_link.py` is prepare-only. It checks the
sanitized evidence shape/digest and adds opaque run/digest references to an
existing UNKNOWN provider source. It cannot mark the Jules source VERIFIED,
create a `VerifiedSourceAttestation`, or issue owner authority. An independent
trusted reader for the exact Actions artifact and a separately authenticated
Jules Session GET/target binding remain required for provider trust.

## Explicit exclusions

No Jules GET/POST, model/provider call, API billing, owner ACQUIRE, runtime
publication, Issue #33 mutation, registry promotion, final loop-ID decision,
artifact attestation, settings/permission change, or PR merge.
