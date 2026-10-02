# Sensitive Fan-out Static Inventory

This is a machine-checkable inventory of the current Relay sensitive-data fan-out boundary using checked-in code only.
This document strictly enforces the distinction between generic control-plane override rejection, defensive copying, and an actual secret/PII/private-code classification or redaction policy.

**Important Operational Boundaries:**
- Zero real sensitive data is used.
- Zero external/read-only/live evidence is acquired.
- Zero provider/network send occurs.
- No production filter is added.
- The `common_sensitive_fanout` gap remains completely unresolved (`BLOCKED_UNKNOWN`).
- The first live provider/model turn remains separately human-approved.
- Accepting a synthetic marker proves the absence of a generic sensitive-data filter at that static boundary; it does NOT prove any real secret is safe to send.

| surface_id | canonical_source | current_static_behavior | sensitive_data_protection_meaning | evidence_kind | still_missing | state |
| --- | --- | --- | --- | --- | --- | --- |
| payload_type_gate | validate_payload | Requires the input payload to be a dict. | Type check only; not redaction. | STATIC_OBSERVED | None | STATIC_PROVEN |
| payload_control_plane_override_gate | validate_payload | Rejects specific top-level override keys (e.g. `model`, `billing`); allows synthetic keys. | Prevents control plane override; does NOT inspect arbitrary values for secret/PII. | STATIC_OBSERVED | None | STATIC_PROVEN |
| dispatch_envelope_copy | DispatchEnvelope.build | Deep-copies payload. | Defensive immutability isolation; not redaction. | STATIC_OBSERVED | None | STATIC_PROVEN |
| intent_hash_binding | compute_intent_hash | Deterministic hashing of payload + timeout. | Intent identity binding; not redaction. | STATIC_OBSERVED | None | STATIC_PROVEN |
| bridge_prepare_copy | RelayProviderAdapterBridge.prepare | Validates and deep-copies payload. | Structural prep and isolation; not redaction. | STATIC_OBSERVED | None | STATIC_PROVEN |
| dispatcher_prepared_payload | RelayDispatcher.dispatch | Forwards validated/prepared payload to dispatch. | Orchestration forwarding; not redaction. | STATIC_OBSERVED | None | STATIC_PROVEN |
| lifecycle_prompt_payload | RelayLifecycle.dispatch_mock | Forwards `envelope.payload` to transport prompt. | Orchestration forwarding; not redaction. | STATIC_OBSERVED | None | STATIC_PROVEN |
| mock_transport_payload_boundary | MockTransport.prompt | Receives forwarded payload in test transport. | Mock receiver; not redaction. | STATIC_OBSERVED | None | STATIC_PROVEN |
| core_adapter_raw_response | RelayCoreAdapter.collect | Returns raw response bytes. | Shape/type check; not sanitization. | STATIC_OBSERVED | None | STATIC_PROVEN |
| relay_result_raw_bytes | RelayResult | Holds raw bytes of response. | Storage container; not sanitization. | STATIC_OBSERVED | None | STATIC_PROVEN |
| acp_client_mock_response | ACPClient.prompt | Returns configured mock bytes and evidence. | Mock evidence capture; not a production protection policy. | STATIC_OBSERVED | None | STATIC_PROVEN |
| whole_path_sensitive_fanout_policy | RELAY_LIVE_BLOCKERS.md | Pre-existing generic validations do not establish a sensitive data policy. | MISSING | MISSING_STATIC_EVIDENCE | explicit secret/PII/private-code fan-out filtering/redaction policy | BLOCKED_UNKNOWN |
