# Relay Subscription Route Read-Only Checklist

This document is a PREPARED/static checklist only. It defines exactly what a future, separately authorized read-only inspection would have to observe to prove that each intended subscription/auth route is the route actually used for a provider turn, without enabling API keys, Cloud Billing, overages, alternate paid routes, or sending any model turn.

Zero external/read-only account or billing evidence is acquired by this batch. `common_subscription_route` remains unresolved/BLOCKED_UNKNOWN.

## Explicit Distinctions

This checklist explicitly distinguishes between:
- intended configured/provider route;
- authenticated account identity;
- credential mechanism/kind;
- absence of API-key route;
- absence of Cloud Billing route;
- absence of overage/extra-pay route;
- proof that the authenticated subscription route is actually the route that would fund/account for a future turn;
- read-only evidence source and exact capture boundary.

Checked-in config/profile/default/auth-kind values alone are insufficient to prove the real route actually used or billed.
The absence of an API key in repository source alone is insufficient to prove no API-key environment/credential path exists at runtime.
A successful login/account label alone is insufficient to prove the intended subscription route is the route funding the turn.

## Current State Table

| provider_id | intended_route_state | authenticated_identity_state | credential_kind_state | api_key_absence_state | cloud_billing_absence_state | overage_absence_state | route_ownership_evidence_state | readonly_inspection_state | blocker_state |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| openai | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | BLOCKED_UNKNOWN |
| anthropic | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | BLOCKED_UNKNOWN |
| google | STATIC_PREPARED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | EVIDENCE_REQUIRED | UNKNOWN | BLOCKED_UNKNOWN |

## Provider-Specific Future Evidence Requirements

These are evidence requirements, not current factual claims. Evidence must be bounded to a specific inspection event and provider. Evidence from one provider cannot satisfy another.

- **OpenAI/Codex**: intended ChatGPT/subscription-auth route identity and no alternate API-key/custom-paid route selected;
- **Anthropic/Claude**: intended claude.ai/account subscription auth remains account-based and no alternate API-key/billing route selected;
- **Google/Antigravity**: intended Google AI Pro/Antigravity authenticated route and no API-key/Cloud Billing/overage route selected.

## Future Conceptual Read-Only Evidence Record Fields

- `provider_id`
- `inspection_correlation_id`
- `intended_route`
- `observed_authenticated_identity_class`
- `observed_credential_kind`
- `api_key_route_state`
- `cloud_billing_route_state`
- `overage_route_state`
- `route_ownership_evidence`
- `evidence_source`
- `evidence_locator_or_hash`
- `captured_at`
- `verification_state`

No secrets, tokens, or account numbers are included as required fields.

## Fail-Closed Semantics

Fail closed / remain BLOCKED_UNKNOWN when:
- authenticated identity is unavailable or ambiguous;
- credential kind is UNKNOWN;
- API-key route absence cannot be proven;
- Cloud Billing route absence cannot be proven where applicable;
- overage/extra-pay route absence cannot be proven where applicable;
- intended route and observed route conflict;
- route ownership/payment responsibility cannot be established read-only;
- evidence source is UNKNOWN/untrusted under then-approved provenance policy;
- evidence cannot be bound to the exact provider/inspection;
- evidence would require revealing/storing a secret;
- only configured/default/static source evidence exists without real read-only observation.

## Privacy and Minimization

- Future records must store classifications and durable locators/hashes where possible, not raw tokens/secrets;
- No API keys, OAuth tokens, cookies, passwords, account numbers, payment instrument data, or full private profile dumps belong in evidence.
