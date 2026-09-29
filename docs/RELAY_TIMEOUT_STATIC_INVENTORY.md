# Relay Timeout Static Inventory

**Note**:
- This inventory performs zero live execution.
- It does not choose timeout values.
- It does not resolve common_timeout.
- provider-specific exact finite live timeout values remain UNKNOWN
- first live provider turn remains separately human-approved

## Inventory Table

| surface_id | canonical_source | current_static_contract | exact_value_or_default | evidence_kind | live_meaning | state |
|---|---|---|---|---|---|---|
| timeout_validator | `src/relay/envelope.py` | Accepts `None` and positive non-bool integers; rejects bools, zero, negative, floats, strings, lists, mappings | N/A | STATIC_PROVEN | Enforces transport timeout type bounds | STATIC_PROVEN |
| dispatch_envelope | `src/relay/envelope.py` | `DispatchEnvelope.timeout_seconds` defaults to `None` | `None` | STATIC_PROVEN | Default unbounded transport timeout | STATIC_PROVEN |
| dispatcher_forwarding | `src/relay/dispatcher.py` | Forwards `timeout_seconds` from context to adapter prepare | `None` | STATIC_PROVEN | Pass-through to adapter | STATIC_PROVEN |
| lifecycle_forwarding | `src/relay/lifecycle.py` | Forwards `envelope.timeout_seconds` to exactly one prompt attempt; cancels before close on `TimeoutError` | N/A | STATIC_PROVEN | Guarantees bounded mock/live execution | STATIC_PROVEN |
| transport_protocol | `src/relay/transport.py` | `RelayTransport.prompt` `timeout_seconds` defaults to `None` | `None` | STATIC_PROVEN | Formal definition of transport bounds | STATIC_PROVEN |
| mock_transport_observation | `src/relay/mock_transport.py` | Records the forwarded timeout and simulates `TimeoutError` | `None` | STATIC_OBSERVED | Mock behavior only, not a live timeout | STATIC_OBSERVED |
| acp_client_mock | `src/relay/acp_client.py` | Accepts `timeout_seconds` but does not prove a real provider process enforces it | `None` | STATIC_OBSERVED | Test double simulation | STATIC_OBSERVED |
| provider_policy_openai | `src/providers/policy.py` | `CODEX_POLICY` has no provider-specific timeout field | UNKNOWN | STATIC_PROVEN | OpenAI exact live timeout value is UNKNOWN | UNKNOWN_LIVE |
| provider_policy_anthropic | `src/providers/policy.py` | `CLAUDE_POLICY` has no provider-specific timeout field | UNKNOWN | STATIC_PROVEN | Anthropic exact live timeout value is UNKNOWN | UNKNOWN_LIVE |
| provider_policy_google | `src/providers/policy.py` | `ANTIGRAVITY_POLICY` has no provider-specific timeout field | UNKNOWN | STATIC_PROVEN | Google exact live timeout value is UNKNOWN | UNKNOWN_LIVE |
| provider_preflight | `src/providers/preflight.py` | `validate_provider_static` does not expose or establish provider-specific timeout values | UNKNOWN | STATIC_PROVEN | Preflight does not set timeout | UNKNOWN_LIVE |
| provider_factory | `src/providers/factory.py` | Path does not establish an exact provider timeout value | UNKNOWN | STATIC_PROVEN | Factory does not configure timeout | UNKNOWN_LIVE |
