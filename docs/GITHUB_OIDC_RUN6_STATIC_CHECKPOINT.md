# OIDC run 6: exact self job-workflow identity confirmed

Run 36618807245 was the sole authorized sixth live OIDC proof.
It ran once at exact head `0e2df7e01bcb4bf933b77948673a9fe5c1e27c44`
with `run_attempt=1`. No rerun is authorized.

## Exact GitHub readback

- Workflow: `.github/workflows/github-oidc-proof.yml`
- Offline preflight: SUCCESS
- Proof job: FAILURE
- Sanitized upload: SUCCESS
- Artifact ID: 11056617216
- Artifact archive SHA-256:
  `b0937f56c2a1bc1771c30968343cc359c7957d1c6c71178ae1ca60ce6773772d`
- Evidence payload SHA-256:
  `07a82fe737984c3bf1967f8d638b49f0f40005630cfd01dc792e3b8b9d099618`
- Terminal evidence:
  `FAIL / WORKFLOW / OIDC_WORKFLOW_JOB_IDENTITY_MATCHES_WORKFLOW_REJECTED`
- GitHub run metadata reports `referenced_workflows: []`.

No raw JWT, OIDC request token, authorization header, or credential is
recorded by this checkpoint.

## What run 6 establishes

After GitHub signature verification, both relations were confirmed for this
exact inline proof job:

- `job_workflow_ref == workflow_ref`
- `job_workflow_sha == workflow_sha`

The raw claim values were not emitted. GitHub's current documentation describes
`job_workflow_ref` and `job_workflow_sha` as reusable-workflow claims, so
this observed behavior is recorded as exact runtime evidence rather than
generalized into an undocumented platform rule.

Official reference:
https://docs.github.com/en/actions/reference/security/oidc

## Static policy update

The bounded proof now explicitly expects the exact self job-workflow ref+SHA
pair observed in runs 5 and 6. This is not a wildcard or presence-based
relaxation. Both values must exactly equal the already-bound workflow identity.

The generic claims policy is strengthened at the same time: when a reusable
job-workflow identity is explicitly expected, ref and full lowercase SHA must
be supplied as a pair. Missing, partial, malformed, or mismatched identities
remain BLOCKED.

No seventh live proof is authorized by the sixth-run approval or by this
checkpoint.
