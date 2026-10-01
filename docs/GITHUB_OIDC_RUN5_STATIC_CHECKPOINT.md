# OIDC run 5: exact job-workflow ref relation and next static boundary

Run 36616669310 was the sole authorized fifth live OIDC proof.
It ran once at exact head `73b130711018556c211022264be88c8a6c78a68a`
with `run_attempt=1`. No rerun is authorized.

## Exact GitHub readback

- Workflow: `.github/workflows/github-oidc-proof.yml`
- Offline preflight: SUCCESS
- Proof job: FAILURE
- Sanitized upload: SUCCESS
- Artifact ID: 11056240440
- Artifact archive SHA-256:
  `93c499bf6ae70958505e501166e5f3607b4dec20d7aac325bfb023cbf6f8076d`
- Evidence payload SHA-256:
  `2df2af4021558a1368d47b79c406c6dff65f6735dc47227b5fad89a6d96db766`
- Terminal evidence:
  `FAIL / WORKFLOW / OIDC_WORKFLOW_JOB_REF_MATCHES_WORKFLOW_REF_REJECTED`
- GitHub run metadata reports `referenced_workflows: []`.

No raw `job_workflow_ref`, `job_workflow_sha`, JWT, OIDC request token,
authorization header, or other credential is recorded by this checkpoint.

## What run 5 establishes

After GitHub signature verification, the signed `job_workflow_ref` claim was
non-empty and exactly equal to the signed `workflow_ref` claim.

The proof workflow defines both jobs inline and the run metadata reports no
referenced workflows. GitHub's current OIDC documentation describes
`job_workflow_ref` and `job_workflow_sha` as reusable-workflow claims.
The observed equality is therefore treated as verified runtime behavior for
this exact proof, not as permission to infer an undocumented general rule.

Official references:
- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows

## Static next boundary

Before considering any relaxation, the diagnostic now checks the paired
`job_workflow_sha` without exposing its value. When the already-confirmed
`job_workflow_ref == workflow_ref` relation holds, it emits only one fixed
rejection category:

- job workflow SHA missing
- job workflow SHA empty
- job workflow SHA exactly equals workflow SHA
- job workflow SHA differs from workflow SHA

A differing or empty `job_workflow_ref` remains separately rejected.
Every outcome is still fail-closed. A sixth live proof is not authorized by
the fifth-run approval or by this checkpoint.
