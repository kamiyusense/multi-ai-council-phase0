# Relay Antigravity Billing Route Read-Only Checklist

This document is a PREPARED/static checklist only. It defines exactly what a future separately authorized read-only inspection must observe to establish that API-key, Cloud Billing, and overage/extra-pay routes are not selected for the Google AI Pro / Antigravity product route, without sending any provider/model turn, revealing private billing/account identifiers or credentials, changing authentication/settings/billing/permissions, or claiming the billing route is already proven.

Zero external/read-only billing-route evidence is acquired by this batch. `antigravity_billing_route` remains unresolved/BLOCKED_UNKNOWN.

## Explicit Distinctions

This checklist explicitly distinguishes between:
- static preflight guard `api_key_present=false`;
- static preflight guard `cloud_billing_selected=false`;
- static preflight guard `overages_enabled=false`;
- static preflight guards for ADC/Vertex/gateway/external-cloud;
- actual runtime API-key route selection;
- actual Cloud Billing route selection;
- actual overage/extra-pay route selection;
- actual payment responsibility / route ownership;
- available quota/billing visibility;
- inspection event identity and evidence provenance.

Checked-in config/defaults, successful preflight, binary/profile selection, successful login/account label, or repository absence of API-key/billing config are individually insufficient to prove the actual billing/payment route.

`antigravity_account_route` is separate; even if account identity were later proven, it would not by itself prove billing ownership/payment route.

## Current State Table

| provider_id | gap_id | static_api_key_guard_state | static_cloud_billing_guard_state | static_overage_guard_state | static_adc_vertex_guard_state | observed_api_key_route_state | observed_cloud_billing_route_state | observed_overage_route_state | observed_payment_responsibility_state | quota_billing_visibility_state | readonly_inspection_state | evidence_provenance_state | blocker_state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| google | antigravity_billing_route | STATIC_PREPARED | STATIC_PREPARED | STATIC_PREPARED | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | UNKNOWN | BLOCKED_UNKNOWN |

## Future Conceptual Read-Only Evidence Record Fields

- `provider_id`
- `gap_id`
- `inspection_correlation_id`
- `intended_billing_route`
- `observed_api_key_route_state`
- `observed_cloud_billing_route_state`
- `observed_overage_route_state`
- `observed_adc_route_state`
- `observed_vertex_route_state`
- `observed_payment_responsibility_class`
- `quota_billing_visibility_state`
- `evidence_source`
- `evidence_locator_or_hash`
- `captured_at`
- `verification_state`

Evidence stores classifications/durable locators or hashes only. No raw secrets, API keys, OAuth tokens, cookies, passwords, account emails, account IDs, billing account IDs, cloud project IDs tied to billing, payment instruments, quota identifiers, invoices, transaction records, or full private profile dumps.

## Fail-Closed Semantics

Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown, ambiguous, conflicting, or unverifiable:
- API-key route absence
- Cloud Billing route absence
- overage/extra-pay route absence
- ADC route absence
- Vertex route absence
- payment responsibility/route ownership
- quota/billing visibility where needed for the decision
- provider/inspection binding
- evidence provenance

Any observed selected API-key, Cloud Billing, overage/extra-pay, ADC, Vertex, gateway, external-cloud, or mismatched payment route is a hard proof failure for the intended subscription-only path and must not be normalized to safe.

If the current product/runtime cannot expose enough read-only quota/billing evidence to prove route ownership/payment responsibility, explicitly remain BLOCKED_UNKNOWN rather than inferring from static config or account identity.

Evidence must be Google/Antigravity inspection-event bound. Evidence from OpenAI, Anthropic, another Google account, another product route, another cloud project/account, or another inspection cannot satisfy this gap.

If proof would require sending a model/provider turn, reading a raw secret/private billing identifier, changing login/auth/settings/permissions/billing, enabling API key/Cloud Billing/overages, or widening access, that proof method is outside this batch and forbidden.
