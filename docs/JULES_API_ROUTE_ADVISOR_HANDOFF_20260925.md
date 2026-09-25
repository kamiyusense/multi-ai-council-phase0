# Jules API Route — Advisor / Command Sol Handoff — 2026-09-25

Role: consultation, second review, architecture guidance, external research, and
user-facing explanation. Do not steal the executor's implementation branch.

Canonical decision:
`docs/JULES_API_ROUTE_DECISION_20260925.md`

## 1. Current conclusion

The previous custom BrowserHook route is frozen after repeated capability/
session/contract failures.

The user now explicitly permits the Jules API route.

Current predecessor choice:
`google-labs-code/jules-action`, pinned for first smoke to
`bff7875eaa123cac6742b7cfc51005b95ba4d566`.

This was selected after independent ChatGPT and Claude review because it is the
smallest GitHub-native route that already supports exact
`startingBranch`, one API submission, and Jules auto-PR creation.

## 2. What Claude's review added

Important findings to preserve:

- upstream README's `google-labs-code/jules-invoke@v1` example is not a safe
  copy target; use the verified repository/commit pin
- action submits only once, fitting retry=0
- action can be supplied from GitHub Secrets
- action does not reliably fail the job on every API HTTP error
- action does not provide formal session/PR outputs
- resulting PR base behavior for a non-default starting branch still needs live
  proof
- cjules has better readback UX but its creation retry behavior is a worse fit
  for the first bounded smoke

Therefore the verdict is:
**COPY_WITH_MINIMAL_CHANGE**, not blind COPY_AS_IS.

## 3. User-facing explanation

Explain simply:

- the expensive custom browser bridge is no longer the plan
- GitHub can call Jules directly through the already-existing Action
- exact branch can be passed directly
- only one small live smoke is needed to prove non-default branch ancestry
- API key stays in a secret store, never in Chat/code
- the remaining human actions are key creation, Secret registration, and later
  Merge approval
- Actions green is not enough; GitHub ancestry/diff must be read back

Use Japanese and separate CONFIRMED from UNKNOWN.

## 4. Review duties

When the executor reports a result, independently fresh-read:

- PR #4 current head/tree
- workflow/action commit identity
- Jules-created PR
- commit ancestry
- PR base/head
- changed paths
- test/check evidence
- duplicate/retry evidence

Do not accept screenshots or UI success alone when GitHub evidence exists.

## 5. Do not revive old routes

Unless the user explicitly reverses direction, do not propose:

- BrowserHook 006+
- another Work A -> Work B browser transfer
- more Jules selector diagnostics
- new auth/session persistence machinery
- a new custom relay just to start Jules

If jules-action fails, classify the concrete failure first. Then search for an
existing predecessor that solves that exact failure before proposing custom code.

## 6. Billing wording

Current billing classification remains:
`PROBABLY_SAFE_BUT_NOT_EXPLICITLY_GUARANTEED`.

Known:

- Jules key is generated in Jules Settings, not the Gemini Developer API key flow
- examined Jules API setup did not require Cloud Project/Billing enablement
- no Jules API usage pricing table was found in the examined first-party docs

Unknown:

- no first-party sentence was found guaranteeing every API session can never
  incur additional usage-based charges

Do not overstate either side.

## 7. Secondary tools

`hahwul/cjules` may be reconsidered for diagnostics/readback if a concrete
need appears. Do not make it a second runtime by default.

`google-labs-code/jules-sdk` is a future library candidate only if the Action
cannot expose needed lifecycle data and that limitation is proven material.

## 8. Success decision

For the first smoke, advisor acceptance requires:

- exact non-default branch used
- commit ancestry rooted at the fresh PR #4 head
- resulting PR relationship consistent with that branch
- only the intended test file changed
- no retry/duplicate submission
- no Merge
- evidence of tests, or test state explicitly UNKNOWN

If any of these is unverifiable, say UNKNOWN instead of inferring PASS.
