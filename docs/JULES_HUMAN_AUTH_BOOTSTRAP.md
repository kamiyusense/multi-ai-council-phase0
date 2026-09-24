# Jules Human Auth Bootstrap

Status: STATIC CONTRACT HARDENED / SAME-ASSOCIATED-WORK CONTINUATION PREFERRED

Authentication is a human-controlled boundary. Closed or terminal commands are
never replayed, and retry remains zero.

## Operator surface

The Scheduled Task `Phase 0 PR6 Command Bus` has been directly observed by the
user through the associated user-visible Work surface labeled
`WORK【クラウド】`. That surface may be used as the human-auth operator surface.

This is transport evidence only:
- GitHub durable state remains the correctness source.
- No chat/thread/conversation/browser/session identifier is persisted or used
  as a correctness input.
- The operator must be able to see and interact with the native Cloud Browser
  handoff in the associated Work; a configured label alone is not proof.

## Preferred bounded flow

1. A NEW durable `JULES_HUMAN_AUTH_BOOTSTRAP` command is written on PR #6.
2. A matching GitHub event wakes the associated `WORK【クラウド】`.
3. Work fresh-reads PR #4 head/tree and requires exact command binding.
4. Work opens `jules.google.com` in native Cloud Browser.
5. If sign-in is required, Work proves the native secure sign-in/takeover entry
   is visible to the human and records `WAITING_FOR_HUMAN_AUTH`.
6. The human completes Google/Jules authentication from that same associated
   Work and does not close the Work/browser context.
7. Human completion is only `HUMAN_COMPLETED_UNVERIFIED`; it is never auth
   PASS.
8. The same bounded flow moves to `VERIFYING_POST_AUTH` only if the associated
   Work is still user-visible, the same browser context is still open, the
   executor has actually resumed in that Work, and PR #4 head/tree are
   fresh-read again.
9. All pre-auth DOM/selector/page assumptions are discarded.
10. Work freshly observes the current page. It must directly prove:
    - no auth gate is present;
    - Jules task-creation UI is reached;
    - repository selection is explicit and exactly
      `kamiyusense/multi-ai-council-phase0`;
    - branch selection is explicit and exactly
      `feature/relay-transport-7070955470193506982`;
    - task_submitted=false;
    - jules_task_started=false;
    - model_started=false.
11. Only this fresh same-Work observation may produce
    `AUTHENTICATED_OBSERVED`.
12. No Jules task is submitted by this bootstrap flow.

State progression:

```text
WAITING_FOR_HUMAN_AUTH
  -> HUMAN_COMPLETED_UNVERIFIED
  -> VERIFYING_POST_AUTH
  -> AUTHENTICATED_OBSERVED | BLOCKED | UNKNOWN
```

A separate fresh event-triggered selector run is no longer the first-choice
continuation after human authentication. Cross-run session persistence is not a
correctness requirement.

## Same-Work continuity fail-closed rule

If the platform cannot keep or resume the same associated Work/browser context
across the human takeover, record that fact as BLOCKED/UNKNOWN. Do not infer
that a later Work inherited authentication.

A separate later run may be used only as an explicitly new diagnostic/preflight
with fresh identity. It must never be treated as proof that the previous
human-auth context persisted.

## Execution-stream failure evidence

For a stream/tool failure during or after takeover, durable evidence must record
the following independently:

- whether the Jules session page was visibly reached;
- whether a message-stream error was observed;
- whether call_tool communication was interrupted;
- whether a terminal receipt/state write landed;
- whether PR #4 changed;
- whether Jules/model started;
- runtime-timeout cause: PASS/FAIL/UNKNOWN evidence state;
- human-wait-ended-runtime cause: PASS/FAIL/UNKNOWN evidence state;
- post-takeover executor-resume failure: PASS/FAIL/UNKNOWN evidence state;
- durable-write-before-turn-cut status.

Do not collapse these into a guessed root cause.

The current bootstrap-005 evidence proves a user-visible message-stream /
call_tool interruption before durable completion. It does not prove whether the
platform cause was timeout, human-wait termination, or resume failure; those
remain UNKNOWN.

## Secret and mutation boundaries

Never persist or echo:
- password, MFA, cookie, credential or auth token;
- takeover URL;
- browser-control token;
- session identifier.

Never perform during this flow:
- Jules task submission or model start;
- PR #4 mutation;
- Merge/main write/force push;
- Billing/settings/permissions mutation.

Static implementation:
- `automation/command_bus/auth_handoff.py`
- `automation/command_bus/schema/auth_handoff.schema.json`
- `automation/command_bus/schema/state.schema.json`
- `automation/command_bus/tests/test_auth_handoff.py`
- `docs/WORK_COMMAND_BUS_RUNTIME_CONTRACT.md`
