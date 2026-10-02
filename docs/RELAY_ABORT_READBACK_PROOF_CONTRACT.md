# Relay Abort Readback Proof Contract

## Status
This document is a PREPARED static contract only. Zero live abort/readback evidence is acquired by this batch, and the `common_abort_readback` blocker remains completely unresolved / BLOCKED_UNKNOWN.

## Core Principles & Distinctions
We explicitly distinguish the following stages of abort/cancel behavior:
1. **Relay asking for abort/cancel:** The local intent to terminate.
2. **Provider/runtime acknowledging the abort request:** A network/API ack.
3. **The intended provider/session/turn actually terminating:** The physical halt of generation.
4. **Durable readback proving no further model output/turn/restart occurred for that exact dispatch:** External evidence that generation stayed stopped.
5. **Replay prevention after abort:** Ensuring no fallback or retry restarts generation.
6. **Evidence-source trust/provenance:** The origin of the external evidence must be authenticated.

## Insufficiency of Local/Mock State
Calling a local/mock abort method or receiving a local return value alone is insufficient to prove a real provider turn was terminated. Furthermore, a provider-side acknowledgment alone is insufficient without exact scope/correlation and durable post-abort readback. Mock abort/cancel counts do not prove real provider/runtime behavior. STOP, pre-dispatch abort, and mock timeout/cancel behavior may be cited as STATIC_PREPARED evidence only.

## Fail-Closed Rules
Any future proof evaluation MUST strictly fail closed and reject the proof when:
*   Abort request evidence is missing.
*   Provider/session/turn scope is missing or mismatched.
*   Acknowledgment is missing, malformed, or contradictory.
*   Termination cannot be proven.
*   Post-abort readback is missing/unavailable.
*   Any additional model output/turn/restart appears after the abort boundary.
*   Multiple conflicting termination states exist.
*   Evidence source is UNKNOWN/untrusted under the then-approved provenance policy.
*   Durable evidence cannot be correlated to the exact dispatch.
*   Retry/fallback/restart behavior is UNKNOWN.

## Exact Single-Dispatch Binding
An exact single-dispatch binding is mandatory. It requires `provider_id` + internal correlation id + provider session/turn/process identifier (when available). A later/earlier observation must not prove a different dispatch.

## Replay Prevention
We require strict replay prevention:
*   No automatic second prompt/model turn.
*   No automatic fallback.
*   No automatic restart/recovery producing a new turn.
*   Retry remains 0.

## Provider Specificity
Proof is provider-specific. Evidence for one provider must not satisfy another provider's row.

## Current State Table

| provider_id | abort_request_state | abort_scope_binding_state | provider_ack_state | process_or_session_termination_state | post_abort_readback_state | replay_prevention_state | evidence_source_state | blocker_state |
|-------------|---------------------|---------------------------|--------------------|--------------------------------------|---------------------------|-------------------------|-----------------------|---------------|
| openai | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN |
| anthropic | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN |
| google | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN |

## Future Conceptual Proof Record
This is a conceptual record design, not a production schema:

| Field | Required | Description |
|-------|----------|-------------|
| provider_id | Yes | The provider (e.g., openai, anthropic, google). |
| dispatch_correlation_id | Yes | The internal Relay correlation ID. |
| provider_session_or_turn_id | Yes | The provider's unique session or turn identifier. |
| abort_requested_at | Yes | Timestamp of the abort request. |
| abort_request_evidence | Yes | Evidence of the request transmission. |
| provider_ack_evidence | Yes | Evidence of the provider's acknowledgment. |
| termination_evidence | Yes | Evidence of the actual process/session termination. |
| post_abort_readback_evidence | Yes | Durable evidence proving no output/turn after abort. |
| evidence_locator_or_hash | Yes | Hash or locator for the external proof payload. |
| captured_at | Yes | Timestamp of the readback capture. |
| verification_state | Yes | Evaluation state remains BLOCKED_UNKNOWN until separately authorized future evidence is actually validated; this static contract does not authorize a positive live state. |
