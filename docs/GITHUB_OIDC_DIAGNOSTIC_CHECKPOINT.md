# OIDC proof failure diagnostics — static-only checkpoint

This change does **not** request an OIDC token or rerun proof run
[36515385841](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/36515385841).
It does not merge PR #107, modify Issue #33, or grant provider/owner authority.

## What the existing run actually establishes

GitHub readback: offline-preflight succeeded; the proof job started and checkout
succeeded; the in-memory request/verification step failed; sanitized evidence
upload succeeded. The old evidence has status UNKNOWN, so token acquisition,
signature validation, and all identity bindings remain UNKNOWN. The old
artifact cannot retrospectively identify a terminal failure stage.

The digests are **different objects**:

- `artifact_archive_sha256` (GitHub artifact API, archive ID 11010736680):
  `9b35d3e3f5fba929f878ad7d4e4259d3de2f49361413dc8e67d7704d7479a7bd`.
- `evidence_payload_sha256` (old v1 field `evidence_sha256`, canonical JSON
  body excluding its digest): `04a9c958bf7e195487ee05b946b86776cf127a49a17bf0c15dab4373cab92d3f`.
- `evidence_file_sha256` (downloaded `oidc-proof-evidence.json` bytes):
  `3b29f082dab1f1c911dec71ca0b40882929b8b51e6ce988057ad932fedc4a99e`.

The payload digest is **not** a file-byte digest. The archive digest is assigned
only after upload and is read back from GitHub; it cannot truthfully be embedded
inside the file that the archive contains. For a future run, record the three
names separately in the readback/checkpoint. Do not equate any two of them.

## New v2 diagnostic contract

The static code records one fixed `terminal_stage`:
`TOKEN_REQUEST`, `JWT_STRUCTURE`, `JWKS_FETCH`, `SIGNATURE`, `ISSUER`,
`AUDIENCE`, `TIME`, `REPOSITORY`, `WORKFLOW`, `REF_SHA`, `RUN_ID`, or
`COMPLETE`. A failure records only `OIDC_<STAGE>_REJECTED`; success records
`COMPLETE` and `NONE`. No exception text crosses into logs or artifacts.

The v2 evidence allowlist is `schema_version`, `proof_kind`, `status`,
`terminal_stage`, `safe_error_code`, `run_id`, `exact_commit_sha`,
`expected_workflow_identity`, and `evidence_payload_sha256`.
The workflow identity is labelled **expected**; it is not independently
attested by the artifact alone. Token/JWT, bearer header, request URL,
subject, actor, jti, raw claims, JWKS, and stack traces are excluded.
The prepare-only adapter accepts v2 only for complete PASS and still leaves
Jules provider verification UNKNOWN. Caller-supplied JSON is never authority:
a future trusted Actions artifact reader and separate Jules Session GET binding
are still required.

Every stage has an offline mock failure. Negative tests inject token-like
strings into errors and malformed diagnostic objects, and assert that only
fixed codes survive. The old v1 adapter path remains for compatibility.

The proof workflow file is **unchanged**. Its push path filter selects only
changes to `.github/workflows/github-oidc-proof.yml`, and its exact commit
message gate remains the prior one-shot message. This static commit changes
neither condition, so its push must not start an OIDC proof. Read back Actions
after push to verify. Another live proof needs a separately reviewed workflow
change and renewed explicit approval; retry remains zero.

## Second proof readback and bounded diagnosis (run 36532692328)

Readback at `5fbab080972a480adb9de0b74c5fc1abf1eb04ce`:
offline-preflight SUCCESS, proof FAILURE, sanitized upload SUCCESS.
Artifact ID `11016831760` has GitHub archive digest
`artifact_archive_sha256=40ae168d90082372e93f5a6de5ae5fa8627fc95681264159aa1754fb7d9690e4`.
The downloaded evidence has `evidence_payload_sha256=a6e0e9503e5981e642ad760b2969e800e6b87418f3a76d850c0d06a7120dd7af`
(recomputed and matching) and
`evidence_file_sha256=8a3432fefa7d4da290ed232bb9bc3b90e65ee136fa2752127e4b012c1deb3723`.
These are three distinct digests.

The v2 evidence says `FAIL / WORKFLOW / OIDC_WORKFLOW_REJECTED`.
It means no exception was recorded in earlier diagnostic handlers; it is
**not** an independent PASS record for each earlier field. The specific
WORKFLOW rejection cause is **UNKNOWN**. The artifact records no match
booleans or runner/signed workflow values, and the Actions run API does not
supply them. Do not infer a mismatch from the run's displayed workflow name.

Official GitHub references:
- https://docs.github.com/en/actions/reference/security/oidc
- https://docs.github.com/en/actions/reference/workflows-and-actions/variables

GitHub documents OIDC `workflow_ref` as the workflow ref path and
`workflow_sha` as the workflow-file commit SHA; it documents
`GITHUB_WORKFLOW_REF` and `GITHUB_WORKFLOW_SHA` with corresponding
meanings, and `GITHUB_WORKFLOW` as the workflow name. The run API confirms
the workflow path/name and triggering SHA, but not the exact signed claim or
runner variable values in this job. The existing policy's exact comparisons
remain unchanged. In particular, it still rejects repository/ref/SHA/run
drift and unexpected reusable-workflow identity.

The previous `WORKFLOW` stage conflated runner workflow ref/name failures,
a signed `workflow_ref` failure, and unexpected `job_workflow_ref`.
The static-only change adds bounded `safe_error_code` categories for those
known cases and separately identifies runner/claim workflow SHA rejection
under `REF_SHA`. Only the **first** policy failure is categorized; if it
cannot be uniquely classified, the generic code remains. No claim values,
token, request URL, exception text, or sensitive runner data are persisted.
The signed `workflow` name claim is not newly accepted as authority or used
to relax the existing policy.

This change does not alter `.github/workflows/github-oidc-proof.yml`.
Its path-filtered push trigger therefore does not start a proof on this
code/test/docs commit. No third live proof is authorized here. A future
one-shot proof needs an explicit new user decision and separately reviewed
workflow trigger change. Until that run, the run-2 root cause remains UNKNOWN.
