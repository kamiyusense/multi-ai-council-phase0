# Relay Live Readiness Contract

This document and the associated `src/providers/live_readiness.py` module constitute a **static, prepare-only policy machinery**.

**Important:** This module does not authorize live provider execution, nor does it resolve any real live blockers. It solely implements a side-effect-free, deterministic gate that formalizes the requirements defined in `RELAY_LIVE_BLOCKERS.md`. It will only transition from `BLOCKED_UNKNOWN` to `READY_FOR_HUMAN_APPROVAL`, and it enforces `live_ready=false` and `dispatch_allowed=false` under all circumstances.

## Common Proof Categories Mapped to Blockers

The following proofs map directly to the common blockers defined in Section 1 of `RELAY_LIVE_BLOCKERS.md`:

- `finite_timeout`: Exact finite timeout values.
- `minimum_permission_profile`: Exact minimum permission profile.
- `executed_model_verification_mechanism`: Executed-model verification mechanism.
- `intended_subscription_billing_route`: Proof that the intended subscription/auth route is the route actually paying for the turn.
- `provider_specific_abort_readback`: Provider-specific abort/readback evidence.
- `final_fanout_secret_pii_private_code_policy`: Final secret/PII/private-code fan-out patterns.
- `filesystem_network_confinement`: Live filesystem/network confinement feasibility.
- `zero_hidden_retry_fallback_end_to_end`: End-to-end proof that no hidden retry/fallback violates Phase 0 policy.

## Provider-Specific Proof Categories Mapped to Blockers

### OpenAI (Section 2)
- `chatgpt_route_retry_zero`: Built-in ChatGPT-auth provider can be configured/verified with zero automatic request retry.
- `no_stream_reconnect_replay`: Zero stream/reconnect replay that can cause another model request.
- `no_auth_recovery_replay`: No auth recovery path silently replays a turn.
- `single_model_request_evidence`: Evidence can distinguish a single model request from a replay.

### Anthropic (Section 3)
- `sdk_retry_zero`: Provider/SDK automatic model-call retry can be disabled or deterministically prevented.
- `model_fallback_disabled`: Model fallback can be disabled.
- `no_restart_recovery_extra_turn`: No restart/recovery path creates another model turn without a new human/Phase0 dispatch.
- `account_auth`: Subscription auth status remains `account`.
- `dangerous_skip_permissions_false`: `allowDangerouslySkipPermissions=false` is effective on new/load.
- `independent_executed_model_verification`: Executed model is independently verified.

### Google (Section 4)
- `intended_account_route`: The authenticated identity is the intended Google AI Pro/Antigravity account route.
- `api_key_cloud_billing_overage_absent`: API-key/Cloud Billing/overage paths are not selected.
- `internal_retry_fallback_zero`: Internal retry/fallback behavior satisfies Phase0 auto-retry=0/no-fallback.
- `executed_model_verification`: Executed model is verifiable.
- `cancel_teardown_no_restart`: Active-turn cancellation/process teardown can be proven without automatic restart.
- `quota_billing_unknown_blocks`: Quota/billing UNKNOWN can be detected and stops before send.
