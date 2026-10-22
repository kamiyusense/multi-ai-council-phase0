# Relay Antigravity Account Route Read-Only Checklist

> **撤回済み（2026-10-23）**: the Antigravity route was withdrawn from the Relay for terms reasons. Do not run these steps. The launch code is archived and disabled in `archive/antigravity_launch/`; see `docs/RELAY_TOWER_DIRECTION_V4.md` §4.

This document is a PREPARED/static checklist only. It defines exactly what a future separately authorized read-only inspection must observe to establish that the authenticated identity is the intended Google AI Pro / Antigravity account route, without sending any provider/model turn, revealing private account identifiers or credentials, changing authentication/settings/billing/permissions, or claiming the route is already proven.

Zero external/read-only account-route evidence is acquired by this batch. `antigravity_account_route` remains unresolved/BLOCKED_UNKNOWN.
`antigravity_billing_route` is separate and remains unresolved/BLOCKED_UNKNOWN; this checklist must not claim billing ownership/payment route is proven.

## Explicit Distinctions

This checklist explicitly distinguishes between:
- ProviderPolicy required_auth_kind=account;
- preflight static rejection of API-key/gateway/external-cloud/ADC/Vertex alternate routes;
- static Antigravity binary/profile selection;
- actual observed authenticated identity class;
- actual observed credential mechanism/kind;
- actual observed Google AI Pro / Antigravity product/account route;
- proof that API-key/ADC/Vertex routes are not selected;
- inspection event identity and evidence provenance.

Checked-in config/defaults, successful preflight, binary/profile selection, successful login label, or repository absence of API-key material are individually insufficient to prove the actual authenticated account route.

## Current State Table

| provider_id | gap_id | static_expected_auth_kind_state | static_alternate_route_guard_state | observed_authenticated_identity_state | observed_credential_kind_state | observed_product_route_state | api_key_route_absence_state | adc_route_absence_state | vertex_route_absence_state | readonly_inspection_state | evidence_provenance_state | blocker_state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| google | antigravity_account_route | STATIC_PREPARED | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | UNKNOWN | BLOCKED_UNKNOWN |

## Future Conceptual Read-Only Evidence Record Fields

- `provider_id`
- `gap_id`
- `inspection_correlation_id`
- `intended_account_route`
- `observed_auth_kind`
- `observed_identity_class`
- `observed_credential_kind`
- `observed_product_route`
- `api_key_route_state`
- `adc_route_state`
- `vertex_route_state`
- `evidence_source`
- `evidence_locator_or_hash`
- `captured_at`
- `verification_state`

No secrets, tokens, or account numbers are included as required fields. Evidence stores classifications/durable locators or hashes only. No raw secrets, API keys, OAuth tokens, cookies, passwords, account emails, account IDs, full private profile dumps, payment identifiers, or billing data.

## Fail-Closed Semantics

Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:
- observed auth kind
- authenticated identity class
- credential kind
- product/account route
- API-key route absence
- ADC route absence
- Vertex route absence
- provider/inspection binding
- evidence provenance

Any observed API-key, ADC, Vertex, gateway, external-cloud, or mismatched product/account route is a hard proof failure for this gap and must not be normalized to the intended account route.

Evidence must be bounded to a specific inspection event and provider. Evidence from OpenAI, Anthropic, another Google account, another product route, or another inspection cannot satisfy this gap.

If proof would require sending a model/provider turn, reading a raw secret/private account identifier, changing login/auth/settings/permissions/billing, enabling an API key/Cloud Billing/overage route, or widening access, that proof method is outside this batch and forbidden.

## STATIC dispatch integration (2026-10-04; still no LIVE evidence)
`src/relay/antigravity_dispatch.py` (`AntigravityStaticDispatcher`) assembles existing parts only: provider must be Google -> `providers.policy.antigravity_route_admission(settings)` on a host-owned settings snapshot, **before any transport or process exists** -> existing `RelayLifecycle` (initialize -> `session/new` -> one prompt -> terminal). Tests: `tests/relay/test_antigravity_dispatch_static.py` (fake agent only).
- Admitted only when `auth.type == "oauth-personal"`. `gemini-api-key`, `agent-platform`, `oauth-business`, missing, unknown, malformed -> BLOCKED (`NO_AUTH_SELECTION` / `ROUTE_<type>`). `monitor_only` (existing wrapper) records the decision and blocks nothing; there is no "off".
- Basis (public sources only, nothing downloaded or run): `initialize` lists the *available* auth methods, not the selected one; `session/new` without a selection returns `-32000 "Authentication required"`; the server does not inherit the `agy` CLI login.
- **Not built (UNKNOWN):** a mid-turn identity signal (none found in public sources), so no mid-turn cancel; an Admission-Gate equivalent, so Google's one-generation boundary is UNKNOWN.
- **Limits:** a settings snapshot is not proof of the account actually used or billed; it can change after the check (TOCTOU). The real server's behavior is UNKNOWN until an approved LIVE trial (binary download, Google login and terms are human-only steps).
- Counts: LIVE 0, real account read 0, pin change 0 (Antigravity 1.2.1), Billing/API-key operations 0, retry 0, fallback disabled.
