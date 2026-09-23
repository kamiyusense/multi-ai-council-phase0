# Jules Human Auth Bootstrap

Status: STATIC CONTRACT HARDENED / GITHUB-TRIGGERED HUMAN BOUNDARY PENDING

The closed exact-selector Cloud Browser command is never replayed.
Authentication is a separate prerequisite, never a retry.

Canonical route:
1. A NEW durable `JULES_HUMAN_AUTH_BOOTSTRAP` command is written on PR #6.
2. The GitHub event wakes Work/Luna; direct Chat -> Work handoff is not a
   correctness requirement.
3. Work fresh-reads PR #4 head/tree and requires exact command binding.
4. Work opens `jules.google.com` with native Cloud Browser only.
5. If sign-in is required, Work must surface ChatGPT's native secure
   sign-in/takeover flow to the human.
6. Password, MFA, cookie, token, takeover URL, browser-control token, or other
   credentials are never persisted in GitHub or chat.
7. While authentication is unresolved, state is
   `WAITING_FOR_HUMAN_AUTH`; no Jules task is submitted and no model starts.
8. Human completion is recorded only as `HUMAN_COMPLETED_UNVERIFIED`, never
   authentication PASS.
9. All pre-auth DOM/selector/page assumptions are discarded.
10. PR #4 is fresh-read again and a NEW exact-selector preflight is issued.
11. The fresh preflight must independently reach Jules task creation UI with no
    authentication gate, then select/read back the exact repository and branch
    from fresh observations with `task_submit=false`.
12. Only that fresh observation may produce `AUTHENTICATED_OBSERVED`.

User-visible entry gate:
- do not ask the human to locate an old Work or guess a browser/session;
- if a native user-visible sign-in/takeover entry cannot be surfaced and
  verified, terminalize the bootstrap as BLOCKED/UNKNOWN;
- do not persist the takeover URL as a locator;
- do not retry the same command.

Correctness does not depend on Work/chat/browser session identity or same-run
resume. Cloud Browser authentication persistence is only a convenience for the
future fresh preflight.

Fail-closed details:
- only explicit post-bootstrap `auth_state=AUTHENTICATED` may be promoted to
  `AUTHENTICATED_OBSERVED`;
- unknown/error/signed-out auth states are UNKNOWN, not PASS;
- auth handoff records reject unexpected fields and secret-bearing fields;
- append-only handoff successor transitions are validated and terminal records
  cannot be advanced/replayed;
- fresh target head/tree must be concrete lowercase 40-hex identities before a
  new exact-selector preflight is eligible.

Static implementation:
- `automation/command_bus/auth_handoff.py`
- `automation/command_bus/schema/auth_handoff.schema.json`
- `automation/command_bus/schema/auth_bootstrap_command.schema.json`
- `automation/command_bus/tests/test_auth_handoff.py`
