# Relay Static-to-Live Gap Audit

This document is a machine-checkable snapshot of the remaining gap between the
currently accepted static Relay stack and any future first live provider turn.

**Evidence boundary:** this audit reflects current checked-in canonical evidence
only. It is **not fresh external provider verification** and it resolves zero
real live blockers.

The terminal interpretation is:

```text
STATIC/PREPARED complete
!= real blocker resolved
!= human provenance verified
!= execution authorized
!= first live provider turn approved
```

## Next safe work

- static maintenance and regression audits may continue;
- read-only evidence gathering may continue when separately authorized and
  non-live;
- permission/auth/trust-source changes require explicit human architecture
  authorization;
- the first real provider/model turn requires separate explicit human approval.

## Gap audit table

| gap_id | scope/provider | class | current_state | canonical_source | missing_evidence_or_decision | forbidden_until_resolved |
| --- | --- | --- | --- | --- | --- | --- |
| common_timeout | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | exact finite timeout values | live provider/model execution |
| common_min_permissions | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | exact minimum permission profile | permission widening and live provider/model execution |
| common_model_verification | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | executed-model verification mechanism | live provider/model execution |
| common_subscription_route | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | proof that the intended subscription/auth route is the route actually paying for the turn | live provider/model execution |
| common_abort_readback | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | provider-specific abort/readback evidence | live provider/model execution |
| common_sensitive_fanout | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | final secret/PII/private-code fan-out patterns | live provider/model execution |
| common_confinement | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | live filesystem/network confinement feasibility | live provider/model execution |
| common_hidden_retry | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | end-to-end proof that no hidden retry/fallback violates Phase 0 policy | live provider/model execution |
| openai_request_retry | OpenAI/Codex | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | built-in ChatGPT-auth provider can be configured/verified with zero automatic request retry | live provider/model execution |
| openai_stream_replay | OpenAI/Codex | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | zero stream/reconnect replay that can cause another model request | live provider/model execution |
| openai_auth_replay | OpenAI/Codex | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | no auth recovery path silently replays a turn | live provider/model execution |
| openai_single_request_evidence | OpenAI/Codex | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | evidence can distinguish a single model request from a replay | live provider/model execution |
| claude_retry | Claude | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | provider/SDK automatic model-call retry can be disabled or deterministically prevented | live provider/model execution |
| claude_fallback | Claude | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | model fallback can be disabled | live provider/model execution |
| claude_recovery | Claude | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | no restart/recovery path creates another model turn without a new human/Phase0 dispatch | live provider/model execution |
| claude_account_auth | Claude | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | subscription auth status remains `account` | live provider/model execution |
| claude_permissions | Claude | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | `allowDangerouslySkipPermissions=false` is effective on new/load | live provider/model execution |
| claude_model_verification | Claude | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | executed model is independently verified | live provider/model execution |
| antigravity_account_route | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | the authenticated identity is the intended Google AI Pro/Antigravity account route | live provider/model execution |
| antigravity_billing_route | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | API-key/Cloud Billing/overage paths are not selected | live provider/model execution |
| antigravity_retry_fallback | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | internal retry/fallback behavior satisfies Phase0 auto-retry=0/no-fallback | live provider/model execution |
| antigravity_model_verification | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | executed model is verifiable | live provider/model execution |
| antigravity_cancel | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | active-turn cancellation/process teardown can be proven without automatic restart | live provider/model execution |
| antigravity_quota_billing | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED_UNKNOWN | RELAY_LIVE_BLOCKERS.md | quota/billing UNKNOWN can be detected and stops before send | live provider/model execution |
| gemini_cli | Gemini CLI | DEFERRED_NOT_SELECTED | DEFERRED | RELAY_LIVE_BLOCKERS.md | Gemini CLI is not the selected Google transport for the current design | automatic fallback to Gemini CLI |
| provenance_keep_not_wired | Production provenance | HUMAN_DECISION_REQUIRED | KEEP_NOT_WIRED | RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md | KEEP_NOT_WIRED = current safe default / no provenance advancement | production provenance advancement |
| provenance_actions_readback | Production provenance | HUMAN_DECISION_REQUIRED | TRANSPORT_EVIDENCE_ONLY | RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md | GITHUB_ACTIONS_READBACK_ONLY = transport evidence only / insufficient as authenticator | treating Actions readback as an independent authenticator |
| provenance_oidc | Production provenance | HUMAN_DECISION_REQUIRED | NOT_AUTHORIZED | RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md | GITHUB_OIDC_AUTHENTICATOR = candidate / NOT_AUTHORIZED | OIDC permission/token/authenticator changes |
| provenance_attestation | Production provenance | HUMAN_DECISION_REQUIRED | NOT_AUTHORIZED | RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md | GITHUB_ARTIFACT_ATTESTATION = strong candidate / NOT_AUTHORIZED | attestation permission/generation/authenticator changes |
| first_live_turn | all providers | FINAL_HUMAN_APPROVAL | EXPLICIT_HUMAN_APPROVAL_REQUIRED | RELAY_LIVE_BLOCKERS.md | the first real provider/model turn remains a separate explicit-user-approval boundary | first real provider/model turn |

## Current conclusion

Every row above is an unresolved evidence gate, deferred route, architecture
decision, or final human approval boundary. This document does not turn any row
into PASS, RESOLVED, VERIFIED, authorized execution, or live readiness.

Production provenance remains `KEEP_NOT_WIRED` until an explicit architecture
decision changes that boundary. OIDC remains **NOT_AUTHORIZED**. Artifact
Attestation remains **NOT_AUTHORIZED**. GitHub Actions readback remains
transport evidence only and is insufficient as an independent authenticator.
Gemini CLI remains deferred and is not an automatic fallback.

The first live provider/model turn remains separately bounded and explicitly
human-approved even after every technical evidence item and any future
provenance verification have been satisfied.
