# Relay Claude Permissions Read-Only Checklist

This document is a PREPARED/static read-only inspection plan only. It defines exactly what a future separately authorized read-only inspection would have to observe to establish that `allowDangerouslySkipPermissions=false` is effective on new/load, without changing permissions/settings/auth, starting a provider/model turn, revealing credentials, or claiming runtime enforcement is already proven.

Zero external/read-only permission evidence is acquired by this batch. `claude_permissions` remains unresolved/BLOCKED_UNKNOWN.

## Explicit Distinctions

This checklist explicitly distinguishes between:
- ProviderPolicy `dangerous_permission_bypass=false`;
- `claude_session_meta()` `allowDangerouslySkipPermissions=false`;
- preflight exact `provider_meta` equality;
- actual effective permission mode when creating a new session;
- actual effective permission mode when loading/resuming;
- proof that a dangerous bypass was not silently enabled elsewhere;
- inspection event identity and evidence provenance.

Static source/config values, successful preflight, or a mock/static session-meta fixture alone are insufficient to prove runtime enforcement on new/load.

## Current State Table

| provider_id | gap_id | static_policy_bypass_state | static_session_meta_state | new_session_effective_state | load_session_effective_state | observed_permission_mode_state | bypass_absence_state | readonly_inspection_state | evidence_provenance_state | blocker_state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic | claude_permissions | STATIC_PREPARED | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN |

## Future Conceptual Read-Only Evidence Record Fields

- `provider_id`
- `gap_id`
- `inspection_correlation_id`
- `expected_allow_dangerously_skip_permissions`
- `observed_new_session_permission_mode`
- `observed_load_session_permission_mode`
- `observed_bypass_state`
- `evidence_source`
- `evidence_locator_or_hash`
- `captured_at`
- `verification_state`

No raw secrets, tokens, cookies, passwords, account numbers, private profile dumps, or raw credential material belong in evidence.

Evidence must be Anthropic/inspection-event bound; evidence from another provider/account/inspection cannot satisfy this gap.

## Fail-Closed Semantics

Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:
- effective new-session permission mode
- effective load-session permission mode
- bypass absence
- provider/session binding
- evidence provenance

Any observed true/enabled/ambiguous dangerous-permission bypass is a hard failure for proof and must not be normalized to false.

If proof would require changing permissions/settings/auth, starting a model/provider turn, reading a raw secret, or widening access, that method is outside this batch and forbidden.
