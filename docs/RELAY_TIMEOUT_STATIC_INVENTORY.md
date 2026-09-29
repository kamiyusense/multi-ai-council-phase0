# Relay Timeout Static Inventory

This is a **PREPARED/static inventory only**.

- This inventory performs zero live execution.
- It does not choose or authorize any timeout value.
- It does not resolve `common_timeout`.
- Provider-specific exact finite live timeout values remain **UNKNOWN** for OpenAI, Anthropic, and Google.
- Numeric timeouts from tests, GitHub Actions, command-bus HTTP calls, probes, or other controller infrastructure are not provider live-timeout policy.
- The first real provider/model turn remains separately human-approved.

## Inventory table

| surface_id | canonical_source | current_static_contract | exact_value_or_default | evidence_kind | live_meaning | state |
| --- | --- | --- | --- | --- | --- | --- |
| timeout_validator | `src/relay/envelope.py` | `validate_timeout` accepts `None` and positive non-bool integers; rejects bool, non-int, zero, and negative values | validation rule only; no selected value | STATIC_PROVEN | Static input validation only; it does not choose or prove a provider live timeout | STATIC_PROVEN |
| dispatch_envelope | `src/relay/envelope.py` | `DispatchEnvelope.timeout_seconds` and `DispatchEnvelope.build(... timeout_seconds=...)` default to `None` | `None` | STATIC_PROVEN | No explicit Relay timeout is selected at envelope construction by default; provider live timeout remains unknown | STATIC_PROVEN |
| dispatcher_forwarding | `src/relay/dispatcher.py` | `RelayDispatcher.dispatch` validates the context timeout and forwards the same value into adapter preparation | caller-supplied positive int or `None` | STATIC_PROVEN | Pass-through only; dispatcher does not establish a provider-specific finite live timeout | STATIC_PROVEN |
| lifecycle_forwarding | `src/relay/lifecycle.py` | mock lifecycle forwards `envelope.timeout_seconds` into one prompt attempt; after a post-open `TimeoutError`, it cancels once before final close | caller-supplied positive int or `None` | STATIC_PROVEN | Proven for the static/mock lifecycle path only; this does not prove a real provider process enforces the timeout | STATIC_PROVEN |
| transport_protocol | `src/relay/transport.py` | `RelayTransport.prompt(... timeout_seconds=None)` exposes an optional timeout parameter | `None` | STATIC_PROVEN | Interface contract only; it does not impose a finite provider live timeout | STATIC_PROVEN |
| mock_transport_observation | `src/relay/mock_transport.py` | `MockTransport` records the forwarded timeout and can deterministically raise `TimeoutError` | observed test value is caller-selected | STATIC_OBSERVED | Mock evidence only; no real provider enforcement is proved | STATIC_OBSERVED |
| acp_client_mock | `src/relay/acp_client.py` | static/mock `ACPClient.prompt(... timeout_seconds=None)` accepts the parameter but its mock body does not use it to control a real provider process | `None` | STATIC_OBSERVED | Test-double API surface only; real provider timeout enforcement remains unknown | STATIC_OBSERVED |
| provider_policy_openai | `src/providers/policy.py` | `CODEX_POLICY` / `ProviderPolicy` define no provider-specific timeout field | UNKNOWN | STATIC_PROVEN | OpenAI exact finite live timeout is not established here | UNKNOWN_LIVE |
| provider_policy_anthropic | `src/providers/policy.py` | `CLAUDE_POLICY` / `ProviderPolicy` define no provider-specific timeout field | UNKNOWN | STATIC_PROVEN | Anthropic exact finite live timeout is not established here | UNKNOWN_LIVE |
| provider_policy_google | `src/providers/policy.py` | `ANTIGRAVITY_POLICY` / `ProviderPolicy` define no provider-specific timeout field | UNKNOWN | STATIC_PROVEN | Google exact finite live timeout is not established here | UNKNOWN_LIVE |
| provider_preflight | `src/providers/preflight.py` | `validate_provider_static` has no timeout parameter and its result establishes no exact provider timeout value | UNKNOWN | STATIC_PROVEN | Static provider preflight does not resolve provider live timeout policy | UNKNOWN_LIVE |
| provider_factory | `src/providers/factory.py` / `src/providers/base.py` | `create_core_adapter` and `ProviderStaticProfile` establish no dedicated provider-specific timeout field or exact finite value | UNKNOWN | STATIC_PROVEN | Factory/profile wiring does not resolve provider live timeout policy | UNKNOWN_LIVE |

## Current conclusion

The repository already proves several **static plumbing** properties: timeout input validation, optional timeout forwarding, one-attempt mock lifecycle behavior, and cancel/close handling after a simulated timeout.

Those properties are not evidence that a real OpenAI, Anthropic, or Google provider process will enforce a selected finite value. The accepted static provider policy/preflight/factory layer currently does not establish provider-specific exact finite timeout values.

Therefore `common_timeout` remains unresolved and the provider live timeout values remain **UNKNOWN_LIVE**.
