# Jules Human Auth Bootstrap

Status: STATIC CONTRACT IMPLEMENTED / HUMAN ACTION PENDING

The closed exact-selector Cloud Browser command is never replayed.
Authentication is a separate human prerequisite.

Canonical first implementation:
1. Open a new visible normal Work.
2. Open jules.google.com with native Cloud Browser.
3. If sign-in is required, use ChatGPT native browser takeover.
4. The human enters Google login/MFA directly into the remote browser.
5. Do not submit a Jules task and do not mutate the repository.
6. Phase 0 persists only non-secret handoff metadata.
7. Human completion is HUMAN_COMPLETED_UNVERIFIED, never authentication PASS.
8. Fresh-read PR #4 and create a NEW exact-selector preflight.
9. The fresh browser run must reach Jules task creation UI without an auth gate.
10. Discard all pre-takeover DOM/selector/page assumptions; select and read back exact repo/branch from scratch.

Never persist raw takeover URLs, passwords, MFA, cookies, credentials, session tokens, bearer/control tokens, or browser auth material. Browser/chat/work session identity is convenience metadata only.

WAITING_FOR_HUMAN_AUTH is a nonterminal human-prerequisite state but is deliberately non-dispatchable. The first implementation does not depend on same-run resume.

Only fresh post-bootstrap observation can produce AUTHENTICATED_OBSERVED.
