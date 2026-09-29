# Relay Static-to-Live Gap Audit

This document is a machine-checkable audit of the remaining gap between the currently accepted static Relay stack and any future first live provider turn.

**This is a snapshot of current checked-in canonical evidence only, not fresh external provider verification.**
- PREPARED/static complete != real blocker resolved
- real blocker resolved != provenance verified
- provenance verified != execution authorized
- execution authorized != first live turn approved

## Next safe work
- static maintenance/audits may continue
- read-only evidence gathering may continue when authorized and non-live
- permission/auth/trust-source changes require explicit human architecture authorization
- first live provider turn requires explicit human approval

## Gap Audit Table

| gap_id | scope/provider | class | current_state | canonical_source | missing_evidence | forbidden_until_resolved |
| --- | --- | --- | --- | --- | --- | --- |
| timeout | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | exact finite timeout values | live execution |
| permissions | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | exact minimum permission profile | permission changes |
| model_verify | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | executed-model verification mechanism | live model execution |
| billing_route | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | proof intended subscription/auth route is actually paying for the turn | live execution |
| readback | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | provider-specific abort/readback evidence | live execution |
| secrets_fanout | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | final secret/PII/private-code fan-out patterns | live execution |
| confinement | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | live filesystem/network confinement feasibility | live execution |
| hidden_retry | common | EVIDENCE_REQUIRED | UNKNOWN | RELAY_LIVE_BLOCKERS.md | end-to-end proof no hidden retry/fallback violates policy | live execution |
| openai_retry | OpenAI/Codex | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | built-in ChatGPT-auth zero request retry | live execution |
| openai_replay | OpenAI/Codex | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | zero stream-reconnect replay / no auth-recovery replay | live execution |
| openai_single | OpenAI/Codex | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | single-request evidence | live execution |
| claude_retry | Claude | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | automatic model-call retry / model fallback | live execution |
| claude_recovery | Claude | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | restart-recovery | live execution |
| claude_auth | Claude | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | account auth | live execution |
| claude_perms | Claude | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | dangerous-skip-permissions false | live execution |
| claude_verify | Claude | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | executed-model verification | live execution |
| antigravity_route | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | intended account route / no API-key-cloud-billing-overage path | live execution |
| antigravity_retry | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | internal retry-fallback | live execution |
| antigravity_verify | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | executed model | live execution |
| antigravity_cancel | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | cancellation without restart | live execution |
| antigravity_quota | Google Antigravity | EVIDENCE_REQUIRED | BLOCKED | RELAY_LIVE_BLOCKERS.md | quota-billing UNKNOWN stop-before-send | live execution |
| gemini_cli | Gemini CLI | DEFERRED_NOT_SELECTED | DEFERRED | RELAY_LIVE_BLOCKERS.md | DEFERRED_NOT_SELECTED | automatic fallback |
| provenance_keep | Production Trust | HUMAN_DECISION_REQUIRED | KEEP_NOT_WIRED | RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md | remains safe default | ZERO architecture choice |
| provenance_readback | Production Trust | HUMAN_DECISION_REQUIRED | UNKNOWN | RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md | Actions readback is transport evidence only / insufficient authenticator | ZERO architecture choice |
| provenance_oidc | Production Trust | HUMAN_DECISION_REQUIRED | NOT_AUTHORIZED | RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md | OIDC candidate remains NOT_AUTHORIZED | ZERO permission change |
| provenance_attest | Production Trust | HUMAN_DECISION_REQUIRED | NOT_AUTHORIZED | RELAY_PROVENANCE_TRUST_SOURCE_DECISION_SUPPORT.md | Artifact Attestation strong candidate remains NOT_AUTHORIZED | ZERO permission change |
| first_turn | All | FINAL_HUMAN_APPROVAL | UNKNOWN | RELAY_LIVE_BLOCKERS.md | explicit human approval required for first turn | live provider execution |
