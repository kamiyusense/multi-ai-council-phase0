# Relay Provenance Trust Source Decision Support

This document provides a concise decision matrix for the human architecture choice regarding provenance verification.

**CRITICAL: ZERO ARCHITECTURE CHOICE AND ZERO PERMISSION CHANGE**
This document makes ZERO architecture choice and ZERO permission change.
No real live blocker is resolved by this matrix or any synthetic fixtures.

## Decision Matrix

| Candidate | KEEP_NOT_WIRED | GITHUB_ACTIONS_READBACK_ONLY | GITHUB_OIDC_AUTHENTICATOR | GITHUB_ARTIFACT_ATTESTATION |
| :--- | :--- | :--- | :--- | :--- |
| **Project Classification** | current safe default / no provenance advancement | transport evidence only / insufficient as authenticator | candidate / NOT_AUTHORIZED | strong candidate / NOT_AUTHORIZED |
| **Evidence Strength** | None | Weak (Transport only) | Medium-Strong | Strong |
| **Independently Authenticates Execution/Human Provenance** | No | No | Yes | Yes |
| **Documented Permissions Needed** | None | `actions: read` (typical) | `id-token: write` | `id-token: write`, `attestations: write`, `contents: read` |
| **Repository/Workflow Mutation Required** | No | Yes (to pass run_id) | Yes | Yes |
| **New Secret/Key Requirement** | No | No | No | No |
| **Offline/Static-Testability** | Yes | Partial | Hard (Needs OIDC mock) | Hard (Needs GH API mock) |
| **Implementation Complexity** | Zero | Low | Medium | High |
| **Blast Radius** | None | Low | High (OIDC token access) | High (Attestation creation) |
| **What it still does NOT prove** | Provenance | Identity of approver | Intent/tampering pre-OIDC | Execution context post-attestation |
| **Explicit Human Authorization Required** | N/A | No (just config) | Yes | Yes |

## The Exact Next Human Decision

The exact next human decision that remains is to:
**Choose whether to keep NOT_WIRED or authorize a narrowly scoped signed trust mechanism; if authorizing, separately choose OIDC vs Artifact Attestation based on desired assurance and permission/blast-radius tradeoff.**

## Architectural Constraints

1. **Separation of Concerns:** Any later implementation must keep provenance verification separate from execution authorization and first-live dispatch.
2. **False Claims Avoidance:** We do not claim GitHub Actions success, a JSON field, Jules session data, or a same-controller receipt authenticates itself.
