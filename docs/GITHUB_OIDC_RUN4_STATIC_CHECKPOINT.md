# OIDC run 4: bounded live result and static next-boundary preparation

Run 36614530386 was the sole authorized fourth live OIDC proof.
It ran once at exact head `30be7a6bb869c182dfabf4dbdcf17234aead709a`
with `run_attempt=1`. No rerun is authorized.

## Exact GitHub readback

- Workflow: `.github/workflows/github-oidc-proof.yml`
- Offline preflight: SUCCESS
- Proof job: FAILURE
- Sanitized upload: SUCCESS
- Artifact ID: 11054233484
- Artifact archive SHA-256:
  `be2686429545cfd2f83f8664bfe3901e2b091ef1e1576aae92fa9378c460f7be`
- Evidence payload SHA-256:
  `63a88f06e487531782ea654ccd4df5e07e6cf6d50b81d2b8835b8ae0a18e64e9`
- Terminal evidence:
  `FAIL / WORKFLOW / OIDC_WORKFLOW_JOB_REF_PRESENT_REJECTED`
- GitHub run metadata reports `referenced_workflows: []`.

No raw `job_workflow_ref` value, JWT, OIDC request token, authorization
header, or other credential is recorded by this checkpoint.

## What run 4 establishes

Run 3 established only that a `job_workflow_ref` key was present.
Run 4 additionally establishes that its signed value was non-empty.
The value itself and the reason GitHub supplied it remain UNKNOWN.

The reviewed proof workflow defines its jobs inline. GitHub's OIDC
documentation describes `job_workflow_ref` and `job_workflow_sha` as the
called reusable-workflow identity when a job uses a reusable workflow, while
this run's GitHub metadata reports no referenced workflows. This mismatch is
evidence for further diagnosis, not permission to weaken the policy.

Official references:
- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows

## Static next boundary

The next static diagnostic classifies the already-rejected, non-empty
`job_workflow_ref` only by relation to the signed `workflow_ref`:

- exact same value -> fixed MATCHES_WORKFLOW_REF rejection code
- different value -> fixed DIFFERS_FROM_WORKFLOW_REF rejection code
- empty value -> fixed EMPTY rejection code

All outcomes still reject. No claim value is emitted. Repository/ref/SHA/run
binding remains unchanged. A fifth live proof is not authorized by this file
or by the run-4 approval.
