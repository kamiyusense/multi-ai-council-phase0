# Relay Minimum Permissions Static Inventory

**Disclaimer:**
- Zero permission changes are made.
- Zero external/read-only/live evidence is acquired.
- No exact whole-path minimum-permission profile is selected.
- common_min_permissions remains unresolved / BLOCKED_UNKNOWN.
- The first live provider/model turn remains separately human-approved.

| surface_id | provider/scope | canonical_source | current_static_control | evidence_kind | what_is_still_unproven | state |
|---|---|---|---|---|---|---|
| provider_policy_common | Relay Core | `src/providers/policy.py` | Rejects non-subscription auth route, dangerous permission bypass, and requires live_ready false in static phase. | PARTIAL_STATIC_EVIDENCE | The full minimum permission profile | BLOCKED_UNKNOWN |
| openai_route_controls | OpenAI | `src/providers/preflight.py` | Requires `api_key_present`, `gateway_configured`, `external_cloud_configured`, `custom_model_provider_configured`, and `arbitrary_codex_config_present` explicitly False. | PARTIAL_STATIC_EVIDENCE | Real live control path evidence | BLOCKED_UNKNOWN |
| anthropic_route_controls | Anthropic | `src/providers/preflight.py` | Requires `api_key_present`, `gateway_configured`, `external_cloud_configured`, `hide_claude_auth` explicitly False. | PARTIAL_STATIC_EVIDENCE | Real live control path evidence | BLOCKED_UNKNOWN |
| anthropic_dangerous_permission_bypass | Anthropic | `src/providers/preflight.py` | Requires `dangerous_permission_bypass` explicitly False. | PARTIAL_STATIC_EVIDENCE | Real live control path evidence | BLOCKED_UNKNOWN |
| anthropic_session_meta | Anthropic | `src/providers/policy.py` | Pins `allowDangerouslySkipPermissions` to False in `claude_session_meta()`. | STATIC_PROVEN | Real live enforcement of session meta | BLOCKED_UNKNOWN |
| google_route_controls | Google | `src/providers/preflight.py` | Requires `api_key_present`, `gateway_configured`, `external_cloud_configured`, `adc_present`, `vertex_selected` explicitly False. | PARTIAL_STATIC_EVIDENCE | Real live control path evidence | BLOCKED_UNKNOWN |
| google_billing_route_controls | Google | `src/providers/preflight.py` | Requires `cloud_billing_selected`, `overages_enabled` explicitly False. | PARTIAL_STATIC_EVIDENCE | Real live control path evidence | BLOCKED_UNKNOWN |
| relay_payload_control_overrides | Relay Envelope | `src/relay/envelope.py` | `validate_payload` rejects control-plane permission/route overrides. | PARTIAL_STATIC_EVIDENCE | Secret/PII filtering | BLOCKED_UNKNOWN |
| whole_path_minimum_permission_profile | Whole Path | Multiple | No combined profile is statically proven. | PARTIAL_STATIC_EVIDENCE | The exact minimum permission profile across the real provider/runtime path. | BLOCKED_UNKNOWN |
