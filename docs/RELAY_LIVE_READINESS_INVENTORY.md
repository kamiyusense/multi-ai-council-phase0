# Relay Live Readiness Inventory

This document and the associated `src/providers/live_readiness_inventory.py` module constitute a **static, side-effect-free worklist/checklist layer**.

**Important:** This module does not authorize live provider execution, nor does it resolve or infer any real live blockers. It solely implements a deterministic inventory builder that converts the required proof categories into a machine-readable explicit list of unresolved evidence.

- Current real-world proof inventory remains `UNRESOLVED/UNKNOWN`.
- Synthetic `CONFIRMED` test records resolve nothing and must never be presented as real proof.
- The inventory aggregates to `PROOF_RECORDS_COMPLETE` only when all required records are syntactically present and set to `CONFIRMED` with a non-empty `evidence_ref`. Even then, it MUST NOT imply provider readiness.
- Every output strictly enforces `live_ready=false`, `dispatch_allowed=false`, `retry_count=0`, and `fallback_state=disabled`.

## Proof Record Rules
- `status`: Exactly `UNKNOWN` or `CONFIRMED`.
- `evidence_ref`: Exactly `null` when `UNKNOWN`, or a non-empty string when `CONFIRMED`.

## Conversion Rules
- The inventory can be converted to the exact proof mappings expected by `evaluate_live_readiness` **ONLY** when the aggregate state is `PROOF_RECORDS_COMPLETE`.
- Any `UNKNOWN` proof, or any malformed input, will cause the conversion to fail-closed and return an explicit blocked/empty result.
