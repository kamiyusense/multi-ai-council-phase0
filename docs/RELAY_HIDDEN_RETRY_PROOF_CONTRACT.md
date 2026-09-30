# Relay Hidden Retry Proof Contract

## Status
This document is a PREPARED static contract only. Zero live hidden-retry evidence is acquired by this batch, and the `common_hidden_retry` blocker remains completely unresolved / BLOCKED_UNKNOWN.

## Core Principles & Distinctions
We explicitly distinguish the following stages/paths of possible extra turns:
1. **Relay/controller retry:** The internal Relay logic attempting a new turn.
2. **Transport retry:** The transport layer attempting a new network request.
3. **Provider/SDK internal retry:** The provider's SDK or internal infrastructure automatically retrying.
4. **Stream reconnect/replay:** An automatic re-establishment of a stream that causes the prompt to be processed again.
5. **Auth recovery/replay:** An automatic token refresh or auth recovery that resends the prompt.
6. **Restart/recovery replay:** A process or container restart that causes the dispatch to be executed a second time.
7. **Model fallback:** Automatically sending the prompt to a secondary model after a failure.

## Insufficiency of Local/Mock State
Explicitly, retry=0/fallback=disabled in Relay code, one local prompt_attempt tracked by `RelayLifecycle`, transport layer interfaces/comments, mock tests, or static preflight values do NOT prove end-to-end hidden provider behavior. These static declarations may be `STATIC_PREPARED`, but provider-internal and runtime replay evidence remain `EVIDENCE_REQUIRED` or `UNKNOWN`.

## Fail-Closed Rules
A successful future proof requires exact `outbound_model_request_count=1`, zero provider retry/reconnect/auth-recovery/restart replay counts, `fallback_observed=false`, unambiguous evidence provenance, and exact provider/proof-event binding.

Missing or ambiguous observation fails closed.
If proving a property requires a real provider/model turn, that is outside this batch and requires separate explicit authorization.

Negative / tamper / failure cases:
- provider-internal retry UNKNOWN fails closed.
- outbound_model_request_count missing, ambiguous, zero, or greater than one fails proof.
- any provider retry/reconnect/auth-recovery/restart replay count greater than zero fails proof.
- fallback_observed missing/UNKNOWN/true fails proof.
- missing proof_correlation_id or provider/event binding fails proof.
- cross-provider evidence cannot satisfy another provider.
- replayed/reused evidence event cannot satisfy a distinct proof event.

## Current State Table

| provider_id | relay_prompt_attempt_state | transport_retry_state | provider_internal_retry_state | stream_reconnect_replay_state | auth_recovery_replay_state | restart_replay_state | model_fallback_state | request_count_evidence_state | evidence_stage | blocker_state |
|-------------|----------------------------|-----------------------|-------------------------------|-------------------------------|----------------------------|----------------------|----------------------|------------------------------|----------------|---------------|
| openai | STATIC_PREPARED | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN |
| anthropic | STATIC_PREPARED | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN |
| google | STATIC_PREPARED | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN |

## Future Conceptual Proof Record
No raw tokens, credentials, private prompts, or secret values belong in future evidence; use safe counters, hashes/locators, synthetic markers, and metadata only.

| Field | Required | Description |
|-------|----------|-------------|
| provider_id | Yes | The provider (e.g., openai, anthropic, google). |
| proof_correlation_id | Yes | Unique correlation ID bounding the proof event. |
| session_or_turn_id | Yes | Provider-specific identifier. |
| relay_prompt_attempts_observed | Yes | Must be 1. |
| outbound_model_request_count | Yes | Must be 1. |
| provider_retry_count_observed | Yes | Must be 0. |
| reconnect_replay_count | Yes | Must be 0. |
| auth_recovery_replay_count | Yes | Must be 0. |
| restart_replay_count | Yes | Must be 0. |
| fallback_observed | Yes | Must be false. |
| requested_model | Yes | Model requested. |
| executed_model | Yes | Model executed. |
| evidence_source | Yes | Origin of evidence. |
| evidence_locator_or_hash | Yes | Safe hash/locator. |
| captured_at | Yes | Timestamp. |
| verification_state | Yes | Final verification status. |
