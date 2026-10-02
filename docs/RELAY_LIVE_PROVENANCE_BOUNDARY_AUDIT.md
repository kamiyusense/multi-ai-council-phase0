# Relay Live Provenance Boundary Audit

## Scope

This document represents the end-to-end static provenance boundary integration audit, terminating the currently safe static Relay approval/provenance preparation chain:

`synthetic complete readiness`
-> `static approval packet`
-> `structural approval receipt`
-> `durable provenance verification request`
-> STOP at `PROVENANCE_VERIFICATION_REQUIRED`

This audit does **not** add a production implementation. It does **not** choose a production trust source, access GitHub, request OIDC, create attestations, change workflow permissions, verify human provenance, authorize execution, or perform any live/provider/API/auth/billing/network action.

## Terminal Trust-Source Boundary

- **PROVENANCE_VERIFICATION_REQUIRED is terminal for current static Relay code.**
- GitHub Actions readback alone is transport evidence, not independent human provenance.
- OIDC and Artifact Attestation are NOT AUTHORIZED in this batch.
- No `id-token: write`, `attestations: write`, or permission changes are made.
- The production authenticator remains NOT_WIRED.
- The first live provider turn remains separately bounded and explicit-human-approved even after any future provenance verification.

## Verified Tamper Proofs

- Unknown/unresolved readiness paths correctly fail to advance to a provenance request.
- REJECT and DEFER receipts correctly fail to advance to a provenance request.
- Tampering the structural approval receipt at any important binding (state, decision, scope, one_shot, next_action, retry_count, hashes, etc.) proves the provenance request fails closed.
- Tampering the durable locator at any important boundary (source_kind, repository owner/repo syntax, ref conservative syntax, path absolute/traversal/non-json forms, expected record hash format/length) proves it fails closed.
- Changing only ref/path/expected_record_sha256 deterministically changes the locator and request digests.
- Two identical inputs give byte-for-byte equal output. Equivalent dict key ordering gives identical output/digests.

## Leakage Boundary
- Renderer/output does not contain raw repository_full_name, ref, path, or source_kind values.
- Renderer strictly does not expose recorded_at, URLs, route_evidence, provider_meta, evidence_ref, reasons, secrets, or arbitrary untrusted marker strings.

## Source Static Verification
- Parses `src/providers/live_provenance_request.py` via Python AST in the test boundary to guarantee no `os`, `pathlib`, `subprocess`, `socket`, `http`, `urllib`, `requests`, `github`, `time`, or `random` imports are present.
- Guarantees no hidden live network or disk reads during the bounding step.

## Synthetic Evidence Boundary

The complete-evidence path used by this audit is **synthetic fixture data** only.
No real live blocker is resolved by these fixtures, and no actual human approval,
GitHub durable provenance, provider authorization, billing state, or first live
execution permission is established.

The current terminal meaning remains:

`PROVENANCE_VERIFICATION_REQUIRED`
!= human provenance verified
!= execution authorized
!= first live provider turn authorized

