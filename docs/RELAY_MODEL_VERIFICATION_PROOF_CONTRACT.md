# Relay Model Verification Proof Contract

This document is a PREPARED/static contract only. It defines the machine-checkable static proof contract for the future `common_model_verification` blocker.

**Important:** This document DOES NOT execute any provider/model/API call, acquire live evidence, select a real model, authorize live execution, or wire production verification. It only defines what evidence a future separately authorized bounded live proof would have to produce.

## Current Status
- Zero live evidence is acquired by this batch.
- `common_model_verification` remains unresolved/BLOCKED_UNKNOWN.
- Current real values for each provider remain UNKNOWN/BLOCKED_UNKNOWN.
- Production provenance (OIDC/attestation) remains KEEP_NOT_WIRED / NOT_AUTHORIZED.
- OIDC/attestation are not authorized or required by this static contract.

## Identity and Provenance Distinctions
To rigorously prove the executed model, any future bounded proof must explicitly distinguish the following distinct concepts:

1. **Requested/configured model identity:** The model identity requested by the system (e.g., config default, runtime request param).
   - **Crucially:** Requested/configured/default model identity alone is insufficient to prove the executed model.
2. **Executed-model identity (Provider-returned or runtime-observed):** The actual model identity that the provider states or evidence shows was executed.
3. **Independent evidence:** Evidence that binds the observed identity to exactly one dispatched turn.
   - **Crucially:** Provider self-report alone must not automatically be treated as independent verification unless a future approved trust source explicitly establishes that property.
4. **Correlation:** The cryptographic or structural binding connecting the provider_id, the specific correlation/session/turn identity, and the immutable evidence.
5. **Evidence-source trust/provenance:** The authorized system/authenticator providing the evidence.

## Future Proof Record Shape

A future valid proof record must conceptually include exactly the following fields (defined in prose/table, not a production schema):

| Conceptual Field | Description |
|------------------|-------------|
| `provider_id` | The provider identity (e.g., openai, anthropic, google). |
| `dispatch_correlation_id` | The unique identifier for the internal Relay dispatch. |
| `provider_session_or_turn_id` | The unique identifier from the provider bounding the specific turn. |
| `requested_model_if_known` | The model requested, if determinable. |
| `observed_executed_model` | The model identity proven to have executed. |
| `evidence_source` | The trusted source/authenticator providing the evidence. |
| `evidence_locator_or_hash` | The cryptographic hash or durable locator to the immutable evidence. |
| `captured_at` | The exact timestamp of evidence capture. |
| `verification_state` | The confirmed verification state of this record. |

## Provider Contract State Table

The provider set and exact order is `openai`, `anthropic`, `google`.

| provider_id | requested_model_state | executed_model_state | independent_evidence_state | evidence_source_state | correlation_binding_state | mismatch_policy | missing_evidence | blocker_state |
|-------------|-----------------------|----------------------|----------------------------|-----------------------|---------------------------|-----------------|------------------|---------------|
| openai | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | TERMINAL_FAIL_CLOSED | FAIL_CLOSED | BLOCKED_UNKNOWN |
| anthropic | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | TERMINAL_FAIL_CLOSED | FAIL_CLOSED | BLOCKED_UNKNOWN |
| google | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | TERMINAL_FAIL_CLOSED | FAIL_CLOSED | BLOCKED_UNKNOWN |

## Fail-Closed Evaluation Rules

A future proof validation MUST fail closed (denying verification and rejecting execution authorization) under any of the following conditions:

1. **Missing Evidence:** Missing executed-model evidence fails closed.
2. **Malformed Evidence:** Malformed evidence fails closed.
3. **Provider Mismatch:** Provider identity mismatch fails closed.
4. **Correlation Binding:** Correlation/turn mismatch fails closed.
   - Exact single-turn binding is required. It is explicitly forbidden to treat a later or earlier session observation as proof for a different dispatch.
5. **Requested/Observed Conflict:** Requested-vs-observed conflict fails closed when both are present.
6. **Untrusted Source:** Unknown/untrusted evidence source fails closed under the then-approved provenance policy.
7. **Contradictory Identities:** Contradictory multiple identities fail closed (e.g., conflicting internal evidence records).
8. **Durable Readback:** Unavailable durable readback fails closed.

## Mismatch Handling
Mismatch is terminal. Mismatch must remain terminal BLOCKED_UNKNOWN for the proof attempt; no automatic fallback or second model turn is authorized.
