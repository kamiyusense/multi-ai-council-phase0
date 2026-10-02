# Relay Live Approval Receipt

This document and the associated `src/providers/live_approval_receipt.py` module strictly implement a **static, PREPARED-only structural validation** for human approval records.

## Purpose

This module exists solely to validate the *structure and binding* of a caller-supplied human approval record against a known valid live readiness approval packet.

**Important Constraints:**
- This module **DOES NOT** prove human provenance.
- The `provenance_verified=false` flag is completely fixed at this layer.
- A result of `STRUCTURALLY_VALID_APPROVAL_RECORD` indicates *only* that the approval record was structurally well-formed, hashes align, and the request is logically sound.
- A future durable GitHub-backed provenance and readback mechanism is still strictly required to prove human origination.
- This module **DOES NOT** authorize live execution.
- Even if human approval were verified in the future, the first live turn remains a completely separate bounded command/action that must be explicitly executed outside of this static machinery.

## Next Action Mappings
- **APPROVE_FIRST_LIVE_POC**: Yields `VERIFY_DURABLE_HUMAN_PROVENANCE`.
- **REJECT / DEFER**: Yields `NO_LIVE_ACTION`.
- **Any Invalid/Blocked state**: Yields `RESOLVE_BLOCKERS`.
