# Relay Live Readiness Chain Audit

## Scope

This document represents the end-to-end regression audit across the static readiness chain:

`explicit provider configs + inventory`
-> `live readiness snapshot`
-> `human approval request packet`
-> `structural approval receipt`

This audit does **not** add a production runtime layer. It is an integration/audit batch only.

## Verified Invariants

- **Hash Binding Chain**:
  - The snapshot packet explicitly binds the output of the snapshot.
  - The approval packet binds the approval packet and the exact same snapshot hash.
  - The structural approval record target hashes match the exact approval and snapshot hashes.
  - Tampering with any hash at each boundary successfully proves fail closed.

- **Determinism**:
  - Equivalent input dict key ordering correctly produces identical snapshot, approval, and receipt hashes.
  - Two identical complete inputs produce byte-for-byte equivalent safe outputs.

- **Evidence Sensitivity Without Leakage**:
  - Changing exactly one valid evidence_ref in a synthetic complete inventory correctly changes the snapshot and approval hashes deterministically.
  - The output renderers safely sanitize arbitrary strings without exposing `evidence_ref` or its raw value.

- **Renderer Boundaries**:
  - The snapshot, approval, and receipt Japanese renderers strictly keep live execution prohibited.
  - The receipt renderer explicitly states human provenance is unverified and execution is unauthorized.
  - No `recorded_at`, raw URLs, `provider_meta`, `route_evidence`, reasons, or `evidence_ref` values appear in the outputs.

- **Cross-Layer Tamper Cases**:
  - Mutating a ready snapshot state or dispatch flag/hash correctly proves the downstream approval cannot safely advance.
  - Mutating the approval packet `approval_granted` or provider keys/hash correctly proves the receipt cannot safely advance.
  - Mutating the receipt record scope, timestamp, or target hashes successfully proves fail closed.

- **No Authorization Word/State Regression**:
  - Across the produced runtime mappings, there is absolutely no true `execution_authorized`, `dispatch_allowed`, `live_ready`, `approval_granted`, or `provenance_verified` state.

## Explicit Terminal Boundary

**STATIC chain complete != human provenance verified != first live command authorized.**

This pipeline solely implements a side-effect-free preparation layer. The first live turn remains a completely separate process requiring explicit human approval. No real blocker is resolved by the existence of this pipeline. Complete evidence data used in testing represents synthetic fixture data.