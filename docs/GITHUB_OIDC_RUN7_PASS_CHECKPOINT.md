# OIDC run 7: bounded GitHub identity proof PASS

Run 36621648500 was the sole authorized seventh live OIDC proof.
It ran once at exact head `163b1dacca2d73921a77a0428ae6a7166e3b1a03`
with `run_attempt=1`. No rerun was used.

## Exact GitHub readback

- Workflow: `.github/workflows/github-oidc-proof.yml`
- Overall run conclusion: SUCCESS
- Offline preflight: SUCCESS
- Proof job: SUCCESS
- Signature/context step: SUCCESS
- Sanitized evidence upload: SUCCESS
- Artifact ID: 11058835925
- Artifact archive SHA-256:
  `1ae555d94e6e2d2ec881828ab218ec85eb8109bce294265e02c9f27d4eda43bf`
- Evidence payload SHA-256:
  `3c195306fdf1e343f36a8c43645a307fc0dca9edfebaa623cbe2647071e52542`
- Terminal evidence:
  `PASS / COMPLETE / NONE`
- GitHub run metadata reports `referenced_workflows: []`.

No raw JWT, OIDC request token, authorization header, raw claim values, or
credential is recorded by this checkpoint.

## What run 7 establishes

For this exact repository, branch, workflow, commit, run ID, run attempt,
GitHub-hosted runner, audience, subject and temporal window, the one-off proof:

1. requested one GitHub Actions OIDC token,
2. verified its GitHub signature in memory,
3. applied the exact context policy,
4. accepted the observed exact self job-workflow identity pair,
5. emitted only sanitized PASS evidence.

The observed self identity is exact-bound:

- expected `job_workflow_ref == workflow_ref`
- expected `job_workflow_sha == workflow_sha`

This is not a wildcard or a general statement about all GitHub workflows.

## Trust boundary

This PASS establishes only the bounded GitHub OIDC identity/signature/context
proof for this exact run. It does NOT by itself establish Jules/provider/model
state, production owner authority, durable loop ownership, Control Tower
DURABLE state, FINAL_LOOP_ID, runtime publication, takeover, or Issue #33
liveness.

No eighth OIDC live proof is required to establish this bounded proof result.
Any later live OIDC execution requires separate authorization.
