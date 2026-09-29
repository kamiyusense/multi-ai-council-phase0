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
