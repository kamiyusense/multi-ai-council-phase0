# Relay Live Evidence Acquisition Plan

**WARNING:** this file performs zero evidence acquisition; no provider/network/GitHub readback is performed by this batch; no real live blocker is resolved; no provenance is verified; no execution is authorized.

## Safe work queue categories

- static preparation/audits
- separately authorized read-only evidence gathering
- bounded live proof requiring explicit authorization
- human architecture decision
- final human approval

## Evidence Acquisition Plan

| gap_id | current_gap_class | evidence_stage | safe_now_action | external_or_live_boundary | completion_evidence_required | result_state_if_not_proven |
| --- | --- | --- | --- | --- | --- | --- |
| common_timeout | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | exact finite timeout values | BLOCKED_UNKNOWN |
| common_min_permissions | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | exact minimum permission profile | BLOCKED_UNKNOWN |
| common_model_verification | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | executed-model verification mechanism | BLOCKED_UNKNOWN |
| common_subscription_route | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | proof that the intended subscription/auth route is the route actually paying for the turn | BLOCKED_UNKNOWN |
| common_abort_readback | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | provider-specific abort/readback evidence | BLOCKED_UNKNOWN |
| common_sensitive_fanout | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | final secret/PII/private-code fan-out patterns | BLOCKED_UNKNOWN |
| common_confinement | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | live filesystem/network confinement feasibility | BLOCKED_UNKNOWN |
| common_hidden_retry | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | end-to-end proof that no hidden retry/fallback violates Phase 0 policy | BLOCKED_UNKNOWN |
| openai_request_retry | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | built-in ChatGPT-auth provider can be configured/verified with zero automatic request retry | BLOCKED_UNKNOWN |
| openai_stream_replay | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | zero stream/reconnect replay that can cause another model request | BLOCKED_UNKNOWN |
| openai_auth_replay | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | no auth recovery path silently replays a turn | BLOCKED_UNKNOWN |
| openai_single_request_evidence | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | evidence can distinguish a single model request from a replay | BLOCKED_UNKNOWN |
| claude_retry | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | provider/SDK automatic model-call retry can be disabled or deterministically prevented | BLOCKED_UNKNOWN |
| claude_fallback | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | model fallback can be disabled | BLOCKED_UNKNOWN |
| claude_recovery | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | no restart/recovery path creates another model turn without a new human/Phase0 dispatch | BLOCKED_UNKNOWN |
| claude_account_auth | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | subscription auth status remains `account` | BLOCKED_UNKNOWN |
| claude_permissions | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | `allowDangerouslySkipPermissions=false` is effective on new/load | BLOCKED_UNKNOWN |
| claude_model_verification | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | executed model is independently verified | BLOCKED_UNKNOWN |
| antigravity_account_route | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | the authenticated identity is the intended Google AI Pro/Antigravity account route | BLOCKED_UNKNOWN |
| antigravity_billing_route | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | API-key/Cloud Billing/overage paths are not selected | BLOCKED_UNKNOWN |
| antigravity_retry_fallback | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | internal retry/fallback behavior satisfies Phase0 auto-retry=0/no-fallback | BLOCKED_UNKNOWN |
| antigravity_model_verification | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | executed model is verifiable | BLOCKED_UNKNOWN |
| antigravity_cancel | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | active-turn cancellation/process teardown can be proven without automatic restart | BLOCKED_UNKNOWN |
| antigravity_quota_billing | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | static test integration / mock isolation | live provider/model execution | quota/billing UNKNOWN can be detected and stops before send | BLOCKED_UNKNOWN |
| gemini_cli | DEFERRED_NOT_SELECTED | DEFERRED_NOT_SELECTED | none | automatic fallback to Gemini CLI | Gemini CLI is not the selected Google transport for the current design | DEFERRED |
| provenance_keep_not_wired | HUMAN_DECISION_REQUIRED | HUMAN_ARCHITECTURE_DECISION | architectural review | production provenance advancement | KEEP_NOT_WIRED = current safe default / no provenance advancement | KEEP_NOT_WIRED |
| provenance_actions_readback | HUMAN_DECISION_REQUIRED | HUMAN_ARCHITECTURE_DECISION | architectural review | production provenance advancement | GITHUB_ACTIONS_READBACK_ONLY = transport evidence only / insufficient as authenticator | TRANSPORT_EVIDENCE_ONLY |
| provenance_oidc | HUMAN_DECISION_REQUIRED | HUMAN_ARCHITECTURE_DECISION | architectural review | production provenance advancement | GITHUB_OIDC_AUTHENTICATOR = candidate / NOT_AUTHORIZED | NOT_AUTHORIZED |
| provenance_attestation | HUMAN_DECISION_REQUIRED | HUMAN_ARCHITECTURE_DECISION | architectural review | production provenance advancement | GITHUB_ARTIFACT_ATTESTATION = strong candidate / NOT_AUTHORIZED | NOT_AUTHORIZED |
| first_live_turn | FINAL_HUMAN_APPROVAL | FINAL_HUMAN_APPROVAL | none | first real provider/model turn | the first real provider/model turn remains a separate explicit-user-approval boundary | EXPLICIT_HUMAN_APPROVAL_REQUIRED |
