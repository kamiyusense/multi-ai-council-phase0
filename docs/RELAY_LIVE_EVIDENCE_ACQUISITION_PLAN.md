# Relay Live Evidence Acquisition Plan

This document is a **PREPARED/static work-queue classification only**.

It performs zero evidence acquisition. No provider/network/GitHub readback is
performed by this batch. No real live blocker is resolved. No human provenance
is verified. No execution is authorized.

The source of truth for the 30 current gaps is
`docs/RELAY_STATIC_TO_LIVE_GAP_AUDIT.md`. This plan preserves the same gap_id
set and current gap classes, and only classifies what kind of evidence work
would be needed next.

## Evidence stage meanings

- `STATIC_PREPARATION_ONLY`: useful static/spec/test work may be prepared now,
  but that preparation alone does not prove the real-world blocker resolved.
- `READ_ONLY_EVIDENCE_CANDIDATE`: a future separately authorized read-only
  inspection may collect relevant evidence without sending a provider/model
  turn. If read-only evidence is unavailable or inconclusive, remain blocked.
- `REQUIRES_BOUNDED_LIVE_PROOF`: the blocker depends on runtime behavior that
  static/read-only inspection cannot safely prove by itself. A future bounded
  live proof requires separate explicit authorization.
- `HUMAN_ARCHITECTURE_DECISION`: human architecture choice is required.
- `FINAL_HUMAN_APPROVAL`: final explicit human approval is required.
- `DEFERRED_NOT_SELECTED`: deliberately not selected; never an automatic
  fallback.

No evidence stage is an authorization.

## Safe work queue categories

- static preparation/audits
- separately authorized read-only evidence gathering
- bounded live proof requiring explicit authorization
- human architecture decision
- final human approval

## Evidence Acquisition Plan

| gap_id | current_gap_class | evidence_stage | safe_now_action | external_or_live_boundary | completion_evidence_required | result_state_if_not_proven |
| --- | --- | --- | --- | --- | --- | --- |
| common_timeout | EVIDENCE_REQUIRED | STATIC_PREPARATION_ONLY | inspect current timeout constants/specs and prepare exact static assertions; do not claim runtime proof | any real provider timing/timeout behavior remains outside this static batch | exact finite timeout values | BLOCKED_UNKNOWN |
| common_min_permissions | EVIDENCE_REQUIRED | STATIC_PREPARATION_ONLY | inspect checked-in permission/config requirements and prepare a minimum-permission checklist; do not change permissions | any permission change or real execution remains separately authorized | exact minimum permission profile | BLOCKED_UNKNOWN |
| common_model_verification | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare a bounded executed-model proof contract only | proving the model actually executed requires separately authorized runtime evidence | executed-model verification mechanism | BLOCKED_UNKNOWN |
| common_subscription_route | EVIDENCE_REQUIRED | READ_ONLY_EVIDENCE_CANDIDATE | prepare a read-only route/account/billing inspection checklist; do not send a turn | if route ownership cannot be proven read-only, a separately authorized bounded proof is required | proof that the intended subscription/auth route is the route actually paying for the turn | BLOCKED_UNKNOWN |
| common_abort_readback | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare bounded abort/readback acceptance criteria only | real abort/readback behavior requires separately authorized runtime proof | provider-specific abort/readback evidence | BLOCKED_UNKNOWN |
| common_sensitive_fanout | EVIDENCE_REQUIRED | STATIC_PREPARATION_ONLY | audit checked-in fan-out/filter policy and prepare negative fixtures; do not fan out real private data | real data/provider transmission remains forbidden | final secret/PII/private-code fan-out patterns | BLOCKED_UNKNOWN |
| common_confinement | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare confinement harness/checklist without provider/model execution | real live filesystem/network confinement feasibility remains separately proven | live filesystem/network confinement feasibility | BLOCKED_UNKNOWN |
| common_hidden_retry | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare exact request-count/retry/fallback evidence contract | hidden runtime retries/fallbacks require separately authorized runtime proof | end-to-end proof that no hidden retry/fallback violates Phase 0 policy | BLOCKED_UNKNOWN |
| openai_request_retry | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare exact request-count proof and stop conditions only | zero automatic request retry must be proven in a separately authorized bounded OpenAI/Codex run | built-in ChatGPT-auth provider can be configured/verified with zero automatic request retry | BLOCKED_UNKNOWN |
| openai_stream_replay | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare reconnect/replay detection criteria only | zero stream/reconnect replay requires separately authorized runtime evidence | zero stream/reconnect replay that can cause another model request | BLOCKED_UNKNOWN |
| openai_auth_replay | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare auth-recovery replay detection criteria only | no auth-recovery replay requires separately authorized runtime evidence | no auth recovery path silently replays a turn | BLOCKED_UNKNOWN |
| openai_single_request_evidence | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare a single-request evidence format and exact-count assertion only | actual single-request proof requires separately authorized runtime evidence | evidence can distinguish a single model request from a replay | BLOCKED_UNKNOWN |
| claude_retry | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare retry-count proof contract only | automatic model-call retry behavior requires separately authorized runtime proof | provider/SDK automatic model-call retry can be disabled or deterministically prevented | BLOCKED_UNKNOWN |
| claude_fallback | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare model-fallback detection criteria only | absence of model fallback requires separately authorized runtime proof | model fallback can be disabled | BLOCKED_UNKNOWN |
| claude_recovery | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare restart/recovery replay detection criteria only | restart/recovery behavior requires separately authorized runtime proof | no restart/recovery path creates another model turn without a new human/Phase0 dispatch | BLOCKED_UNKNOWN |
| claude_account_auth | EVIDENCE_REQUIRED | READ_ONLY_EVIDENCE_CANDIDATE | prepare a read-only authenticated-account/status inspection; do not trigger a model turn | if account route cannot be proven read-only, remain blocked until separately authorized evidence exists | subscription auth status remains `account` | BLOCKED_UNKNOWN |
| claude_permissions | EVIDENCE_REQUIRED | READ_ONLY_EVIDENCE_CANDIDATE | prepare a read-only configuration/state inspection for dangerous-skip-permissions; do not mutate settings | settings/permission mutation remains human-authorized only | `allowDangerouslySkipPermissions=false` is effective on new/load | BLOCKED_UNKNOWN |
| claude_model_verification | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare an executed-model proof contract only | executed model identity requires separately authorized runtime proof | executed model is independently verified | BLOCKED_UNKNOWN |
| antigravity_account_route | EVIDENCE_REQUIRED | READ_ONLY_EVIDENCE_CANDIDATE | prepare a read-only authenticated-route/account inspection; do not send a model turn | if route identity cannot be proven read-only, remain blocked | the authenticated identity is the intended Google AI Pro/Antigravity account route | BLOCKED_UNKNOWN |
| antigravity_billing_route | EVIDENCE_REQUIRED | READ_ONLY_EVIDENCE_CANDIDATE | prepare a read-only configuration/account-path inspection; do not enable API keys, billing, or overages | any billing/auth change remains forbidden without explicit human authorization | API-key/Cloud Billing/overage paths are not selected | BLOCKED_UNKNOWN |
| antigravity_retry_fallback | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare retry/fallback count evidence and stop conditions only | runtime retry/fallback behavior requires separately authorized bounded proof | internal retry/fallback behavior satisfies Phase0 auto-retry=0/no-fallback | BLOCKED_UNKNOWN |
| antigravity_model_verification | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare executed-model identity proof contract only | executed model identity requires separately authorized runtime proof | executed model is verifiable | BLOCKED_UNKNOWN |
| antigravity_cancel | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare cancellation/restart observation criteria only | cancellation/process teardown behavior requires separately authorized runtime proof | active-turn cancellation/process teardown can be proven without automatic restart | BLOCKED_UNKNOWN |
| antigravity_quota_billing | EVIDENCE_REQUIRED | REQUIRES_BOUNDED_LIVE_PROOF | prepare stop-before-send observation criteria only | proving quota/billing UNKNOWN blocks send requires separately authorized bounded runtime evidence | quota/billing UNKNOWN can be detected and stops before send | BLOCKED_UNKNOWN |
| gemini_cli | DEFERRED_NOT_SELECTED | DEFERRED_NOT_SELECTED | none; preserve current transport selection | automatic fallback to Gemini CLI remains forbidden | Gemini CLI is not the selected Google transport for the current design | DEFERRED |
| provenance_keep_not_wired | HUMAN_DECISION_REQUIRED | HUMAN_ARCHITECTURE_DECISION | preserve the current safe default and decision packet | production provenance advancement requires explicit human architecture authorization | KEEP_NOT_WIRED = current safe default / no provenance advancement | KEEP_NOT_WIRED |
| provenance_actions_readback | HUMAN_DECISION_REQUIRED | HUMAN_ARCHITECTURE_DECISION | keep Actions readback classified as transport evidence only; do not promote it to an authenticator | any production provenance trust-source change requires explicit human architecture authorization | GITHUB_ACTIONS_READBACK_ONLY = transport evidence only / insufficient as authenticator | TRANSPORT_EVIDENCE_ONLY |
| provenance_oidc | HUMAN_DECISION_REQUIRED | HUMAN_ARCHITECTURE_DECISION | keep OIDC as an unselected candidate; no token request or permission change | `id-token: write` or authenticator wiring requires explicit human architecture authorization | GITHUB_OIDC_AUTHENTICATOR = candidate / NOT_AUTHORIZED | NOT_AUTHORIZED |
| provenance_attestation | HUMAN_DECISION_REQUIRED | HUMAN_ARCHITECTURE_DECISION | keep Artifact Attestation as an unselected candidate; no attestation generation or permission change | attestation permissions/generation/verification require explicit human architecture authorization | GITHUB_ARTIFACT_ATTESTATION = strong candidate / NOT_AUTHORIZED | NOT_AUTHORIZED |
| first_live_turn | FINAL_HUMAN_APPROVAL | FINAL_HUMAN_APPROVAL | preserve the explicit human approval gate; do not schedule or execute a provider turn | the first real provider/model turn itself | the first real provider/model turn remains a separate explicit-user-approval boundary | EXPLICIT_HUMAN_APPROVAL_REQUIRED |

## Terminal boundary

This file performs **zero evidence acquisition**.

No provider/network/GitHub readback is performed by this batch. No OIDC token is
requested. No attestation is generated or verified. No auth, billing,
permission, or settings state is changed.

No real live blocker is resolved. Human provenance remains unverified.
Execution remains unauthorized. The first real provider/model turn remains a
separate explicit-human-approved bounded action.

## Fixed safety boundaries

- GitHub Actions readback remains **transport evidence only / insufficient as authenticator**.
- OIDC remains **NOT_AUTHORIZED**.
- Artifact Attestation remains **NOT_AUTHORIZED**.
- Gemini CLI remains **DEFERRED_NOT_SELECTED** and is not an automatic fallback.
- The first real provider/model turn remains **FINAL_HUMAN_APPROVAL** and cannot be satisfied automatically by this plan.
- No real live blocker is resolved.
- No provenance is verified.
- No execution is authorized.

