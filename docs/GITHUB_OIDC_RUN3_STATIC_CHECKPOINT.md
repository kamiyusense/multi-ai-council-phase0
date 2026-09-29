# OIDC run 3: static-only readback and bounded diagnostic correction

No OIDC token was requested in this batch. Run 36554957597 was not rerun.
The proof workflow file remains unchanged; no fourth proof is authorized.

## Exact readback

- Run: 36554957597, exact head: `9e6dc251568d0f7545962820f2f27e8c14566ff6`.
- Offline preflight: SUCCESS. Proof job: FAILURE. Sanitized upload: SUCCESS.
- Artifact ID: 11028040232.
- `artifact_archive_sha256`: `c75651b5f16fd60d258644d05c8f1025c57931ebc3f3bc146823f5f24a5d843a` (GitHub API).
- `evidence_file_sha256`: `21d7731f1fd9310425205b15f2d58896cbcd81811f0857721569f498cc5bb43b` (downloaded JSON bytes).
- `evidence_payload_sha256`: `afb0487a9dc44450a0b9cb27caffebc2aed941ca042f2896a69967b2b06a5cb2` (canonical payload).
- Evidence: schema 2, FAIL, WORKFLOW, `OIDC_WORKFLOW_REUSABLE_REF_REJECTED`.

These three digests describe different objects. Do not equate them.
No token, JWT, raw claims, authorization header, or secret is in the
allowlisted evidence file.

## What is established, and what remains unknown

The run-3 code is emitted only after `expected_from_runner` succeeds and
the post-signature claims policy rejects a `job_workflow_ref` key while
no expected reusable-workflow ref was configured. This establishes presence
of that key in the in-memory claims dictionary and no earlier exception in
the diagnostic pipeline. It does **not** establish its value, whether the
job actually ran through a reusable workflow, or why GitHub supplied it.
There is no independent per-stage PASS record for earlier checks.

At this exact head the proof workflow defines inline `offline-preflight`
and `proof` jobs; step-level `uses` calls actions, not a reusable
workflow job. GitHub's OIDC documentation says `job_workflow_ref` and
`job_workflow_sha` describe a called reusable workflow when one is used;
it does not promise that an ordinary job always omits those keys. We must
not infer a reusable job from key presence alone or accept an unverified
value. The exact repo/ref/SHA/run binding stays unchanged.

Official sources:
- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows
- https://docs.github.com/en/actions/reference/workflows-and-actions/variables

## Static correction and next boundary

The old code name asserted `REUSABLE` on presence alone. Static code now
uses fixed `JOB_REF_EMPTY` and `JOB_REF_PRESENT` rejection codes.
Both still reject. The distinction reveals no claim value, and negative
tests inject a token-like string to ensure only a fixed code survives.
