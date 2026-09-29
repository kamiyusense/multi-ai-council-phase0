# Relay Minimum Permissions Static Inventory

This is a **PREPARED/static inventory only**.

- Zero permission changes are made.
- Zero external/read-only/live evidence is acquired.
- No exact whole-path minimum-permission profile is selected.
- `common_min_permissions` remains unresolved / `BLOCKED_UNKNOWN`.
- Static deny/guard rules are not equivalent to runtime effective permissions.
- Static route-selection controls do not prove the authenticated live identity or subscription billing route.
- The first live provider/model turn remains separately human-approved.

## Inventory table

| surface_id | provider/scope | canonical_source | current_static_control | evidence_kind | what_is_still_unproven | state |
| --- | --- | --- | --- | --- | --- | --- |
| provider_policy_common | Relay provider policy | `src/providers/policy.py` | `automatic_retry == 0`; fallback disabled; API-key, gateway, external-cloud and dangerous-permission-bypass allowances disabled; `live_ready == false`; required auth kind defaults to account | STATIC_PROVEN | whether these static policy fields equal the minimum effective permissions of every real provider/runtime process | STATIC_PROVEN |
| openai_route_controls | OpenAI | `src/providers/preflight.py` | requires account auth plus `api_key_present`, `gateway_configured`, `external_cloud_configured`, `custom_model_provider_configured`, and `arbitrary_codex_config_present` explicitly false | STATIC_PROVEN | real runtime identity, effective permissions, subscription charging route, and live enforcement | PARTIAL_STATIC_EVIDENCE |
| anthropic_route_controls | Anthropic | `src/providers/preflight.py` | requires account auth plus `api_key_present`, `gateway_configured`, `external_cloud_configured`, and `hide_claude_auth` explicitly false | STATIC_PROVEN | real runtime identity, effective permissions, subscription charging route, and live enforcement | PARTIAL_STATIC_EVIDENCE |
| anthropic_dangerous_permission_bypass | Anthropic | `src/providers/preflight.py` | requires `dangerous_permission_bypass` explicitly false | STATIC_PROVEN | whether the real provider/runtime path preserves the restriction end to end | PARTIAL_STATIC_EVIDENCE |
| anthropic_session_meta | Anthropic | `src/providers/policy.py` | `claude_session_meta()` pins `allowDangerouslySkipPermissions=false`; preflight requires exact metadata equality | STATIC_PROVEN | real runtime enforcement of that metadata | PARTIAL_STATIC_EVIDENCE |
| google_route_controls | Google | `src/providers/preflight.py` | requires account auth plus `api_key_present`, `gateway_configured`, `external_cloud_configured`, `adc_present`, and `vertex_selected` explicitly false | STATIC_PROVEN | real runtime identity, effective permissions, and live enforcement | PARTIAL_STATIC_EVIDENCE |
| google_billing_route_controls | Google | `src/providers/preflight.py` | requires `cloud_billing_selected` and `overages_enabled` explicitly false | STATIC_PROVEN | proof that the intended account/subscription route actually pays for the live turn | PARTIAL_STATIC_EVIDENCE |
| relay_payload_control_overrides | Relay envelope | `src/relay/envelope.py` | `validate_payload` rejects listed control-plane override fields including approval, sandbox, config, billing, auth-route, and timeout overrides | STATIC_PROVEN | this is not secret/PII/private-code filtering and does not prove provider/runtime effective permissions | PARTIAL_STATIC_EVIDENCE |
| whole_path_minimum_permission_profile | Whole path | multiple static sources above | only partial provider-specific/static deny controls are proven; no combined whole-path profile is selected | PARTIAL_STATIC_EVIDENCE | exact minimum effective permission profile across Relay, provider process, auth route, filesystem/network boundary, and first live execution | BLOCKED_UNKNOWN |

## Current boundary

The static repository proves useful fail-closed controls, but those controls do
not establish the exact whole-path minimum permission profile of a real live
provider/runtime path.

Therefore:

- `common_min_permissions` remains `BLOCKED_UNKNOWN`;
- no workflow/provider/account permission is changed or authorized here;
- no authentication, billing, overage, network, or provider action occurs;
- no live readiness or execution authorization is created;
- first live provider/model execution remains a separate explicit-human boundary.
