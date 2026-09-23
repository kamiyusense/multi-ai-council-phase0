# Human Auth Bootstrap Checkpoint — 2026-09-24

Root cause: BLOCKED_AUTH was terminalized correctly, but no visible operator handoff route existed.

Starting evidence:
- triggering command: jules-exact-selector-cloud-preflight-001-000001
- state: BLOCKED
- receipt: BLOCKED
- evidence terminal_state: BLOCKED_AUTH
- browser_opened: true
- jules_page_reached: true
- auth_state: AUTHENTICATION_REQUIRED
- task_submitted: false
- jules_task_started: false
- model_started: false
- retry: 0
- fallback: disabled
- PR #4 modified: false

Static fix:
- visible normal Work + native Cloud Browser takeover is canonical;
- auth is separate prerequisite, never retry;
- auth_handoffs/** is append-only non-secret metadata;
- takeover URL and credentials/tokens/cookies are forbidden;
- WAITING_FOR_HUMAN_AUTH is accepted but non-dispatchable;
- BLOCKED is now accepted by common state validator/schema;
- human completion remains unverified until a NEW preflight freshly reaches Jules task creation UI.

Safety:
- credential material persisted: NO
- Jules task started: NO
- target mutation: NO
- external browser service added: NO
