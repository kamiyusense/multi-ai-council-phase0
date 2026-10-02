# Relay Claude Account-Auth Read-Only Checklist

This document is a PREPARED/static read-only inspection plan only. It defines exactly what a future separately authorized read-only inspection would have to observe to establish that the intended account/claude.ai subscription-auth route remains the observed route, without sending any provider/model turn, revealing credentials, changing authentication/settings/billing/permissions, or claiming the route is already proven.

Zero external/read-only account evidence is acquired by this batch. `claude_account_auth` remains unresolved/BLOCKED_UNKNOWN.

## Explicit Distinctions

This checklist explicitly distinguishes between:
- checked-in required auth kind `account`;
- checked-in `hide_claude_auth=false` guard behavior;
- actual observed authenticated identity class;
- actual observed credential mechanism/kind;
- actual observed claude.ai/subscription route;
- proof that no alternate API-key route is selected at runtime;
- proof event identity and evidence provenance.

Checked-in static config/profile/default values, a successful login/account label, or repository-only absence of API-key material are individually insufficient to prove the actual account/subscription route.

The current blocker rule is preserved: `--hide-claude-auth` is incompatible with the intended claude.ai subscription route and must not be used as a proof shortcut.

## Current State Table

| provider_id | gap_id | static_expected_auth_kind_state | static_hide_auth_guard_state | observed_authenticated_identity_state | observed_credential_kind_state | observed_subscription_route_state | api_key_absence_state | readonly_inspection_state | evidence_provenance_state | blocker_state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| anthropic | claude_account_auth | STATIC_PREPARED | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN |

## Future Conceptual Read-Only Evidence Record Fields

- `provider_id`
- `gap_id`
- `inspection_correlation_id`
- `intended_auth_kind`
- `observed_auth_kind`
- `observed_identity_class`
- `hide_claude_auth_observation`
- `api_key_route_state`
- `subscription_route_observation`
- `evidence_source`
- `evidence_locator_or_hash`
- `captured_at`
- `verification_state`

No raw secrets, tokens, cookies, passwords, account numbers, billing identifiers, payment instrument data, or full private profile dumps belong in evidence.

Evidence must be Anthropic/inspection-event bound; evidence from OpenAI, Google, another account, or another inspection cannot satisfy this gap.

## Fail-Closed Semantics

Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:
- observed auth kind
- observed identity class
- credential mechanism
- hide-claude-auth state
- API-key route absence
- subscription route ownership
- evidence provenance
- exact provider/inspection binding

If proof would require sending a model/provider turn, reading a raw secret, changing login/auth/settings/permissions/billing, or enabling an alternate paid route, that proof method is outside this batch and forbidden.
