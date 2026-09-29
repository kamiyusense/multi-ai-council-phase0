# Relay Live Provenance Verification Request

This document and the associated `src/providers/live_provenance_request.py` module strictly implement a **static, PREPARED-only structural request generation layer** for a future durable human-provenance readback.

## Purpose

This module exists solely to validate the structure of an incoming approval receipt and a durable GitHub record locator, and emit a deterministic request packet that can be consumed by a future readback mechanism.

**Important Constraints:**
- This is PREPARED/static request construction only.
- **NO GitHub readback** is performed here.
- The `provenance_verified=false` flag remains fixed at this layer.
- A future separately bounded GitHub-backed readback/verification mechanism must compare the durable record against this request.
- Even successful future provenance verification must NOT itself execute a provider; first live execution remains a separate explicit-human-approved bounded command.

## Next Action Mappings
- **PROVENANCE_VERIFICATION_REQUIRED**: Yields `READBACK_DURABLE_HUMAN_PROVENANCE`.
- **Any Invalid/Blocked state**: Yields `RESOLVE_BLOCKERS`.
